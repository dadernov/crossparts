import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.aggregator import Aggregator
from app.sources.base import Cross, SourceResult, SourceStatus


def _res(source, crosses, status=SourceStatus.OK):
    return SourceResult(source, status, crosses=[
        Cross(brand=b, number=n, kind="oem", source=source) for b, n in crosses
    ])


def test_merge_dedupes_across_sources_and_keeps_provenance():
    merged = Aggregator.merge("58101H5A25", [
        _res("sbparts", [("HYUNDAI", "58101-H5A25"), ("KIA", "58101H8A05")]),
        _res("brembo", [("HYUNDAI", "58101H5A25"), ("GEELY", "1014031279")]),
    ])
    by_key = {(c["brand"], c["number"]): c for c in merged["crosses"]}
    hyundai = [c for c in merged["crosses"] if c["brand"] == "HYUNDAI"]
    assert len(hyundai) == 1, "58101-H5A25 and 58101H5A25 are the same number"
    assert sorted(hyundai[0]["sources"]) == ["brembo", "sbparts"]
    assert merged["status"] == "ok"
    assert len(merged["unique_numbers"]) == 3


def test_merge_reports_blocked_when_no_source_answered():
    merged = Aggregator.merge("X", [
        SourceResult("jnbk", SourceStatus.BLOCKED, message="403"),
        SourceResult("mintex", SourceStatus.BLOCKED, message="cloudflare"),
    ])
    assert merged["status"] == "blocked"
    assert merged["crosses"] == []


def test_searched_number_is_pushed_to_the_end():
    merged = Aggregator.merge("58101H5A25", [
        _res("sbparts", [("HYUNDAI", "58101H5A25"), ("KIA", "58101H8A05")]),
    ])
    assert merged["crosses"][-1]["number"] == "58101H5A25"
