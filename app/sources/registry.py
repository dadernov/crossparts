from __future__ import annotations

import json
from copy import copy
from pathlib import Path

from ..groups import BY_KEY, title as group_title
from .base import BaseSource
from .brembo import BremboSource
from .brannor import BrannorSource
from .ate import AteSource
from .brixo import BrixoSource
from .browser import BrowserPool
from .generic import BrowserProfile, BrowserProfileSource
from .hel import HelSource
from .hola import HolaSource
from .jnbk import JnbkSource
from .kyb import KybSource
from .luzar import LuzarSource
from .lynxauto import LynxautoSource
from .masterkit import MasterkitSource
from .monaer import MonaerSource
from .mintex import MintexSource
from .metaco import MetacoSource
from .marshall import MarshallSource
from .fap import FapSource
from .febest import FebestSource
from .ganz import GanzSource
from .nissens import NissensSource
from .nibkru import NibkRuSource
from .sbparts import SbPartsSource
from .trialli import TrialliSource
from .torr import TorrSource
from .zimmermann import ZimmermannSource

PROFILES_PATH = Path(__file__).with_name("profiles.json")
CATALOG_PATH = Path(__file__).with_name("catalog.json")

BUILTIN = (SbPartsSource, BremboSource, TrialliSource, BrixoSource, NibkRuSource,
           LuzarSource, NissensSource, KybSource, HolaSource, BrannorSource, HelSource,
           JnbkSource, MintexSource)
CANDIDATES = (MetacoSource, MarshallSource, LynxautoSource, MasterkitSource, FapSource,
              GanzSource, ZimmermannSource, MonaerSource, AteSource, FebestSource, TorrSource)


class SourceRegistry:
    """Владеет адаптерами каталогов и знает, какой из них какую группу покрывает."""

    def __init__(self, settings):
        self.settings = settings
        self.pool = BrowserPool(settings)
        self._sources: dict[str, BaseSource] = {}
        self._candidate_keys = {cls.key for cls in CANDIDATES}
        self._pilot_rules = settings.pilot_rule_map

        for cls in BUILTIN:
            src = cls(settings, None, self.pool)
            self._sources[src.key] = src

        for cls in CANDIDATES:
            if cls.key in self._pilot_rules:
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

    def all(self, *, tenant: str | None = None) -> list[BaseSource]:
        return [
            source for source in self._sources.values()
            if source.key not in self._candidate_keys
            or self._pilot_tenant_allowed(source.key, tenant)
        ]

    def get(self, key: str, *, group: str | None = None,
            tenant: str | None = None) -> BaseSource | None:
        source = self._sources.get(key)
        if source is None or not self._source_allowed(source, group, tenant):
            return None
        return self._scoped(source, group)

    def for_group(self, group: str | None, *, tenant: str | None = None) -> list[BaseSource]:
        """Источники, покрывающие товарную группу и доступные tenant."""
        if not group:
            return self.all(tenant=tenant)
        return [
            source for source in self._sources.values()
            if self._source_allowed(source, group, tenant)
        ]

    def resolve(self, keys: list[str] | None, group: str | None = None,
                *, tenant: str | None = None) -> list[BaseSource]:
        """Явно запрошенные источники, иначе — умолчания, суженные по группе."""
        if keys:
            chosen = [self._sources[k] for k in keys if k in self._sources]
        else:
            chosen = [self._sources[k] for k in self.settings.default_sources
                      if k in self._sources]
            chosen.extend(
                source for source in self._sources.values()
                if source.key in self._candidate_keys
                and self._pilot_rules[source.key]["default"]
                and source not in chosen
            )
        return [
            self._scoped(source, group) for source in chosen
            if self._source_allowed(source, group, tenant)
        ]

    def _scoped(self, source: BaseSource, group: str | None) -> BaseSource:
        if source.key not in self._candidate_keys:
            return source
        scoped = copy(source)
        if group:
            scoped.groups = (group,)
        else:
            rule = self._pilot_rules[source.key]
            scoped.groups = tuple(
                value for value in source.groups if value in rule["groups"]
            ) if rule["ungrouped"] else ()
        version = source.cache_version
        scoped.cache_key = f"{source.key}:{'+'.join(scoped.groups)}"
        if version:
            scoped.cache_key += f"@{version}"
        return scoped

    def select_for_job(self, keys: list[str] | None, *, tenant: str) -> list[BaseSource]:
        """Выбрать источники задачи; проверка группы выполняется для каждой строки."""
        if keys:
            chosen = [self._sources[key] for key in keys if key in self._sources]
        else:
            chosen = [
                self._sources[key]
                for key in self.settings.default_sources
                if key in self._sources
            ]
            chosen.extend(
                source for source in self._sources.values()
                if source.key in self._candidate_keys
                and self._pilot_rules[source.key]["default"]
                and source not in chosen
            )
        return [
            source for source in chosen
            if source.key not in self._candidate_keys
            or self._pilot_tenant_allowed(source.key, tenant)
        ]

    def _pilot_tenant_allowed(self, key: str, tenant: str | None) -> bool:
        rule = self._pilot_rules.get(key)
        return bool(
            rule
            and tenant
            and ("*" in rule["tenants"] or tenant in rule["tenants"])
        )

    def _source_allowed(self, source: BaseSource, group: str | None,
                        tenant: str | None) -> bool:
        if source.key not in self._candidate_keys:
            # Preserve the existing profile-source behaviour: an older source
            # without declared groups remains universal. Candidate adapters are
            # fail-closed below and always require an exact group.
            if group is not None and source.groups and group not in source.groups:
                return False
            return True
        rule = self._pilot_rules.get(source.key)
        return bool(
            rule
            and tenant
            and ("*" in rule["tenants"] or tenant in rule["tenants"])
            and (
                (group is None and rule["ungrouped"])
                or (group in rule["groups"] and group in source.groups)
            )
        )

    def describe(self, tenant: str | None = None) -> list[dict]:
        return [
            {
                "key": s.key,
                "title": s.title,
                "homepage": s.homepage,
                "verified": s.verified,
                "note": s.note,
                "groups": self._visible_groups(s, tenant),
                "group_titles": [group_title(g) for g in self._visible_groups(s, tenant)],
                "enabled_by_default": (
                    s.key in self.settings.default_sources
                    if s.key not in self._candidate_keys
                    else self._pilot_rules[s.key]["default"]
                ),
            }
            for s in self.all(tenant=tenant)
        ]

    def _visible_groups(self, source: BaseSource, tenant: str | None) -> list[str]:
        if source.key not in self._candidate_keys:
            return list(source.groups)
        rule = self._pilot_rules.get(source.key, {})
        if not self._pilot_tenant_allowed(source.key, tenant):
            return []
        return [group for group in source.groups if group in rule.get("groups", [])]

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
