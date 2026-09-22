"""HEL — https://helrussia.ru/

Магазин на OpenCart: ``GET /index.php?route=product/search&search=<номер>``.
Искать по ОЕ можно — оригинальные номера лежат прямо в карточке выдачи,
открывать товар не нужно:

* ``.product-thumb__model`` — артикул HEL (``VW-4-409``);
* ``.product-thumb__description .product-thumb__attribute-value`` — блок
  «аналог оригинальных шлангов» со списком номеров через перевод строки.

Марку авто сайт рядом с номером не пишет, поэтому ставим ``OEM``.
Ассортимент узкий — армированные шланги под конкретные модели.
"""
from __future__ import annotations

from selectolax.parser import HTMLParser

from ..groups import BRAKE_HOSES
from ..normalize import KIND_OEM
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client

BASE = "https://helrussia.ru"
SEARCH = f"{BASE}/index.php"


class HelSource(BaseSource):
    key = "hel"
    title = "HEL Performance (helrussia.ru)"
    homepage = "https://helrussia.ru/"
    verified = True
    groups = (BRAKE_HOSES,)
    note = "Армированные тормозные шланги. Оригинальные номера видны прямо в выдаче."

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy,
                                timeout=min(self.settings.source_timeout, 10),
                                base_headers={"Referer": BASE}) as client:
            try:
                found = await client.get(SEARCH, params={"route": "product/search",
                                                         "search": oe})
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR,
                                    message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))
            if looks_blocked(found.status_code, found.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, url=BASE,
                                    message=f"HTTP {found.status_code}",
                                    elapsed_ms=self.elapsed(started))

            crosses, products = self.parse_results(found.text, url=str(found.url))
            if not crosses:
                return SourceResult(self.key, SourceStatus.NOT_FOUND, url=BASE,
                                    message="номер не найден в каталоге HEL",
                                    elapsed_ms=self.elapsed(started))
            return SourceResult(self.key, SourceStatus.OK, crosses=crosses,
                                products=products, url=BASE,
                                elapsed_ms=self.elapsed(started))

    # -- разбор разметки ------------------------------------------------

    def parse_results(self, html: str, *, url: str):
        crosses, products = [], []
        for card in HTMLParser(html).css(".product-thumb"):
            model = card.css_first(".product-thumb__model")
            article = model.text(strip=True) if model is not None else ""
            link = card.css_first("a[href]")
            card_url = (link.attributes.get("href") if link is not None else None) or url
            if article:
                products.append(article)
                crosses.extend(self.make_cross("HEL", article, product=article, url=card_url))
            for value in card.css(".product-thumb__description .product-thumb__attribute-value"):
                for number in value.text().split():
                    crosses.extend(self.make_cross("OEM", number, product=article or None,
                                                   url=card_url, kind=KIND_OEM))
        return crosses, products
