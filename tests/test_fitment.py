from __future__ import annotations

import io
import datetime as dt
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from openpyxl import load_workbook
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import main
from app.config import Settings
from app.fitment import FitmentService
from app.fitment_jobs import FitmentJobRunner
from app.excel import build_fitment_workbook
from app.models import (
    Base, FeatureEntitlement, FitmentEvidence, FitmentJob, FitmentPart, FitmentRecord,
)
from app.security import has_feature_access
from app.schemas import FitmentJobCreate, FitmentJobPart, FitmentLookupRequest
from app.sources.trialli_fitment import TrialliFitmentSource
from app.sources.kyb_fitment import KybFitmentSource
from app.sources.hola_fitment import HolaFitmentSource
from app.sources.metaco_fitment import MetacoFitmentSource
from app.sources.torr_fitment import TorrFitmentSource


CARD = """
<html><head><title>Амортизатор задний AG 29125 купить недорого</title></head><body>
<h1>Амортизатор для LADA XRAY задний</h1>
<table class="props"><tr><td>Ось (сторона установки):</td><td>Сзади, слева/справа</td></tr>
<tr><td>Тип амортизатора:</td><td>Двухтрубный</td></tr></table>
<table class="js-table-car"><tr><th>Марка</th><th>Модель</th><th>Модификация</th>
<th>Код двигателя</th><th>Мощность, лс</th><th>Объём двигателя</th><th>Год выпуска</th></tr>
<tr><td>LADA</td><td>XRAY (GAB_)</td><td>1.6 Cross</td><td>H4M</td><td>113</td>
<td>1598</td><td>2019 - н.в.</td></tr>
<tr><td>SUZUKI</td><td>SX4</td><td>1.6 4x4</td><td>M16A</td><td>107</td>
<td>1586</td><td>2006 - 2013</td></tr></table>
<table class="js-table-car"><tr><th>Марка</th><th>Модель</th><th>Двигатель</th>
<th>Мощность, лс</th><th>Объём двигателя</th><th>Год</th></tr>
<tr><td>LADA</td><td>XRAY</td><td>H4M</td><td>113</td><td>1598</td><td>2019 - н.в.</td></tr></table>
</body></html>
"""


def test_trialli_fitment_parser_uses_full_table_and_keeps_period_semantics():
    result = TrialliFitmentSource.parse_page(CARD, source_url="https://trialli.ru/card/")
    assert result is not None
    assert result["number"] == "AG 29125"
    assert result["installation_position"] == "Сзади, слева/справа"
    assert len(result["applications"]) == 2  # reduced mobile duplicate is ignored
    assert result["applications"][0] == {
        "make": "LADA",
        "model": "XRAY (GAB_)",
        "modification": "1.6 Cross",
        "engine_code": "H4M",
        "power_hp": "113",
        "engine_cc": "1598",
        "raw_period": "2019 - н.в.",
        "year_from": 2019,
        "year_to": None,
        "end_is_open": True,
    }
    assert result["applications"][1]["year_to"] == 2013
    assert result["applications"][1]["end_is_open"] is False


