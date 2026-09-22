"""MasterKit brake-pad OE lookup.

The public autocomplete endpoint returns an own MasterKit article for a
requested OE number.  The article page is checked before it is returned, so a
similarly numbered item from another product group never enters the brake-pad
source.
"""
from __future__ import annotations

from urllib.parse import quote

from selectolax.parser import HTMLParser

from ..groups import BRAKE_PADS
from ..normalize import KIND_AFTERMARKET, clean_number
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client


BASE = "https://masterkit.it"
SEARCH = BASE + "/"


class MasterkitSource(BaseSource):
    key = "masterkit"
    title = "MasterKit"
    homepage = BASE + "/production"
    verified = True
    groups = (BRAKE_PADS,)
    note = "Тормозные колодки. Публичный OE-поиск MasterKit с проверкой карточки товара."

    @staticmethod
    def products(payload: object) -> list[str]:
        if not isinstance(payload, dict) or not isinstance(payload.get("result"), list):
            return []
        seen: set[str] = set()
        out: list[str] = []
        for item in payload["result"]:
            cross = item.get("cross") if isinstance(item, dict) else None
            if not isinstance(cross, dict):
                continue
            article = clean_number(cross.get("number", ""))
            if article and article not in seen:
                seen.add(article)
                out.append(article)
        return out

    @staticmethod
    def is_brake_pad(html: str) -> bool:
        document = HTMLParser(html)
        # Site navigation mentions pads on unrelated product pages too.
        # Use the explicit product-group property, not whole-page text.
        for row in document.css(".partsInfoPropertiesRow"):
            label = row.css_first(".partsInfoPropertiesRowProperty")
            if label is not None and label.text(strip=True).casefold().rstrip(":") == "товарная группа":
                values = row.css("span")
                return len(values) >= 2 and values[-1].text(strip=True).casefold() == "тормозные колодки"
        return False

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        headers = {
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": self.homepage,
        }
        async with build_client(self.settings, proxy=self.proxy, base_headers=headers) as client:
            try:
                response = await client.get(SEARCH, params={
                    "action": "carTree/search/tip", "q": oe, "uc": "true",
                })
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR, message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started), url=SEARCH)
            if looks_blocked(response.status_code, response.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, message=f"HTTP {response.status_code}",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))
            try:
                payload = response.json()
            except ValueError:
                return SourceResult(self.key, SourceStatus.ERROR, message="MasterKit вернул не JSON",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))
            all_articles = self.products(payload)
            truncated = len(all_articles) > self.settings.max_products_per_oe
            articles = all_articles[:self.settings.max_products_per_oe]
            if not articles:
                return SourceResult(self.key, SourceStatus.NOT_FOUND,
                                    message="номер не найден в каталоге MasterKit",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))

            products: list[str] = []
            crosses = []
            failed_checks = 0
            for article in articles:
                product_url = BASE + "/parts_info/?" + "&".join((
                    "searchString=" + quote(article), "brand=MasterKit", "number=" + quote(article),
                ))
                try:
                    page = await client.get(product_url)
                except Exception:
                    failed_checks += 1
                    continue
                if page.status_code >= 400:
                    failed_checks += 1
                    continue
                if not self.is_brake_pad(page.text):
                    continue
                products.append(article)
                crosses.extend(self.make_cross("MasterKit", article, product=article,
                                               url=str(page.url), kind=KIND_AFTERMARKET))

        if not crosses and failed_checks == len(articles):
            return SourceResult(self.key, SourceStatus.ERROR,
                                message="не удалось проверить карточку MasterKit",
                                elapsed_ms=self.elapsed(started), url=SEARCH)
        incomplete = failed_checks > 0 or truncated
        return SourceResult(
            self.key, SourceStatus.PARTIAL if crosses and incomplete else (
                SourceStatus.OK if crosses else SourceStatus.NOT_FOUND
            ),
            crosses=crosses, products=products,
            message=(f"не проверено карточек: {failed_checks}; выдача ограничена: {truncated}"
                     if incomplete else None) if crosses else
                    "номер не относится к тормозным колодкам MasterKit",
            elapsed_ms=self.elapsed(started), url=SEARCH,
        )
