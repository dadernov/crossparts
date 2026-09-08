"""Определение антибот-заглушек.

Cloudflare локализует страницу challenge («Just a moment…», «Один момент…»,
«Un momento…»), поэтому опираться на текст ненадёжно. Надёжный признак —
скрипт challenge-платформы и объект ``_cf_chl_opt``, они одинаковы на всех языках.
"""
from __future__ import annotations

#: Структурные маркеры — не зависят от языка страницы.
STRUCTURAL_MARKERS = (
    "/cdn-cgi/challenge-platform/",
    "_cf_chl_opt",
    "cf-browser-verification",
    "__cf_chl_",
)

#: Текстовые — на случай, если разметку поменяют.
TEXT_MARKERS = (
    "just a moment",
    "one moment",
    "один момент",
    "performing security verification",
    "проверка безопасности",
    "attention required",
    "checking your browser",
    "403 forbidden",
    "access denied",
    "доступ запрещён",
)

BLOCKED_STATUSES = (401, 403, 429, 503)


def looks_blocked(status: int | None, body: str | None, *, statuses=BLOCKED_STATUSES) -> bool:
    if status in statuses:
        return True
    head = (body or "")[:20000].lower()
    if any(m.lower() in head for m in STRUCTURAL_MARKERS):
        return True
    return any(m in head for m in TEXT_MARKERS)
