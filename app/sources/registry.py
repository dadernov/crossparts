from __future__ import annotations

import json
from pathlib import Path

from ..groups import BY_KEY, title as group_title
from .base import BaseSource
from .brembo import BremboSource
from .brannor import BrannorSource
from .brixo import BrixoSource
from .browser import BrowserPool
from .generic import BrowserProfile, BrowserProfileSource
from .hel import HelSource
from .hola import HolaSource
from .jnbk import JnbkSource
from .kyb import KybSource
from .luzar import LuzarSource
from .mintex import MintexSource
from .nissens import NissensSource
from .sbparts import SbPartsSource
from .trialli import TrialliSource

PROFILES_PATH = Path(__file__).with_name("profiles.json")
CATALOG_PATH = Path(__file__).with_name("catalog.json")

BUILTIN = (SbPartsSource, BremboSource, TrialliSource, BrixoSource,
           LuzarSource, NissensSource, KybSource, HolaSource, BrannorSource, HelSource,
           JnbkSource, MintexSource)


class SourceRegistry:
    """Владеет адаптерами каталогов и знает, какой из них какую группу покрывает."""

    def __init__(self, settings):
        self.settings = settings
        self.pool = BrowserPool(settings)
        self._sources: dict[str, BaseSource] = {}

        for cls in BUILTIN:
            src = cls(settings, None, self.pool)
            self._sources[src.key] = src

        for raw in self._load_profiles():
            profile = BrowserProfile(**raw)
            source = BrowserProfileSource(settings, None, profile, self.pool)
            self._sources[profile.key] = source

        self.catalog = self._load_catalog()

    @staticmethod
    def _load_profiles() -> list[dict]:
        if not PROFILES_PATH.exists():
            return []
        return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))

    @staticmethod
    def _load_catalog() -> list[dict]:
        if not CATALOG_PATH.exists():
            return []
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8")).get("sites", [])

    # -- доступ ---------------------------------------------------------

    def all(self) -> list[BaseSource]:
        return list(self._sources.values())

    def get(self, key: str) -> BaseSource | None:
        return self._sources.get(key)

    def for_group(self, group: str | None) -> list[BaseSource]:
        """Источники, покрывающие товарную группу.

        Источник без объявленных групп считается универсальным, чтобы новый
        адаптер не выпадал из выдачи только потому, что забыли проставить группы.
        """
        if not group:
            return self.all()
        return [s for s in self._sources.values() if not s.groups or group in s.groups]

    def resolve(self, keys: list[str] | None, group: str | None = None) -> list[BaseSource]:
        """Явно запрошенные источники, иначе — умолчания, суженные по группе."""
        if keys:
            chosen = [self._sources[k] for k in keys if k in self._sources]
        else:
            chosen = [self._sources[k] for k in self.settings.default_sources
                      if k in self._sources]
        if group:
            chosen = [s for s in chosen if not s.groups or group in s.groups]
        return chosen

    def describe(self) -> list[dict]:
        return [
            {
                "key": s.key,
                "title": s.title,
                "homepage": s.homepage,
                "verified": s.verified,
                "note": s.note,
                "groups": list(s.groups),
                "group_titles": [group_title(g) for g in s.groups],
                "enabled_by_default": s.key in self.settings.default_sources,
            }
            for s in self._sources.values()
        ]

    def coverage(self) -> list[dict]:
        """Покрытие по товарным группам: что готово, что заблокировано, что впереди.

        Отвечает на вопрос заказчика из переписки — «для какой товарной группы
        какой сайт для парсинга».
        """
        out = []
        for key, group in BY_KEY.items():
            sites = [s for s in self.catalog if key in s.get("groups", [])]
            out.append({
                "group": key,
                "title": group.title,
                "total": len(sites),
                "implemented": [s["brand"] for s in sites if s["status"] == "implemented"],
                "blocked": [s["brand"] for s in sites if s["status"] == "blocked"],
                "planned": [s["brand"] for s in sites if s["status"] == "planned"],
                "sites": sites,
            })
        return out

    async def close(self):
        await self.pool.close()
