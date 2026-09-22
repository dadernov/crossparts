from __future__ import annotations

import asyncio
import json

import pytest

from app.config import Settings
from app.groups import BRAKE_DISCS, BRAKE_PADS
from app.normalize import KIND_AFTERMARKET, KIND_OEM, number_key
from app.sources.ate import AteSource, PROVIDER
from app.sources.base import SourceStatus
from app.sources.registry import SourceRegistry


PAD = {"articleNumber": "13.0460-5548.2", "genericArticles": [
    {"genericArticleDescription": "Brake Pad Set, disc brake"}],
    "oemNumbers": [{"mfrName": "HYUNDAI", "articleNumber": "58101-H5A25"}]}
DISC = {"articleNumber": "24.0325-0158.1", "genericArticles": [
    {"genericArticleDescription": "Brake Disc"}],
    "oemNumbers": [{"mfrName": "SEAT", "articleNumber": "1K0 615 301 AA"}]}


def test_group_detection_and_payload_follow_ate_public_contract():
    assert AteSource.article_group(PAD) == BRAKE_PADS
    assert AteSource.article_group(DISC) == BRAKE_DISCS
    payload = AteSource.request_payload("58101H5A25")["getArticles"]
    assert payload["provider"] == PROVIDER
    assert payload["searchQuery"] == "58101H5A25"
    assert payload["searchMatchType"] == "exact"
    assert payload["includeOEMNumbers"] is True


@pytest.mark.asyncio
async def test_source_returns_own_ate_article_and_oem_rows(monkeypatch):
    class Response:
        status_code = 200
        text = "{}"
        url = "https://webservice.tecalliance.services/test"
        def json(self): return {"articles": [PAD, PAD, DISC]}
    class Client:
        async def post(self, *args, **kwargs): return Response()
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None
    import app.sources.ate as module
    monkeypatch.setattr(module, "build_client", lambda *args, **kwargs: Client())
    result = await AteSource(Settings(_env_file=None), None).lookup("58101H5A25")
    assert result.status is SourceStatus.OK
    assert result.products == ["13.0460-5548.2", "24.0325-0158.1"]
    assert {(row.brand, number_key(row.number), row.kind) for row in result.crosses} == {
        ("ATE", "13046055482", KIND_AFTERMARKET),
        ("HYUNDAI", "58101H5A25", KIND_OEM),
        ("ATE", "24032501581", KIND_AFTERMARKET),
        ("SEAT", "1K0615301AA", KIND_OEM),
    }


def test_candidate_is_scoped_to_confirmed_brake_groups():
    settings = Settings(_env_file=None, enabled_sources="", browser_fallback=False,
        pilot_rules=json.dumps({"ate": {"groups": [BRAKE_PADS, BRAKE_DISCS],
            "tenants": ["catalogue-review"], "default": True}}))
    registry = SourceRegistry(settings)
    try:
        assert [source.key for source in registry.resolve(None, BRAKE_PADS, tenant="catalogue-review")] == ["ate"]
        assert [source.key for source in registry.resolve(None, BRAKE_DISCS, tenant="catalogue-review")] == ["ate"]
    finally:
        asyncio.run(registry.close())
