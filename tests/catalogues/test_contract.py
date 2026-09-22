from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from app.normalize import number_key


ROOT = Path(__file__).parents[1] / "fixtures" / "catalogues"
MANIFESTS = sorted(ROOT.glob("*/*/manifest.yaml"))
PAIR_FIELDS = {
    "brand_raw",
    "brand_canonical",
    "number_raw",
    "number_key",
    "kind",
    "source_product",
    "evidence_locator",
}
CASE_FIELDS = {
    "case_id",
    "query_raw",
    "query_key",
    "expected_status",
    "expected_products",
    "expected_pairs",
    "forbidden_pairs",
}


@pytest.mark.parametrize("manifest_path", MANIFESTS, ids=lambda path: str(path.parent.relative_to(ROOT)))
def test_golden_manifest_schema_hashes_and_keys(manifest_path):
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["source"] == manifest_path.parts[-3]
    assert manifest["group"] == manifest_path.parts[-2]
    assert manifest["captured_at"]
    assert manifest["source_url"].startswith("https://")
    assert manifest["completeness_scope"]
    assert manifest["reviewed_by"]
    assert manifest["review_evidence"]

    for relative, expected_hash in manifest["fixtures"].items():
        fixture = (manifest_path.parent / relative).resolve()
        assert fixture.is_file()
        assert fixture.is_relative_to((ROOT.parent).resolve())
        assert hashlib.sha256(fixture.read_bytes()).hexdigest() == expected_hash

    case_ids = set()
    for case in manifest["cases"]:
        assert CASE_FIELDS <= set(case)
        assert case["case_id"] not in case_ids
        case_ids.add(case["case_id"])
        assert str(case["query_key"]) == number_key(str(case["query_raw"]))
        assert case["expected_status"] in {"ok", "not_found", "blocked", "error", "partial"}
        expected = set()
        for field in ("expected_pairs", "forbidden_pairs"):
            for pair in case[field]:
                assert PAIR_FIELDS <= set(pair)
                key = (
                    pair["brand_canonical"],
                    str(pair["number_key"]),
                    pair["kind"],
                    pair["source_product"],
                )
                assert key not in expected if field == "expected_pairs" else True
                if field == "expected_pairs":
                    expected.add(key)
                assert str(pair["number_key"]) == number_key(str(pair["number_raw"]))
                assert pair["kind"] in {"oem", "aftermarket", "standard"}
                assert pair["evidence_locator"]
