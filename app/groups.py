"""Товарные группы.

Заказчик присылает группу текстом в колонке файла («Тормозные колодки NEW»),
а сайты-источники в его же таблице сгруппированы иначе («Тормозная система
диски - колодки» покрывает сразу диски и колодки). Здесь оба словаря сводятся
к общим ключам, чтобы по группе позиции выбирались нужные источники.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

BRAKE_PADS = "brake_pads"
BRAKE_DISCS = "brake_discs"
BRAKE_HOSES = "brake_hoses"
SHOCK_ABSORBERS = "shock_absorbers"
RADIATORS = "radiators"


@dataclass(frozen=True)
class Group:
    key: str
    title: str
    #: Как группа может быть записана в присланном файле.
    aliases: tuple[str, ...]


GROUPS: tuple[Group, ...] = (
    Group(BRAKE_PADS, "Тормозные колодки",
          ("тормозные колодки new", "тормозные колодки", "колодки")),
    Group(BRAKE_DISCS, "Тормозные диски",
          ("тормозные диски", "диски тормозные", "диски")),
    Group(BRAKE_HOSES, "Тормозные шланги",
          ("тормозные шланги", "шланги тормозные", "шланги")),
    Group(SHOCK_ABSORBERS, "Амортизаторы",
          ("амортизаторы", "амортизатор", "стойки")),
    Group(RADIATORS, "Радиаторы охлаждения",
          ("радиаторы основные (ленточные)", "радиаторы основные", "радиаторы",
           "радиаторы охлаждения", "радиатор")),
)

BY_KEY = {g.key: g for g in GROUPS}

#: Заголовки разделов на листе «Сайты для парсинга» -> ключи групп.
SITE_SECTIONS = {
    "тормозная система диски - колодки": (BRAKE_PADS, BRAKE_DISCS),
    "тормозная система": (BRAKE_PADS, BRAKE_DISCS),
    "амортизаторы": (SHOCK_ABSORBERS,),
    "радиаторы охлаждения": (RADIATORS,),
    "тормозные шланги": (BRAKE_HOSES,),
}

_WS = re.compile(r"\s+")


def _norm(value: str) -> str:
    return _WS.sub(" ", (value or "").strip().lower())


def resolve(value: str) -> str | None:
    """Текст группы из файла -> ключ. ``None``, если не распознали."""
    text = _norm(value)
    if not text:
        return None
    if text in BY_KEY:
        return text
    for group in GROUPS:
        if text in group.aliases:
            return group.key
    # Мягкое совпадение: «Тормозные колодки NEW 2026» и подобные вариации.
    for group in GROUPS:
        for alias in group.aliases:
            if text.startswith(alias) or alias in text:
                return group.key
    return None


def title(key: str | None) -> str:
    if not key:
        return "—"
    group = BY_KEY.get(key)
    return group.title if group else key


def all_keys() -> list[str]:
    return [g.key for g in GROUPS]
