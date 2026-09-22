"""TORR — https://controltorr.de/catalog

The manufacturer keeps a server-rendered OE search: ``/catalog?search=<OE>``.
Every found article page contains its type and a cross-reference table.  The
adapter first checks that the product is a shock absorber, then reads the table
instead of inferring relationships from vehicle applicability rows.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from selectolax.parser import HTMLParser

from ..groups import SHOCK_ABSORBERS
from ..normalize import KIND_AFTERMARKET
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client


BASE = "https://controltorr.de"
CATALOGUE = BASE + "/ru/catalog"
_PRODUCT_PATH = re.compile(r"^/?(?:ru/)?catalog/([A-Za-z0-9._-]+)$")


class TorrSource(BaseSource):
    key = "torr"
    title = "TORR"
    homepage = CATALOGUE
    verified = True
    groups = (SHOCK_ABSORBERS,)
    note = "Амортизаторы. Официальный серверный OE-поиск и таблица кросс-номеров TORR."

    @staticmethod
    def product_paths(html: str) -> list[tuple[str, str]]:
        seen, out = set(), []
        for node in HTMLParser(html).css("a[href]"):
            href = (node.attributes.get("href") or "").split("?", 1)[0]
            match = _PRODUCT_PATH.match(href)
            if match and href not in seen:
                seen.add(href)
                out.append(("/ru/catalog/" + match.group(1), match.group(1)))
        return out

    @staticmethod
    def is_shock(html: str) -> bool:
        title = HTMLParser(html).css_first(".product-page__title")
        return bool(title and "shock absorber" in title.text(strip=True).casefold())

    def parse_crosses(self, html: str, *, product: str, url: str):
        document = HTMLParser(html)
        out = []
        # The first table is vehicle applicability and has a header.  The
        # following headerless table is the actual cross-reference list.
        for table in document.css(".item-page__applicability"):
            if table.css_first("thead") is not None:
                continue
            for cell in table.css("td"):
                text = cell.text(separator=" ", strip=True)
                match = re.match(r"^(.+?)\s+([A-Za-z0-9._/-]+)$", text)
                if match:
                    brand = match.group(1).replace("/", " / ")
                    out.extend(self.make_cross(brand, match.group(2),
                                               product=product, url=url))
        return out

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        search_url = CATALOGUE + "?search=" + quote(oe.strip(), safe="")
        async with build_client(self.settings, proxy=self.proxy,
                                base_headers={"Referer": CATALOGUE}) as client:
            try:
                response = await client.get(CATALOGUE, params={"search": oe.strip()})
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR, url=search_url,
                                    message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))
            if looks_blocked(response.status_code, response.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, url=str(response.url),
                                    message=f"HTTP {response.status_code}",
                                    elapsed_ms=self.elapsed(started))
            paths = self.product_paths(response.text)
            if not paths:
                return SourceResult(self.key, SourceStatus.NOT_FOUND, url=search_url,
                                    message="номер не найден в каталоге TORR",
                                    elapsed_ms=self.elapsed(started))
            products, crosses = [], []
            for path, product in paths[:self.settings.max_products_per_oe]:
                page_url = BASE + path
                try:
                    page = await client.get(page_url)
                except Exception:
                    continue
                if page.status_code >= 400 or not self.is_shock(page.text):
                    continue
                products.append(product)
                crosses.extend(self.make_cross("TORR", product, product=product,
                                               url=page_url, kind=KIND_AFTERMARKET))
                crosses.extend(self.parse_crosses(page.text, product=product, url=page_url))
        return SourceResult(self.key, SourceStatus.OK if crosses else SourceStatus.NOT_FOUND,
                            products=products, crosses=crosses, url=search_url,
                            message=None if crosses else "карточки TORR не являются амортизаторами",
                            elapsed_ms=self.elapsed(started))
