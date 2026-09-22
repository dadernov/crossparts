from __future__ import annotations

import asyncio
import json

from app.config import Settings
from app.groups import BRAKE_DISCS, BRAKE_PADS
from app.normalize import KIND_AFTERMARKET, KIND_OEM
from app.sources.registry import SourceRegistry
from app.sources.zimmermann import ZimmermannSource


PAD = {"articleNumber": "25348.180.1", "genericArticles": [
    {"genericArticleDescription": "Комплект тормозных колодок, дисковый тормоз"}],
    "oemNumbers": [{"mfrName": "HYUNDAI", "articleNumber": "58101-H5A25"}]}
DISC = {"articleNumber": "100.3300.20", "genericArticles": [
    {"genericArticleDescription": "Тормозной диск"}],
    "oemNumbers": [{"mfrName": "VAG", "articleNumber": "1K0 615 301 AA"}]}


def test_article_group_and_payload_keep_exact_number_contract():
    assert ZimmermannSource.article_group(PAD) == BRAKE_PADS
    assert ZimmermannSource.article_group(DISC) == BRAKE_DISCS
    payload = ZimmermannSource.request_payload("58101H5A25")["getArticles"]
    assert payload["searchQuery"] == "58101H5A25"
    assert payload["searchMatchType"] == "exact"
    assert payload["provider"] == 2254


def test_candidate_is_scoped_to_verified_brake_groups():
    settings = Settings(_env_file=None, enabled_sources="", browser_fallback=False,
        pilot_rules=json.dumps({"zimmermann": {"groups": [BRAKE_PADS, BRAKE_DISCS],
            "tenants": ["catalogue-review"], "default": True}}))
    registry = SourceRegistry(settings)
    try:
        assert [source.key for source in registry.resolve(None, BRAKE_PADS, tenant="catalogue-review")] == ["zimmermann"]
        assert [source.key for source in registry.resolve(None, BRAKE_DISCS, tenant="catalogue-review")] == ["zimmermann"]
    finally:
        asyncio.run(registry.close())


def test_own_and_oem_rows_are_distinguishable():
    source = ZimmermannSource(Settings(_env_file=None), None)
    own = source.make_cross("ZIMMERMANN", PAD["articleNumber"], kind=KIND_AFTERMARKET)
    oem = source.make_cross("HYUNDAI", PAD["oemNumbers"][0]["articleNumber"], kind=KIND_OEM)
    assert own[0].kind == KIND_AFTERMARKET
    assert oem[0].kind == KIND_OEM
