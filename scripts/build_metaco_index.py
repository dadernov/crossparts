#!/usr/bin/env python3
"""Build a local METACO SQLite index from reviewed official CSV snapshots."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.sources.metaco import build_sqlite_index


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--oem", type=Path, required=True)
    parser.add_argument("--replacements", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_sqlite_index(args.oem, args.replacements, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
