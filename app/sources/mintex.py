"""Mintex — https://mintex.brakebook.com/

Brakebook — это JSF-приложение TMD Friction. Работает так:

1. ``GET /bb/<config>/<locale>/applicationSearch.xhtml`` — отдаёт сессию и
   скрытое поле ``javax.faces.ViewState``.
2. ``POST /bb/public/applicationSearch.xhtml`` формой ``searchByKeywordsForm``
   с полем ``search_keywords`` — поиск по номеру (OE, WVA, артикул).
3. Найденный артикул открывается статeless-ссылкой
   ``/bb/<config>/<locale>/<АРТИКУЛ>_<тип>/datasheet.xhtml``; там в блоке
   «OE-Referenzen» лежит таблица ``div.relationTableCR`` с колонками
   ``td.manufacturer`` (бренд) и ``td.name div.objectCode`` (номер).

Разметка снята с реального сайта (см. tests/fixtures/SOURCE.md) и проверена
офлайн-тестами. Живьём домен закрыт Cloudflare managed challenge для
дата-центровых IP — нужен ``CP_PROXY_URL`` с разрешённым egress.
"""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from .antibot import looks_blocked
from ..groups import BRAKE_DISCS, BRAKE_PADS
from .base import BaseSource, SourceResult, SourceStatus
from .clearance import ClearanceStore
from .http import build_client

BASE = "https://mintex.brakebook.com"
CONFIG = "mintex"
LOCALE = "ru"
SEARCH_PAGE = f"{BASE}/bb/{CONFIG}/{LOCALE}/applicationSearch.xhtml"
SEARCH_ACTION = f"{BASE}/bb/public/applicationSearch.xhtml"

_DATASHEET_HREF = re.compile(r"/bb/[^/]+/[^/]+/([A-Za-z0-9._-]+)/datasheet\.xhtml")
_VIEWSTATE = re.compile(r'name="javax\.faces\.ViewState"[^>]*value="([^"]*)"')


