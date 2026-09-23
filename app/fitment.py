"""Admin-only pilot service for explicit vehicle-applicability enrichment."""
from __future__ import annotations

import asyncio
from collections import defaultdict
import datetime as dt
import time
import weakref

from sqlalchemy import select

from .fitment_data import normalize_result, persist_result
from .models import CacheEntry, utcnow
from .normalize import number_key
from .sources.kyb_fitment import KybFitmentSource
from .sources.hola_fitment import HolaFitmentSource
from .sources.metaco_fitment import MetacoFitmentSource
from .sources.torr_fitment import TorrFitmentSource
from .sources.trialli_fitment import TrialliFitmentSource


class FitmentService:
    def __init__(self, settings, session_factory):
        self.settings = settings
        self.session_factory = session_factory
        self.sources = {
            source.brand: source(settings)
            for source in (
                TrialliFitmentSource, TorrFitmentSource, KybFitmentSource,
                HolaFitmentSource, MetacoFitmentSource,
            )
        }
        self._gate = asyncio.Semaphore(1)
        self._metrics = defaultdict(lambda: {"requests": 0, "cache_hits": 0,
                                             "errors": 0, "elapsed_ms": 0})
        self._locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
            weakref.WeakValueDictionary()
        )

    @property
    def supported_brands(self) -> tuple[str, ...]:
        return tuple(self.sources)

    async def lookup(self, brand: str, article: str) -> dict:
        source = self.sources[brand.strip().upper()]
        key = number_key(article)
        cached = await self._cache_get(source, key)
        if cached is not None:
            self._metrics[source.key]["cache_hits"] += 1
            result = normalize_result(cached, source)
            if result["status"] == "ok":
                await persist_result(self.session_factory, result)
            return result | {"cached": True}

        lock_key = f"{source.key}:{key}"
        lock = self._locks.get(lock_key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[lock_key] = lock
        async with lock:
            cached = await self._cache_get(source, key)
            if cached is not None:
                self._metrics[source.key]["cache_hits"] += 1
                result = normalize_result(cached, source)
                if result["status"] == "ok":
                    await persist_result(self.session_factory, result)
                return result | {"cached": True}
            async with self._gate:
                started = time.monotonic()
                self._metrics[source.key]["requests"] += 1
                for attempt in range(self.settings.fitment_retry_attempts):
                    try:
                        result = await asyncio.wait_for(
                            source.lookup(article), timeout=self.settings.source_timeout + 15
                        )
                    except asyncio.TimeoutError:
                        result = source._result(article, "error", message=f"Таймаут {source.brand}")
                    if result.get("status") != "error" or attempt + 1 >= self.settings.fitment_retry_attempts:
                        break
                    await asyncio.sleep(0.25 * (2 ** attempt))
                elapsed = round((time.monotonic() - started) * 1000)
                self._metrics[source.key]["elapsed_ms"] += elapsed
                if result.get("status") in {"error", "blocked"}:
                    self._metrics[source.key]["errors"] += 1
            result = normalize_result(result, source)
            if result["status"] in {"ok", "not_found"}:
                await self._cache_put(source, key, result)
            if result["status"] == "ok":
                await persist_result(self.session_factory, result)
            return result | {"cached": False}

    async def _cache_get(self, source, key: str) -> dict | None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(CacheEntry).where(
                        CacheEntry.source == source.cache_key,
                        CacheEntry.oe_key == key,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            created = row.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=dt.timezone.utc)
            hours = (self.settings.fitment_not_found_ttl_hours
                     if row.payload.get("status") == "not_found"
                     else self.settings.cache_ttl_hours)
            ttl = dt.timedelta(hours=hours)
            if utcnow() - created > ttl:
                return None
            return dict(row.payload)

    async def _cache_put(self, source, key: str, payload: dict) -> None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(CacheEntry).where(
                        CacheEntry.source == source.cache_key,
                        CacheEntry.oe_key == key,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(
                    CacheEntry(source=source.cache_key, oe_key=key, payload=payload)
                )
            else:
                row.payload = payload
                row.created_at = utcnow()
            await session.commit()

    def metrics_snapshot(self) -> dict:
        return {key: dict(value) for key, value in sorted(self._metrics.items())}
