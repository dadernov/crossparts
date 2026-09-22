from __future__ import annotations

import asyncio
import json

from app.config import Settings
from app.groups import BRAKE_DISCS, BRAKE_PADS
from app.sources.ganz import GanzSource
from app.sources.registry import SourceRegistry


SEARCH = '''<div class="search-custom-results"><div class="search-item">
<div class="h4"><a href="/catalog/gij07044c/">Колодки</a></div></div>
<div class="search-item"><div class="h4"><a href="/catalog/gij07044c/">Дубль</a></div></div></div>'''
PAD = '''<h1 class="product_page_title">Колодки тормозные передние</h1>
<div class="product_page_info_prop"><span class="product_page_info_prop_title">Артикул</span><span class="product_page_info_prop_value">GIJ07044C</span></div>
<div class="product_page_info_prop"><span class="product_page_info_prop_title">Оригинальный номер</span><span class="product_page_info_prop_value">58101H5A25</span></div>'''
DISC = PAD.replace("Колодки", "Диск").replace("GIJ07044C", "GIJ10516").replace("58101H5A25", "51712G4000")


def test_parser_keeps_exact_catalog_products_and_classifies_card():
    assert GanzSource.product_urls(SEARCH) == ["/catalog/gij07044c/"]
    assert GanzSource.product_data(PAD) == ("GIJ07044C", BRAKE_PADS, {"58101H5A25"})
    assert GanzSource.product_data(DISC) == ("GIJ10516", BRAKE_DISCS, {"51712G4000"})


def test_candidate_is_scoped_to_verified_brake_groups():
    settings = Settings(_env_file=None, enabled_sources="", browser_fallback=False,
        pilot_rules=json.dumps({"ganz": {"groups": [BRAKE_PADS, BRAKE_DISCS],
            "tenants": ["catalogue-review"], "default": True}}))
    registry = SourceRegistry(settings)
    try:
        assert [source.key for source in registry.resolve(None, BRAKE_PADS, tenant="catalogue-review")] == ["ganz"]
        assert [source.key for source in registry.resolve(None, BRAKE_DISCS, tenant="catalogue-review")] == ["ganz"]
    finally:
        asyncio.run(registry.close())
