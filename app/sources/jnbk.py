"""NIBK / JNBK — https://www.jnbk-brakes.com/catalogue/cars

Поиск оказался обычной form-POST, без JavaScript, поэтому источник работает
через httpx и браузер ему не нужен:

1. ``POST /catalogue/cars`` с полями ``txtPartNo`` / ``txtClass`` / ``btnProductSearch``.
   Ответ — либо сразу карточка товара, либо список ссылок вида
   ``/catalogue/cars/brake/<id>/<артикул NiBK>``.
2. На карточке есть блок ``Cross Reference``:
   ``div.detail__plate > div.detail__body .str`` с ``div.owner`` (бренд) и
   ``div.field`` (номер).

Разметка снята с реального сайта (см. tests/fixtures/SOURCE.md) и проверена
офлайн-тестами. Живьём источник отдаёт 403 на AWS WAF для дата-центровых IP —
нужен ``CP_PROXY_URL`` с разрешённым egress.
"""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from ..groups import BRAKE_DISCS, BRAKE_PADS
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client

BASE = "https://jnbk-brakes.com"
SEARCH_URL = f"{BASE}/catalogue/cars"
_PRODUCT_HREF = re.compile(r"/catalogue/(?:cars|bikes)/brake/(\d+)/([A-Za-z0-9._-]+)")

#: Классы каталога: 1 — легковые, 2 — мото. Ищем по легковым.
PRODUCT_CLASS = "1"


class JnbkSource(BaseSource):
    key = "jnbk"
    title = "NIBK / JNBK (jnbk-brakes.com)"
    homepage = "https://www.jnbk-brakes.com/catalogue/cars"
    verified = False
    groups = (BRAKE_PADS, BRAKE_DISCS)
    note = (
        "Парсер написан по реальной разметке сайта и покрыт офлайн-тестами. "
        "Живой доступ закрыт AWS WAF для дата-центровых IP — задайте CP_PROXY_URL."
    )

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(
            self.settings,
            proxy=self.proxy,
            base_headers={"Referer": SEARCH_URL, "Origin": BASE},
        ) as client:
            try:
                resp = await client.post(
                    SEARCH_URL,
                    data={
                        "txtPartNo": oe,
                        "txtClass": PRODUCT_CLASS,
                        "btnProductSearch": "Search",
                    },
                )
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR, message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))

            if resp.status_code in (401, 403, 429):
                return SourceResult(
                    self.key, SourceStatus.BLOCKED, url=SEARCH_URL,
                    message=(f"HTTP {resp.status_code}: сайт закрыт антибот-защитой "
                             f"для этого IP. Укажите CP_PROXY_URL с разрешённым egress."),
                    elapsed_ms=self.elapsed(started))
            if resp.status_code >= 400:
                return SourceResult(self.key, SourceStatus.ERROR,
                                    message=f"HTTP {resp.status_code}",
                                    elapsed_ms=self.elapsed(started))

            crosses, products = [], []

            # Поиск по точному номеру часто сразу открывает карточку товара.
            direct = self.parse_product(resp.text, url=str(resp.url))
            if direct:
                article = self.article_from_html(resp.text)
                products.append(article or "?")
                crosses.extend(direct)
            else:
                for path, article in self.result_links(resp.text):
                    if len(products) >= self.settings.max_products_per_oe:
                        break
                    url = BASE + path
                    products.append(article)
                    try:
                        page = await client.get(url)
                    except Exception:
                        continue
                    if page.status_code >= 400:
                        continue
                    crosses.extend(self.make_cross("NIBK", article, product=article, url=url))
                    crosses.extend(self.parse_product(page.text, url=url, product=article))

            status = SourceStatus.OK if crosses else SourceStatus.NOT_FOUND
            return SourceResult(self.key, status, crosses=crosses, products=products,
                                elapsed_ms=self.elapsed(started), url=SEARCH_URL,
                                message=None if crosses else "номер не найден в каталоге NiBK")

    # -- разбор разметки ------------------------------------------------

    @staticmethod
    def result_links(html: str) -> list[tuple[str, str]]:
        """Ссылки на карточки товаров со страницы результатов поиска."""
        seen, out = set(), []
        for node in HTMLParser(html).css("a[href]"):
            m = _PRODUCT_HREF.search(node.attributes.get("href") or "")
            if not m:
                continue
            path, article = m.group(0), m.group(2)
            if path not in seen:
                seen.add(path)
                out.append((path, article))
        return out

    @staticmethod
    def article_from_html(html: str) -> str | None:
        """Артикул NiBK из <title>: «… for NiBK : ROTOR DISC : RN2713»."""
        m = re.search(r"<title>([^<]*)</title>", html, re.I)
        if not m:
            return None
        parts = [p.strip() for p in m.group(1).split(":") if p.strip()]
        return parts[-1] if parts else None

    def parse_product(self, html: str, *, url: str, product: str | None = None):
        """Пары «бренд + номер» из блока Cross Reference."""
        tree = HTMLParser(html)
        block = None
        for plate in tree.css("div.detail__plate"):
            title = plate.css_first(".box-title")
            if title is not None and "cross reference" in title.text(strip=True).lower():
                block = plate
                break
        if block is None:
            return []
        out = []
        for row in block.css("div.str"):
            owner = row.css_first(".owner")
            field = row.css_first(".field")
            if owner is None or field is None:
                continue
            out.extend(self.make_cross(owner.text(strip=True), field.text(strip=True),
                                       product=product, url=url))
        return out
