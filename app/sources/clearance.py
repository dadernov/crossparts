"""Кэш cookies антибот-сессии.

Прохождение Cloudflare-challenge стоит ~1.6 МБ трафика (сам challenge грузит
около мегабайта XHR). На резидентном прокси трафик метрический, поэтому cookies
``cf_clearance`` сохраняются и переиспользуются: challenge решается один раз,
дальше идут обычные HTTP-запросы по ~150 КБ.
"""
from __future__ import annotations

import asyncio
import time


class ClearanceStore:
    """Cookies на источник, с TTL и защитой от параллельных прогревов."""

    def __init__(self, ttl_seconds: int = 20 * 60, cooldown_seconds: int = 10 * 60,
                 failures_before_cooldown: int = 2):
        self.ttl = ttl_seconds
        self.cooldown = cooldown_seconds
        self.failures_before_cooldown = failures_before_cooldown
        self._cookies: list[dict] = []
        self._obtained_at: float = 0.0
        self._failures = 0
        self._cooldown_until: float = 0.0
        self._lock = asyncio.Lock()

    @property
    def lock(self) -> asyncio.Lock:
        """Берётся перед запуском браузера, чтобы не греть сессию в N потоков."""
        return self._lock

    def get(self) -> list[dict]:
        if not self._cookies or time.monotonic() - self._obtained_at > self.ttl:
            return []
        return self._cookies

    def put(self, cookies: list[dict]) -> None:
        self._cookies = cookies or []
        self._obtained_at = time.monotonic()
        self._failures = 0
        self._cooldown_until = 0.0

    def mark_failure(self) -> None:
        """Браузер не смог пройти защиту — значит IP не годится.

        После нескольких неудач подряд перестаём запускать браузер на время:
        каждая попытка стоит ~1.6 МБ метрического трафика, а на плохом адресе
        она заведомо бесполезна.
        """
        self._failures += 1
        if self._failures >= self.failures_before_cooldown:
            self._cooldown_until = time.monotonic() + self.cooldown

    def in_cooldown(self) -> bool:
        return time.monotonic() < self._cooldown_until

    def cooldown_left(self) -> int:
        return max(0, int(self._cooldown_until - time.monotonic()))

    def clear(self) -> None:
        self._cookies = []
        self._obtained_at = 0.0

    def apply(self, client) -> bool:
        """Перенести сохранённые cookies в httpx-клиент. True — если было что нести."""
        cookies = self.get()
        for c in cookies:
            client.cookies.set(c["name"], c["value"],
                               domain=c.get("domain", ""), path=c.get("path", "/"))
        return bool(cookies)
