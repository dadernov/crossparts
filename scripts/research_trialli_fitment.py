"""Recheck the ten fitment edge cases selected from the TRIALLI seed."""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.sources.trialli_fitment import TrialliFitmentSource


CASES = {
    "AG 29125": "открытый период; комплект задних амортизаторов",
    "AG 29194": "4x4; передняя левая/правая стойка",
    "AG 02056": "две марки; много модификаций; открытые периоды",
    "AG 19403": "ограничение после 08.2003",
    "AG 09055": "усиленная подвеска; большое число строк",
    "AG 09505": "стандартная подвеска; большое число строк",
    "AG 14521": "одна строка применяемости",
    "AG 08501": "ограничение после 09.2006",
    "AG 08516": "ограничение до 08.2006; 4x4",
    "AG 26056": "2WD; спортивная подвеска; много строк",
}


def comparable(row: dict) -> tuple:
    return tuple(
        row.get(key)
        for key in (
            "make", "model", "modification", "engine_code", "power_hp",
            "engine_cc", "raw_period", "year_from", "year_to",
        )
    )


async def run(seed_path: Path, output_path: Path) -> int:
    seed = json.loads(seed_path.read_text())
    parts = {part["part_number"]: part for part in seed["parts"]}
    stored = {}
    for row in seed["applications"]:
        stored.setdefault(row["part_number"], []).append(row)

    source = TrialliFitmentSource(get_settings())
    cases, all_exact = [], True
    for article, reason in CASES.items():
        result = await source.lookup(article)
        old_rows = stored.get(article, [])
        old_set = {comparable(row) for row in old_rows}
        live_set = {comparable(row) for row in result["applications"]}
        exact = result["status"] == "ok" and old_set == live_set
        all_exact = all_exact and exact
        cases.append({
            "brand": "TRIALLI",
            "part_number": article,
            "selection_reason": reason,
            "status": result["status"],
            "source_url": result["source_url"],
            "title": result["title"],
            "expected_application_count": len(old_rows),
            "live_application_count": len(result["applications"]),
            "exact_snapshot_match": exact,
            "missing_from_live": len(old_set - live_set),
            "new_in_live": len(live_set - old_set),
            "applications": result["applications"],
        })

    payload = {
        "schema_version": "1.0",
        "dataset_id": "shock-absorbers-trialli-golden-10-2026-09-23",
        "checked_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": {
            "key": "trialli",
            "title": "TRIALLI",
            "url": "https://trialli.ru/catalogue/amortizatory-i-opory/amortizatory/",
        },
        "scope": "Проверка точности извлечения официальной таблицы TRIALLI; не независимая гарантия применимости.",
        "summary": {
            "checked_parts": len(cases),
            "successful_parts": sum(case["status"] == "ok" for case in cases),
            "exact_snapshot_matches": sum(case["exact_snapshot_match"] for case in cases),
            "all_exact": all_exact,
        },
        "cases": cases,
    }
    output_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(payload["summary"], ensure_ascii=False))
    return 0 if all_exact else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--seed",
        type=Path,
        default=Path("output/fitment-research/shock-absorbers-2026-09-23/trialli-seed-30.json"),
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("output/fitment-research/shock-absorbers-2026-09-23/golden-fitments.json"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    return asyncio.run(run(args.seed, args.output))


if __name__ == "__main__":
    raise SystemExit(main())
