from pathlib import Path

import pytest

from app.config import Settings
from app.groups import BRAKE_DISCS, BRAKE_PADS, RADIATORS
from app.normalize import KIND_AFTERMARKET, KIND_OEM, number_key
from app.sources.base import SourceStatus
from app.sources.metaco import (
    MetacoIndex,
    MetacoSource,
    SQLiteMetacoIndex,
    build_sqlite_index,
    classify_group,
)
from app.sources.registry import BUILTIN


FIXTURES = Path(__file__).parents[1] / "fixtures" / "catalogues" / "metaco"


def _index(group: str) -> MetacoIndex:
    root = FIXTURES / group
    return MetacoIndex.from_files(root / "oem.csv", root / "replacements.csv")


def test_classifies_only_w1_brake_descriptions():
    assert classify_group("Колодки тормозные передние к-кт") == BRAKE_PADS
    assert classify_group("Диск тормозной передний вентилируемый") == BRAKE_DISCS
    assert classify_group("Радиатор основной") is None
    assert classify_group("Диск сцепления") is None
    assert classify_group("Пыльник тормозного диска") is None
    assert classify_group("Регулировочный к-кт тормозных колодок") is None
    assert classify_group("Барабан тормозной") is None


def test_oem_csv_apostrophes_are_removed_and_kind_is_preserved():
    products, crosses = _index("brake_discs").lookup(
        "1K0 615 301-AA", groups={BRAKE_DISCS}
    )
    assert products == ["3050-016"]
    pairs = {(cross.brand, cross.number, cross.kind) for cross in crosses}
    assert ("METACO", "3050-016", KIND_AFTERMARKET) in pairs
    assert ("VAG", "1K0615301AA", KIND_OEM) in pairs
    assert ("BREMBO", "09.9772.75", KIND_AFTERMARKET) in pairs
    assert all(not cross.number.startswith("'") for cross in crosses)


def test_replacement_number_finds_the_same_complete_fixture_product():
    products, crosses = _index("brake_pads").lookup(
        "58101H5A25", groups={BRAKE_PADS}
    )
    assert products == [
        "3000-410",
        "3000-555",
        "3000-587",
        "3000-745",
        "3000-746",
        "3000-1131",
        "3000-1131PRM",
    ]
    pairs = {(cross.brand, number_key(cross.number)) for cross in crosses}
    assert {
        ("METACO", "3000555"),
        ("HYUNDAI-KIA", "58101H5A25"),
        ("HYUNDAI-KIA", "581011RA05"),
        ("BREMBO", "P30098"),
        ("NIBK", "PN8019"),
    } <= pairs


def test_group_filter_prevents_cross_category_results():
    products, crosses = _index("brake_discs").lookup(
        "1K0615301AA", groups={BRAKE_PADS}
    )
    assert products == []
    assert crosses == []


@pytest.mark.asyncio
async def test_source_reports_not_found_and_missing_snapshot_error():
    settings = Settings(_env_file=None)
    source = MetacoSource(settings, index=_index("brake_pads"))
    result = await source.lookup("ZZ-NOT-A-REAL-NUMBER-987")
    assert result.status is SourceStatus.NOT_FOUND

    missing = await MetacoSource(settings).lookup("58101H5A25")
    assert missing.status is SourceStatus.ERROR
    assert "индекс METACO" in missing.message


def test_pilot_source_is_not_registered_or_enabled():
    assert "metaco" not in {source.key for source in BUILTIN}
    assert "metaco" not in Settings(_env_file=None).default_sources


def test_compiled_sqlite_index_matches_fixture_lookup(tmp_path):
    pads = FIXTURES / "brake_pads"
    database = tmp_path / "metaco.sqlite3"
    report = build_sqlite_index(
        pads / "oem.csv", pads / "replacements.csv", database
    )
    assert report["rows"] == 1469
    assert report["size_bytes"] > 0

    products, crosses = SQLiteMetacoIndex(database).lookup(
        "58101-H5A25", groups={BRAKE_PADS}
    )
    assert "3000-555" in products
    assert ("BREMBO", "P30098") in {(cross.brand, cross.number) for cross in crosses}


@pytest.mark.asyncio
async def test_source_reads_compiled_index_without_registering_it(tmp_path):
    discs = FIXTURES / "brake_discs"
    database = tmp_path / "metaco.sqlite3"
    build_sqlite_index(discs / "oem.csv", discs / "replacements.csv", database)
    settings = Settings(_env_file=None, metaco_index_path=str(database))
    result = await MetacoSource(settings).lookup("1K0615301AA")
    assert result.status is SourceStatus.OK
    assert result.products == ["3050-016"]
