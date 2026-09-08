#!/usr/bin/env python3
"""Прогнать xlsx через сервис без HTTP-сервера.

    python3 scripts/run_file.py "Тест - парсинг кроссов.xlsx" out/result.xlsx [sbparts,brembo]
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.aggregator import Aggregator
from app.config import get_settings
from app.db import SessionLocal, init_db
from app.excel import build_workbook, read_input
from app.sources.registry import SourceRegistry


async def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    src_path, dst_path = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    keys = sys.argv[3].split(",") if len(sys.argv) > 3 else None

    await init_db()
    settings = get_settings()
    registry = SourceRegistry(settings)
    agg = Aggregator(settings, registry, SessionLocal)

    items = read_input(src_path.read_bytes())
    print(f"Позиций во входном файле: {len(items)}")

    out = []
    for n, item in enumerate(items, 1):
        res = await agg.lookup(item["oe_number"], keys, group=item.get("group"))
        per_source = ", ".join(f"{s['source']}:{s['status']}/{s['crosses']}" for s in res["sources"])
        print(f"[{n:>3}/{len(items)}] {item['our_sku']:<10} {item['oe_number']:<16} "
              f"{res['status']:<10} кроссов={len(res['crosses']):<4} {per_source}")
        out.append({**item, "status": res["status"], "crosses": res["crosses"],
                    "source_reports": res["sources"]})

    dst_path.parent.mkdir(parents=True, exist_ok=True)
    dst_path.write_bytes(build_workbook(out, meta={
        "Входной файл": src_path.name,
        "Источники": ", ".join(keys or settings.default_sources),
        "Позиций": len(items),
    }))
    print(f"\nГотово: {dst_path}")
    await registry.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
