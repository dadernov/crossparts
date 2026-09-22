"""FEBEST — public exact OE search for suspension parts.

The catalogue exposes ``/api/v3/articles/strict-search?value=<OE>`` without a
session.  Results contain the FEBEST article, a short English description and
the OE analogue pairs.  We accept only rows explicitly described as shock
absorbers; this prevents bushes and repair kits from entering the suspension
results merely because they share an OE search response.
"""
from __future__ import annotations

from urllib.parse import quote

from ..groups import SHOCK_ABSORBERS
from ..normalize import KIND_AFTERMARKET, KIND_OEM, number_key
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client


BASE = "https://catalog.febest.club"
SEARCH = BASE + "/api/v3/articles/strict-search"


class FebestSource(BaseSource):
    key = "febest"
    title = "FEBEST"
    homepage = BASE
    verified = True
    groups = (SHOCK_ABSORBERS,)
    note = "Амортизаторы. Публичный точный OE-поиск FEBEST с подтверждёнными аналогами."

    @staticmethod
    def is_shock(row: object) -> bool:
        if not isinstance(row, dict):
            return False
        text = str(row.get("description") or "").casefold()
        return "shock absorber" in text

    def parse_rows(self, payload: object, *, url: str):
        if not isinstance(payload, list):
            return [], []
        products: list[str] = []
        crosses = []
        for row in payload:
            if not self.is_shock(row):
                continue
            product = str(row.get("name") or "").strip()
            if not product:
                continue
            products.append(product)
            crosses.extend(self.make_cross("FEBEST", product, product=product,
                                           url=url, kind=KIND_AFTERMARKET))
            for analogue in row.get("analogues") or []:
                if not isinstance(analogue, dict) or not analogue.get("matched"):
                    continue
                crosses.extend(self.make_cross(str(analogue.get("brand") or ""),
                                               str(analogue.get("name") or ""),
                                               product=product, url=url,
                                               kind=KIND_OEM))
        return products, crosses

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        endpoint = SEARCH + "?value=" + quote(number_key(oe), safe="")
        async with build_client(self.settings, proxy=self.proxy, base_headers={
            "Accept": "application/json", "Referer": self.homepage,
        }) as client:
            try:
                response = await client.get(SEARCH, params={"value": number_key(oe)})
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR, url=endpoint,
                                    message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))
            if looks_blocked(response.status_code, response.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, url=str(response.url),
                                    message=f"HTTP {response.status_code}",
                                    elapsed_ms=self.elapsed(started))
            try:
                products, crosses = self.parse_rows(response.json(), url=endpoint)
            except ValueError:
                return SourceResult(self.key, SourceStatus.ERROR, url=str(response.url),
                                    message="FEBEST вернул не JSON",
                                    elapsed_ms=self.elapsed(started))
        return SourceResult(self.key, SourceStatus.OK if crosses else SourceStatus.NOT_FOUND,
                            products=products, crosses=crosses, url=endpoint,
                            message=None if crosses else "номер не найден среди амортизаторов FEBEST",
                            elapsed_ms=self.elapsed(started))
