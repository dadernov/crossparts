"""Vehicle applicability from an exact official METACO product card."""
from __future__ import annotations

import datetime as dt
import re

from selectolax.parser import HTMLParser

from ..groups import SHOCK_ABSORBERS
from ..normalize import number_key
from .antibot import looks_blocked
from .http import build_client


BASE = "https://metaco.parts"


def _text(node) -> str:
    return " ".join(node.text(separator=" ", strip=True).split())


class MetacoFitmentSource:
    key = "metaco"
    brand = "METACO"
    group = SHOCK_ABSORBERS
    cache_key = "fitment:metaco:v1"

    def __init__(self, settings):
        self.settings = settings

    async def lookup(self, article: str) -> dict:
        requested = number_key(article)
        url = f"{BASE}/catalog/{requested.lower()}"
        async with build_client(
            self.settings, proxy=self.settings.proxy_for("metaco"),
            base_headers={"Referer": f"{BASE}/category/shock_absorbers"},
        ) as client:
            try:
                page = await client.get(url)
            except Exception as exc:
                return self._result(article, "error", message=str(exc)[:300], source_url=url)
        if looks_blocked(page.status_code, page.text):
            return self._result(article, "blocked", message=f"HTTP {page.status_code}", source_url=url)
        if page.status_code >= 400:
            return self._result(article, "not_found", message="Карточка METACO не найдена", source_url=url)
        parsed = self.parse_page(page.text, source_url=str(page.url))
        if parsed is None or number_key(parsed["number"]) != requested:
            return self._result(article, "not_found", message="Точный артикул METACO не найден", source_url=url)
        parsed["status"] = "ok" if parsed["applications"] else "not_found"
        parsed["message"] = None if parsed["applications"] else "В карточке METACO нет строк применяемости"
        return parsed

    @classmethod
    def parse_page(cls, html: str, *, source_url: str) -> dict | None:
        document = HTMLParser(html)
        article_node = document.css_first(".active-breadcumb")
        title_node = document.css_first("h1")
        if article_node is None or title_node is None:
            return None
        article = _text(article_node)
        properties = {}
        for row in document.css(".characteristics-block .text-2"):
            key, value = row.css_first(".key"), row.css_first(".val")
            if key is not None and value is not None:
                properties[_text(key)] = _text(value)
        applications = cls.parse_applications(document)
        return {
            "status": "ok" if applications else "not_found", "brand": cls.brand,
            "number": article, "group": cls.group, "source": cls.key,
            "source_url": source_url, "title": _text(title_node),
            "installation_position": None, "damper_type": properties.get("Тип"),
            "damper_kind": None, "applications": applications,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(), "message": None,
        }

    @staticmethod
    def parse_applications(document: HTMLParser) -> list[dict]:
        out, seen = [], set()
        for control in document.css(".metaco-model-control"):
            nested = control.css_first(".metaco-model-list")
            if nested is None:
                continue
            make_text = _text(control).split(_text(nested), 1)[0].strip()
            make = re.sub(r"\s+\d+$", "", make_text).strip()
            for node in nested.css("li"):
                period_node = node.css_first(".secondary-text")
                raw_period = _text(period_node) if period_node is not None else ""
                raw_label = _text(node)
                label = raw_label[:-len(raw_period)].strip() if raw_period and raw_label.endswith(raw_period) else raw_label
                model = label[len(make):].strip() if make and label.casefold().startswith(make.casefold()) else label
                years = [int(value) for value in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", raw_period)]
                open_end = ">" in raw_period
                generation = None
                generation_match = re.search(r"(\[[^]]+\]|\([^)]+\))", model)
                if generation_match:
                    generation = generation_match.group(1)
                item = {
                    "make": make, "model": model, "generation": generation,
                    "modification": "", "engine_code": "", "engine_cc": "",
                    "power_kw": "", "power_hp": "", "body": None,
                    "transmission": None, "axle": None, "restrictions": [],
                    "raw_vehicle_label": label, "raw_period": raw_period,
                    "year_from": years[0] if years else None,
                    "year_to": years[1] if len(years) > 1 else None,
                    "month_from": None, "month_to": None, "end_is_open": open_end,
                    "verification_status": "confirmed", "info": "",
                }
                identity = (make, model, raw_period)
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
