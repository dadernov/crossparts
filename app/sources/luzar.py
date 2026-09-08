"""LUZAR — https://luzar.ru/catalogue/

Радиаторы и остальная система охлаждения. Каталог на Bitrix, поиск обычным
GET, браузер не нужен:

1. ``GET /catalogue/?q=<номер>&s=Поиск`` — ищет и по своему артикулу, и по ОЕМ
   (``1118-1301012`` и ``11181301012`` находят одно и то же).
2. На карточке блок ``div.list-oems``: каждый номер лежит в ``div[data-find]``,
   марка авто — во вложенном ``span.marka`` (часто пустом).

Бренд у номеров сайт указывает не всегда, поэтому пустой ставим ``OEM``.
Собственный артикул LUZAR тоже возвращаем как кросс.
"""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from ..groups import RADIATORS
from ..normalize import KIND_OEM
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client

BASE = "https://luzar.ru"
SEARCH = f"{BASE}/catalogue/"
_PRODUCT_HREF = re.compile(r"^/catalogue/(?:[a-z0-9_-]+/){2,}[a-z0-9_-]+/$")


class LuzarSource(BaseSource):
    key = "luzar"
    title = "LUZAR (luzar.ru)"
    homepage = "https://luzar.ru/catalogue"
    verified = True
    groups = (RADIATORS,)
    note = "Радиаторы охлаждения. Ищет по ОЕМ-номеру, отдаёт полный список ОЕМ карточки."

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy,
                                base_headers={"Referer": SEARCH}) as client:
            try:
                found = await client.get(SEARCH, params={"q": oe, "s": "Поиск"})
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR,
                                    message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))
            if looks_blocked(found.status_code, found.text):
                return SourceResult(self.key, SourceStatus.BLOCKED,
                                    message=f"HTTP {found.status_code}", url=SEARCH,
                                    elapsed_ms=self.elapsed(started))

            paths = self.product_paths(found.text)
            if not paths:
                return SourceResult(self.key, SourceStatus.NOT_FOUND, url=SEARCH,
                                    message="номер не найден в каталоге LUZAR",
                                    elapsed_ms=self.elapsed(started))

            crosses, products = [], []
            for path in paths[: self.settings.max_products_per_oe]:
                url = BASE + path
                try:
                    page = await client.get(url)
                except Exception:
                    continue
                if page.status_code >= 400:
                    continue
                tree = HTMLParser(page.text)
                article = self.article_from_tree(tree)
                if article:
                    products.append(article)
                    crosses.extend(self.make_cross("LUZAR", article, product=article, url=url))
                crosses.extend(self.parse_oems(tree, url=url, product=article))

            return SourceResult(
                self.key,
                SourceStatus.OK if crosses else SourceStatus.NOT_FOUND,
                crosses=crosses, products=products, url=SEARCH,
                elapsed_ms=self.elapsed(started),
                message=None if crosses else "карточки без ОЕМ-номеров",
            )

    # -- разбор разметки ------------------------------------------------

    @staticmethod
    def product_paths(html: str) -> list[str]:
        seen, out = set(), []
        for node in HTMLParser(html).css("a[href]"):
            href = (node.attributes.get("href") or "").split("?")[0]
            if _PRODUCT_HREF.match(href) and href not in seen:
                seen.add(href)
                out.append(href)
        return out

    @staticmethod
    def article_from_tree(tree: HTMLParser) -> str | None:
        node = tree.css_first("[data-code]")
        if node is None:
            return None
        return (node.attributes.get("data-code") or "").strip() or None

    def parse_oems(self, tree: HTMLParser, *, url: str, product: str | None = None):
        out = []
        for node in tree.css("div.list-oems div[data-find]"):
            marka = node.css_first("span.marka")
            brand = marka.text(strip=True) if marka is not None else ""
            number = node.text(strip=True)
            if brand and number.startswith(brand):
                number = number[len(brand):]
            number = number.strip() or (node.attributes.get("data-find") or "")
            out.extend(self.make_cross(brand or "OEM", number, product=product,
                                       url=url, kind=None if brand else KIND_OEM))
        return out
