"""GANZ catalogue lookup through the manufacturer's public exact-number search."""
from __future__ import annotations

from urllib.parse import quote, urljoin

from selectolax.parser import HTMLParser

from ..groups import BRAKE_DISCS, BRAKE_PADS, RADIATORS, SHOCK_ABSORBERS
from ..normalize import KIND_AFTERMARKET, clean_number, number_key
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client


BASE = "https://ganz-parts.ru"
SEARCH = BASE + "/search/"


class GanzSource(BaseSource):
    key = "ganz"
    title = "GANZ"
    homepage = BASE + "/catalog/"
    verified = True
    groups = (BRAKE_PADS, BRAKE_DISCS, SHOCK_ABSORBERS, RADIATORS)
    note = "Колодки, диски, амортизаторы и основные радиаторы; точный OE-поиск подтверждается карточкой GANZ."

    @staticmethod
    def product_urls(html: str) -> list[str]:
        document = HTMLParser(html)
        urls: list[str] = []
        for node in document.css(".search-custom-results .search-item .h4 a"):
            href = node.attributes.get("href", "")
            if href.startswith("/catalog/") and href not in urls:
                urls.append(href)
        return urls

    @staticmethod
    def product_data(html: str) -> tuple[str, str | None, set[str]]:
        document = HTMLParser(html)
        values: dict[str, str] = {}
        for row in document.css(".product_page_info_prop"):
            label = row.css_first(".product_page_info_prop_title")
            value = row.css_first(".product_page_info_prop_value")
            if label is not None and value is not None:
                values[label.text(strip=True).casefold()] = value.text(strip=True)

        title = (document.css_first(".product_page_title") or document.css_first("h1"))
        text = title.text(strip=True).casefold() if title is not None else ""
        group = None
        if "колодк" in text and "тормозн" in text:
            group = BRAKE_PADS
        elif "диск" in text and "тормозн" in text:
            group = BRAKE_DISCS
        elif "амортизатор" in text and not any(
            word in text for word in ("багаж", "капот", "двер")
        ):
            group = SHOCK_ABSORBERS
        elif "радиатор охлаждения" in text and not any(
            word in text for word in ("масл", "акпп", "кондиционер", "отоп")
        ):
            group = RADIATORS
        original = values.get("оригинальный номер", "")
        originals = {number_key(value) for value in original.replace(",", " ").split() if value}
        return clean_number(values.get("артикул", "")), group, originals

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy,
                                base_headers={"Referer": self.homepage}) as client:
            try:
                response = await client.get(SEARCH, params={"q": oe})
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR, message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started), url=SEARCH)
            if looks_blocked(response.status_code, response.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, message=f"HTTP {response.status_code}",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))
            if response.status_code >= 400:
                return SourceResult(self.key, SourceStatus.ERROR, message=f"HTTP {response.status_code}",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))
            all_urls = self.product_urls(response.text)
            truncated = len(all_urls) > self.settings.max_products_per_oe
            urls = all_urls[:self.settings.max_products_per_oe]
            if not urls:
                return SourceResult(self.key, SourceStatus.NOT_FOUND,
                                    message="номер не найден в каталоге GANZ",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))

            products: list[str] = []
            crosses = []
            failed_checks = 0
            query_key = number_key(oe)
            for path in urls:
                product_url = urljoin(BASE, path)
                try:
                    page = await client.get(product_url)
                except Exception:
                    failed_checks += 1
                    continue
                if page.status_code >= 400:
                    failed_checks += 1
                    continue
                article, group, original_numbers = self.product_data(page.text)
                # The result page is exact, but the product card is the second
                # proof: a recommendation or a stale search index never becomes
                # a cross-reference.
                if not article or group not in self.groups or query_key not in original_numbers:
                    continue
                if article not in products:
                    products.append(article)
                    crosses.extend(self.make_cross("GANZ", article, product=article,
                                                   url=str(page.url), kind=KIND_AFTERMARKET))

        if not crosses and failed_checks == len(urls):
            return SourceResult(
                self.key, SourceStatus.ERROR,
                message="не удалось проверить карточки GANZ",
                elapsed_ms=self.elapsed(started), url=SEARCH,
            )
        incomplete = failed_checks > 0 or truncated
        return SourceResult(
            self.key, SourceStatus.PARTIAL if crosses and incomplete else (
                SourceStatus.OK if crosses else SourceStatus.NOT_FOUND
            ),
            crosses=crosses, products=products,
            message=(f"не проверено карточек: {failed_checks}; выдача ограничена: {truncated}"
                     if incomplete else None) if crosses else
                    "нет подтверждённого GANZ-аналога в выбранной группе",
            elapsed_ms=self.elapsed(started), url=SEARCH,
        )
