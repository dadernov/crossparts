from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.aggregator import Aggregator
from app.config import Settings
from app.groups import BRAKE_DISCS, BRAKE_PADS, RADIATORS, SHOCK_ABSORBERS
from app.sources.registry import SourceRegistry
from app.sources.metaco import build_sqlite_index


def _registry(rules=""):
    return SourceRegistry(Settings(
        _env_file=None,
        pilot_rules=json.dumps(rules) if isinstance(rules, dict) else rules,
        enabled_sources="sbparts,brixo",
        browser_fallback=False,
    ))


def test_candidate_is_not_instantiated_without_a_valid_rule():
    for rules in ("", "not-json", "[]", '{"metaco":{"groups":[]}}'):
        registry = _registry(rules)
        assert registry.get("metaco", group=BRAKE_PADS, tenant="pilot") is None
        assert "metaco" not in {source.key for source in registry.all(tenant="pilot")}


def test_explicit_candidate_key_cannot_bypass_tenant_or_group_rule():
    registry = _registry({
        "metaco": {
            "groups": [BRAKE_PADS],
            "tenants": ["pilot-account"],
            "default": False,
        }
    })
    assert registry.resolve(["metaco"], BRAKE_PADS, tenant="other") == []
    assert registry.resolve(["metaco"], BRAKE_DISCS, tenant="pilot-account") == []
    assert registry.resolve(["metaco"], None, tenant="pilot-account") == []
    assert [source.key for source in registry.resolve(
        ["metaco"], BRAKE_PADS, tenant="pilot-account"
    )] == ["metaco"]


def test_candidate_can_be_default_only_for_its_pilot_cohort_and_group():
    registry = _registry({
        "metaco": {
            "groups": [BRAKE_PADS],
            "tenants": ["pilot-account"],
            "default": True,
        }
    })
    assert [source.key for source in registry.resolve(
        None, BRAKE_PADS, tenant="pilot-account"
    )] == ["sbparts", "metaco"]
    assert [source.key for source in registry.resolve(
        None, BRAKE_PADS, tenant="other"
    )] == ["sbparts"]
    assert [source.key for source in registry.resolve(
        None, BRAKE_DISCS, tenant="pilot-account"
    )] == ["sbparts"]


def test_job_selection_defers_group_gate_but_not_tenant_gate():
    registry = _registry({
        "metaco": {
            "groups": [BRAKE_PADS],
            "tenants": ["pilot-account"],
            "default": True,
        }
    })
    assert [source.key for source in registry.select_for_job(
        None, tenant="pilot-account"
    )] == ["sbparts", "brixo", "metaco"]
    assert [source.key for source in registry.select_for_job(
        ["metaco"], tenant="other"
    )] == []
    assert [source.key for source in registry.select_for_job(
        ["metaco"], tenant="pilot-account"
    )] == ["metaco"]


def test_candidate_visibility_exposes_only_allowed_groups():
    registry = _registry({
        "metaco": {
            "groups": [BRAKE_PADS],
            "tenants": ["pilot-account"],
            "default": True,
        }
    })
    assert "metaco" not in {item["key"] for item in registry.describe("other")}
    metaco = next(item for item in registry.describe("pilot-account") if item["key"] == "metaco")
    assert metaco["groups"] == [BRAKE_PADS]
    assert metaco["enabled_by_default"] is True


def test_wildcard_rule_enables_candidate_for_every_resolved_tenant():
    registry = _registry({
        "metaco": {
            "groups": [BRAKE_PADS, BRAKE_DISCS],
            "tenants": ["*"],
            "default": True,
        }
    })
    for tenant in ("autobody", "guest-ip-hash", "api-client"):
        assert [source.key for source in registry.resolve(
            None, BRAKE_PADS, tenant=tenant
        )] == ["sbparts", "metaco"]
    assert "metaco" not in {source.key for source in registry.all(tenant=None)}


@pytest.mark.asyncio
async def test_ungrouped_rollout_searches_only_configured_candidate_groups(tmp_path):
    pads = Path(__file__).parents[1] / "fixtures/catalogues/metaco/brake_pads"
    discs = Path(__file__).parents[1] / "fixtures/catalogues/metaco/brake_discs"
    # The production index contains both groups; combine the reviewed fixture
    # closures here to exercise the same ungrouped routing contract.
    oem = tmp_path / "oem.csv"
    replacements = tmp_path / "replacements.csv"
    oem.write_bytes((pads / "oem.csv").read_bytes() + (discs / "oem.csv").read_bytes())
    replacements.write_bytes(
        (pads / "replacements.csv").read_bytes()
        + (discs / "replacements.csv").read_bytes()
    )
    database = tmp_path / "metaco.sqlite3"
    build_sqlite_index(oem, replacements, database)
    settings = Settings(
        _env_file=None,
        enabled_sources="",
        browser_fallback=False,
        metaco_index_path=str(database),
        pilot_rules=json.dumps({
            "metaco": {
                "groups": [BRAKE_PADS, BRAKE_DISCS],
                "tenants": ["*"],
                "default": True,
                "ungrouped": True,
            }
        }),
    )
    registry = SourceRegistry(settings)
    try:
        result = await Aggregator(settings, registry, None).lookup(
            "1K0615301AA", use_cache=False, tenant="ordinary-user"
        )
        assert result["status"] == "ok"
        assert result["sources"][0]["source"] == "metaco"
        assert result["sources"][0]["products"] == ["3050-016"]
    finally:
        await registry.close()


