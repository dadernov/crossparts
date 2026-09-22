from __future__ import annotations

import asyncio
import json
import statistics
import time
from pathlib import Path

import pytest
from openpyxl import Workbook

from app.config import Settings
from app.groups import BRAKE_DISCS, BRAKE_PADS
from app.normalize import KIND_AFTERMARKET, KIND_OEM, number_key
from app.sources.base import SourceStatus
from app.sources.marshall import (
    MarshallIndex,
    MarshallSource,
    SQLiteMarshallIndex,
    brake_pad_rows,
    build_sqlite_index,
    parse_references,
)
from app.sources.registry import SourceRegistry


def _workbook(path: Path) -> Path:
    book = Workbook()
    sheet = book.active
    sheet.append([
        "Дата ввода в ассортимент", "Артикул MARSHALL", "Статус", "Категория ",
        "Тип товара", "Краткое наименование", "Полное наименование",
        "Ассортиментная категория", "Сторона установки", "Ось установки",
        "Пара по стороне (лев/прав)", "Оригинальные номера", "Аналоги",
        "Рекомендованная розничная цена, руб", "Ссылка на страницу товара",
    ])
    def row(article, status, category, oems, analogues, url):
        return [None, article, status, category, None, None, None, None, None, None,
                None, oems, analogues, None, url]
    sheet.append(row(
        "M2625349", "Активный ассортимент", "Тормозные колодки (легковые)",
        "58101H5A25(HYUNDAI / KIA); S581011WA35(HYUNDAI / KIA)",
        "PF0806(TRIALLI); 13046056502(ATE); GDB3630(TRW)",
        "https://cars.marshall.parts/product/m2625349/",
    ))
    sheet.append(row(
        "M2625360", "Активный ассортимент", "Тормозные колодки PLUS (легковые)",
        "58101H5A25(HYUNDAI / KIA); 58101H8A05(HYUNDAI / KIA)",
        "PF2701(TRIALLI); P30098(BREMBO)",
        "https://cars.marshall.parts/product/m2625360/",
    ))
    sheet.append(row(
        "M2624606", "Активный ассортимент", "Тормозные колодки (легковые)",
        "8K0698451D(VAG)", "13046027472(ATE); 246061751(ZIMMERMANN)",
        "https://cars.marshall.parts/product/m2624606/",
    ))
    sheet.append(row(
        "M-OLD", "Выведен из ассортимента", "Тормозные колодки (легковые)",
        "OLD-001(VAG)", "OLD1(ATE)", "https://example.test/old",
    ))
    sheet.append(row(
        "M-DISC", "Активный ассортимент", "Диски и барабаны (легковые)",
        "1K0615301AA(VAG)", "24012501581(ATE)", "https://example.test/disc",
    ))
    book.save(path)
    return path


def _pairs(crosses):
    return {(cross.brand, number_key(cross.number), cross.kind, cross.source_product) for cross in crosses}


def test_reference_parser_requires_explicit_brand_and_deduplicates():
    refs = parse_references(
        "58101H5A25(HYUNDAI / KIA); 58101H5A25(HYUNDAI / KIA); без бренда",
        kind=KIND_OEM,
    )
    assert [(r.brand, r.number, r.kind) for r in refs] == [
        ("HYUNDAI", "58101H5A25", KIND_OEM),
        ("KIA", "58101H5A25", KIND_OEM),
    ]


