"""Recheck representative official shock-absorber fitment cards.

The output is deliberately compact: parser fixtures cover field-level behavior,
while this report records live availability, counts and representative rows.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.sources.hola_fitment import HolaFitmentSource
from app.sources.kyb_fitment import KybFitmentSource
from app.sources.metaco_fitment import MetacoFitmentSource
from app.sources.torr_fitment import TorrFitmentSource
from app.sources.trialli_fitment import TrialliFitmentSource


CASES = (
    (TrialliFitmentSource, "AG29125"),
    (TorrFitmentSource, "DH1270"),
    (TorrFitmentSource, "DH1317"),
    (KybFitmentSource, "333754"),
    (KybFitmentSource, "341841"),
    (HolaFitmentSource, "SH20-037G"),
    (MetacoFitmentSource, "4800-013"),
)
OUTPUT = Path("output/fitment-research/shock-absorbers-2026-09-23/multi-source-golden.json")


async def main() -> None:
    settings = get_settings()
    cases = []
    for source_type, article in CASES:
        started = time.monotonic()
        result = await source_type(settings).lookup(article)
        applications = result.get("applications") or []
        encoded = json.dumps(applications, ensure_ascii=False, sort_keys=True).encode()
        cases.append({
            "source": source_type.key,
            "brand": source_type.brand,
            "article": article,
            "status": result.get("status"),
            "source_url": result.get("source_url"),
            "application_count": len(applications),
            "applications_sha256": hashlib.sha256(encoded).hexdigest(),
            "elapsed_ms": round((time.monotonic() - started) * 1000),
            "first_application": applications[0] if applications else None,
            "last_application": applications[-1] if applications else None,
            "message": result.get("message"),
        })
    report = {
        "schema_version": "1.0",
        "checked_at": "2026-09-23",
        "product_group": "shock_absorbers",
        "method": "Direct lookup of an exact article in an official manufacturer catalogue.",
        "cases": cases,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"{OUTPUT}: {len(cases)} cases")


if __name__ == "__main__":
    asyncio.run(main())
