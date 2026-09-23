"""Vehicle applicability for an exact TRIALLI shock-absorber article.

The regular TRIALLI adapter answers a different question: which catalogue
numbers cross to the searched OE.  This adapter starts from one branded
TRIALLI article and reads only that product card's applicability table.
"""
from __future__ import annotations

import datetime as dt
import re

from selectolax.parser import HTMLParser

from ..groups import SHOCK_ABSORBERS
from ..normalize import number_key
from .antibot import looks_blocked
from .http import build_client
from .trialli import BASE, SEARCH, TrialliSource


_SHOCK_PATH = "/catalogue/amortizatory-i-opory/amortizatory/"


def _text(value: str) -> str:
    return " ".join((value or "").split())


def _period(raw: str) -> tuple[int | None, int | None, bool]:
    """Keep the source text and extract only explicit four-digit years."""
    value = _text(raw)
    years = [int(year) for year in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", value)]
    open_end = bool(re.search(r"н\s*\.?\s*в\s*\.?", value, re.IGNORECASE))
    return (years[0] if years else None, years[1] if len(years) > 1 else None, open_end)


class TrialliFitmentSource:
    key = "trialli"
    brand = "TRIALLI"
    group = SHOCK_ABSORBERS
    cache_key = "fitment:trialli:v1"

    def __init__(self, settings):
        self.settings = settings

    async def lookup(self, article: str) -> dict:
        requested_key = number_key(article)
        async with build_client(
            self.settings, proxy=self.settings.proxy_for("trialli"),
            base_headers={"Referer": SEARCH},
        ) as client:
            try:
                search = await client.get(SEARCH, params={"q": article})
            except Exception as exc:
                return self._result(article, "error", message=str(exc)[:300])
            if looks_blocked(search.status_code, search.text):
                return self._result(
                    article, "blocked", message=f"HTTP {search.status_code}", source_url=SEARCH
                )
            if search.status_code >= 400:
                return self._result(
                    article, "error", message=f"HTTP {search.status_code}", source_url=SEARCH
                )

            candidates = [
                path for path in TrialliSource.product_paths(search.text)
                if path.startswith(_SHOCK_PATH)
            ]
            for path in candidates[: self.settings.max_products_per_oe]:
                url = BASE + path
                try:
                    page = await client.get(url)
                except Exception:
                    continue
                if page.status_code >= 400 or looks_blocked(page.status_code, page.text):
                    continue
                parsed = self.parse_page(page.text, source_url=url)
                if parsed and number_key(parsed["number"]) == requested_key:
                    parsed["status"] = "ok" if parsed["applications"] else "not_found"
                    parsed["message"] = (
                        None if parsed["applications"]
                        else "В карточке TRIALLI нет строк применяемости"
                    )
                    return parsed

        return self._result(
            article,
            "not_found",
            message="Точный артикул TRIALLI не найден среди амортизаторов",
            source_url=SEARCH,
        )

    @classmethod
    def parse_page(cls, html: str, *, source_url: str) -> dict | None:
        document = HTMLParser(html)
        article = TrialliSource.article_from_html(html)
        heading = document.css_first("h1")
        if not article or heading is None:
            return None

        properties: dict[str, str] = {}
        properties_table = document.css_first("table.props")
        if properties_table is not None:
            for row in properties_table.css("tr"):
                cells = row.css("th,td")
                if len(cells) >= 2:
                    key = _text(cells[0].text(separator=" ", strip=True)).rstrip(":")
                    value = _text(cells[-1].text(separator=" ", strip=True))
                    if key and value:
                        properties[key] = value

        applications = cls.parse_applications(document)
        return {
            "status": "ok" if applications else "not_found",
            "brand": cls.brand,
            "number": article,
            "group": cls.group,
            "source": cls.key,
            "source_url": source_url,
            "title": _text(heading.text(separator=" ", strip=True)),
            "installation_position": properties.get("Ось (сторона установки)"),
            "damper_type": properties.get("Тип амортизатора"),
            "damper_kind": properties.get("Вид амортизатора"),
            "applications": applications,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "message": None,
        }

    @staticmethod
    def parse_applications(document: HTMLParser) -> list[dict]:
        """Use the seven-column desktop table; the page repeats a reduced mobile table."""
        table = None
        for candidate in document.css("table.js-table-car"):
            headers = [_text(cell.text(strip=True)).casefold() for cell in candidate.css("tr th")]
            if "модификация" in headers and len(headers) >= 7:
                table = candidate
                break
        if table is None:
            return []

        out, seen = [], set()
        for row in table.css("tr"):
            cells = [_text(cell.text(separator=" ", strip=True)) for cell in row.css("td")]
            if len(cells) != 7:
                continue
            raw_period = cells[6]
            year_from, year_to, end_is_open = _period(raw_period)
            application = {
                "make": cells[0],
                "model": cells[1],
                "modification": cells[2],
                "engine_code": cells[3],
                "power_hp": cells[4],
                "engine_cc": cells[5],
                "raw_period": raw_period,
                "year_from": year_from,
                "year_to": year_to,
                "end_is_open": end_is_open,
            }
            identity = tuple(application.values())
            if identity not in seen:
                seen.add(identity)
                out.append(application)
        return out

    @classmethod
    def _result(
        cls, article: str, status: str, *, message: str | None, source_url: str | None = None
    ) -> dict:
        return {
            "status": status,
            "brand": cls.brand,
            "number": article,
            "group": cls.group,
            "source": cls.key,
            "source_url": source_url,
            "title": None,
            "installation_position": None,
            "damper_type": None,
            "damper_kind": None,
            "applications": [],
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "message": message,
        }
