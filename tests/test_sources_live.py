"""Живые проверки источников. Запуск: CP_LIVE=1 python3 -m pytest tests/test_sources_live.py -q"""
import os, pathlib, sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.normalize import number_key
from app.sources.brembo import BremboSource
from app.sources.base import SourceStatus
from app.sources.sbparts import SbPartsSource

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.getenv("CP_LIVE") != "1",
        reason="нужен явный доступ в интернет: CP_LIVE=1",
    ),
]

OE = "58101H5A25"


@pytest.mark.asyncio
async def test_sbparts_returns_real_crosses():
    res = await SbPartsSource(get_settings(), None).lookup(OE)
    assert res.status is SourceStatus.OK
    assert "BP11537" in res.products
    keys = {number_key(c.number) for c in res.crosses}
    assert {"PN0537", "58101H5A25", "1064001724 02".replace(" ", "")} & keys
    assert any(c.brand == "HYUNDAI" for c in res.crosses)


@pytest.mark.asyncio
async def test_brembo_returns_oe_and_competitor_refs():
    res = await BremboSource(get_settings(), None).lookup(OE)
    assert res.status is SourceStatus.OK
    assert res.products == ["P 30 122"]
    kinds = {c.kind for c in res.crosses}
    assert {"oem", "aftermarket"} <= kinds
    assert number_key("58101H5A25") in {number_key(c.number) for c in res.crosses}


@pytest.mark.asyncio
async def test_luzar_returns_oem_numbers_for_radiator():
    from app.sources.luzar import LuzarSource
    res = await LuzarSource(get_settings(), None).lookup("8200735038")
    assert res.status is SourceStatus.OK
    assert any(p.startswith("LRc") for p in res.products)
    keys = {number_key(c.number) for c in res.crosses}
    assert {"8200735038", "214104453R"} <= keys


@pytest.mark.asyncio
async def test_nissens_returns_oem_numbers_for_radiator():
    from app.sources.nissens import NissensSource
    res = await NissensSource(get_settings(), None).lookup("8200735038")
    assert res.status is SourceStatus.OK
    assert res.products == ["637609"]
    keys = {number_key(c.number) for c in res.crosses}
    assert {"637609", "8200735038", "8660003459"} <= keys


@pytest.mark.asyncio
async def test_brixo_returns_branded_crosses():
    from app.sources.brixo import BrixoSource
    res = await BrixoSource(get_settings(), None).lookup(OE)
    assert res.status is SourceStatus.OK
    assert "PN0537" in res.products
    keys = {number_key(c.number) for c in res.crosses}
    assert {"PN0537", "58101H5A25", "581014LA00"} <= keys
    assert {"KIA", "HYUNDAI"} <= {c.brand for c in res.crosses}


@pytest.mark.asyncio
async def test_kyb_normalises_the_number_before_asking():
    from app.sources.kyb import KybSource
    # Сайт находит номер только записанный слитно; адаптер обязан это делать сам.
    res = await KybSource(get_settings(), None).lookup("48510-80378")
    assert res.status is SourceStatus.OK
    assert "339267" in res.products


@pytest.mark.asyncio
async def test_hola_returns_oe_numbers_with_brands():
    from app.sources.hola import HolaSource
    res = await HolaSource(get_settings(), None).lookup(OE)
    assert res.status is SourceStatus.OK
    assert res.products == ["BD836"]
    assert {"HYUNDAI", "KIA"} <= {c.brand for c in res.crosses}


@pytest.mark.asyncio
async def test_brannor_returns_oe_numbers_with_spaces():
    from app.sources.brannor import BrannorSource
    res = await BrannorSource(get_settings(), None).lookup("8K0698451D")
    assert res.status is SourceStatus.OK
    assert res.products == ["BRP1386A"]
    # Номера на сайте записаны с пробелами — сверяем по нормализованному ключу.
    assert number_key("8K0698451D") in {number_key(c.number) for c in res.crosses}


@pytest.mark.asyncio
async def test_hel_finds_hose_by_oe():
    from app.sources.hel import HelSource
    res = await HelSource(get_settings(), None).lookup("1K0611701")
    assert res.status is SourceStatus.OK
    assert res.products == ["VW-4-409"]


@pytest.mark.asyncio
async def test_sbparts_also_covers_brake_hoses():
    # Каталог отдаёт серию BH по ОЕ шланга — значит источник должен
    # спрашиваться и для группы «Тормозные шланги», а не только колодок.
    from app.groups import BRAKE_HOSES
    assert BRAKE_HOSES in SbPartsSource.groups
    res = await SbPartsSource(get_settings(), None).lookup("58731-2E000")
    assert res.status is SourceStatus.OK
    assert res.products == ["BH13001FL"]
