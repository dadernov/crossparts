"""Runs the configured sources for one OE number and merges their answers."""
from __future__ import annotations

import asyncio
import datetime as dt
import weakref
from dataclasses import replace

from sqlalchemy import select

from .models import CacheEntry, utcnow
from .normalize import KIND_AFTERMARKET, KIND_OEM, looks_like_part_number, number_key
from .sources.base import SourceResult, SourceStatus


class Aggregator:
    def __init__(self, settings, registry, session_factory):
        self.settings = settings
        self.registry = registry
        self.session_factory = session_factory
        # One gate per source: parallel across catalogues, polite within each.
        self._gates: dict[str, asyncio.Semaphore] = {}
        # A cache miss for the same source+number must produce one upstream
        # request. Weak values prevent an unbounded lock table over time.
        self._lookup_locks: weakref.WeakValueDictionary[
            tuple[str, str], asyncio.Lock
        ] = weakref.WeakValueDictionary()
        # One unavailable upstream must not add the same timeout to every new
        # part number. This is deliberately process-local and short-lived.
        self._source_failures: dict[str, tuple[float, SourceResult]] = {}

    async def lookup(self, oe: str, source_keys: list[str] | None = None,
                     *, use_cache: bool = True, group: str | None = None,
                     tenant: str | None = None) -> dict:
        # Товарная группа сужает список каталогов: искать колодки в каталоге
        # радиаторов бессмысленно и только тратит запросы.
        sources = self.registry.resolve(source_keys, group, tenant=tenant)
        results = await asyncio.gather(
            *(self._run_source(src, oe, use_cache) for src in sources)
        )
        attempts = None
        if getattr(self.settings, "circular_search_enabled", False):
            results, attempts = await self._circular_search(oe, sources, results, use_cache)
        merged = self.merge(oe, results)
        if attempts is not None:
            merged["circular_search"] = {"attempts": attempts}
        merged["group"] = group
        if not sources:
            merged["status"] = "no_sources"
            merged["message"] = "для этой товарной группы пока нет готовых источников"
        return merged

    async def _circular_search(self, oe, sources, results, use_cache):
        """One bounded pass using only direct matches; never recurse or cache expansion."""
        candidates = []
        seen = {number_key(oe)}
        for result in results:
            if result.status is not SourceStatus.OK:
                continue
            for cross in result.crosses:
                key = number_key(cross.number)
                if (key in seen or cross.kind not in (KIND_OEM, KIND_AFTERMARKET)
                        or not looks_like_part_number(key)):
                    continue
                seen.add(key)
                candidates.append(key)

        # Each source receives the same first candidate before any gets a second.
        active = [i for i, result in enumerate(results)
                  if result.status is SourceStatus.NOT_FOUND]
        expanded = list(results)
        attempts = []
        budget = self.settings.circular_search_max_queries
        deadline = asyncio.get_running_loop().time() + self.settings.circular_search_timeout

        async def query(index, number, remaining):
            try:
                return await asyncio.wait_for(
                    self._run_source(sources[index], number, use_cache), remaining)
            except asyncio.TimeoutError:
                return SourceResult(sources[index].key, SourceStatus.ERROR,
                                    message="таймаут кругового поиска")

        for number in candidates[:self.settings.circular_search_max_queries_per_source]:
            remaining = deadline - asyncio.get_running_loop().time()
            if not active or budget <= 0 or remaining <= 0:
                break
            batch = active[:budget]
            budget -= len(batch)
            replies = await asyncio.gather(*(query(i, number, remaining) for i in batch))
            for index, reply in zip(batch, replies):
                attempts.append({"source": reply.source, "number": number,
                                 "status": reply.status.value, "crosses": len(reply.crosses),
                                 "message": reply.message})
                if reply.status is SourceStatus.OK and reply.crosses:
                    original = results[index]
                    # Copy instead of mutating a cached direct response. Reports remain
                    # one per catalogue, with the successful indirect query explained.
                    expanded[index] = replace(
                        reply, elapsed_ms=original.elapsed_ms + reply.elapsed_ms,
                        message=f"Найдено через кросс {number}")
                    active.remove(index)
                elif reply.status in (SourceStatus.BLOCKED, SourceStatus.ERROR):
                    active.remove(index)
        return expanded, attempts

    # -- one source -----------------------------------------------------

    async def _run_source(self, source, oe: str, use_cache: bool) -> SourceResult:
        use_cache = use_cache and getattr(source, "cache_enabled", True)
        cache_source = getattr(source, "cache_key", source.key)
        key = number_key(oe)
        if use_cache:
            cached = await self._cache_get(cache_source, key)
            if cached is not None:
                return cached
        failure = self._active_source_failure(source.key)
        if failure is not None:
            return failure
        lock = self._lookup_lock_for(cache_source, key) if use_cache else None
        if lock is None:
            return await self._lookup_and_cache(
                source, oe, key, cache_source=cache_source, use_cache=False
            )
        async with lock:
            # Another coroutine may have filled the cache while this one was
            # waiting for the same source+number lock.
            cached = await self._cache_get(cache_source, key)
            if cached is not None:
                return cached
            return await self._lookup_and_cache(
                source, oe, key, cache_source=cache_source, use_cache=True
            )

    async def _lookup_and_cache(self, source, oe: str, key: str,
                                *, cache_source: str, use_cache: bool) -> SourceResult:
        async with self._gate_for(source.key):
            failure = self._active_source_failure(source.key)
            if failure is not None:
                return failure
            try:
                result = await asyncio.wait_for(
                    source.lookup(oe), timeout=self.settings.source_timeout + 15
                )
            except asyncio.TimeoutError:
                result = SourceResult(
                    source.key, SourceStatus.ERROR, message="таймаут источника"
                )
            except Exception as exc:
                result = SourceResult(
                    source.key, SourceStatus.ERROR, message=str(exc)[:300]
                )
        if result.status in (SourceStatus.ERROR, SourceStatus.BLOCKED):
            self._remember_source_failure(source.key, result)
        else:
            self._source_failures.pop(source.key, None)
        # Only cache deterministic answers; blocks and errors should be retried.
        if use_cache and result.status in (SourceStatus.OK, SourceStatus.NOT_FOUND):
            await self._cache_put(cache_source, key, result)
        return result

    def _remember_source_failure(self, source: str, result: SourceResult) -> None:
        cooldown = getattr(self.settings, "source_failure_cooldown_seconds", 300)
        if cooldown > 0:
            until = asyncio.get_running_loop().time() + cooldown
            self._source_failures[source] = (until, result)

    def _active_source_failure(self, source: str) -> SourceResult | None:
        stored = self._source_failures.get(source)
        if stored is None:
            return None
        until, result = stored
        if asyncio.get_running_loop().time() >= until:
            self._source_failures.pop(source, None)
            return None
        return replace(result, elapsed_ms=0)

    def _lookup_lock_for(self, source: str, oe_key: str) -> asyncio.Lock:
        key = (source, oe_key)
        lock = self._lookup_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._lookup_locks[key] = lock
        return lock

    def _gate_for(self, key: str) -> asyncio.Semaphore:
        gate = self._gates.get(key)
        if gate is None:
            gate = asyncio.Semaphore(max(1, self.settings.source_concurrency))
            self._gates[key] = gate
        return gate

    async def _cache_get(self, source: str, oe_key: str) -> SourceResult | None:
        ttl = dt.timedelta(hours=self.settings.cache_ttl_hours)
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(CacheEntry).where(
                        CacheEntry.source == source, CacheEntry.oe_key == oe_key
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                return None
            created = row.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=dt.timezone.utc)
            if utcnow() - created > ttl:
                return None
            return SourceResult.from_dict(row.payload)

    async def _cache_put(self, source: str, oe_key: str, result: SourceResult) -> None:
        async with self.session_factory() as session:
            row = (
                await session.execute(
                    select(CacheEntry).where(
                        CacheEntry.source == source, CacheEntry.oe_key == oe_key
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                session.add(CacheEntry(source=source, oe_key=oe_key, payload=result.to_dict()))
            else:
                row.payload = result.to_dict()
                row.created_at = utcnow()
            await session.commit()

    # -- merging --------------------------------------------------------

    @staticmethod
    def merge(oe: str, results: list[SourceResult]) -> dict:
        """Deduplicate crosses across sources, keeping provenance."""
        merged: dict[tuple[str, str], dict] = {}
        for res in results:
            for cross in res.crosses:
                slot = merged.get(cross.key)
                if slot is None:
                    merged[cross.key] = {
                        "brand": cross.brand,
                        "number": cross.number,
                        "kind": cross.kind,
                        "sources": [cross.source],
                        "source_products": [cross.source_product] if cross.source_product else [],
                        "url": cross.url,
                    }
                else:
                    if cross.source not in slot["sources"]:
                        slot["sources"].append(cross.source)
                    if cross.source_product and cross.source_product not in slot["source_products"]:
                        slot["source_products"].append(cross.source_product)

        crosses = sorted(merged.values(), key=lambda c: (c["brand"], c["number"]))
        # The searched OE number itself is not a useful "cross" in the output.
        oe_key = number_key(oe)
        crosses = [c for c in crosses if number_key(c["number"]) != oe_key] + [
            c for c in crosses if number_key(c["number"]) == oe_key
        ]

        status = "not_found"
        if any(r.status is SourceStatus.OK for r in results):
            status = "ok"
        elif any(r.status is SourceStatus.BLOCKED for r in results) and not any(
            r.status is SourceStatus.NOT_FOUND for r in results
        ):
            status = "blocked"
        elif all(r.status is SourceStatus.ERROR for r in results) and results:
            status = "error"

        return {
            "oe": oe,
            "status": status,
            "crosses": crosses,
            "unique_numbers": _unique_numbers(crosses),
            "sources": [r.to_dict() | {"crosses": len(r.crosses)} for r in results],
        }


def _unique_numbers(crosses: list[dict]) -> list[str]:
    seen, out = set(), []
    for c in crosses:
        k = number_key(c["number"])
        if k not in seen:
            seen.add(k)
            out.append(c["number"])
    return out
