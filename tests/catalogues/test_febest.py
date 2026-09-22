from __future__ import annotations

import asyncio
import json

from app.config import Settings
from app.groups import BRAKE_PADS, SHOCK_ABSORBERS
from app.normalize import KIND_AFTERMARKET, KIND_OEM, number_key
from app.sources.febest import FebestSource
from app.sources.registry import SourceRegistry


SHOCK = {
    "name": "2207G-006R", "description": "rear shock absorber, gas pressure",
    "analogues": [
        {"brand": "HYUNDAI", "name": "553101G210", "matched": True},
        {"brand": "KIA", "name": "55310-1G210", "matched": True},
        {"brand": "HYUNDAI", "name": "553101G110", "matched": False},
    ],
}
OTHER = {
    "name": "HYAB-ELAN", "description": "rear arm bushing",
    "analogues": [{"brand": "HYUNDAI", "name": "553101G210", "matched": True}],
}


def test_parse_rows_keeps_only_shock_absorbers_and_exact_oe_pairs():
    source = FebestSource(Settings(_env_file=None), None)
    products, rows = source.parse_rows([SHOCK, OTHER], url="fixture")
    assert products == ["2207G-006R"]
    assert {(row.brand, number_key(row.number), row.kind, row.source_product) for row in rows} == {
        ("FEBEST", "2207G006R", KIND_AFTERMARKET, "2207G-006R"),
        ("HYUNDAI", "553101G210", KIND_OEM, "2207G-006R"),
        ("KIA", "553101G210", KIND_OEM, "2207G-006R"),
    }


def test_candidate_is_limited_to_shocks_and_the_allowed_tenant():
    settings = Settings(_env_file=None, enabled_sources="", browser_fallback=False,
        pilot_rules=json.dumps({"febest": {"groups": [SHOCK_ABSORBERS],
            "tenants": ["catalogue-review"], "default": True}}))
    registry = SourceRegistry(settings)
    try:
        assert [item.key for item in registry.resolve(None, SHOCK_ABSORBERS,
                                                       tenant="catalogue-review")] == ["febest"]
        assert registry.resolve(["febest"], BRAKE_PADS, tenant="catalogue-review") == []
        assert registry.resolve(["febest"], SHOCK_ABSORBERS, tenant="another") == []
    finally:
        asyncio.run(registry.close())
