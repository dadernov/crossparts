"""Persistent queue for explicit fitment enrichment batches."""
from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from .models import FitmentJob, utcnow


log = logging.getLogger("crossparts.fitment_jobs")


class FitmentJobRunner:
    def __init__(self, service, session_factory):
        self.service = service
        self.session_factory = session_factory
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._worker_task = asyncio.create_task(self._worker())
        async with self.session_factory() as session:
            jobs = (await session.execute(
                select(FitmentJob).where(FitmentJob.status.in_(["queued", "running"]))
                .order_by(FitmentJob.created_at)
            )).scalars().all()
            for job in jobs:
                job.status = "queued"
            await session.commit()
        for job in jobs:
            await self.submit(job.id)

    async def stop(self) -> None:
        if self._worker_task is None:
            return
        self._worker_task.cancel()
        await asyncio.gather(self._worker_task, return_exceptions=True)
        self._worker_task = None

    async def submit(self, job_id: str) -> None:
        await self._queue.put(job_id)

    async def _worker(self) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._run(job_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("fitment job %s failed", job_id)
                await self._fail(job_id, "Внутренняя ошибка задания")
            finally:
                self._queue.task_done()

    async def _run(self, job_id: str) -> None:
        async with self.session_factory() as session:
            job = await session.get(FitmentJob, job_id)
            if job is None or job.status in {"done", "partial", "failed", "cancelled"}:
                return
            job.status = "running"; await session.commit()

        while True:
            async with self.session_factory() as session:
                job = await session.get(FitmentJob, job_id)
                if job is None:
                    return
                if job.cancel_requested:
                    job.status = "cancelled"; job.finished_at = utcnow(); await session.commit(); return
                if job.processed_count >= job.total:
                    ok = sum(1 for item in job.results if item.get("status") == "ok")
                    job.status = "done" if ok == job.total else "partial" if ok else "failed"
                    job.finished_at = utcnow(); await session.commit(); return
                index = job.processed_count
                part = job.requested_parts[index]

            try:
                result = await self.service.lookup(part["brand"], part["number"])
                error = None
                if result.get("status") in {"error", "blocked"}:
                    error = {
                        "position": index, "brand": part["brand"],
                        "number": part["number"],
                        "message": result.get("message") or "Источник недоступен",
                    }
            except Exception as exc:
                result = {**part, "status": "error", "applications": [],
                          "message": str(exc)[:300]}
                error = {"position": index, "brand": part["brand"],
                         "number": part["number"], "message": str(exc)[:300]}

            async with self.session_factory() as session:
                job = await session.get(FitmentJob, job_id)
                if job is None:
                    return
                results = list(job.results or []); results.append(result); job.results = results
                if error:
                    errors = list(job.errors or []); errors.append(error); job.errors = errors
                job.processed_count = len(results)
                await session.commit()

    async def _fail(self, job_id: str, message: str) -> None:
        async with self.session_factory() as session:
            job = await session.get(FitmentJob, job_id)
            if job is not None:
                errors = list(job.errors or []); errors.append({"message": message})
                job.errors = errors; job.status = "failed"; job.finished_at = utcnow()
                await session.commit()
