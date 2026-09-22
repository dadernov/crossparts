"""FAP brake catalogue through the manufacturer's public product API."""
from __future__ import annotations

import json
from urllib.parse import quote

from ..groups import BRAKE_DISCS, BRAKE_PADS
from ..normalize import KIND_AFTERMARKET, KIND_OEM, clean_number
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client


BASE = "https://fapbrakes.ru"
API = BASE + "/db-proxy/api"


class FapSource(BaseSource):
    key = "fap"
    title = "FAP"
    homepage = BASE + "/ru/catalogue"
    verified = True
    groups = (BRAKE_PADS, BRAKE_DISCS)
    note = "Колодки и тормозные диски. Публичный API FAP по OE-номеру."

    @staticmethod
    def product_group(row: object) -> str | None:
        if not isinstance(row, dict) or row.get("deleted") == 1:
            return None
        try:
            attributes = json.loads(row.get("ext3") or "{}")
        except (TypeError, ValueError):
            return None
        value = str(attributes.get("Goods group", "")).casefold().replace(" ", "")
        if value == "brakepad":
            return BRAKE_PADS
        if value == "brakedisc":
            return BRAKE_DISCS
        return None

    @staticmethod
    def product_code(row: object) -> str:
        return clean_number(row.get("fapProductCode", "")) if isinstance(row, dict) else ""

    @staticmethod
    def oe_pairs(payload: object) -> list[tuple[str, str]]:
        if not isinstance(payload, list):
            return []
        seen: set[tuple[str, str]] = set()
        out: list[tuple[str, str]] = []
        for row in payload:
            if not isinstance(row, dict) or row.get("deleted") == 1:
                continue
            brand = str(row.get("oeDesc") or "").strip()
            number = clean_number(row.get("oeCode") or "")
            pair = brand, number
            if brand and number and pair not in seen:
                seen.add(pair)
                out.append(pair)
        return out

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        allowed_groups = set(self.groups)
        endpoint = API + "/carProduct/code/" + quote(oe, safe="")
        async with build_client(self.settings, proxy=self.proxy,
                                base_headers={"Accept": "application/json", "Referer": self.homepage}) as client:
            try:
                response = await client.get(endpoint, params={"baseCode": oe, "page": "0"})
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR, message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started), url=endpoint)
            if looks_blocked(response.status_code, response.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, message=f"HTTP {response.status_code}",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))
            if response.status_code >= 400:
                return SourceResult(self.key, SourceStatus.ERROR, message=f"HTTP {response.status_code}",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))
            try:
                rows = response.json()
                if not isinstance(rows, list):
                    raise ValueError("invalid product response")
            except ValueError:
                return SourceResult(self.key, SourceStatus.ERROR, message="FAP вернул не JSON",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))
            all_selected = [row for row in rows if self.product_group(row) in allowed_groups]
            truncated = len(all_selected) > self.settings.max_products_per_oe
            selected = all_selected[:self.settings.max_products_per_oe]
            if not selected:
                return SourceResult(self.key, SourceStatus.NOT_FOUND,
                                    message="номер не найден в выбранной группе FAP",
                                    elapsed_ms=self.elapsed(started), url=str(response.url))

            products: list[str] = []
            crosses = []
            failed_refs = 0
            for row in selected:
                product = self.product_code(row)
                group = self.product_group(row)
                if not product or group is None:
                    continue
                products.append(product)
                product_url = API + "/carProductOeOe/code/" + quote(product, safe="")
                crosses.extend(self.make_cross("FAP", product, product=product,
                                               url=product_url, kind=KIND_AFTERMARKET))
                try:
                    refs = await client.get(product_url, params={"group": "Brake pad" if group == BRAKE_PADS else "Brake disc"})
                    if refs.status_code >= 400:
                        failed_refs += 1
                        continue
                    payload = refs.json()
                    if not isinstance(payload, list):
                        failed_refs += 1
                        continue
                    pairs = self.oe_pairs(payload)
                except (Exception, ValueError):
                    failed_refs += 1
                    continue
                for brand, number in pairs:
                    crosses.extend(self.make_cross(brand, number, product=product,
                                                   url=product_url, kind=KIND_OEM))

        incomplete = failed_refs > 0 or truncated
        return SourceResult(self.key, SourceStatus.PARTIAL if crosses and incomplete else (
                                SourceStatus.OK if crosses else SourceStatus.NOT_FOUND),
                            crosses=crosses, products=products,
                            message=(f"не загружено таблиц OE: {failed_refs}; выдача ограничена: {truncated}"
                                     if incomplete else None),
                            elapsed_ms=self.elapsed(started), url=endpoint)
