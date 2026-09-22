#!/usr/bin/env python3
"""Bounded, read-only transport check for catalogues excluded from runtime.

This does not prove a usable cross-reference contract.  It records the current
HTTP/TLS boundary so planning metadata does not rely on stale observations.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

import httpx


TARGETS = {
    "jnbk": "https://www.jnbk-brakes.com/catalogue/cars",
    "mintex": "https://mintex.brakebook.com/",
    "monroe": "https://www.monroe.com/ru-ru/find-my-part.html",
    "nrf": "https://webshop.nrf.eu/catalogsearch/advanced/result/?p_oen=8200735038",
    "ava": "https://ava-cooling.com/ru/",
    "patron": "https://patron.ru/",
    "trw": "https://aftermarket.zf.com/catalog",
    "stellox": "https://ru.stellox.com/catalog/",
}


async def inspect(client: httpx.AsyncClient, key: str, url: str) -> dict:
    row = {"key": key, "url": url}
    try:
        response = await client.get(url)
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
        return row
    row.update({
        "status": response.status_code,
        "final_url": str(response.url),
        "bytes": len(response.content),
        "server": response.headers.get("server"),
        "content_type": response.headers.get("content-type"),
    })
    if key == "nrf":
        body = response.text.casefold()
        row["oe_query_echoed"] = "8200735038" in body
        row["product_result_markers"] = body.count("product-item-link")
    return row


async def run() -> dict:
    limits = httpx.Limits(max_connections=3, max_keepalive_connections=3)
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, limits=limits) as client:
        rows = await asyncio.gather(*(
            inspect(client, key, url) for key, url in TARGETS.items()
        ))
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "scope": "transport and public-page availability only",
        "results": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = asyncio.run(run())
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
