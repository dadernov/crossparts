from pathlib import Path

from scripts.verify_catalogue_acceptance import measure


def test_acceptance_report_keeps_incomplete_pairs_fail_closed():
    report = measure(Path("tests/fixtures/catalogues"))
    by_pair = {(row["source"], row["group"]): row for row in report["pairs"]}
    assert by_pair[("metaco", "brake_pads")]["accepted"] is True
    assert by_pair[("metaco", "brake_discs")]["accepted"] is True
    assert by_pair[("ate", "brake_hoses")]["accepted"] is False
    assert report["ok"] is False
