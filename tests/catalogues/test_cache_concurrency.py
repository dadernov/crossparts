from __future__ import annotations

import asyncio

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.aggregator import Aggregator
from app.models import Base
from app.sources.base import Cross, SourceResult, SourceStatus


class _Source:
    key = "concurrency-fixture"

    def __init__(self):
        self.calls = 0

    async def lookup(self, oe):
        self.calls += 1
        await asyncio.sleep(0.01)
        return SourceResult(
            self.key,
            SourceStatus.OK,
            crosses=[Cross("TEST", f"CROSS-{oe}", "aftermarket", self.key)],
        )


class _ErrorSource:
    key = "error-fixture"

    def __init__(self):
        self.calls = 0

    async def lookup(self, oe):
        self.calls += 1
        return SourceResult(self.key, SourceStatus.ERROR, message="upstream unavailable")


class _PartialSource:
    key = "partial-fixture"

    def __init__(self):
        self.calls = 0

    async def lookup(self, oe):
        self.calls += 1
        return SourceResult(
            self.key,
            SourceStatus.PARTIAL,
            crosses=[Cross("TEST", f"PARTIAL-{oe}", "aftermarket", self.key)],
            message="one card failed",
        )


class _Registry:
    def __init__(self, source):
        self.source = source

    def resolve(self, keys, group, *, tenant=None):
        return [self.source]


@pytest.mark.asyncio
async def test_twenty_concurrent_identical_cache_misses_use_one_source_call(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'cache.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source = _Source()
    settings = type("Settings", (), {
        "source_concurrency": 4,
        "source_timeout": 1,
        "cache_ttl_hours": 168,
        "circular_search_enabled": False,
    })()
    aggregator = Aggregator(settings, _Registry(source), sessions)

    results = await asyncio.gather(*(
        aggregator.lookup("OE-123", use_cache=True) for _ in range(20)
    ))

    assert source.calls == 1
    assert {result["crosses"][0]["number"] for result in results} == {"CROSS-OE-123"}
    assert not aggregator._lookup_locks
    await engine.dispose()


@pytest.mark.asyncio
async def test_cache_bypass_remains_an_explicit_fresh_lookup(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'bypass.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source = _Source()
    settings = type("Settings", (), {
        "source_concurrency": 4,
        "source_timeout": 1,
        "cache_ttl_hours": 168,
        "circular_search_enabled": False,
    })()
    aggregator = Aggregator(settings, _Registry(source), sessions)

    await asyncio.gather(*(
        aggregator.lookup("OE-123", use_cache=False) for _ in range(5)
    ))

    assert source.calls == 5
    await engine.dispose()


@pytest.mark.asyncio
async def test_failing_source_is_short_circuited_for_other_numbers(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'failure.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source = _ErrorSource()
    settings = type("Settings", (), {
        "source_concurrency": 1,
        "source_timeout": 1,
        "source_failure_cooldown_seconds": 300,
        "cache_ttl_hours": 168,
        "circular_search_enabled": False,
    })()
    aggregator = Aggregator(settings, _Registry(source), sessions)

    first = await aggregator.lookup("OE-ONE")
    second = await aggregator.lookup("OE-TWO")

    assert first["status"] == second["status"] == "error"
    assert source.calls == 1
    assert second["sources"][0]["elapsed_ms"] == 0
    await engine.dispose()


@pytest.mark.asyncio
async def test_zero_failure_cooldown_does_not_suppress_retries(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'no-cooldown.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source = _ErrorSource()
    settings = type("Settings", (), {
        "source_concurrency": 1,
        "source_timeout": 1,
        "source_failure_cooldown_seconds": 0,
        "cache_ttl_hours": 168,
        "circular_search_enabled": False,
    })()
    aggregator = Aggregator(settings, _Registry(source), sessions)

    await aggregator.lookup("OE-ONE")
    await aggregator.lookup("OE-TWO")

    assert source.calls == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_partial_result_is_explicit_and_never_cached(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'partial.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    source = _PartialSource()
    settings = type("Settings", (), {
        "source_concurrency": 1,
        "source_timeout": 1,
        "source_failure_cooldown_seconds": 0,
        "cache_ttl_hours": 168,
        "circular_search_enabled": False,
    })()
    aggregator = Aggregator(settings, _Registry(source), sessions)

    first = await aggregator.lookup("OE-123")
    second = await aggregator.lookup("OE-123")

    assert first["status"] == second["status"] == "partial"
    assert source.calls == 2
    await engine.dispose()
