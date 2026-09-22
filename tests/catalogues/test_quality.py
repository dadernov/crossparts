from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml

from app.normalize import number_key
from app.sources.metaco import MetacoIndex


ROOT = Path(__file__).parents[1] / "fixtures" / "catalogues"
MANIFESTS = sorted(ROOT.glob("*/*/manifest.yaml"))


def _load(path: Path) -> tuple[dict, MetacoIndex]:
    manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    for filename, expected_hash in manifest["fixtures"].items():
        actual_hash = hashlib.sha256((path.parent / filename).read_bytes()).hexdigest()
        assert actual_hash == expected_hash, f"fixture drift: {path.parent / filename}"
    return manifest, MetacoIndex.from_files(
        path.parent / "oem.csv", path.parent / "replacements.csv"
    )


@pytest.mark.parametrize("manifest_path", MANIFESTS, ids=lambda path: str(path.parent.relative_to(ROOT)))
def test_reviewed_golden_pairs_are_exact(manifest_path):
    manifest, index = _load(manifest_path)
    for case in manifest["cases"]:
        products, crosses = index.lookup(case["query_raw"], groups={manifest["group"]})
        actual = {(cross.brand, number_key(cross.number), cross.kind) for cross in crosses}
        expected = {
            (pair["brand_canonical"], str(pair["number_key"]), pair["kind"])
            for pair in case["expected_pairs"]
        }
        forbidden = {
            (pair["brand_canonical"], str(pair["number_key"]), pair["kind"])
            for pair in case["forbidden_pairs"]
        }
        assert products == [str(value) for value in case["expected_products"]]
        assert actual == expected
        assert actual.isdisjoint(forbidden)
        assert ("ok" if products else "not_found") == case["expected_status"]

