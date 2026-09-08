"""TRIALLI — https://trialli.ru/catalogue/

Каталог на Bitrix, поиск обычным GET, браузер не нужен:

1. ``GET /catalogue/?q=<номер>`` — выдача со ссылками на карточки товаров.
2. На карточке блок «ОЕМ-номер»: ``div.detail_main_oem[data-code]``.

Бренд у всех кроссов один и тот же — это OE-номера производителей авто,
поэтому конкретную марку сайт не указывает; проставляем ``OEM``.
Сам артикул TRIALLI тоже возвращаем как кросс.

Покрывает четыре товарные группы: колодки, диски, шланги, амортизаторы.
"""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from ..groups import BRAKE_DISCS, BRAKE_HOSES, BRAKE_PADS, SHOCK_ABSORBERS
from ..normalize import KIND_OEM
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client

BASE = "https://trialli.ru"
SEARCH = f"{BASE}/catalogue/"
_PRODUCT_HREF = re.compile(r"^/catalogue/(?:[a-z0-9_-]+/){2,}[a-z0-9_-]+/$")
# Артикул в конце названия: «… PF 1811 купить недорого …»
_ARTICLE = re.compile(r"\b([A-Z]{2,3}[\s-]?\d{3,6}[A-Z]{0,3})\b")


class TrialliSource(BaseSource):
    key = "trialli"
    title = "TRIALLI (trialli.ru)"
    homepage = "https://trialli.ru/catalogue/"
    verified = True
    groups = (BRAKE_PADS, BRAKE_DISCS, BRAKE_HOSES, SHOCK_ABSORBERS)
    note = "Колодки, диски, шланги, амортизаторы. Отдаёт ОЕМ-номера по каждому артикулу."

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy,
                                base_headers={"Referer": SEARCH}) as client:
            try:
                found = await client.get(SEARCH, params={"q": oe})
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
                                    message="номер не найден в каталоге TRIALLI",
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
                article = self.article_from_html(page.text)
                products.append(article or path.rstrip("/").rsplit("/", 1)[-1])
                if article:
                    crosses.extend(self.make_cross("TRIALLI", article, product=article, url=url))
                crosses.extend(self.parse_oems(page.text, url=url, product=article))

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
    def article_from_html(html: str) -> str | None:
        node = HTMLParser(html).css_first("title")
        if node is None:
            return None
        text = node.text(strip=True)
        # Отрезаем маркетинговый хвост, артикул стоит перед ним.
        head = re.split(r"купить|—|–", text)[0]
        matches = _ARTICLE.findall(head.upper())
        return matches[-1].replace(" ", " ").strip() if matches else None

    def parse_oems(self, html: str, *, url: str, product: str | None = None):
        out = []
        for node in HTMLParser(html).css("div.detail_main_oem"):
            code = node.attributes.get("data-code") or node.text(strip=True)
            out.extend(self.make_cross("OEM", code, product=product, url=url, kind=KIND_OEM))
        return out