def test_build_reads_only_active_brake_pads_and_preserves_exact_pairs(tmp_path):
    products = brake_pad_rows(_workbook(tmp_path / "marshall.xlsx"))
    assert [product.article for product in products] == ["M2625349", "M2625360", "M2624606"]
    found, crosses = MarshallIndex(products).lookup("58101-H5A25", max_products=5)
    assert found == ["M2625349", "M2625360"]
    assert _pairs(crosses) == {
        ("MARSHALL", "M2625349", KIND_AFTERMARKET, "M2625349"),
        ("HYUNDAI", "58101H5A25", KIND_OEM, "M2625349"),
        ("KIA", "58101H5A25", KIND_OEM, "M2625349"),
        ("HYUNDAI", "S581011WA35", KIND_OEM, "M2625349"),
        ("KIA", "S581011WA35", KIND_OEM, "M2625349"),
        ("TRIALLI", "PF0806", KIND_AFTERMARKET, "M2625349"),
        ("ATE", "13046056502", KIND_AFTERMARKET, "M2625349"),
        ("TRW", "GDB3630", KIND_AFTERMARKET, "M2625349"),
        ("MARSHALL", "M2625360", KIND_AFTERMARKET, "M2625360"),
        ("HYUNDAI", "58101H5A25", KIND_OEM, "M2625360"),
        ("KIA", "58101H5A25", KIND_OEM, "M2625360"),
        ("HYUNDAI", "58101H8A05", KIND_OEM, "M2625360"),
        ("KIA", "58101H8A05", KIND_OEM, "M2625360"),
        ("TRIALLI", "PF2701", KIND_AFTERMARKET, "M2625360"),
        ("BREMBO", "P30098", KIND_AFTERMARKET, "M2625360"),
    }


def test_compiled_index_matches_in_memory_and_has_no_disc_or_inactive_leak(tmp_path):
    workbook = _workbook(tmp_path / "marshall.xlsx")
    database = tmp_path / "marshall.sqlite3"
    report = build_sqlite_index(workbook, database)
    assert report["products"] == 3
    assert report["matches"] > 0
    assert report["references"] > 0
    index = SQLiteMarshallIndex(database)
    products, crosses = index.lookup("8K0698451D", max_products=5)
    assert products == ["M2624606"]
    assert ("MARSHALL", "M2624606", KIND_AFTERMARKET, "M2624606") in _pairs(crosses)
    assert index.lookup("1K0615301AA", max_products=5) == ([], [])
    assert index.lookup("OLD001", max_products=5) == ([], [])


@pytest.mark.asyncio
async def test_source_uses_local_index_and_reports_missing_index(tmp_path):
    workbook = _workbook(tmp_path / "marshall.xlsx")
    database = tmp_path / "marshall.sqlite3"
    build_sqlite_index(workbook, database)
    source = MarshallSource(Settings(_env_file=None, marshall_index_path=str(database)))
    result = await source.lookup("58101H5A25")
    assert result.status is SourceStatus.OK
    assert result.products == ["M2625349", "M2625360"]
    assert (not_found := await source.lookup("ZZ-NOT-REAL-001"))
    assert not_found.status is SourceStatus.NOT_FOUND
    missing = await MarshallSource(Settings(_env_file=None)).lookup("58101H5A25")
    assert missing.status is SourceStatus.ERROR
    assert "индекс MARSHALL" in (missing.message or "")


def test_marshall_candidate_is_fail_closed_by_tenant_and_group():
    settings = Settings(_env_file=None, enabled_sources="", browser_fallback=False,
        pilot_rules=json.dumps({"marshall": {"groups": [BRAKE_PADS],
            "tenants": ["catalogue-review"], "default": True}}))
    registry = SourceRegistry(settings)
    try:
        assert [source.key for source in registry.resolve(
            None, BRAKE_PADS, tenant="catalogue-review"
        )] == ["marshall"]
        assert registry.resolve(["marshall"], BRAKE_PADS, tenant="other") == []
        assert registry.resolve(["marshall"], BRAKE_DISCS, tenant="catalogue-review") == []
    finally:
        asyncio.run(registry.close())


def test_local_lookup_meets_pure_parse_budget(tmp_path):
    workbook = _workbook(tmp_path / "marshall.xlsx")
    database = tmp_path / "marshall.sqlite3"
    build_sqlite_index(workbook, database)
    index = SQLiteMarshallIndex(database)
    samples = []
    for _ in range(120):
        started = time.perf_counter()
        products, crosses = index.lookup("58101H5A25", max_products=5)
        samples.append((time.perf_counter() - started) * 1000)
    assert products == ["M2625349", "M2625360"]
    assert len(crosses) == 15
    assert statistics.median(samples) < 25
    assert sorted(samples)[113] < 100
