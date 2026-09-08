"""Shared headless-Chromium pool.

Only the profile-driven sources need a browser; it is started lazily so a
deployment that runs HTTP-only sources never pays for Chromium.
"""
from __future__ import annotations

import asyncio


class BrowserPool:
    def __init__(self, settings):
        self.settings = settings
        self._pw = None
        self._browser = None
        self._lock = asyncio.Lock()

    async def browser(self):
        async with self._lock:
            if self._browser is None:
                from playwright.async_api import async_playwright

                self._pw = await async_playwright().start()
                self._browser = await self._pw.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage",
                          "--disable-blink-features=AutomationControlled"],
                )
            return self._browser

    async def new_context(self, **kwargs):
        browser = await self.browser()
        opts = {
            "user_agent": self.settings.user_agent,
            "locale": "ru-RU",
            "viewport": {"width": 1366, "height": 900},
        }
        proxy = kwargs.pop("proxy_url", None)
        proxy = self.settings.proxy_url if proxy is None else proxy
        if proxy:
            opts["proxy"] = {"server": proxy}
        opts.update(kwargs)
        return await browser.new_context(**opts)

    async def close(self):
        async with self._lock:
            if self._browser is not None:
                await self._browser.close()
                self._browser = None
            if self._pw is not None:
                await self._pw.stop()
                self._pw = None
