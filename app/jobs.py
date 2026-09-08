"""In-process job runner.

Jobs live in SQLite, so a restart can pick up whatever was left ``running``.
For a single-node MVP an asyncio worker is enough; the same interface swaps to
Celery/RQ later without touching the API layer.
"""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import func, select

from .models import Job, JobItem, utcnow

log = logging.getLogger("crossparts.jobs")


class JobRunner:
    def __init__(self, settings, aggregator, session_factory):
        self.settings = settings
        self.aggregator = aggregator
        self.session_factory = session_factory
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []

    async def start(self) -> None:
        for _ in range(max(1, self.settings.job_concurrency)):
            self._workers.append(asyncio.create_task(self._worker()))
        await self._requeue_unfinished()

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        self._workers.clear()

    async def submit(self, job_id: str) -> None:
        await self._queue.put(job_id)

    async def _requeue_unfinished(self) -> None:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Job.id).where(Job.status.in_(["pending", "running"]))
                )
            ).scalars().all()
        for job_id in rows:
            await self._queue.put(job_id)

    async def _worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run_job(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("job %s failed", job_id)
                await self._mark_failed(job_id)
            finally:
                self._queue.task_done()

    async def _run_job(self, job_id: str) -> None:
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is None or job.status == "done":
                return
            job.status = "running"
            await session.commit()
            sources = list(job.sources or [])
            pending = (
                await session.execute(
                    select(JobItem).where(
                        JobItem.job_id == job_id,
                        JobItem.status.in_(["pending", "error", "blocked"]),
                    ).order_by(JobItem.position)
                )
            ).scalars().all()
            todo = [(i.id, i.oe_number, i.group) for i in pending]

        for item_id, oe, group in todo:
            result = await self.aggregator.lookup(oe, sources, group=group)
            async with self.session_factory() as session:
                item = await session.get(JobItem, item_id)
                if item is None:
                    continue
                item.crosses = result["crosses"]
                item.source_reports = [
                    {k: v for k, v in r.items() if k != "crosses"} | {"crosses": r["crosses"]}
                    for r in result["sources"]
                ]
                item.status = result["status"]
                await session.flush()
                job = await session.get(Job, job_id)
                job.done = await _completed_count(session, job_id)
                await session.commit()

        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                job.status = "done"
                job.finished_at = utcnow()
                await session.commit()

    async def _mark_failed(self, job_id: str) -> None:
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                job.status = "failed"
                job.finished_at = utcnow()
                await session.commit()


async def _completed_count(session, job_id: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count(JobItem.id)).where(
                    JobItem.job_id == job_id, JobItem.status != "pending"
                )
            )
        ).scalar_one()
    )
