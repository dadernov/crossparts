#!/usr/bin/env python3
"""Measure golden coverage without silently declaring incomplete waves done."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.sources.registry import BUILTIN, CANDIDATES  # noqa: E402


def measure(fixtures: Path) -> dict:
    fixtures = fixtures.resolve()
    manifests = {}
    for path in fixtures.glob("*/*/manifest.yaml"):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        key = (path.parent.parent.name, data["group"])
        cases = data.get("cases", [])
        manifests[key] = {
            "path": str(path.resolve().relative_to(ROOT)),
            "positive": sum(case.get("case_class") == "positive" for case in cases),
            "negative": sum(case.get("case_class") == "negative" for case in cases),
            "ambiguous_or_partial": sum(
                case.get("case_class") in {"ambiguous", "partial"}
                or case.get("expected_status") in {"partial", "blocked", "error"}
                or bool(case.get("forbidden_pairs"))
                for case in cases
            ),
        }

    rows = []
    for source in (*BUILTIN, *CANDIDATES):
        for group in source.groups:
            counts = manifests.get((source.key, group), {})
            gates = {
                "positive": counts.get("positive", 0) >= 12,
                "negative": counts.get("negative", 0) >= 4,
                "ambiguous_or_partial": counts.get("ambiguous_or_partial", 0) >= 4,
            }
            rows.append({
                "source": source.key,
                "group": group,
                **counts,
                "gates": gates,
                "accepted": all(gates.values()),
            })
    return {
        "requirements": {"positive": 12, "negative": 4, "ambiguous_or_partial": 4},
        "pairs": rows,
        "accepted_pairs": sum(row["accepted"] for row in rows),
        "total_pairs": len(rows),
        "ok": all(row["accepted"] for row in rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixtures", type=Path,
                        default=ROOT / "tests" / "fixtures" / "catalogues")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = measure(args.fixtures)
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 1 if args.strict and not report["ok"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
