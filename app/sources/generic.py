"""Profile-driven browser source.

Catalogues differ only in a handful of CSS selectors, so they are described in
``profiles.json`` instead of Python.  Adding a catalogue to the service is
therefore a config change, which is what the client asked for — the list of
sites to parse is still growing.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .antibot import looks_blocked
from .base import BaseSource, SourceResult, SourceStatus


@dataclass
class BrowserProfile:
    key: str
    title: str
    homepage: str
    search_url: str
    row_selector: str
    brand_selector: str = ""
    number_selector: str = ""
    input_selector: str = ""
    submit_selector: str = ""
    wait_selector: str = ""
    wait_ms: int = 4000
    verified: bool = False
    note: str = ""
    default_brand: str = ""
    extra: dict = field(default_factory=dict)


class BrowserProfileSource(BaseSource):
    """Drives a real browser, then reads (brand, number) pairs from the DOM."""

    def __init__(self, settings, http_factory, profile: BrowserProfile, pool):
        super().__init__(settings, http_factory)
        self.profile = profile
        self.pool = pool
        self.key = profile.key
        self.title = profile.title
        self.homepage = profile.homepage
        self.verified = profile.verified
        self.note = profile.note

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        p = self.profile
        url = p.search_url.format(oe=oe)
        context = None
        try:
            context = await self.pool.new_context(proxy_url=self.proxy)
            page = await context.new_page()
            response = await page.goto(url, wait_until="domcontentloaded",
                                       timeout=self.settings.source_timeout * 1000)
            status = response.status if response else None

            if p.input_selector:
                try:
                    await page.fill(p.input_selector, oe, timeout=15000)
                    if p.submit_selector:
                        await page.click(p.submit_selector, timeout=15000)
                    else:
                        await page.keyboard.press("Enter")
                except Exception:
                    pass

            if p.wait_selector:
                try:
                    await page.wait_for_selector(p.wait_selector, timeout=p.wait_ms + 8000)
                except Exception:
                    pass
            else:
                await page.wait_for_timeout(p.wait_ms)

            blocked = looks_blocked(status, await page.content())
            if blocked:
                return SourceResult(
                    self.key, SourceStatus.BLOCKED, url=url, elapsed_ms=self.elapsed(started),
                    message=(f"HTTP {status}: сайт закрыт антибот-защитой для этого IP. "
                             f"Укажите CP_PROXY_URL с разрешённым egress."),
                )

            crosses = []
            for row in await page.query_selector_all(p.row_selector):
                brand = p.default_brand
                if p.brand_selector:
                    node = await row.query_selector(p.brand_selector)
                    if node:
                        brand = (await node.inner_text()).strip()
                number = ""
                if p.number_selector:
                    node = await row.query_selector(p.number_selector)
                    if node:
                        number = (await node.inner_text()).strip()
                else:
                    number = (await row.inner_text()).strip()
                crosses.extend(self.make_cross(brand, number, url=url))

            return SourceResult(
                self.key,
                SourceStatus.OK if crosses else SourceStatus.NOT_FOUND,
                crosses=crosses, url=url, elapsed_ms=self.elapsed(started),
                message=None if crosses else "совпадений не найдено",
            )
        except Exception as exc:
            return SourceResult(self.key, SourceStatus.ERROR, url=url,
                                message=str(exc)[:300], elapsed_ms=self.elapsed(started))
        finally:
            if context is not None:
                await context.close()
