#!/usr/bin/env python3
"""Verify that the parsing workbook, inventory and adapter metadata agree.

This command is intentionally read-only.  It performs no HTTP requests and
does not import the database or application entrypoint.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

import yaml
from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
DEFAULT_WORKBOOK = ROOT / "Ресурсы для парсинга.xlsx"
DEFAULT_INVENTORY = ROOT / "plans" / "catalogue-resource-inventory.yaml"

SECTION_GROUPS = {
    "Тормозная система диски - колодки": ("brake_pads", "brake_discs"),
    "Амортизаторы": ("shock_absorbers",),
    "Радиаторы охлаждения": ("radiators",),
    "Тормозные шланги": ("brake_hoses",),
}


def workbook_resources(path: Path) -> list[dict]:
    workbook = load_workbook(path, read_only=True, data_only=True)
    sheet = workbook["Сайты для парсинга"]
    current_groups: tuple[str, ...] | None = None
    resources: list[dict] = []
    for row_number, (brand, url) in enumerate(sheet.iter_rows(values_only=True), start=1):
        if brand == "Бренды для парсинга":
            if url not in SECTION_GROUPS:
                raise ValueError(f"unknown section at workbook row {row_number}: {url!r}")
            current_groups = SECTION_GROUPS[url]
            continue
        if brand is None and url is None:
            continue
        if current_groups is None or not brand or not url:
            raise ValueError(f"invalid resource at workbook row {row_number}: {(brand, url)!r}")
        resources.append({
            "row": row_number,
            "brand_raw": str(brand),
            "url_raw": str(url),
            "groups_requested": list(current_groups),
        })
    return resources


def verify(workbook_path: Path, inventory_path: Path) -> dict:
    inventory = yaml.safe_load(inventory_path.read_text(encoding="utf-8"))
    actual = workbook_resources(workbook_path)
    declared = inventory["resources"]
    errors: list[str] = []

    by_row = {item["row"]: item for item in declared}
    if len(by_row) != len(declared):
        errors.append("inventory contains duplicate workbook row numbers")
    if set(by_row) != {item["row"] for item in actual}:
        errors.append("workbook row set differs from inventory")

    for item in actual:
        expected = by_row.get(item["row"])
        if expected is None:
            continue
        for field in ("brand_raw", "url_raw", "groups_requested"):
            if expected[field] != item[field]:
                errors.append(
                    f"row {item['row']} {field}: workbook={item[field]!r}, "
                    f"inventory={expected[field]!r}"
                )

    source_ids = [source["id"] for source in inventory["sources"]]
    resource_source_ids = {item["source_key"] for item in declared}
    if set(source_ids) != resource_source_ids:
        errors.append("logical source keys differ between resources and sources")
    if len(source_ids) != len(set(source_ids)):
        errors.append("inventory contains duplicate logical source ids")

    requested_pairs = {
        (item["source_key"], group)
        for item in declared
        for group in item["groups_requested"]
    }
    counts = inventory["counts"]
    measured = {
        "workbook_rows": len(actual),
        "brands": len({item["brand"].casefold() for item in declared}),
        "literal_urls": len({item["url"] for item in declared}),
        "logical_sources": len(source_ids),
        "registered_adapters": sum(bool(item["registered_in_code"])
                                   for item in inventory["sources"]),
        "missing_adapters": sum(not item["registered_in_code"]
                                for item in inventory["sources"]),
        "requested_source_group_pairs": len(requested_pairs),
    }
    for key, value in measured.items():
        if counts[key] != value:
            errors.append(f"count {key}: measured={value}, inventory={counts[key]}")

    section_rows = Counter()
    section_by_groups = {groups: title for title, groups in SECTION_GROUPS.items()}
    for item in actual:
        section_rows[section_by_groups[tuple(item["groups_requested"])]] += 1
    if dict(section_rows) != counts["section_rows"]:
        errors.append(
            f"section counts: measured={dict(section_rows)!r}, "
            f"inventory={counts['section_rows']!r}"
        )

    from app.sources.registry import BUILTIN

    builtin = {source.key: source for source in BUILTIN}
    declared_registered = {
        source["id"]: source for source in inventory["sources"]
        if source["registered_in_code"]
    }
    if set(builtin) != set(declared_registered):
        errors.append(
            f"registered adapters: code={sorted(builtin)}, "
            f"inventory={sorted(declared_registered)}"
        )
    for key in set(builtin) & set(declared_registered):
        code_groups = set(builtin[key].groups)
        inventory_groups = set(declared_registered[key]["code_groups"])
        if code_groups != inventory_groups:
            errors.append(
                f"adapter {key} groups: code={sorted(code_groups)}, "
                f"inventory={sorted(inventory_groups)}"
            )

    return {
        "ok": not errors,
        "workbook": str(workbook_path.relative_to(ROOT)),
        "workbook_sha256": hashlib.sha256(workbook_path.read_bytes()).hexdigest(),
        "inventory": str(inventory_path.relative_to(ROOT)),
        "inventory_sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
        "measured": measured,
        "section_rows": dict(section_rows),
        "registered_keys": sorted(builtin),
        "errors": errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workbook", type=Path, default=DEFAULT_WORKBOOK)
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify(args.workbook.resolve(), args.inventory.resolve())
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
