from __future__ import annotations

import asyncio
import json
from pathlib import Path

from app.config import Settings
from app.groups import BRAKE_DISCS, BRAKE_PADS
from app.sources.monaer import MonaerProduct, MonaerSource, build_sqlite_index, parse_product_page
from app.sources.registry import SourceRegistry


CARD = '''<script>var product = {"title":"Передние тормозные диски М61784",
"text":"Категория товара: Тормозные диски"};</script>
<div class="t-store__tabs__item"><h2 class="t-store__tabs__item-title">OEM-номера</h2>
<div class="t-store__tabs__content">204001529AA; 204002964AA</div></div>'''


def test_product_card_extracts_own_article_group_and_oem_numbers():
    assert parse_product_page(CARD, "https://monaer-russia.ru/card") == MonaerProduct(
        "M61784", "https://monaer-russia.ru/card", BRAKE_DISCS,
        ("204001529AA", "204002964AA"),
    )


def test_index_returns_only_requested_group(tmp_path: Path):
    index_path = tmp_path / "monaer.sqlite3"
    build_sqlite_index([
        MonaerProduct("M61784", "https://example.test/disc", BRAKE_DISCS, ("204001529AA",)),
        MonaerProduct("M0802-S", "https://example.test/pad", BRAKE_PADS, ("204001529AA",)),
    ], index_path, source_hash="test")
    source = MonaerSource(Settings(_env_file=None), None)
    source._index = source_index = __import__('app.sources.monaer', fromlist=['SQLiteMonaerIndex']).SQLiteMonaerIndex(index_path)
    products, crosses = source_index.lookup("204001529AA", groups={BRAKE_DISCS}, max_products=5)
    assert products == ["M61784"]
    assert crosses[0].brand == "MONAER"


def test_candidate_is_scoped_to_brake_groups():
    settings = Settings(_env_file=None, enabled_sources="", browser_fallback=False,
        pilot_rules=json.dumps({"monaer": {"groups": [BRAKE_PADS, BRAKE_DISCS],
            "tenants": ["catalogue-review"], "default": True}}))
    registry = SourceRegistry(settings)
    try:
        assert [source.key for source in registry.resolve(None, BRAKE_PADS, tenant="catalogue-review")] == ["monaer"]
        assert [source.key for source in registry.resolve(None, BRAKE_DISCS, tenant="catalogue-review")] == ["monaer"]
    finally:
        asyncio.run(registry.close())
