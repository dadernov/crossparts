"""KYB — https://kyb.ru/support/cross

У KYB есть собственный сервис кроссировки: ``POST /api/2/cross`` с телом
``{"partNumber": "<номер>"}``. Ответ — ``{"data": {"cross": [...]}, "err": 0}``,
в каждой строке ``oe_pn`` (оригинальный номер), ``maker`` (автопроизводитель)
и ``kyb_pn`` (артикул KYB).

Сайт прямо предупреждает: «Оригинальные номера следует вводить слитно, без
дополнительных символов» — поэтому номер отправляем нормализованным
(``48530-80605`` сам по себе не находится, ``4853080605`` находится).
"""
from __future__ import annotations

from ..groups import SHOCK_ABSORBERS
from ..normalize import number_key
from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus
from .http import build_client

BASE = "https://kyb.ru"
PAGE = f"{BASE}/support/cross"
CROSS = f"{BASE}/api/2/cross"


class KybSource(BaseSource):
    key = "kyb"
    title = "KYB (kyb.ru)"
    homepage = "https://kyb.ru/support/cross"
    verified = True
    groups = (SHOCK_ABSORBERS,)
    note = "Амортизаторы. Сервис кроссировки KYB: по ОЕ отдаёт артикулы KYB."

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        async with build_client(self.settings, proxy=self.proxy, base_headers={
            "Accept": "application/json",
            "Referer": PAGE,
        }) as client:
            try:
                answer = await client.post(CROSS, json={"partNumber": number_key(oe)})
            except Exception as exc:
                return SourceResult(self.key, SourceStatus.ERROR,
                                    message=self.describe_error(exc),
                                    elapsed_ms=self.elapsed(started))
            if looks_blocked(answer.status_code, answer.text):
                return SourceResult(self.key, SourceStatus.BLOCKED, url=PAGE,
                                    message=f"HTTP {answer.status_code}",
                                    elapsed_ms=self.elapsed(started))
            try:
                payload = answer.json()
            except ValueError:
                return SourceResult(self.key, SourceStatus.ERROR, url=PAGE,
                                    message=f"сервис ответил не JSON (HTTP {answer.status_code})",
                                    elapsed_ms=self.elapsed(started))
            if payload.get("err"):
                return SourceResult(self.key, SourceStatus.ERROR, url=PAGE,
                                    message=str(payload.get("errmsg") or payload["err"]),
                                    elapsed_ms=self.elapsed(started))

            crosses = self.parse_cross(payload, url=PAGE)
            products = sorted({c.number for c in crosses if c.brand == "KYB"})
            return SourceResult(
                self.key,
                SourceStatus.OK if crosses else SourceStatus.NOT_FOUND,
                crosses=crosses, products=products, url=PAGE,
                elapsed_ms=self.elapsed(started),
                message=None if crosses else "номер не найден в кроссировке KYB",
            )

    # -- разбор данных --------------------------------------------------

    def parse_cross(self, payload: dict, *, url: str):
        rows = ((payload or {}).get("data") or {}).get("cross") or []
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            article = str(row.get("kyb_pn") or "").strip()
            oe_number = str(row.get("oe_pn") or "").strip()
            maker = str(row.get("maker") or "").strip()
            if article:
                out.extend(self.make_cross("KYB", article, product=article, url=url))
            if oe_number and maker:
                out.extend(self.make_cross(maker, oe_number, product=article or None, url=url))
        return out
