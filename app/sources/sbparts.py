"""SB NAGAMOCHI — https://sbparts.ru/catalog/

Flow
----
1. ``POST /wp-admin/admin-ajax.php`` with ``action=search_submit`` and the OE
   number.  The response is a JSON envelope whose ``products`` key holds the
   rendered result cards; each card links to ``/catalog/<SKU>``.
2. Each product page carries a "Номера аналогов" table of
   ``(brand, number)`` pairs — the cross-references we want.
"""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from ..groups import BRAKE_DISCS, BRAKE_HOSES, BRAKE_PADS
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client

BASE = "https://sbparts.ru"
AJAX = f"{BASE}/wp-admin/admin-ajax.php"
_PRODUCT_HREF = re.compile(r'href="(/catalog/[A-Za-z0-9._-]+)"')


class SbPartsSource(BaseSource):
    key = "sbparts"
    title = "SB NAGAMOCHI (sbparts.ru)"
    homepage = "https://sbparts.ru/catalog/"
    verified = True
    groups = (BRAKE_PADS, BRAKE_DISCS, BRAKE_HOSES)
    note = "Каталог кроссов SB NAGAMOCHI. Отдаёт бренд + номер аналога."

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(
            self.settings,
            proxy=self.proxy,
            base_headers={
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE}/catalog/",
            },
        ) as client:
            try:
                resp = await client.post(
                    AJAX,
                    data={"action": "search_submit", "sku": oe, "type[tab]": "filter_sku"},
                )
            except Exception as exc:  # network level
                return SourceResult(self.key, SourceStatus.ERROR, message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))

            if resp.status_code in (401, 403, 429):
                return SourceResult(self.key, SourceStatus.BLOCKED,
                                    message=f"HTTP {resp.status_code}",
                                    elapsed_ms=self.elapsed(started))
            if resp.status_code >= 400:
                return SourceResult(self.key, SourceStatus.ERROR,
                                    message=f"HTTP {resp.status_code}",
                                    elapsed_ms=self.elapsed(started))

            try:
                payload = resp.json()
            except Exception:
                return SourceResult(self.key, SourceStatus.ERROR,
                                    message="ответ не является JSON",
                                    elapsed_ms=self.elapsed(started))

            paths = self._product_paths(payload.get("products") or "")
            if not paths:
                return SourceResult(self.key, SourceStatus.NOT_FOUND,
                                    message="артикул не найден в каталоге",
                                    elapsed_ms=self.elapsed(started))

            crosses, products = [], []
            for path in paths[: self.settings.max_products_per_oe]:
                sku = path.rsplit("/", 1)[-1]
                url = f"{BASE}{path}"
                products.append(sku)
                try:
                    page = await client.get(url)
                except Exception:
                    continue
                if page.status_code >= 400:
                    continue
                # The catalogue SKU is itself a valid cross-reference.
                crosses.extend(self.make_cross("SB NAGAMOCHI", sku, product=sku, url=url))
                crosses.extend(self._parse_analogs(page.text, sku, url))

            status = SourceStatus.OK if crosses else SourceStatus.NOT_FOUND
            return SourceResult(
                self.key, status, crosses=crosses, products=products,
                elapsed_ms=self.elapsed(started),
                url=f"{BASE}{paths[0]}" if paths else None,
            )

    @staticmethod
    def _product_paths(html_fragment: str) -> list[str]:
        seen, out = set(), []
        for path in _PRODUCT_HREF.findall(html_fragment):
            if path not in seen:
                seen.add(path)
                out.append(path)
        return out

    def _parse_analogs(self, html: str, sku: str, url: str):
        tree = HTMLParser(html)
        block = tree.css_first("div.analog_cont")
        if block is None:
            return []
        out = []
        for row in block.css("tr"):
            cells = [c.text(strip=True) for c in row.css("td")]
            if len(cells) < 2:
                continue
            out.extend(self.make_cross(cells[0], cells[1], product=sku, url=url))
        return out
