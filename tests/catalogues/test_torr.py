from __future__ import annotations

import asyncio
import json

from app.config import Settings
from app.groups import BRAKE_PADS, SHOCK_ABSORBERS
from app.normalize import KIND_AFTERMARKET, KIND_OEM, number_key
from app.sources.registry import SourceRegistry
from app.sources.torr import TorrSource


CARD = """
<div class='product-page__title'>Shock absorber, Gas, LEFT/RIGHT, REAR<br>Art: DH1270</div>
<table class='item-page__applicability'><tr>
 <td>HYUNDAI/KIA <span>553101G210</span></td>
 <td>KYB <span>348007</span></td>
</tr></table>
"""


def test_torr_card_parser_uses_cross_table_and_confirms_shock_type():
    source = TorrSource(Settings(_env_file=None), None)
    assert source.product_paths('<a href="catalog/DH1270">details</a>') == [("/ru/catalog/DH1270", "DH1270")]
    assert source.is_shock(CARD)
    rows = [*source.make_cross("TORR", "DH1270", product="DH1270", url="fixture",
                               kind=KIND_AFTERMARKET),
            *source.parse_crosses(CARD, product="DH1270", url="fixture")]
    assert {(row.brand, number_key(row.number), row.kind, row.source_product) for row in rows} == {
        ("TORR", "DH1270", KIND_AFTERMARKET, "DH1270"),
        ("HYUNDAI", "553101G210", KIND_OEM, "DH1270"),
        ("KIA", "553101G210", KIND_OEM, "DH1270"),
        ("KYB", "348007", KIND_AFTERMARKET, "DH1270"),
    }


def test_candidate_is_limited_to_shocks_and_the_allowed_tenant():
    settings = Settings(_env_file=None, enabled_sources="", browser_fallback=False,
        pilot_rules=json.dumps({"torr": {"groups": [SHOCK_ABSORBERS],
            "tenants": ["catalogue-review"], "default": True}}))
    registry = SourceRegistry(settings)
    try:
        assert [item.key for item in registry.resolve(None, SHOCK_ABSORBERS,
                                                       tenant="catalogue-review")] == ["torr"]
        assert registry.resolve(["torr"], BRAKE_PADS, tenant="catalogue-review") == []
        assert registry.resolve(["torr"], SHOCK_ABSORBERS, tenant="another") == []
    finally:
        asyncio.run(registry.close())