@pytest.mark.asyncio
async def test_fitment_service_caches_complete_answer(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'fitment.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    service = FitmentService(Settings(_env_file=None), sessions)
    answer = TrialliFitmentSource.parse_page(CARD, source_url="https://trialli.ru/card/")
    service.sources["TRIALLI"].lookup = AsyncMock(return_value=answer)

    first = await service.lookup("TRIALLI", "AG 29125")
    second = await service.lookup("TRIALLI", "AG29125")
    assert first["cached"] is False
    assert second["cached"] is True
    assert len(second["applications"]) == 2
    service.sources["TRIALLI"].lookup.assert_awaited_once()
    async with sessions() as session:
        assert (await session.execute(select(func.count()).select_from(FitmentPart))).scalar_one() == 1
        assert (await session.execute(select(func.count()).select_from(FitmentRecord))).scalar_one() == 2
        assert (await session.execute(select(func.count()).select_from(FitmentEvidence))).scalar_one() == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_fitment_endpoint_is_server_side_admin_only(monkeypatch):
    lookup = AsyncMock(return_value={"status": "ok", "applications": []})
    monkeypatch.setattr(main.fitment, "lookup", lookup)
    request = FitmentLookupRequest(
        brand="TRIALLI", number="AG 29125", group="shock_absorbers"
    )

    with pytest.raises(HTTPException) as denied:
        await main.fitment_lookup(request, tenant="another-user")
    assert denied.value.status_code == 403
    lookup.assert_not_awaited()

    assert await main.fitment_lookup(request, tenant="admin") == {
        "status": "ok", "applications": []
    }
    lookup.assert_awaited_once_with("TRIALLI", "AG 29125")


@pytest.mark.asyncio
async def test_fitment_endpoint_rejects_other_brands_and_groups(monkeypatch):
    lookup = AsyncMock()
    monkeypatch.setattr(main.fitment, "lookup", lookup)
    with pytest.raises(HTTPException) as brand_error:
        await main.fitment_lookup(
            FitmentLookupRequest(brand="SACHS", number="333754", group="shock_absorbers"),
            tenant="admin",
        )
    assert brand_error.value.status_code == 400
    with pytest.raises(HTTPException) as group_error:
        await main.fitment_lookup(
            FitmentLookupRequest(brand="TRIALLI", number="PF0806", group="brake_pads"),
            tenant="admin",
        )
    assert group_error.value.status_code == 400
    lookup.assert_not_awaited()


TORR_CARD = """
<div class="product-page__title">Shock absorber, Gas, LEFT/RIGHT, REAR Art: DH1270</div>
<table class="item-page__applicability"><thead><tr><th>MARKE</th><th>MODELL</th>
<th>BAUJAHR</th><th>MODIFIKATION</th><th>MOTOR</th><th>HUBRAUM</th><th>KW/PS</th><th>INFO</th>
</tr></thead><tbody><tr><td>KIA</td><td><span class="tooltip" data-tooltip="Rio II Sedan (JB)">Rio II Sed...</span></td>
<td>2005-03/-</td><td><span class="tooltip" data-tooltip="Rio 1.4 16V">Rio 1.4...</span></td>
<td>G4EE</td><td>1399</td><td>71/97</td><td>Standard</td></tr></tbody></table>
<table class="item-page__applicability"><tbody><tr><td>OEM 553101G200</td></tr></tbody></table>
"""


def test_torr_fitment_parser_uses_applicability_table_and_tooltips():
    result = TorrFitmentSource.parse_page(TORR_CARD, source_url="https://controltorr.de/catalog/DH1270")
    assert result is not None
    assert result["number"] == "DH1270"
    assert result["applications"] == [{
        "make": "KIA", "model": "Rio II Sedan (JB)", "modification": "Rio 1.4 16V",
        "engine_code": "G4EE", "engine_cc": "1399", "power_kw": "71", "power_hp": "97",
        "raw_period": "2005-03/-", "year_from": 2005, "year_to": None,
        "end_is_open": True, "info": "Standard",
    }]


def test_kyb_fitment_parser_preserves_open_ended_period():
    result = KybFitmentSource.parse_data({
        "partNumber": "333754",
        "application": [{"startMonth": 6, "startYear": 2006, "endMonth": 99,
                         "endYear": 9999, "firm": "Suzuki", "model": "SX4"}],
        "spec": {"part": "Амортизатор", "series": "Excel-G",
                 "type": "Двухтрубная газонаполненная стойка", "fr": "Передний",
                 "rl": "Левый", "fixType": "Стойка МакФерсон"},
    })
    assert result["status"] == "ok"
    assert result["applications"][0]["raw_period"] == "06.2006 — н.в."
    assert result["applications"][0]["year_to"] is None
    assert result["applications"][0]["end_is_open"] is True


def test_fitment_workbook_has_product_and_application_sheets():
    result = KybFitmentSource.parse_data({
        "partNumber": "333754",
        "application": [{"startMonth": 6, "startYear": 2006, "endMonth": 99,
                         "endYear": 9999, "firm": "Suzuki", "model": "SX4"}],
        "spec": {"part": "Амортизатор", "series": "Excel-G", "fr": "Передний"},
    })
    workbook = load_workbook(io.BytesIO(build_fitment_workbook(result)), data_only=True)
    assert workbook.sheetnames == ["Деталь", "Применяемость"]
    assert workbook["Применяемость"]["A2"].value == "KYB"
    assert workbook["Применяемость"]["C2"].value == "Suzuki"
    assert workbook["Применяемость"]["D2"].value == "SX4"
    workbook.close()


@pytest.mark.asyncio
async def test_fitment_export_is_server_side_admin_only(monkeypatch):
    lookup = AsyncMock(return_value=KybFitmentSource.parse_data({
        "partNumber": "333754", "application": [{"startYear": 2006, "endYear": 9999,
        "firm": "Suzuki", "model": "SX4"}], "spec": {"part": "Амортизатор"},
    }))
    monkeypatch.setattr(main.fitment, "lookup", lookup)
    request = FitmentLookupRequest(brand="KYB", number="333754", group="shock_absorbers")
    with pytest.raises(HTTPException) as denied:
        await main.fitment_export(request, tenant="rnd")
    assert denied.value.status_code == 403
    lookup.assert_not_awaited()
    response = await main.fitment_export(request, tenant="admin")
    assert response.media_type.endswith("spreadsheetml.sheet")
    assert response.body.startswith(b"PK")
    lookup.assert_awaited_once_with("KYB", "333754")


HOLA_CARD = """
<div class="tabs__content-item" data-tabs-value="about"><table>
<tr><td>Артикул</td><td>SH20-037G</td></tr><tr><td>Наименование</td><td>Амортизатор G'Ride</td></tr>
<tr><td>Место установки</td><td>передняя ось</td></tr><tr><td>Сторона установки</td><td>левая / правая</td></tr>
<tr><td>Исполнение</td><td>Амортизатор</td></tr></table></div>
<div class="tabs__content-item" data-tabs-value="stock">
 <div class="accordion__group"><div class="accordion__group-header">VW</div><div>
  <div class="accordion__group"><div class="accordion__group-header accordion__group-header_darken">MULTIVAN V</div><div>
   <table><tr data-id="5263"><td>VW MULTIVAN V 2.0 TDI 4motion</td><td>1968 см3</td><td>140 л.с.</td><td>103 кВт</td><td>09/09 - 08/15</td><td>CAAC, CCHA</td></tr>
   <tr><td colspan="6"><table><tr><th>Ходовая часть</th><td>для усиленной подвески</td></tr></table></td></tr></table>
  </div></div>
 </div></div>
</div>
"""


def test_hola_fitment_parser_keeps_months_engine_and_restrictions():
    result = HolaFitmentSource.parse_page(HOLA_CARD, source_url="https://www.hola-auto.ru/card")
    assert result is not None
    row = result["applications"][0]
    assert (row["make"], row["model"], row["engine_code"]) == ("VW", "MULTIVAN V", "CAAC, CCHA")
    assert (row["year_from"], row["month_from"], row["year_to"], row["month_to"]) == (2009, 9, 2015, 8)
    assert row["restrictions"] == ["Ходовая часть: для усиленной подвески"]


METACO_CARD = """
<span class="active-breadcumb">4800-013</span><h1>Амортизатор передний 4800-013</h1>
<div class="characteristics-block"><div class="text-2"><span class="key">Тип</span><span class="val">Масляный</span></div></div>
<div class="metaco-model-control">Audi <span class="secondary-text">2</span><ul class="metaco-model-list">
<li>Audi 100 [C4]<span class="secondary-text"> 1991-1994 </span></li>
<li>Audi A6 [C4]<span class="secondary-text"> 1994&gt; </span></li></ul></div>
"""


def test_metaco_fitment_parser_preserves_generation_and_open_year():
    result = MetacoFitmentSource.parse_page(METACO_CARD, source_url="https://metaco.parts/catalog/4800013")
    assert result is not None
    assert result["damper_type"] == "Масляный"
    assert result["applications"][0]["model"] == "100 [C4]"
    assert result["applications"][0]["generation"] == "[C4]"
    assert result["applications"][1]["end_is_open"] is True


@pytest.mark.asyncio
async def test_entitlement_expiry_is_enforced(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'entitlements.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(FeatureEntitlement(key="admin:vehicle_fitment", tenant="admin",
            feature_key="vehicle_fitment", enabled=True))
        session.add(FeatureEntitlement(key="expired:vehicle_fitment", tenant="expired",
            feature_key="vehicle_fitment", enabled=True,
            expires_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)))
        await session.commit()
    assert await has_feature_access(sessions, "admin", "vehicle_fitment") is True
    assert await has_feature_access(sessions, "expired", "vehicle_fitment") is False
    assert await has_feature_access(sessions, "missing", "vehicle_fitment") is False
    await engine.dispose()


