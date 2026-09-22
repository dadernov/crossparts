from __future__ import annotations

import httpx


def build_client(
    settings,
    *,
    base_headers: dict | None = None,
    timeout: float | None = None,
    proxy: str | None = None,
) -> httpx.AsyncClient:
    headers = {
        "User-Agent": settings.user_agent,
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    for name, value in (base_headers or {}).items():
        # A few official catalogues route by the mere presence of
        # Accept-Language.  ``None`` is an explicit request to omit a default
        # header for that one source.
        if value is None:
            headers.pop(name, None)
        else:
            headers[name] = value
    kwargs = {
        "headers": headers,
        "timeout": httpx.Timeout(timeout or settings.source_timeout),
        "follow_redirects": True,
    }
    resolved = settings.proxy_url if proxy is None else proxy
    if resolved:
        kwargs["proxy"] = resolved
    return httpx.AsyncClient(**kwargs)
