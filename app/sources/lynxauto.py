"""LYNXauto brake-pad catalogue.

The official site accepts an OE number at ``product/category/search`` and
redirects to one product card.  The card has separate OE and analogue tables;
rows marked «Детали, со схожими параметрами» are deliberately not crosses.
"""
from __future__ import annotations

from selectolax.parser import HTMLParser

from ..groups import BRAKE_HOSES, BRAKE_PADS, SHOCK_ABSORBERS
from ..normalize import KIND_AFTERMARKET, KIND_OEM
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client


BASE = "https://lynxauto.info"
SEARCH = f"{BASE}/index.php"


class LynxautoSource(BaseSource):
    key = "lynxauto"
    title = "LYNXauto"
    homepage = BASE + "/"
    verified = True
    groups = (BRAKE_PADS, SHOCK_ABSORBERS, BRAKE_HOSES)
    note = "Колодки, амортизаторы и тормозные шланги. Официальный OE-поиск и карточки LYNXauto."

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy, base_headers={
            "Referer": self.homepage,
            "Accept-Language": None,
        }) as client:
            try:
                response = await client.get(SEARCH, params={
                    "route": "product/category/search", "keyword": oe, "search_type": "right",
                })
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR, message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started), url=SEARCH)
        if looks_blocked(response.status_code, response.text):
            return SourceResult(self.key, SourceStatus.BLOCKED, message=f"HTTP {response.status_code}",
                                elapsed_ms=self.elapsed(started), url=SEARCH)
        product = self.product_code(response.text)
        if response.status_code >= 400:
            return SourceResult(self.key, SourceStatus.ERROR, message=f"HTTP {response.status_code}",
                                elapsed_ms=self.elapsed(started), url=str(response.url))
        if product is None:
            return SourceResult(self.key, SourceStatus.NOT_FOUND,
                                message="номер не найден в каталоге LYNXauto",
                                elapsed_ms=self.elapsed(started), url=str(response.url))
        group = self.product_group(response.text)
        if group not in self.groups:
            return SourceResult(self.key, SourceStatus.NOT_FOUND,
                                message="найденная карточка LYNXauto не относится к выбранной группе",
                                elapsed_ms=self.elapsed(started), url=str(response.url))
        crosses = [*self.make_cross("LYNXAUTO", product, product=product, url=str(response.url), kind=KIND_AFTERMARKET)]
        crosses.extend(self.parse_table(response.text, ".pcard-oeno-bottom", KIND_OEM,
                                        product=product, url=str(response.url)))
        crosses.extend(self.parse_table(response.text, ".pcard-analog-bottom", KIND_AFTERMARKET,
                                        product=product, url=str(response.url)))
        return SourceResult(self.key, SourceStatus.OK if crosses else SourceStatus.NOT_FOUND,
                            crosses=crosses, products=[product] if crosses else [],
                            elapsed_ms=self.elapsed(started), url=str(response.url))

    @staticmethod
    def product_code(html: str) -> str | None:
        document = HTMLParser(html)
        node = document.css_first(".pcard-model")
        return node.text(strip=True) if node is not None else None

    @staticmethod
    def is_brake_pad(html: str) -> bool:
        return LynxautoSource.product_group(html) == BRAKE_PADS

    @staticmethod
    def product_group(html: str) -> str | None:
        document = HTMLParser(html)
        heading = document.css_first(".pcard-name h1")
        text = heading.text(strip=True).casefold() if heading is not None else ""
        if any(word in text for word in ("опора", "пыльник", "отбойник", "креплен", "кронштейн", "ремкомплект", "подшипник")):
            return None
        if "колодк" in text and "тормозн" in text:
            return BRAKE_PADS
        if "шланг" in text and "тормозн" in text:
            return BRAKE_HOSES
        if "амортизатор" in text:
            return SHOCK_ABSORBERS
        return None

    def parse_table(self, html: str, selector: str, kind: str, *, product: str, url: str):
        document = HTMLParser(html)
        out = []
        for row in document.css(f"{selector} tr"):
            cells = row.css("td")
            if len(cells) < 2:
                continue
            brand = cells[0].text(strip=True)
            number = cells[1].text(strip=True)
            note = cells[2].text(strip=True).casefold() if len(cells) > 2 else ""
            if "схожими параметрами" in note:
                continue
            out.extend(self.make_cross(brand, number, product=product, url=url, kind=kind))
        return out
