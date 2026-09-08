"""Runs the configured sources for one OE number and merges their answers."""
from __future__ import annotations

import asyncio
import datetime as dt

from sqlalchemy import select

from .models import CacheEntry, utcnow
from .normalize import number_key
from .sources.base import SourceResult, SourceStatus


class Aggregator:
    def __init__(self, settings, registry, session_factory):
        self.settings = settings
        self.registry = registry
        self.session_factory = session_factory
        # One gate per source: parallel across catalogues, polite within each.
        self._gates: dict[str, asyncio.Semaphore] = {}

    async def lookup(self, oe: str, source_keys: list[str] | None = None,
                     *, use_cache: bool = True, group: str | None = None) -> dict:
        # Товарная группа сужает список каталогов: искать колодки в каталоге
        # радиаторов бессмысленно и только тратит запросы.
        sources = self.registry.resolve(source_keys, group)
        results = await asyncio.gather(
            *(self._run_source(src, oe, use_cache) for src in sources)
        )
        merged = self.merge(oe, results)
        merged["group"] = group
        if not sources:
            merged["status"] = "no_sources"
            merged["message"] = "для этой товарной группы пока нет готовых источников"
        return merged

    # -- one source -----------------------------------------------------

    async def _run_source(self, source, oe: str, use_cache: bool) -> SourceResult:
        key = number_key(oe)
        if use_cache:
            cached = await self._cache_get(source.key, key)
            if cached is not None:
                return cached
        async with self._gate_for(source.key):
            try:
                result = await asyncio.wait_for(
                    source.lookup(oe), timeout=self.settings.source_timeout + 15
                )
            except asyncio.TimeoutError:
                return SourceResult(source.key, SourceStatus.ERROR, message="таймаут источника")
            except Exception as exc:
                return SourceResult(source.key, SourceStatus.ERROR, message=str(exc)[:300])
        # Only cache deterministic answers; blocks and errors should be retried.
        if result.status in (SourceStatus.OK, SourceStatus.NOT_FOUND):
            await self._cache_put(source.key, key, result)
        return result

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
