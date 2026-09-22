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


@pytest.mark.asyncio
async def test_restart_resumes_unfinished_chunk_and_summary_is_idempotent(tmp_path):
    engine, sessions = await sessions_for(tmp_path)
    settings = Settings(_env_file=None, paced_tenants='', job_concurrency=1)
    aggregator = Aggregator()
    async with sessions() as session:
        for index, status in enumerate(['done', 'running', 'pending']):
            job = Job(id=f'chunk{index}', tenant='audit', batch_id='batch', batch_role='chunk',
                      batch_order=index, total=1, done=int(status=='done'), status=status,
                      sources=['catalogue'], filename=f'test.xlsx · часть {index+1}/3')
            session.add(job)
            session.add(JobItem(job_id=job.id, position=index, oe_number=f'OE{index}',
                                our_sku=f'SKU{index}', status='ok' if index==0 else 'pending',
                                crosses=[], source_reports=[]))
        await session.commit()
    runner = JobRunner(settings, aggregator, sessions)
    try:
        await runner.start()
        await asyncio.wait_for(runner._queue.join(), 5)
        await runner._advance_batch('batch')
        await runner._advance_batch('batch')
        async with sessions() as session:
            jobs=(await session.execute(select(Job))).scalars().all()
            summaries=[j for j in jobs if j.batch_role=='summary']
            assert len(summaries)==1
            assert summaries[0].done==summaries[0].total==3
            items=(await session.execute(select(JobItem).where(JobItem.job_id==summaries[0].id).order_by(JobItem.position))).scalars().all()
            assert [i.our_sku for i in items]==['SKU0','SKU1','SKU2']
        assert aggregator.calls==[('audit','OE1'),('audit','OE2')]
    finally:
        await runner.stop()
        await engine.dispose()


@pytest.mark.asyncio
async def test_pacing_cursor_survives_runner_restart(tmp_path):
    engine, sessions=await sessions_for(tmp_path)
    settings=Settings(_env_file=None,paced_tenants='audit',paced_daily_fast_limit=3,paced_fast_window_seconds=30)
    now=dt.datetime(2026,9,22,8,tzinfo=dt.timezone.utc)
    try:
        assert await TenantPacer(settings,sessions).reserve('audit',now=now)==0
        assert await TenantPacer(settings,sessions).reserve('audit',now=now)==10
        assert await TenantPacer(settings,sessions).reserve('other',now=now)==0
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_paced_tenant_does_not_occupy_worker_while_waiting(tmp_path):
    engine, sessions = await sessions_for(tmp_path)
    settings = Settings(
        _env_file=None,
        paced_tenants="slow",
        paced_daily_fast_limit=2,
        paced_fast_window_seconds=1,
        paced_slow_interval_seconds=1,
        job_concurrency=1,
    )
    aggregator = Aggregator()
    async with sessions() as session:
        slow = Job(id="slow-job", tenant="slow", total=2, sources=["catalogue"])
        fast = Job(id="fast-job", tenant="fast", total=1, sources=["catalogue"])
        session.add_all([slow, fast])
        session.add_all([
            JobItem(job_id=slow.id, position=0, oe_number="SLOW-1"),
            JobItem(job_id=slow.id, position=1, oe_number="SLOW-2"),
            JobItem(job_id=fast.id, position=0, oe_number="FAST-1"),
        ])
        await session.commit()

    runner = JobRunner(settings, aggregator, sessions)
    try:
        await runner.start()
        await runner.submit("slow-job")
        await runner.submit("fast-job")
        for _ in range(50):
            if ("fast", "FAST-1") in aggregator.calls:
                break
            await asyncio.sleep(0.02)
        assert ("fast", "FAST-1") in aggregator.calls
        assert ("slow", "SLOW-2") not in aggregator.calls
        for _ in range(100):
            if ("slow", "SLOW-2") in aggregator.calls:
                break
            await asyncio.sleep(0.02)
        assert aggregator.calls.index(("fast", "FAST-1")) < aggregator.calls.index(("slow", "SLOW-2"))
    finally:
        await runner.stop()
        await engine.dispose()