@pytest.mark.asyncio
async def test_fitment_job_runner_resumes_and_persists_partial_results(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'jobs.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    service = type("Service", (), {})()
    service.lookup = AsyncMock(side_effect=[
        {"brand": "KYB", "number": "333754", "status": "ok", "applications": [{}]},
        {"brand": "TORR", "number": "missing", "status": "not_found", "applications": []},
    ])
    async with sessions() as session:
        job = FitmentJob(tenant="admin", status="queued", total=2,
            requested_parts=[{"brand": "KYB", "number": "333754"},
                             {"brand": "TORR", "number": "missing"}])
        session.add(job); await session.commit(); job_id = job.id
    runner = FitmentJobRunner(service, sessions); await runner.start(); await runner.submit(job_id)
    await runner._queue.join(); await runner.stop()
    async with sessions() as session:
        stored = await session.get(FitmentJob, job_id)
        assert stored.status == "partial"
        assert stored.processed_count == 2
        assert len(stored.results) == 2
    await engine.dispose()


@pytest.mark.asyncio
async def test_fitment_job_api_is_idempotent_and_tenant_isolated(tmp_path, monkeypatch):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'job-api.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with sessions() as session:
        session.add(FeatureEntitlement(
            key="admin:vehicle_fitment", tenant="admin", feature_key="vehicle_fitment",
            enabled=True, limits={"max_parts_per_job": 10},
        ))
        await session.commit()
    monkeypatch.setattr(main, "SessionLocal", sessions)
    submit = AsyncMock()
    monkeypatch.setattr(main.fitment_runner, "submit", submit)
    payload = FitmentJobCreate(
        idempotency_key="stable-key",
        parts=[FitmentJobPart(brand="KYB", number="333754")],
    )
    first = await main.create_fitment_job(payload, tenant="admin")
    repeated = await main.create_fitment_job(payload, tenant="admin")
    assert repeated.id == first.id
    submit.assert_awaited_once_with(first.id)
    with pytest.raises(HTTPException) as hidden:
        await main.get_fitment_job(first.id, tenant="another-user")
    assert hidden.value.status_code == 404
    await engine.dispose()
