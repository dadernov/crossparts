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


class _Registry:
    def __init__(self, source):
        self.source = source

    def resolve(self, keys, group):
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

