from __future__ import annotations

import asyncio
import json

import pytest

from app.config import Settings
from app.groups import BRAKE_DISCS, BRAKE_PADS
from app.normalize import KIND_AFTERMARKET, number_key
from app.sources.base import SourceStatus
from app.sources.masterkit import MasterkitSource
from app.sources.registry import SourceRegistry


PAD_PAGE = "<main><h1>Комплект установочный тормозных колодок</h1><span>тормозные колодки</span></main>"


def test_search_payload_keeps_only_explicit_masterkit_cross_articles():
    payload = {"result": [
        {"type": "cross", "cross": {"brand": "MasterKit", "number": "77AA515"}},
        {"type": "number", "article": {"number": "IGNORED"}},
        {"type": "cross", "cross": {"brand": "MasterKit", "number": "77AA515"}},
        {"type": "cross", "cross": {"brand": "MasterKit", "number": ""}},
    ]}
    assert MasterkitSource.products(payload) == ["77AA515"]
    assert MasterkitSource.is_brake_pad(PAD_PAGE)
    assert not MasterkitSource.is_brake_pad("<h1>Тормозной диск</h1>")


@pytest.mark.asyncio
async def test_source_checks_product_group_before_returning_cross(monkeypatch):
    class Response:
        status_code = 200
        url = "https://masterkit.it/"
        text = PAD_PAGE
        def json(self):
            return {"result": [{"type": "cross", "cross": {"number": "77AA515"}}]}
    class Client:
        async def get(self, *args, **kwargs): return Response()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
    import app.sources.masterkit as module
    monkeypatch.setattr(module, "build_client", lambda *args, **kwargs: Client())
    result = await MasterkitSource(Settings(_env_file=None), None).lookup("58101H5A25")
    assert result.status is SourceStatus.OK
    assert result.products == ["77AA515"]
    assert {(cross.brand, number_key(cross.number), cross.kind) for cross in result.crosses} == {
        ("MASTERKIT", "77AA515", KIND_AFTERMARKET),
    }


def test_candidate_is_fail_closed_by_group_and_tenant():
    settings = Settings(_env_file=None, enabled_sources="", browser_fallback=False,
        pilot_rules=json.dumps({"masterkit": {"groups": [BRAKE_PADS],
            "tenants": ["catalogue-review"], "default": True}}))
    registry = SourceRegistry(settings)
    try:
        assert [source.key for source in registry.resolve(None, BRAKE_PADS, tenant="catalogue-review")] == ["masterkit"]
        assert registry.resolve(["masterkit"], BRAKE_DISCS, tenant="catalogue-review") == []
        assert registry.resolve(["masterkit"], BRAKE_PADS, tenant="another") == []
    finally:
        asyncio.run(registry.close())
