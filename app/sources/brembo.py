"""Brembo — https://www.bremboparts.com/europe/ru

Flow
----
1. ``GET /europe/ru`` to pick up the antiforgery pair: the ``aft`` cookie and
   the ``__RequestVerificationToken`` hidden input.  Without the matching
   ``RequestVerificationToken`` request header every API route answers 404.
2. ``POST /europe/ru/catalogue/search/searchcode`` → ``{"url": "/…/code?code=…"}``.
3. That page lists the matching Brembo codes (``P 30 122`` …).
4. Per Brembo code two JSON endpoints give the crosses:
   ``getproductmanufacturerreferences`` (OE numbers) and
   ``getproductcompetitorreferences`` (aftermarket numbers).
"""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from ..normalize import KIND_AFTERMARKET, KIND_OEM
from ..groups import BRAKE_DISCS, BRAKE_HOSES, BRAKE_PADS
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client

BASE = "https://www.bremboparts.com"
LOCALE = "europe/ru"
_TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')


class BremboSource(BaseSource):
    key = "brembo"
    title = "Brembo (bremboparts.com)"
    homepage = "https://www.bremboparts.com/europe/ru"
    verified = True
    groups = (BRAKE_PADS, BRAKE_DISCS, BRAKE_HOSES)
    note = "Официальный каталог Brembo: OE-номера + кроссы конкурентов."

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy) as client:
            try:
                home = await client.get(f"{BASE}/{LOCALE}")
                match = _TOKEN_RE.search(home.text)
                if not match:
                    return SourceResult(self.key, SourceStatus.BLOCKED,
                                        message="не получен antiforgery-токен",
                                        elapsed_ms=self.elapsed(started))
                headers = {
                    "RequestVerificationToken": match.group(1),
                    "Accept": "application/json, text/plain, */*",
                    "Origin": BASE,
                    "Referer": f"{BASE}/{LOCALE}",
                }

                search = await client.post(
                    f"{BASE}/{LOCALE}/catalogue/search/searchcode",
                    headers=headers,
                    json={"code": oe},
                )
                if search.status_code in (403, 429):
                    return SourceResult(self.key, SourceStatus.BLOCKED,
                                        message=f"HTTP {search.status_code}",
                                        elapsed_ms=self.elapsed(started))
                if search.status_code == 400:
                    # Brembo answers 400 + {"Code": ["Код изделия недействителен"]}
                    # for any number that is simply not in their catalogue.
                    return SourceResult(self.key, SourceStatus.NOT_FOUND,
                                        message=self._validation_message(search),
                                        elapsed_ms=self.elapsed(started))
                if search.status_code >= 400:
                    return SourceResult(self.key, SourceStatus.ERROR,
                                        message=f"searchcode HTTP {search.status_code}",
                                        elapsed_ms=self.elapsed(started))

                target = (search.json() or {}).get("url")
                if not target:
                    return SourceResult(self.key, SourceStatus.NOT_FOUND,
                                        message="код не найден в каталоге Brembo",
                                        elapsed_ms=self.elapsed(started))

                list_url = BASE + target
                page = await client.get(list_url)
                if page.status_code >= 400:
                    return SourceResult(self.key, SourceStatus.ERROR,
                                        message=f"product page HTTP {page.status_code}",
                                        elapsed_ms=self.elapsed(started), url=list_url)
                codes = self._brembo_codes(page.text)
                if not codes:
                    return SourceResult(self.key, SourceStatus.NOT_FOUND,
                                        message="страница результатов пуста",
                                        elapsed_ms=self.elapsed(started), url=list_url)

                truncated = len(codes) > self.settings.max_products_per_oe
                selected_codes = codes[: self.settings.max_products_per_oe]
                crosses = []
                failed_refs = 0
                for code in selected_codes:
                    crosses.extend(self.make_cross("BREMBO", code, product=code, url=list_url))
                    manufacturer, manufacturer_failed = await self._manufacturer_refs(
                        client, headers, code, list_url
                    )
                    competitor, competitor_failed = await self._competitor_refs(
                        client, headers, code, list_url
                    )
                    crosses.extend(manufacturer)
                    crosses.extend(competitor)
                    failed_refs += int(manufacturer_failed) + int(competitor_failed)

                incomplete = failed_refs > 0 or truncated
                return SourceResult(
                    self.key,
                    SourceStatus.PARTIAL if crosses and incomplete else (
                        SourceStatus.OK if crosses else SourceStatus.NOT_FOUND
                    ),
                    crosses=crosses,
                    products=selected_codes,
                    message=(f"не загружено таблиц ссылок: {failed_refs}; выдача ограничена: {truncated}"
                             if incomplete else None),
                    elapsed_ms=self.elapsed(started),
                    url=list_url,
                )
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR, message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))

    @staticmethod
    def _validation_message(response) -> str:
        try:
            payload = response.json()
        except Exception:
            return "код не найден в каталоге Brembo"
        messages = [m for values in payload.values() for m in values]
        return "; ".join(messages) or "код не найден в каталоге Brembo"

    @staticmethod
    def _brembo_codes(html: str) -> list[str]:
        tree = HTMLParser(html)
        seen, out = set(), []
        for node in tree.css("app-globalcaritem .codes-list .info .code"):
            code = node.text(strip=True)
            # The page also ships un-rendered Vue templates ("{{ … }}").
            if code and "{{" not in code and code not in seen:
                seen.add(code)
                out.append(code)
        # A single hydraulic match redirects straight to the product detail,
        # which has no app-globalcaritem list. Accept only the brake-hose
        # subtype (TecDoc 83), never other hydraulic components or suggestions.
        for node in tree.css('.product-detail app-globalcomparatorcta[product-sub-type="00083"]'):
            code = node.attributes.get("brembo-code", "").strip()
            if code and "{{" not in code and code not in seen:
                seen.add(code)
                out.append(code)
        return out

    async def _manufacturer_refs(self, client, headers, code, url):
        resp = await client.post(
            f"{BASE}/{LOCALE}/catalogue/getproductmanufacturerreferences",
            headers=headers, json={"bremboCode": code},
        )
        if resp.status_code >= 400:
            return [], True
        try:
            payload = resp.json()
        except ValueError:
            return [], True
        if not isinstance(payload, list):
            return [], True
        return self.parse_manufacturer_refs(payload, code=code, url=url), False

    async def _competitor_refs(self, client, headers, code, url):
        resp = await client.post(
            f"{BASE}/{LOCALE}/catalogue/getproductcompetitorreferences",
            headers=headers, json={"bremboCode": code},
        )
        if resp.status_code >= 400:
            return [], True
        try:
            payload = resp.json()
        except ValueError:
            return [], True
        if not isinstance(payload, list):
            return [], True
        return self.parse_competitor_refs(payload, code=code, url=url), False

    def parse_manufacturer_refs(self, payload, *, code: str, url: str):
        out = []
        for row in payload or []:
            if not isinstance(row, dict):
                continue
            out.extend(
                self.make_cross(row.get("brandsName", ""), row.get("code", ""),
                                product=code, url=url, kind=KIND_OEM)
            )
        return out

    def parse_competitor_refs(self, payload, *, code: str, url: str):
        out = []
        for row in payload or []:
            if not isinstance(row, dict):
                continue
            out.extend(
                self.make_cross(row.get("brandName", ""), row.get("code", ""),
                                product=code, url=url, kind=KIND_AFTERMARKET)
            )
        return out