def test_existing_sources_keep_their_current_routing():
    registry = _registry()
    assert [source.key for source in registry.resolve(None, BRAKE_PADS)] == ["sbparts"]
    assert [source.key for source in registry.resolve(None, RADIATORS)] == ["brixo"]


@pytest.mark.asyncio
async def test_disabled_candidate_runs_only_for_configured_pilot_path(tmp_path):
    fixture = Path(__file__).parents[1] / "fixtures" / "catalogues" / "metaco" / "brake_discs"
    database = tmp_path / "metaco.sqlite3"
    build_sqlite_index(fixture / "oem.csv", fixture / "replacements.csv", database)
    settings = Settings(
        _env_file=None,
        enabled_sources="",
        browser_fallback=False,
        metaco_index_path=str(database),
        pilot_rules=json.dumps({
            "metaco": {
                "groups": [BRAKE_DISCS],
                "tenants": ["pilot-account"],
                "default": True,
            }
        }),
        source_concurrency=1,
        source_timeout=1,
        cache_ttl_hours=1,
    )
    registry = SourceRegistry(settings)
    aggregator = Aggregator(settings, registry, None)

    allowed = await aggregator.lookup(
        "1K0615301AA",
        use_cache=False,
        group=BRAKE_DISCS,
        tenant="pilot-account",
    )
    denied = await aggregator.lookup(
        "1K0615301AA",
        use_cache=False,
        group=BRAKE_DISCS,
        tenant="other",
    )

    assert allowed["status"] == "ok"
    assert allowed["sources"][0]["source"] == "metaco"
    assert denied["status"] == "no_sources"
    assert denied["sources"] == []
    await registry.close()


@pytest.mark.asyncio
async def test_same_number_in_two_groups_uses_separate_cache_namespaces():
    import asyncio
    from app.sources.metaco import MetacoIndex, MetacoRow

    registry = _registry({
        'metaco': {'groups': [BRAKE_PADS, BRAKE_DISCS],
                   'tenants': ['pilot-account'], 'default': True}
    })
    registry._sources['metaco']._index = MetacoIndex([
        MetacoRow('METACO', 'PAD-123', 'TEST', 'COMMON123',
                  'Колодки тормозные', BRAKE_PADS, 'oem'),
        MetacoRow('METACO', 'DISC-456', 'TEST', 'COMMON123',
                  'Диск тормозной', BRAKE_DISCS, 'oem'),
    ])
    pads_source = registry.resolve(['metaco'], BRAKE_PADS, tenant='pilot-account')[0]
    discs_source = registry.resolve(['metaco'], BRAKE_DISCS, tenant='pilot-account')[0]
    assert pads_source.cache_key == 'metaco:brake_pads'
    assert discs_source.cache_key == 'metaco:brake_discs'
    # The detailed cache behaviour is tested against SQLite in the cache suite.
    aggregator = Aggregator(registry.settings, registry, None)
    pads, discs = await asyncio.gather(*(
        aggregator.lookup('COMMON123', ['metaco'], group=group,
                          tenant='pilot-account', use_cache=False)
        for group in (BRAKE_PADS, BRAKE_DISCS)
    ))
    assert pads['sources'][0]['products'] == ['PAD-123']
    assert discs['sources'][0]['products'] == ['DISC-456']
    assert registry._sources['metaco'].groups == (BRAKE_PADS, BRAKE_DISCS, SHOCK_ABSORBERS)
    await registry.close()


@pytest.mark.asyncio
async def test_excel_job_preserves_pilot_tenant_and_gates_each_row(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from app import main
    from app.jobs import JobRunner
    from app.models import Base, Job, JobItem

    fixture = Path(__file__).parents[1] / 'fixtures/catalogues/metaco/brake_discs'
    database = tmp_path / 'metaco.sqlite3'
    build_sqlite_index(fixture / 'oem.csv', fixture / 'replacements.csv', database)
    settings = Settings(_env_file=None, enabled_sources='',
        metaco_index_path=str(database), browser_fallback=False,
        pilot_rules=json.dumps({'metaco': {'groups': [BRAKE_DISCS],
            'tenants': ['pilot-account'], 'default': True}}))
    registry = SourceRegistry(settings)
    engine = create_async_engine(f'sqlite+aiosqlite:///{tmp_path / "jobs.db"}')
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    runner = JobRunner(settings, Aggregator(settings, registry, sessions), sessions)
    monkeypatch.setattr(main, 'registry', registry)
    monkeypatch.setattr(main, 'SessionLocal', sessions)
    monkeypatch.setattr(main, 'runner', runner)
    monkeypatch.setattr(main, 'reserve_queries', AsyncMock())
    created = await main._create_job([
        {'oe_number': '1K0615301AA', 'group': BRAKE_DISCS},
        {'oe_number': '1K0615301AA', 'group': BRAKE_PADS},
    ], None, 'pilot-account', 'pilot.xlsx')
    await runner._run_job(created.id)
    async with sessions() as session:
        job = await session.get(Job, created.id)
        items = (await session.execute(select(JobItem).where(
            JobItem.job_id == job.id).order_by(JobItem.position))).scalars().all()
        assert job.status == 'done' and job.done == 2
        assert job.sources == ['metaco']
        assert items[0].status == 'ok'
        assert items[0].source_reports[0]['source'] == 'metaco'
        assert items[1].status == 'no_sources' and items[1].crosses == []
    await registry.close()
    await engine.dispose()
