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
from .pacing import TenantPacer

log = logging.getLogger("crossparts.jobs")


class JobRunner:
    def __init__(self, settings, aggregator, session_factory):
        self.settings = settings
        self.aggregator = aggregator
        self.session_factory = session_factory
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._workers: list[asyncio.Task] = []
        self._batch_locks: dict[str, asyncio.Lock] = {}
        self._delayed_submissions: set[asyncio.Task] = set()
        self._reserved_items: set[int] = set()
        self.pacer = TenantPacer(settings, session_factory)

    async def start(self) -> None:
        for _ in range(max(1, self.settings.job_concurrency)):
            self._workers.append(asyncio.create_task(self._worker()))
        await self._requeue_unfinished()

    async def stop(self) -> None:
        for task in self._workers:
            task.cancel()
        for task in self._delayed_submissions:
            task.cancel()
        if self._workers:
            await asyncio.gather(*self._workers, return_exceptions=True)
        if self._delayed_submissions:
            await asyncio.gather(*self._delayed_submissions, return_exceptions=True)
        self._workers.clear()
        self._delayed_submissions.clear()
        self._reserved_items.clear()

    async def submit(self, job_id: str) -> None:
        await self._queue.put(job_id)

    async def _requeue_unfinished(self) -> None:
        async with self.session_factory() as session:
            rows = (
                await session.execute(
                    select(Job).where(Job.status.in_(["pending", "running"]))
                    .order_by(Job.batch_order, Job.created_at)
                )
            ).scalars().all()
            ready_batches = (
                await session.execute(
                    select(Job.batch_id).where(
                        Job.batch_role == "chunk", Job.batch_id.is_not(None)
                    ).distinct()
                )
            ).scalars().all()
        queued_batches = set()
        for job in rows:
            if job.batch_role == "chunk" and job.batch_id:
                if job.batch_id in queued_batches:
                    continue
                queued_batches.add(job.batch_id)
            await self._queue.put(job.id)
        for batch_id in ready_batches:
            if batch_id not in queued_batches:
                await self._advance_batch(batch_id)

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
            tenant = job.tenant
            batch_id = job.batch_id if job.batch_role == "chunk" else None
            item = (
                await session.execute(
                    select(JobItem).where(
                        JobItem.job_id == job_id,
                        JobItem.status == "pending",
                    ).order_by(JobItem.position)
                )
            ).scalars().first()

        if item is None:
            await self._finish_job(job_id, batch_id)
            return

        item_id, oe, group = item.id, item.oe_number, item.group
        if item_id in self._reserved_items:
            self._reserved_items.discard(item_id)
        else:
            delay = await self.pacer.reserve(tenant)
            if delay > 0:
                self._defer(job_id, item_id, delay)
                return

        result = await self.aggregator.lookup(
            oe, sources, group=group, tenant=tenant
        )
        async with self.session_factory() as session:
            current = await session.get(JobItem, item_id)
            if current is not None and current.status == "pending":
                current.crosses = result["crosses"]
                current.source_reports = [
                    {k: v for k, v in r.items() if k != "crosses"} | {"crosses": r["crosses"]}
                    for r in result["sources"]
                ]
                current.status = result["status"]
                await session.flush()
            current_job = await session.get(Job, job_id)
            if current_job is None:
                return
            current_job.done = await _completed_count(session, job_id)
            remaining = current_job.done < current_job.total
            await session.commit()

        if remaining:
            await self._queue.put(job_id)
        else:
            await self._finish_job(job_id, batch_id)

    def _defer(self, job_id: str, item_id: int, delay: float) -> None:
        """Return the worker immediately and queue an already reserved item later."""
        async def submit_after() -> None:
            await asyncio.sleep(delay)
            self._reserved_items.add(item_id)
            await self._queue.put(job_id)

        task = asyncio.create_task(submit_after())
        self._delayed_submissions.add(task)
        task.add_done_callback(self._delayed_submissions.discard)

    async def _finish_job(self, job_id: str, batch_id: str | None) -> None:
        async with self.session_factory() as session:
            job = await session.get(Job, job_id)
            if job is not None:
                job.done = await _completed_count(session, job_id)
                job.status = "done"
                job.finished_at = utcnow()
                await session.commit()
        if batch_id:
            await self._advance_batch(batch_id)

    async def _advance_batch(self, batch_id: str) -> None:
        """Start the next chunk, or create the combined history result."""
        lock = self._batch_locks.setdefault(batch_id, asyncio.Lock())
        async with lock:
            async with self.session_factory() as session:
                chunks = (
                    await session.execute(
                        select(Job).where(
                            Job.batch_id == batch_id, Job.batch_role == "chunk"
                        ).order_by(Job.batch_order)
                    )
                ).scalars().all()
                if not chunks:
                    return
                if any(job.status == "running" for job in chunks):
                    return
                next_job = next((job for job in chunks if job.status == "pending"), None)
                if next_job is not None:
                    # Move the newly active part to the top of the history list.
                    next_job.created_at = utcnow()
                    next_id = next_job.id
                    await session.commit()
                else:
                    next_id = None
                    if not all(job.status == "done" for job in chunks):
                        return
                    existing = (
                        await session.execute(
                            select(Job.id).where(
                                Job.batch_id == batch_id, Job.batch_role == "summary"
                            )
                        )
                    ).scalar_one_or_none()
                    if existing is not None:
                        return
                    await self._create_batch_summary(session, batch_id, chunks)
                    await session.commit()
            if next_id:
                await self._queue.put(next_id)

    async def _create_batch_summary(self, session, batch_id: str, chunks: list[Job]) -> None:
        first = chunks[0]
        base_name = (first.filename or "Общий поиск").rsplit(" · часть ", 1)[0]
        summary = Job(
            tenant=first.tenant,
            status="done",
            total=sum(job.total for job in chunks),
            done=sum(job.done for job in chunks),
            sources=list(first.sources or []),
            filename=f"{base_name} · полный результат"[:255],
            finished_at=utcnow(),
            batch_id=batch_id,
            batch_role="summary",
            batch_order=len(chunks),
        )
        session.add(summary)
        await session.flush()
        position = 0
        for chunk in chunks:
            items = (
                await session.execute(
                    select(JobItem).where(JobItem.job_id == chunk.id)
                    .order_by(JobItem.position)
                )
            ).scalars().all()
            for item in items:
                session.add(JobItem(
                    job_id=summary.id,
                    position=position,
                    our_sku=item.our_sku,
                    part_name=item.part_name,
                    oe_number=item.oe_number,
                    group=item.group,
                    group_raw=item.group_raw,
                    status=item.status,
                    crosses=item.crosses,
                    source_reports=item.source_reports,
                    error=item.error,
                ))
                position += 1

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
