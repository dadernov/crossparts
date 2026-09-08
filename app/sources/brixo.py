"""Brixo — https://brixogroup.com/catalog

Единый каталог брендов Brixo: NiBK (колодки, диски), SAKURA (радиаторы) и
прочие. Заказчик перечислил в таблице два сайта этой группы — NiBK
(`nibkbrakes.com`) и SALURA (`brixogroup.com`); база у них одна, поэтому один
адаптер закрывает обе строки.

API открытый, JSON, без авторизации и без браузера:

1. ``GET /api/sku/search?search_string=<номер>`` — артикулы, у которых номер
   встречается в кроссах.
2. ``GET /api/sku/info/<артикул>`` — карточка, в ней ``references``: готовые
   пары «производитель — номер».

Раньше кроссы NiBK брались с закрытого `jnbk-brakes.com`; здесь те же данные
отдаются напрямую и с брендами.
"""
from __future__ import annotations

from ..groups import BRAKE_DISCS, BRAKE_PADS, RADIATORS
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client

BASE = "https://brixogroup.com"
CATALOG = f"{BASE}/catalog"
SEARCH = f"{BASE}/api/sku/search"
INFO = f"{BASE}/api/sku/info"


class BrixoSource(BaseSource):
    key = "brixo"
    title = "Brixo: NiBK, SAKURA (brixogroup.com)"
    homepage = "https://brixogroup.com/catalog"
    verified = True
    groups = (BRAKE_PADS, BRAKE_DISCS, RADIATORS)
    note = "Колодки и диски NiBK, радиаторы SAKURA. Кроссы приходят сразу с брендами."

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy, base_headers={
            "Accept": "application/json",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": CATALOG,
        }) as client:
            try:
                found = await client.get(SEARCH, params={"search_string": oe})
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR,
                                    message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))
            if looks_blocked(found.status_code, found.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, url=CATALOG,
                                    message=f"HTTP {found.status_code}",
                                    elapsed_ms=self.elapsed(started))

            articles = self.articles(found)
            if articles is None:
                return SourceResult(self.key, SourceStatus.ERROR, url=CATALOG,
                                    message=f"каталог ответил не JSON (HTTP {found.status_code})",
                                    elapsed_ms=self.elapsed(started))
            if not articles:
                return SourceResult(self.key, SourceStatus.NOT_FOUND, url=CATALOG,
                                    message="номер не найден в каталоге Brixo",
                                    elapsed_ms=self.elapsed(started))

            crosses, products = [], []
            for article, brand in articles[: self.settings.max_products_per_oe]:
                url = f"{CATALOG}/part?sku={article}"
                products.append(article)
                crosses.extend(self.make_cross(brand, article, product=article, url=url))
                try:
                    card = await client.get(f"{INFO}/{article}")
                except Exception:
                    continue
                if card.status_code >= 400:
                    continue
                try:
                    info = card.json()
                except ValueError:
                    continue
                crosses.extend(self.parse_references(info, url=url, product=article))

            return SourceResult(
                self.key,
                SourceStatus.OK if crosses else SourceStatus.NOT_FOUND,
                crosses=crosses, products=products, url=CATALOG,
                elapsed_ms=self.elapsed(started),
                message=None if crosses else "карточки без кроссов",
            )

    # -- разбор данных --------------------------------------------------

    @staticmethod
    def articles(response) -> list[tuple[str, str]] | None:
        """Пары «артикул, бренд» из ответа поиска. ``None`` — ответ не JSON."""
        try:
            data = response.json()
        except ValueError:
            return None
        if not isinstance(data, list):
            return None
        out = []
        for item in data:
            if not isinstance(item, dict):
                continue
            article = str(item.get("id") or "").strip()
            if article:
                out.append((article, str(item.get("sku_brand_title") or "").strip()))
        return out

    def parse_references(self, info: dict, *, url: str, product: str | None = None):
        out = []
        for ref in (info or {}).get("references") or []:
            if not isinstance(ref, dict):
                continue
            out.extend(self.make_cross(str(ref.get("manufacturer") or ""),
                                       str(ref.get("number") or ""),
                                       product=product, url=url))
        return out
