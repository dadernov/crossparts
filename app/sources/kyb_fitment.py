"""Vehicle applicability from the official KYB article-card API."""
from __future__ import annotations

import datetime as dt

from ..groups import SHOCK_ABSORBERS
from ..normalize import number_key
from .antibot import looks_blocked
from .http import build_client


BASE = "https://kyb.ru"
PAGE = f"{BASE}/support/online-catalog-part-number"
LOOKUP = f"{BASE}/api/2/by/partnumber"


class KybFitmentSource:
    key = "kyb"
    brand = "KYB"
    group = SHOCK_ABSORBERS
    cache_key = "fitment:kyb:v1"

    def __init__(self, settings):
        self.settings = settings

    async def lookup(self, article: str) -> dict:
        requested = number_key(article)
        async with build_client(
            self.settings,
            proxy=self.settings.proxy_for("kyb"),
            base_headers={"Accept": "application/json", "Referer": PAGE},
        ) as client:
            try:
                answer = await client.post(LOOKUP, json={"partNumber": requested})
            except Exception as exc:
                return self._result(article, "error", message=str(exc)[:300])
        if looks_blocked(answer.status_code, answer.text):
            return self._result(article, "blocked", message=f"HTTP {answer.status_code}")
        try:
            payload = answer.json()
        except ValueError:
            return self._result(article, "error", message=f"Сервис KYB ответил не JSON (HTTP {answer.status_code})")
        if payload.get("err"):
            return self._result(article, "error", message=str(payload.get("errmsg") or payload["err"]))
        data = payload.get("data") or {}
        if data.get("unknownPart") or number_key(data.get("partNumber") or "") != requested:
            return self._result(article, "not_found", message="Точный артикул KYB не найден")
        return self.parse_data(data)

    @classmethod
    def parse_data(cls, data: dict) -> dict:
        spec = data.get("spec") or {}
        applications = []
        for row in data.get("application") or []:
            if not isinstance(row, dict):
                continue
            start_year = row.get("startYear") if isinstance(row.get("startYear"), int) else None
            raw_end = row.get("endYear") if isinstance(row.get("endYear"), int) else None
            open_end = raw_end in {9999, 0}
            end_year = None if open_end else raw_end
            start_month = row.get("startMonth")
            end_month = row.get("endMonth")
            period = str(start_year or "—")
            if start_year and isinstance(start_month, int) and 1 <= start_month <= 12:
                period = f"{start_month:02d}.{start_year}"
            period += " — н.в." if open_end else f" — {end_month:02d}.{end_year}" if end_year and isinstance(end_month, int) and 1 <= end_month <= 12 else f" — {end_year or '—'}"
            applications.append({
                "make": str(row.get("firm") or "").strip(),
                "model": str(row.get("model") or "").strip(),
                "modification": "", "engine_code": "", "engine_cc": "",
                "power_kw": "", "power_hp": "", "raw_period": period,
                "year_from": start_year, "year_to": end_year, "end_is_open": open_end,
                "info": "",
            })
        number = str(data.get("partNumber") or spec.get("partNumber") or "").strip()
        status = "ok" if applications else "not_found"
        return {
            "status": status, "brand": cls.brand, "number": number, "group": cls.group,
            "source": cls.key, "source_url": PAGE,
            "title": " · ".join(filter(None, [spec.get("part"), spec.get("series")])),
            "installation_position": " · ".join(filter(None, [spec.get("fr"), spec.get("rl")])),
            "damper_type": spec.get("type"), "damper_kind": spec.get("fixType"),
            "applications": applications,
            "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "message": None if applications else "В карточке KYB нет строк применяемости",
        }

    @classmethod
    def _result(cls, article: str, status: str, *, message: str | None) -> dict:
        return {
            "status": status, "brand": cls.brand, "number": article, "group": cls.group,
            "source": cls.key, "source_url": PAGE, "title": None,
            "installation_position": None, "damper_type": None, "damper_kind": None,
            "applications": [], "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "message": message,
        }
