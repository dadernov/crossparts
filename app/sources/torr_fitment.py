"""Vehicle applicability from an exact official TORR product card."""
from __future__ import annotations

import datetime as dt
import re
from urllib.parse import quote

from selectolax.parser import HTMLParser

from ..groups import SHOCK_ABSORBERS
from ..normalize import number_key
from .antibot import looks_blocked
from .http import build_client
from .torr import BASE, TorrSource


def _text(node) -> str:
    tooltip = node.css_first(".tooltip[data-tooltip]")
    if tooltip is not None and tooltip.attributes.get("data-tooltip"):
        return " ".join(tooltip.attributes["data-tooltip"].split())
    return " ".join(node.text(separator=" ", strip=True).split())


def _period(raw: str) -> tuple[int | None, int | None, bool]:
    years = [int(value) for value in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", raw)]
    return (
        years[0] if years else None,
        years[1] if len(years) > 1 else None,
        bool(re.search(r"/\s*-$", raw)),
    )


class TorrFitmentSource:
    key = "torr"
    brand = "TORR"
    group = SHOCK_ABSORBERS
    cache_key = "fitment:torr:v1"

    def __init__(self, settings):
        self.settings = settings

    async def lookup(self, article: str) -> dict:
        requested = number_key(article)
        url = f"{BASE}/catalog/{quote(requested, safe='._-')}"
        async with build_client(
            self.settings,
            proxy=self.settings.proxy_for("torr"),
            base_headers={"Referer": f"{BASE}/catalog"},
        ) as client:
            try:
                page = await client.get(url)
            except Exception as exc:
                return self._result(article, "error", message=str(exc)[:300], source_url=url)
        if looks_blocked(page.status_code, page.text):
            return self._result(article, "blocked", message=f"HTTP {page.status_code}", source_url=url)
        if page.status_code >= 400:
            return self._result(article, "not_found", message="Карточка TORR не найдена", source_url=url)
        parsed = self.parse_page(page.text, source_url=str(page.url))
        if parsed is None or number_key(parsed["number"]) != requested or not TorrSource.is_shock(page.text):
            return self._result(
                article, "not_found", message="Точный артикул амортизатора TORR не найден", source_url=url
            )
        parsed["status"] = "ok" if parsed["applications"] else "not_found"
        parsed["message"] = None if parsed["applications"] else "В карточке TORR нет строк применяемости"
        return parsed

    @classmethod
    def parse_page(cls, html: str, *, source_url: str) -> dict | None:
        document = HTMLParser(html)
        heading = document.css_first(".product-page__title")
        if heading is None:
            return None
        title = " ".join(heading.text(separator=" ", strip=True).split())
        match = re.search(r"(?:\bArt|Арт)\s*:\s*([A-Za-z0-9._-]+)", title, re.IGNORECASE)
        if not match:
            return None
        applications = cls.parse_applications(document)
        product_title = re.split(r"(?:\bArt|Арт)\s*:", title, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        tokens = [token.strip() for token in product_title.split(",") if token.strip()]
        return {
            "status": "ok" if applications else "not_found",
            "brand": cls.brand,
            "number": match.group(1),
            "group": cls.group,
            "source": cls.key,
            "source_url": source_url,
            "title": product_title,
            "installation_position": ", ".join(tokens[2:]) or None,
            "damper_type": tokens[1] if len(tokens) > 1 else None,
            "damper_kind": None,
            "applications": applications,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "message": None,
        }

    @staticmethod
    def parse_applications(document: HTMLParser) -> list[dict]:
        table = next((item for item in document.css(".item-page__applicability") if item.css_first("thead")), None)
        if table is None:
            return []
        out, seen = [], set()
        for row in table.css("tbody tr"):
            cells = row.css("td")
            if len(cells) < 8:
                continue
            values = [_text(cell) for cell in cells[:8]]
            year_from, year_to, end_is_open = _period(values[2])
            power = values[6].split("/", 1)
            item = {
                "make": values[0], "model": values[1], "modification": values[3],
                "engine_code": values[4], "engine_cc": values[5],
                "power_kw": power[0].strip(),
                "power_hp": power[1].strip() if len(power) > 1 else "",
                "raw_period": values[2], "year_from": year_from, "year_to": year_to,
                "end_is_open": end_is_open, "info": values[7],
            }
            identity = tuple(item.values())
            if identity not in seen:
                seen.add(identity)
                out.append(item)
        return out

    @classmethod
    def _result(cls, article: str, status: str, *, message: str | None, source_url: str | None = None) -> dict:
        return {
            "status": status, "brand": cls.brand, "number": article, "group": cls.group,
            "source": cls.key, "source_url": source_url, "title": None,
            "installation_position": None, "damper_type": None, "damper_kind": None,
            "applications": [], "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "message": message,
        }