class MintexSource(BaseSource):
    key = "mintex"
    title = "Mintex (mintex.brakebook.com)"
    homepage = "https://mintex.brakebook.com/"
    verified = False
    groups = (BRAKE_PADS, BRAKE_DISCS)
    note = (
        "Парсер написан по реальной разметке brakebook и покрыт офлайн-тестами. "
        "Живой доступ закрыт Cloudflare managed challenge — задайте CP_PROXY_URL."
    )

    def __init__(self, settings, http_factory, pool=None):
        super().__init__(settings, http_factory, pool)
        self.clearance = ClearanceStore()

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy) as client:
            # Переиспользуем cf_clearance с прошлого раза — challenge стоит ~1.6 МБ.
            self.clearance.apply(client)
            try:
                page = await client.get(SEARCH_PAGE)
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR, message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))

            if self._is_block(page.status_code, page.text):
                # Cloudflare managed challenge решается один раз настоящим
                # браузером; дальше работаем по HTTP с его cookies.
                if self.clearance.in_cooldown():
                    return SourceResult(
                        self.key, SourceStatus.BLOCKED, url=SEARCH_PAGE,
                        message=(f"домен закрыт Cloudflare для этого IP; браузерные "
                                 f"попытки приостановлены на {self.clearance.cooldown_left()} с, "
                                 f"чтобы не жечь трафик прокси."),
                        elapsed_ms=self.elapsed(started))
                page = await self._retry_via_browser(client, SEARCH_PAGE)
                if page is None or self._is_block(page.status_code, page.text):
                    self.clearance.mark_failure()
                    return SourceResult(
                        self.key, SourceStatus.BLOCKED, url=SEARCH_PAGE,
                        message=("домен закрыт Cloudflare для этого IP. Нужен "
                                 "резидентный CP_PROXY_URL: с дата-центрового адреса "
                                 "challenge не проходит даже в настоящем браузере."),
                        elapsed_ms=self.elapsed(started))

            payload = {
                "searchByKeywordsForm": "searchByKeywordsForm",
                "search_keywords": oe,
                "searchByKeywords_action": "1",
                "[configId]": CONFIG,
                "locale": LOCALE,
                "_noJavaScript": "false",
            }
            viewstate = _VIEWSTATE.search(page.text)
            if viewstate:
                payload["javax.faces.ViewState"] = viewstate.group(1)

            try:
                result = await client.post(SEARCH_ACTION, data=payload,
                                           headers={"Referer": SEARCH_PAGE, "Origin": BASE})
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR, message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))
            if self._is_block(result.status_code, result.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, url=SEARCH_ACTION,
                                    message=f"HTTP {result.status_code}: антибот-защита",
                                    elapsed_ms=self.elapsed(started))

            crosses, products = [], []
            # Поиск по точному номеру может сразу открыть даташит.
            direct = self.parse_datasheet(result.text, url=str(result.url))
            if direct:
                crosses.extend(direct)
                products.append(self.article_from_html(result.text) or "?")
            else:
                for path, article in self.datasheet_links(result.text):
                    if len(products) >= self.settings.max_products_per_oe:
                        break
                    url = BASE + path
                    products.append(article)
                    try:
                        sheet = await client.get(url)
                    except Exception:
                        continue
                    if sheet.status_code >= 400:
                        continue
                    crosses.extend(self.make_cross("MINTEX", article.split("_")[0],
                                                   product=article, url=url))
                    crosses.extend(self.parse_datasheet(sheet.text, url=url, product=article))

            status = SourceStatus.OK if crosses else SourceStatus.NOT_FOUND
            return SourceResult(self.key, status, crosses=crosses, products=products,
                                elapsed_ms=self.elapsed(started), url=SEARCH_PAGE,
                                message=None if crosses else "номер не найден в каталоге Mintex")

    async def _retry_via_browser(self, client, url):
        """Пройти challenge браузером, сохранить cookies и повторить по HTTP."""
        self.clearance.clear()
        async with self.clearance.lock:
            # Пока ждали блокировку, соседний вызов мог уже прогреть сессию.
            if not self.clearance.apply(client):
                got = await self.browser_cookies(
                    url, cleared=lambda title, html: not self._is_block(200, html))
                if got is None:
                    return None
                cookies, html = got
                # Пустой набор cookies или всё ещё заглушка — защита не пройдена.
                # Считать это успехом нельзя, иначе счётчик неудач не сработает.
                if not cookies or self._is_block(200, html):
                    return None
                self.clearance.put(cookies)
                self.clearance.apply(client)
        try:
            return await client.get(url)
        except Exception:
            return None

    # -- разбор разметки ------------------------------------------------

    @staticmethod
    def _is_block(status: int | None, body: str | None) -> bool:
        return looks_blocked(status, body)

    @staticmethod
    def datasheet_links(html: str) -> list[tuple[str, str]]:
        seen, out = set(), []
        for node in HTMLParser(html).css("a[href]"):
            m = _DATASHEET_HREF.search(node.attributes.get("href") or "")
            if not m:
                continue
            path, article = m.group(0), m.group(1)
            if path not in seen:
                seen.add(path)
                out.append((path, article))
        return out

    @staticmethod
    def article_from_html(html: str) -> str | None:
        m = re.search(r'name="\[object\]"[^>]*value="([^"]+)"', html)
        return m.group(1) if m else None

    def parse_datasheet(self, html: str, *, url: str, product: str | None = None):
        """Таблица OE-ссылок: бренд в td.manufacturer, номер в td.name .objectCode."""
        tree = HTMLParser(html)
        out = []
        # af_table_content — внутренняя таблица; без этого уточнения внешний <tr>,
        # который её оборачивает, отдал бы первую строку ещё раз.
        for table in tree.css("div.relationTableCR table.af_table_content"):
            for row in table.css("tr"):
                brand_cell = row.css_first("td.manufacturer")
                code_cell = row.css_first("td.name div.objectCode")
                if brand_cell is None or code_cell is None:
                    continue
                out.extend(self.make_cross(brand_cell.text(strip=True),
                                           code_cell.text(strip=True),
                                           product=product, url=url))
        return out
