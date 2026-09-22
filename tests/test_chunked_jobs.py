import asyncio
import datetime as dt
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.config import Settings
from app.jobs import JobRunner
from app.models import Base, Job, JobItem, TenantDailyUsage
from app.pacing import TenantPacer


async def sessions_for(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/jobs.db")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


class Registry:
    def select_for_job(self, sources, tenant=None):
        return [SimpleNamespace(key="catalogue")]


class Aggregator:
    def __init__(self):
        self.calls = []

    async def lookup(self, oe, sources, group=None, tenant=None):
        self.calls.append((tenant, oe))
        return {
            "status": "ok",
            "crosses": [{"brand": "TEST", "number": f"X-{oe}", "sources": ["catalogue"]}],
            "sources": [{"source": "catalogue", "status": "ok", "crosses": []}],
        }


@pytest.mark.asyncio
async def test_admin_upload_is_split_sequentially_and_gets_final_summary(tmp_path, monkeypatch):
    engine, sessions = await sessions_for(tmp_path)
    settings = Settings(
        _env_file=None,
        job_chunk_sizes="gerat:50,admin:10",
        paced_tenants="",
        job_concurrency=2,
        api_keys="",
        users="",
    )
    aggregator = Aggregator()
    runner = JobRunner(settings, aggregator, sessions)
    await runner.start()
    charge = AsyncMock()
    monkeypatch.setattr(main, "settings", settings)
    monkeypatch.setattr(main, "SessionLocal", sessions)
    monkeypatch.setattr(main, "registry", Registry())
    monkeypatch.setattr(main, "runner", runner)
    monkeypatch.setattr(main, "reserve_queries", charge)
    items = [{"our_sku": f"SKU-{index:02d}", "oe_number": f"OE{index:02d}"}
             for index in range(33)]
    try:
        first = await main._create_job(items, None, "admin", "test-33.xlsx")
        assert first.total == 10
        assert first.filename == "test-33.xlsx · часть 1/4"
        await asyncio.wait_for(runner._queue.join(), timeout=5)

        async with sessions() as session:
            jobs = (await session.execute(
                select(Job).where(Job.tenant == "admin").order_by(Job.batch_role, Job.batch_order)
            )).scalars().all()
            chunks = sorted((job for job in jobs if job.batch_role == "chunk"),
                            key=lambda job: job.batch_order)
            summary = next(job for job in jobs if job.batch_role == "summary")
            assert [job.total for job in chunks] == [10, 10, 10, 3]
            assert all(job.status == "done" for job in chunks)
            assert summary.total == summary.done == 33
            assert summary.filename == "test-33.xlsx · полный результат"
            summary_items = (await session.execute(
                select(JobItem).where(JobItem.job_id == summary.id).order_by(JobItem.position)
            )).scalars().all()
            assert [item.oe_number for item in summary_items] == [f"OE{i:02d}" for i in range(33)]
        assert aggregator.calls == [("admin", f"OE{i:02d}") for i in range(33)]
        charge.assert_awaited_once_with(sessions, "admin", 33, settings.requests_per_account)
    finally:
        await runner.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_gerat_pacing_switches_to_slow_slots_after_daily_allowance(tmp_path):
    engine, sessions = await sessions_for(tmp_path)
    settings = Settings(
        _env_file=None,
        paced_tenants="gerat",
        paced_daily_fast_limit=3,
        paced_fast_window_seconds=30,
        paced_slow_interval_seconds=1200,
        users="",
    )
    pacer = TenantPacer(settings, sessions)
    now = dt.datetime(2026, 9, 22, 8, 0, tzinfo=dt.timezone.utc)
    assert [await pacer.reserve("gerat", now=now) for _ in range(5)] == [0, 10, 20, 1220, 2420]
    assert await pacer.reserve("admin", now=now) == 0
    assert await pacer.reserve("gerat", now=now + dt.timedelta(days=1)) == 0
    async with sessions() as session:
        rows = (await session.execute(select(TenantDailyUsage))).scalars().all()
        assert [(row.day, row.count) for row in rows] == [("2026-09-22", 5), ("2026-09-23", 1)]
    await engine.dispose()
