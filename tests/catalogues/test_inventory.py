from pathlib import Path

from scripts.verify_catalogue_matrix import ROOT, verify


def test_workbook_inventory_and_registered_adapters_are_in_sync():
    report = verify(
        ROOT / "Ресурсы для парсинга.xlsx",
        ROOT / "plans" / "catalogue-resource-inventory.yaml",
    )
    assert report["errors"] == []
    assert report["measured"] == {
        "workbook_rows": 47,
        "brands": 33,
        "literal_urls": 36,
        "logical_sources": 34,
        "registered_adapters": 13,
        "missing_adapters": 21,
        "requested_source_group_pairs": 64,
    }

