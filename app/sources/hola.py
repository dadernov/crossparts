"""HOLA — https://www.hola-auto.ru/

У бренда есть отдельный поиск по чужим номерам. Форма отправляет не параметр,
а путь: ``/production/search-cross/<номер>/`` (см. обработчик ``.form-search``
в их ``main.js``) — поэтому номер уходит в URL, а не в query-строку.

1. ``GET /production/search-cross/<номер>/`` — карточки найденных артикулов
   HOLA, ссылка вида ``/production/<раздел>/<артикул>/``.
2. На карточке вкладка ``.tabs__content-item[data-tabs-value="numbers"]`` —
   таблица «Номера оригинальных деталей»: слева марка авто, справа номер.
   Класс в селекторе обязателен: тот же ``data-tabs-value`` висит и на
   заголовке вкладки, а он идёт в документе раньше и таблицы не содержит.

Покрывает четыре товарные группы: колодки, диски, шланги, амортизаторы.
"""
from __future__ import annotations

import re
from urllib.parse import quote

from selectolax.parser import HTMLParser

from ..groups import BRAKE_DISCS, BRAKE_HOSES, BRAKE_PADS, SHOCK_ABSORBERS
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client

BASE = "https://www.hola-auto.ru"
SEARCH = f"{BASE}/production/search-cross"
_PRODUCT_HREF = re.compile(r"^/production/[a-z0-9_-]+/([A-Za-z0-9._-]+)/$")


class HolaSource(BaseSource):
    key = "hola"
    title = "HOLA (hola-auto.ru)"
    homepage = "https://www.hola-auto.ru/production/shock-absorbers/"
    verified = True
    groups = (BRAKE_PADS, BRAKE_DISCS, BRAKE_HOSES, SHOCK_ABSORBERS)
    note = "Колодки, диски, шланги, амортизаторы. Поиск по чужому номеру, ОЕМ с брендами."

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        url = f"{SEARCH}/{quote(oe.strip(), safe='')}/"
        async with build_client(self.settings, proxy=self.proxy,
                                base_headers={"Referer": f"{BASE}/production/"}) as client:
            try:
                found = await client.get(url)
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR,
                                    message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))
            if looks_blocked(found.status_code, found.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, url=url,
                                    message=f"HTTP {found.status_code}",
                                    elapsed_ms=self.elapsed(started))

            products = self.product_links(found.text)
            if not products:
                return SourceResult(self.key, SourceStatus.NOT_FOUND, url=url,
                                    message="номер не найден в каталоге HOLA",
                                    elapsed_ms=self.elapsed(started))

            crosses, articles = [], []
            for path, article in products[: self.settings.max_products_per_oe]:
                page_url = BASE + path
                articles.append(article)
                crosses.extend(self.make_cross("HOLA", article, product=article, url=page_url))
                try:
                    page = await client.get(page_url)
                except Exception:
                    continue
                if page.status_code >= 400:
                    continue
                crosses.extend(self.parse_numbers(page.text, url=page_url, product=article))

            return SourceResult(
                self.key,
                SourceStatus.OK if crosses else SourceStatus.NOT_FOUND,
                crosses=crosses, products=articles, url=url,
                elapsed_ms=self.elapsed(started),
                message=None if crosses else "карточки без ОЕМ-номеров",
            )

    # -- разбор разметки ------------------------------------------------

    @staticmethod
    def product_links(html: str) -> list[tuple[str, str]]:
        seen, out = set(), []
        for node in HTMLParser(html).css("a[href]"):
            href = (node.attributes.get("href") or "").split("?")[0]
            match = _PRODUCT_HREF.match(href)
            if match and href not in seen:
                seen.add(href)
                out.append((href, match.group(1)))
        return out

    def parse_numbers(self, html: str, *, url: str, product: str | None = None):
        block = HTMLParser(html).css_first(
            '.tabs__content-item[data-tabs-value="numbers"]')
        if block is None:
            return []
        out = []
        for row in block.css("tr"):
            cells = row.css("td")
            if len(cells) < 2:
                continue
            out.extend(self.make_cross(cells[0].text(strip=True), cells[1].text(strip=True),
                                       product=product, url=url))
        return out
