"""BRANNOR — https://brannor.ru/search-oem/

Поиск по ОЕ есть, но выдача устроена как «уточните автомобиль»: страница
показывает дерево марка → модель → поколение, и ссылка каждого листа ведёт
на карточку товара (``a.itemoemcategory-link``).

Одна и та же карточка висит под каждым поколением авто (четыре ссылки на
``BRP1386A`` для A4/A5/Q5/SQ5), поэтому кандидатов схлопываем по артикулу —
иначе выкачиваем одну и ту же страницу по нескольку раз.

На карточке третья вкладка — ``ol.oems``, по строке на номер в виде
«ПРОИЗВОДИТЕЛЬ НОМЕР» одной строкой: ``VAG 8K0 698 451D``. Номер сам содержит
пробелы, поэтому режем не по первому пробелу, а по первому куску с цифрой.

Свой артикул сайт показывает только в адресе карточки
(``…-brp1386a``) — оттуда его и берём.
"""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from ..groups import BRAKE_DISCS, BRAKE_PADS
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client

BASE = "https://brannor.ru"
SEARCH = f"{BASE}/search-oem/"
_ARTICLE = re.compile(r"^[A-Z]{2,4}\d{2,6}[A-Z]?$")


def split_brand_number(text: str) -> tuple[str, str]:
    """``"VAG 8K0 698 451D"`` -> ``("VAG", "8K0 698 451D")``.

    Марка может быть из двух слов, а номер — из нескольких кусков с пробелами,
    поэтому границей считаем первое слово, в котором есть цифра.
    """
    words = (text or "").split()
    for i, word in enumerate(words):
        if any(ch.isdigit() for ch in word):
            return " ".join(words[:i]), " ".join(words[i:])
    return "", " ".join(words)


class BrannorSource(BaseSource):
    key = "brannor"
    title = "BRANNOR (brannor.ru)"
    homepage = "https://brannor.ru/search-oem/"
    verified = True
    groups = (BRAKE_PADS, BRAKE_DISCS)
    note = "Колодки и диски. Поиск по ОЕ, на карточке список оригинальных номеров."

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy,
                                base_headers={"Referer": SEARCH}) as client:
            try:
                found = await client.get(SEARCH, params={"search": oe})
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR,
                                    message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))
            if looks_blocked(found.status_code, found.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, url=SEARCH,
                                    message=f"HTTP {found.status_code}",
                                    elapsed_ms=self.elapsed(started))

            links = self.product_links(found.text)
            if not links:
                return SourceResult(self.key, SourceStatus.NOT_FOUND, url=SEARCH,
                                    message="номер не найден в каталоге BRANNOR",
                                    elapsed_ms=self.elapsed(started))

            crosses, products = [], []
            for url, article in links[: self.settings.max_products_per_oe]:
                if article:
                    products.append(article)
                    crosses.extend(self.make_cross("BRANNOR", article,
                                                   product=article, url=url))
                try:
                    page = await client.get(url)
                except Exception:
                    continue
                if page.status_code >= 400:
                    continue
                crosses.extend(self.parse_oems(page.text, url=url, product=article))

            return SourceResult(
                self.key,
                SourceStatus.OK if crosses else SourceStatus.NOT_FOUND,
                crosses=crosses, products=products, url=SEARCH,
                elapsed_ms=self.elapsed(started),
                message=None if crosses else "карточки без оригинальных номеров",
            )

    # -- разбор разметки ------------------------------------------------

    @classmethod
    def product_links(cls, html: str) -> list[tuple[str, str | None]]:
        """Пары «адрес карточки, артикул», без повторов по артикулу."""
        seen, out = set(), []
        for node in HTMLParser(html).css("a.itemoemcategory-link"):
            href = (node.attributes.get("href") or "").split("?")[0]
            if href.startswith("/"):
                href = BASE + href
            if not href.startswith(BASE):
                continue
            article = cls.article_from_url(href)
            marker = article or href
            if marker in seen:
                continue
            seen.add(marker)
            out.append((href, article))
        return out

    @staticmethod
    def article_from_url(url: str) -> str | None:
        tail = url.rstrip("/").rsplit("/", 1)[-1].split("-")[-1].upper()
        return tail if _ARTICLE.match(tail) else None

    def parse_oems(self, html: str, *, url: str, product: str | None = None):
        out = []
        for node in HTMLParser(html).css("ol.oems li"):
            brand, number = split_brand_number(node.text(strip=True))
            out.extend(self.make_cross(brand or "OEM", number, product=product, url=url))
        return out
