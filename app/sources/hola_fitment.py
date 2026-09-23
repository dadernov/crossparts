"""Vehicle applicability from an exact official HOLA shock-absorber card."""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import quote

from selectolax.parser import HTMLParser

from ..groups import SHOCK_ABSORBERS
from ..normalize import number_key
from .antibot import looks_blocked
from .hola import BASE
from .http import build_client


def _text(node) -> str:
    return " ".join(node.text(separator=" ", strip=True).split())


def _direct_header(group) -> str:
    child = group.child
    while child is not None:
        if child.tag == "div" and "accordion__group-header" in (child.attributes.get("class") or ""):
            return _text(child)
        child = child.next
    return ""


def _two_digit_year(value: str) -> int | None:
    if not value.isdigit():
        return None
    year = int(value)
    return 2000 + year if year <= 69 else 1900 + year


def _number(value: str) -> str:
    match = re.search(r"\d+(?:[.,]\d+)?", value)
    return match.group(0) if match else ""


def _period(value: str) -> tuple[int | None, int | None, int | None, int | None, bool]:
    points = re.findall(r"(?<!\d)(\d{1,2})/(\d{2})(?!\d)", value)
    start_month = int(points[0][0]) if points else None
    start_year = _two_digit_year(points[0][1]) if points else None
    end_month = int(points[1][0]) if len(points) > 1 else None
    end_year = _two_digit_year(points[1][1]) if len(points) > 1 else None
    return start_year, end_year, start_month, end_month, len(points) == 1


class HolaFitmentSource:
    key = "hola"
    brand = "HOLA"
    group = SHOCK_ABSORBERS
    cache_key = "fitment:hola:v1"

    def __init__(self, settings):
        self.settings = settings

    async def lookup(self, article: str) -> dict:
        requested = number_key(article)
        url = f"{BASE}/production/shock-absorbers/{quote(article.strip(), safe='._-')}/"
        async with build_client(
            self.settings, proxy=self.settings.proxy_for("hola"),
            base_headers={"Referer": f"{BASE}/production/shock-absorbers/"},
        ) as client:
            try:
                page = await client.get(url)
            except Exception as exc:
                return self._result(article, "error", message=str(exc)[:300], source_url=url)
        if looks_blocked(page.status_code, page.text):
            return self._result(article, "blocked", message=f"HTTP {page.status_code}", source_url=url)
        if page.status_code >= 400:
            return self._result(article, "not_found", message="Карточка HOLA не найдена", source_url=url)
        parsed = self.parse_page(page.text, source_url=str(page.url))
        if parsed is None or number_key(parsed["number"]) != requested:
            return self._result(article, "not_found", message="Точный артикул HOLA не найден", source_url=url)
        parsed["status"] = "ok" if parsed["applications"] else "not_found"
        parsed["message"] = None if parsed["applications"] else "В карточке HOLA нет строк применяемости"
        return parsed

    @classmethod
    def parse_page(cls, html: str, *, source_url: str) -> dict | None:
        document = HTMLParser(html)
        about = document.css_first('.tabs__content-item[data-tabs-value="about"]')
        stock = document.css_first('.tabs__content-item[data-tabs-value="stock"]')
        if about is None:
            return None
        properties = {}
        for row in about.css("tr"):
            cells = row.css("td")
            if len(cells) >= 2:
                properties[_text(cells[0])] = _text(cells[1])
        article = properties.get("Артикул")
        if not article:
            return None
        applications = cls.parse_applications(stock) if stock is not None else []
        return {
            "status": "ok" if applications else "not_found", "brand": cls.brand,
            "number": article, "group": cls.group, "source": cls.key,
            "source_url": source_url, "title": properties.get("Наименование"),
            "installation_position": " · ".join(filter(None, [properties.get("Место установки"), properties.get("Сторона установки")])),
            "damper_type": properties.get("Вид амортизатора") or properties.get("Серия"),
            "damper_kind": properties.get("Исполнение"), "applications": applications,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(), "message": None,
        }

    @staticmethod
    def parse_applications(stock) -> list[dict]:
        out, seen = [], set()
        for row in stock.css("tr[data-id]"):
            cells = row.css("td")
            if len(cells) < 6:
                continue
            groups, parent = [], row.parent
            while parent is not None and parent is not stock:
                if parent.tag == "div" and parent.attributes.get("class") == "accordion__group":
                    groups.append(_direct_header(parent))
                parent = parent.parent
            model = groups[0] if groups else ""
            make = groups[1] if len(groups) > 1 else ""
            raw_label = _text(cells[0])
            raw_period = _text(cells[4])
            year_from, year_to, month_from, month_to, end_is_open = _period(raw_period)
            restrictions = []
            detail = row.next
            while detail is not None and detail.tag == "-text":
                detail = detail.next
            if detail is not None and detail.tag == "tr" and detail.attributes.get("data-id") is None:
                for extra in detail.css("tr"):
                    values = extra.css("th,td")
                    if len(values) == 2 and values[0].tag == "th":
                        restrictions.append(f"{_text(values[0])}: {_text(values[1])}")
            item = {
                "make": make, "model": model, "generation": None,
                "modification": raw_label, "engine_code": _text(cells[5]),
                "engine_cc": _number(_text(cells[1])),
                "power_hp": _number(_text(cells[2])),
                "power_kw": _number(_text(cells[3])),
                "body": None, "transmission": None, "axle": None,
                "restrictions": restrictions, "raw_vehicle_label": raw_label,
                "raw_period": raw_period, "year_from": year_from, "year_to": year_to,
                "month_from": month_from, "month_to": month_to,
                "end_is_open": end_is_open, "verification_status": "confirmed",
                "info": " · ".join(restrictions),
            }
            identity = tuple(str(item[key]) for key in item)
            if identity not in seen:
                seen.add(identity); out.append(item)
        return out

    @classmethod
    def _result(cls, article: str, status: str, *, message: str | None, source_url: str | None = None) -> dict:
        return {"status": status, "brand": cls.brand, "number": article, "group": cls.group,
                "source": cls.key, "source_url": source_url, "title": None,
                "installation_position": None, "damper_type": None, "damper_kind": None,
                "applications": [], "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
                "message": message}
