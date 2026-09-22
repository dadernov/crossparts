from __future__ import annotations

import asyncio
import json

import pytest

from app.config import Settings
from app.groups import BRAKE_DISCS, BRAKE_PADS
from app.normalize import KIND_AFTERMARKET, KIND_OEM, number_key
from app.sources.base import SourceStatus
from app.sources.fap import FapSource
from app.sources.registry import SourceRegistry


PAD = {"fapProductCode": "FDP0372", "deleted": 0,
       "ext3": json.dumps({"Goods group": "Brake Pad"})}
DISC = {"fapProductCode": "FP11619", "deleted": 0,
        "ext3": json.dumps({"Goods group": "Brake Disc"})}


def test_group_and_oe_parser_reject_invalid_or_deleted_rows():
    assert FapSource.product_group(PAD) == BRAKE_PADS
    assert FapSource.product_group(DISC) == BRAKE_DISCS
    assert FapSource.product_group({"deleted": 1, "ext3": "{}"}) is None
    assert FapSource.oe_pairs([
        {"oeDesc": "HYUNDAI / KIA", "oeCode": "58101-H5A25"},
        {"oeDesc": "HYUNDAI / KIA", "oeCode": "58101-H5A25"},
        {"deleted": 1, "oeDesc": "SKIP", "oeCode": "123"},
    ]) == [("HYUNDAI / KIA", "58101-H5A25")]


@pytest.mark.asyncio
async def test_source_returns_own_article_and_confirmed_oem_rows(monkeypatch):
    class Response:
        status_code = 200
        url = "https://fapbrakes.ru/db-proxy/api/test"
        text = "[]"
        def __init__(self, data): self.data = data
        def json(self): return self.data
    class Client:
        calls = 0
        async def get(self, *args, **kwargs):
            self.calls += 1
            return Response([PAD] if self.calls == 1 else [
                {"oeDesc": "HYUNDAI / KIA", "oeCode": "58101-H5A25"},
            ])
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
    import app.sources.fap as module
    monkeypatch.setattr(module, "build_client", lambda *args, **kwargs: Client())
    result = await FapSource(Settings(_env_file=None), None).lookup("58101H5A25")
    assert result.status is SourceStatus.OK
    assert result.products == ["FDP0372"]
    assert {(cross.brand, number_key(cross.number), cross.kind) for cross in result.crosses} == {
        ("FAP", "FDP0372", KIND_AFTERMARKET),
        ("HYUNDAI", "58101H5A25", KIND_OEM),
        ("KIA", "58101H5A25", KIND_OEM),
    }


def test_candidate_is_fail_closed_by_group_and_tenant():
    settings = Settings(_env_file=None, enabled_sources="", browser_fallback=False,
        pilot_rules=json.dumps({"fap": {"groups": [BRAKE_PADS, BRAKE_DISCS],
            "tenants": ["catalogue-review"], "default": True}}))
    registry = SourceRegistry(settings)
    try:
        assert [source.key for source in registry.resolve(None, BRAKE_PADS, tenant="catalogue-review")] == ["fap"]
        assert [source.key for source in registry.resolve(None, BRAKE_DISCS, tenant="catalogue-review")] == ["fap"]
        assert registry.resolve(["fap"], BRAKE_PADS, tenant="another") == []
    finally:
        asyncio.run(registry.close())
