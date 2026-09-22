"""Persistent, tenant-wide pacing for catalogue lookups."""
from __future__ import annotations

import asyncio
import datetime as dt

from .models import TenantDailyUsage


def _aware(value: dt.datetime | None) -> dt.datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=dt.timezone.utc)
    return value


class TenantPacer:
    def __init__(self, settings, session_factory):
        self.settings = settings
        self.session_factory = session_factory
        self._locks: dict[str, asyncio.Lock] = {}

    def enabled(self, tenant: str) -> bool:
        return self.settings.pace_enabled_for(tenant)

    async def reserve(self, tenant: str, *, now: dt.datetime | None = None) -> float:
        """Reserve one start slot and return seconds until it may run."""
        if not self.enabled(tenant):
            return 0.0
        now = now or dt.datetime.now(dt.timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=dt.timezone.utc)
        day = now.date().isoformat()
        key = f"{tenant.lower()}:{day}"
        lock = self._locks.setdefault(tenant.lower(), asyncio.Lock())
        async with lock:
            async with self.session_factory() as session:
                usage = await session.get(TenantDailyUsage, key)
                if usage is None:
                    usage = TenantDailyUsage(key=key, tenant=tenant.lower(), day=day)
                    session.add(usage)
                scheduled = max(now, _aware(usage.next_allowed_at) or now)
                usage.count = int(usage.count or 0) + 1
                if usage.count < self.settings.paced_daily_fast_limit:
                    interval = (
                        self.settings.paced_fast_window_seconds
                        / self.settings.paced_daily_fast_limit
                    )
                else:
                    interval = self.settings.paced_slow_interval_seconds
                usage.next_allowed_at = scheduled + dt.timedelta(seconds=interval)
                await session.commit()
        return max(0.0, (scheduled - now).total_seconds())

    async def wait(self, tenant: str) -> None:
        delay = await self.reserve(tenant)
        if delay > 0:
            await asyncio.sleep(delay)
