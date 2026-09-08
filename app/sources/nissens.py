"""Nissens — https://catalogue.nissens.com/Product

Каталог на ASP.NET MVC, три шага и всё по HTTP, браузер не нужен:

1. ``GET /Product`` — форма поиска, из неё берём ``SearchID`` и скрытые поля.
2. ``POST /Product/Search`` с ``SearchParameters.OeNumber`` — таблица
   применяемости. Прямое попадание по номеру помечено классом кнопки
   ``btn--selectedProduct``; все остальные артикулы в таблице — просто другие
   детали для тех же машин, кроссами они не являются.
3. ``POST /Product/ProductDetails`` по параметрам из ``onclick`` этой кнопки —
   карточка, где в ``#otherOe`` лежат ОЕМ-номера.

Бренд ОЕМ-номера сайт не указывает, ставим ``OEM``; сам номер Nissens
возвращаем как кросс бренда ``NISSENS``.
"""
from __future__ import annotations

import re

from selectolax.parser import HTMLParser

from ..groups import RADIATORS
from ..normalize import KIND_OEM
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client

BASE = "https://catalogue.nissens.com"
FORM = f"{BASE}/Product"
DETAILS = f"{BASE}/Product/ProductDetails"

#: Позиции аргументов ``showProductDetails(link, productID, ...)`` -> имена полей
#: формы ``/Product/ProductDetails``.
_DETAIL_ARGS = (
    "productID", "carProductID", "carID", "manufacturerID", "vehicleID",
    "modelID", "transmissionID", "airconditionID", "fuelID", "engineCode",
    "isCore",
)


def split_call_args(text: str) -> list[str]:
    """Разобрать аргументы JS-вызова.

    Наивный ``split(",")`` здесь ломается: значения вроде ``'LOGAN (2005)'``
    содержат и запятые, и скобки. Содержимое кавычек отдаём как есть — сайт
    ждёт его обратно байт в байт, включая хвостовой пробел в ``'1.2 '``.
    """
    out, buf, quote, depth, quoted = [], [], "", 0, False

    def flush():
        nonlocal buf, quoted
        out.append("".join(buf) if quoted else "".join(buf).strip())
        buf, quoted = [], False

    for ch in text:
        if quote:
            if ch == quote:
                quote = ""
            else:
                buf.append(ch)
            continue
        if ch in "'\"":
            # Кавычки открылись — всё, что стояло до них, было отступом.
            quote, quoted, buf = ch, True, []
        elif quoted:
            if ch == "," and depth == 0:
                flush()
        elif ch in "([":
            depth += 1
            buf.append(ch)
        elif ch in ")]":
            depth -= 1
            buf.append(ch)
        elif ch == "," and depth == 0:
            flush()
        else:
            buf.append(ch)
    flush()
    return out


class NissensSource(BaseSource):
    key = "nissens"
    title = "Nissens (catalogue.nissens.com)"
    homepage = "https://catalogue.nissens.com/Product"
    verified = True
    groups = (RADIATORS,)
    note = "Радиаторы и система охлаждения. Поиск по ОЕ, ОЕМ-номера с карточки товара."

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy) as client:
            try:
                form_page = await client.get(FORM)
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR,
                                    message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))
            if looks_blocked(form_page.status_code, form_page.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, url=FORM,
                                    message=f"HTTP {form_page.status_code}",
                                    elapsed_ms=self.elapsed(started))

            action, fields = self.search_form(form_page.text)
            if action is None:
                return SourceResult(self.key, SourceStatus.ERROR, url=FORM,
                                    message="форма поиска не найдена",
                                    elapsed_ms=self.elapsed(started))
            fields["SearchParameters.OeNumber"] = oe

            try:
                found = await client.post(BASE + action, data=fields,
                                          headers={"Referer": FORM})
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR,
                                    message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))
            if looks_blocked(found.status_code, found.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, url=FORM,
                                    message=f"HTTP {found.status_code}",
                                    elapsed_ms=self.elapsed(started))

            hits = self.direct_hits(found.text)
            if not hits:
                return SourceResult(self.key, SourceStatus.NOT_FOUND, url=FORM,
                                    message="номер не найден в каталоге Nissens",
                                    elapsed_ms=self.elapsed(started))

            crosses, products = [], []
            for payload in hits[: self.settings.max_products_per_oe]:
                try:
                    card = await client.post(
                        DETAILS, data=payload,
                        headers={"Referer": BASE + action,
                                 "X-Requested-With": "XMLHttpRequest"})
                except Exception:
                    continue
                if card.status_code >= 400:
                    continue
                article = payload["productID"]
                products.append(article)
                crosses.extend(self.make_cross("NISSENS", article, product=article,
                                               url=FORM))
                crosses.extend(self.parse_oems(card.text, product=article))

            return SourceResult(
                self.key,
                SourceStatus.OK if crosses else SourceStatus.NOT_FOUND,
                crosses=crosses, products=products, url=FORM,
                elapsed_ms=self.elapsed(started),
                message=None if crosses else "карточки без ОЕМ-номеров",
            )

    # -- разбор разметки ------------------------------------------------

    @staticmethod
    def search_form(html: str) -> tuple[str | None, dict]:
        form = HTMLParser(html).css_first("form#formDoSearch")
        if form is None:
            return None, {}
        fields = {}
        for node in form.css("input"):
            name = node.attributes.get("name")
            if name:
                fields[name] = node.attributes.get("value") or ""
        return form.attributes.get("action"), fields

    @staticmethod
    def direct_hits(html: str) -> list[dict]:
        """Артикулы, в которые попал именно искомый номер, без дублей."""
        out, seen = [], set()
        for node in HTMLParser(html).css("button.resultLink"):
            if "btn--selectedProduct" not in (node.attributes.get("class") or ""):
                continue
            onclick = node.attributes.get("onclick") or ""
            match = re.search(r"showProductDetails\((.*)", onclick, re.S)
            if not match:
                continue
            args = split_call_args(match.group(1))[1:]  # [0] — сам элемент
            if len(args) < len(_DETAIL_ARGS):
                continue
            payload = dict(zip(_DETAIL_ARGS, args))
            if payload["productID"] in seen:
                continue
            seen.add(payload["productID"])
            out.append(payload)
        return out

    def parse_oems(self, html: str, *, product: str | None = None):
        out = []
        for node in HTMLParser(html).css("#otherOe span.value"):
            out.extend(self.make_cross("OEM", node.text(strip=True),
                                       product=product, url=FORM, kind=KIND_OEM))
        return out
