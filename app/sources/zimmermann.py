"""Zimmermann public TecDoc catalogue adapter.

Otto Zimmermann publishes an open, branded TecDoc catalogue.  The API request
below is the same anonymous exact-number query made by that catalogue; it is a
single request and does not require a browser session or credentials.
"""
from __future__ import annotations

from ..groups import BRAKE_DISCS, BRAKE_PADS
from ..normalize import KIND_AFTERMARKET, KIND_OEM, clean_number
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client


BASE = "https://web.tecalliance.net/otto-zimmermann/ru/"
API = "https://webservice.tecalliance.services/pegasus-3-0/services/TecdocToCatDLB.jsonEndpoint"
PROVIDER = 2254


class ZimmermannSource(BaseSource):
    key = "zimmermann"
    title = "ZIMMERMANN"
    homepage = BASE
    verified = True
    groups = (BRAKE_PADS, BRAKE_DISCS)
    note = "Колодки и тормозные диски. Открытый фирменный TecDoc-каталог Zimmermann."

    @staticmethod
    def article_group(article: object) -> str | None:
        if not isinstance(article, dict):
            return None
        descriptions = " ".join(
            str(row.get("genericArticleDescription", ""))
            for row in article.get("genericArticles", []) if isinstance(row, dict)
        ).casefold()
        if "тормозной диск" in descriptions:
            return BRAKE_DISCS
        if "колодок" in descriptions and "тормозн" in descriptions:
            return BRAKE_PADS
        return None

    @staticmethod
    def request_payload(oe: str) -> dict:
        return {"getArticles": {
            "applyDqmRules": True, "articleCountry": "US", "provider": PROVIDER,
            "lang": "ru", "searchQuery": oe, "searchMatchType": "exact", "searchType": 10,
            "page": 1, "perPage": 100,
            "sort": [{"field": "mfrName", "direction": "asc"},
                     {"field": "linkageSortNum", "direction": "asc"}],
            "filterQueries": ["(dataSupplierId NOT IN (4978,4982))"],
            "dataSupplierIds": [], "genericArticleIds": [], "criteriaFilters": [],
            "articleStatusIds": [], "includeAll": False, "includeLinkages": False,
            "linkagesPerPage": 100, "includeGenericArticles": True,
            "includeArticleCriteria": False, "includeMisc": False, "includeImages": False,
            "includePDFs": False, "includeLinks": False, "includeArticleText": False,
            "includeOEMNumbers": True, "includeReplacedByArticles": False,
            "includeReplacesArticles": False, "includeComparableNumbers": False,
            "includeGTINs": False, "includeTradeNumbers": False, "includePrices": False,
            "includePartsListArticles": False, "includeAccessoryArticles": False,
            "includeArticleLogisticsCriteria": False, "includeDataSupplierFacets": False,
            "includeGenericArticleFacets": True, "includeArticleStatusFacets": False,
            "includeCriteriaFacets": False,
        }}

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy, base_headers={
            "Origin": "https://web.tecalliance.net", "Referer": self.homepage,
        }) as client:
            try:
                response = await client.post(API, json=self.request_payload(oe))
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR, message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started), url=API)
            if looks_blocked(response.status_code, response.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, message=f"HTTP {response.status_code}",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))
            if response.status_code >= 400:
                return SourceResult(self.key, SourceStatus.ERROR, message=f"HTTP {response.status_code}",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))
            try:
                payload = response.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("articles"), list):
                    raise ValueError("invalid article response")
            except ValueError:
                return SourceResult(self.key, SourceStatus.ERROR, message="Zimmermann вернул не JSON",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))

        products: list[str] = []
        crosses = []
        for article in payload.get("articles", []) if isinstance(payload, dict) else []:
            if self.article_group(article) not in self.groups or not isinstance(article, dict):
                continue
            product = clean_number(article.get("articleNumber", ""))
            if not product or product in products:
                continue
            products.append(product)
            crosses.extend(self.make_cross("ZIMMERMANN", product, product=product,
                                           url=API, kind=KIND_AFTERMARKET))
            for reference in article.get("oemNumbers", []):
                if not isinstance(reference, dict):
                    continue
                crosses.extend(self.make_cross(str(reference.get("mfrName", "")),
                                               str(reference.get("articleNumber", "")),
                                               product=product, url=API, kind=KIND_OEM))
        return SourceResult(
            self.key, SourceStatus.OK if crosses else SourceStatus.NOT_FOUND,
            crosses=crosses, products=products,
            message=None if crosses else "номер не найден в выбранной группе Zimmermann",
            elapsed_ms=self.elapsed(started), url=API,
        )
