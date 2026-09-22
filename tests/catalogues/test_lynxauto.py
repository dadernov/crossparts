from __future__ import annotations

import asyncio
import json

import pytest

from app.config import Settings
from app.groups import BRAKE_DISCS, BRAKE_HOSES, BRAKE_PADS, SHOCK_ABSORBERS
from app.normalize import KIND_AFTERMARKET, KIND_OEM, number_key
from app.sources.base import SourceStatus
from app.sources.lynxauto import LynxautoSource
from app.sources.registry import SourceRegistry


CARD = """
<div class='pcard-model'>BD-3636</div><div class='pcard-name'><h1>Дисковые тормозные колодки, передние</h1></div>
<table class='pcard-oeno-bottom'><tr><td>HYUNDAI / KIA</td><td>58101-H5A25</td><td></td></tr></table>
<table class='pcard-analog-bottom'>
  <tr><td>ATE</td><td>13.0460-5506.2</td><td></td></tr>
  <tr><td>BREMBO</td><td>P30098N</td><td>Детали, со схожими параметрами</td></tr>
</table>
"""
SHOCK_CARD = """
<div class='pcard-model'>G32458LR</div><div class='pcard-name'><h1>Стойка амортизаторная с газовым подпором, передняя</h1></div>
<table class='pcard-oeno-bottom'><tr><td>TOYOTA</td><td>48510-0D030</td><td></td></tr></table>
<table class='pcard-analog-bottom'><tr><td>KYB</td><td>333333</td><td></td></tr></table>
"""
HOSE_CARD = """
<div class='pcard-model'>BL-3102</div><div class='pcard-name'><h1>Шланг тормозной передний</h1></div>
<table class='pcard-oeno-bottom'><tr><td>VAG</td><td>1K0 611 701 K</td><td></td></tr></table>
<table class='pcard-analog-bottom'><tr><td>ATE</td><td>24.5143-0564.3</td><td></td></tr></table>
"""


def _pairs(crosses):
    return {(c.brand, number_key(c.number), c.kind, c.source_product) for c in crosses}


def test_card_parser_uses_separate_tables_and_omits_similar_parameter_rows():
    source = LynxautoSource(Settings(_env_file=None), None)
    assert source.product_code(CARD) == "BD-3636"
    assert source.is_brake_pad(CARD)
    oems = source.parse_table(CARD, ".pcard-oeno-bottom", KIND_OEM, product="BD-3636", url="fixture")
    analogues = source.parse_table(CARD, ".pcard-analog-bottom", KIND_AFTERMARKET, product="BD-3636", url="fixture")
    assert _pairs([*oems, *analogues]) == {
        ("HYUNDAI", "58101H5A25", KIND_OEM, "BD-3636"),
        ("KIA", "58101H5A25", KIND_OEM, "BD-3636"),
        ("ATE", "13046055062", KIND_AFTERMARKET, "BD-3636"),
    }


def test_non_pad_card_is_rejected_before_rows_can_be_used():
    assert not LynxautoSource.is_brake_pad("<div class='pcard-name'><h1>Ремкомплект тормозов</h1></div>")


def test_shock_card_is_classified_and_keeps_oe_and_analogue_rows():
    source = LynxautoSource(Settings(_env_file=None), None)
    assert source.product_group(SHOCK_CARD) == SHOCK_ABSORBERS
    rows = [
        *source.parse_table(SHOCK_CARD, ".pcard-oeno-bottom", KIND_OEM,
                            product="G32458LR", url="fixture"),
        *source.parse_table(SHOCK_CARD, ".pcard-analog-bottom", KIND_AFTERMARKET,
                            product="G32458LR", url="fixture"),
    ]
    assert _pairs(rows) == {
        ("TOYOTA", "485100D030", KIND_OEM, "G32458LR"),
        ("KYB", "333333", KIND_AFTERMARKET, "G32458LR"),
    }


def test_brake_hose_card_is_classified_and_keeps_only_its_tables():
    source = LynxautoSource(Settings(_env_file=None), None)
    assert source.product_group(HOSE_CARD) == BRAKE_HOSES
    rows = [
        *source.parse_table(HOSE_CARD, ".pcard-oeno-bottom", KIND_OEM,
                            product="BL-3102", url="fixture"),
        *source.parse_table(HOSE_CARD, ".pcard-analog-bottom", KIND_AFTERMARKET,
                            product="BL-3102", url="fixture"),
    ]
    assert _pairs(rows) == {
        ("VAG", "1K0611701K", KIND_OEM, "BL-3102"),
        ("ATE", "24514305643", KIND_AFTERMARKET, "BL-3102"),
    }


def test_candidate_is_fail_closed_by_group_and_tenant():
    settings = Settings(_env_file=None, enabled_sources="", browser_fallback=False,
        pilot_rules=json.dumps({"lynxauto": {"groups": [BRAKE_PADS, SHOCK_ABSORBERS, BRAKE_HOSES],
            "tenants": ["catalogue-review"], "default": True}}))
    registry = SourceRegistry(settings)
    try:
        assert [source.key for source in registry.resolve(None, BRAKE_PADS, tenant="catalogue-review")] == ["lynxauto"]
        assert [source.key for source in registry.resolve(None, SHOCK_ABSORBERS, tenant="catalogue-review")] == ["lynxauto"]
        assert [source.key for source in registry.resolve(None, BRAKE_HOSES, tenant="catalogue-review")] == ["lynxauto"]
        assert registry.resolve(["lynxauto"], BRAKE_DISCS, tenant="catalogue-review") == []
        assert registry.resolve(["lynxauto"], BRAKE_PADS, tenant="another") == []
    finally:
        asyncio.run(registry.close())


@pytest.mark.asyncio
async def test_not_found_page_stays_not_found(monkeypatch):
    class Response:
        status_code = 200
        text = "<title>LYNXauto Web Catalogue</title>"
        url = "https://lynxauto.info/index.php?route=product/category/search"
    class Client:
        async def get(self, *args, **kwargs): return Response()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
    import app.sources.lynxauto as module
    monkeypatch.setattr(module, "build_client", lambda *args, **kwargs: Client())
    result = await LynxautoSource(Settings(_env_file=None), None).lookup("ZZNOTREAL001")
    assert result.status is SourceStatus.NOT_FOUND
