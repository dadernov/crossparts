from __future__ import annotations

import pytest

from app.config import Settings
from app.sources.base import SourceStatus


class Response:
    def __init__(self, *, status=200, text="", payload=None, url="https://fixture.invalid/"):
        self.status_code = status
        self.text = text
        self._payload = payload
        self.url = url

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


@pytest.mark.asyncio
async def test_masterkit_keeps_good_card_and_marks_failed_card_partial(monkeypatch):
    from app.sources.masterkit import MasterkitSource
    import app.sources.masterkit as module

    good = '''<div class="partsInfoPropertiesRow">
      <span class="partsInfoPropertiesRowProperty">Товарная группа:</span>
      <span>тормозные колодки</span></div>'''

    class Client:
        async def get(self, url, **kwargs):
            if kwargs.get("params"):
                return Response(payload={"result": [
                    {"cross": {"number": "GOOD-1"}}, {"cross": {"number": "BAD-2"}},
                ]})
            return Response(text=good) if "GOOD-1" in url else Response(status=502)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None

    monkeypatch.setattr(module, "build_client", lambda *args, **kwargs: Client())
    result = await MasterkitSource(Settings(_env_file=None), None).lookup("58101H5A25")
    assert result.status is SourceStatus.PARTIAL
    assert result.products == ["GOOD-1"]
    assert "не проверено карточек: 1" in (result.message or "")


@pytest.mark.asyncio
async def test_ganz_keeps_good_card_and_marks_failed_card_partial(monkeypatch):
    from app.sources.ganz import GanzSource
    import app.sources.ganz as module

    search = '''<div class="search-custom-results">
      <div class="search-item"><div class="h4"><a href="/catalog/good/">good</a></div></div>
      <div class="search-item"><div class="h4"><a href="/catalog/bad/">bad</a></div></div>
    </div>'''
    card = '''<h1 class="product_page_title">Колодки тормозные передние</h1>
      <div class="product_page_info_prop"><span class="product_page_info_prop_title">Артикул</span><span class="product_page_info_prop_value">GIJ0001</span></div>
      <div class="product_page_info_prop"><span class="product_page_info_prop_title">Оригинальный номер</span><span class="product_page_info_prop_value">58101H5A25</span></div>'''

    class Client:
        async def get(self, url, **kwargs):
            if url == module.SEARCH: return Response(text=search, url=url)
            if url.endswith("/good/"): return Response(text=card, url=url)
            return Response(status=502, url=url)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None

    monkeypatch.setattr(module, "build_client", lambda *args, **kwargs: Client())
    result = await GanzSource(Settings(_env_file=None), None).lookup("58101H5A25")
    assert result.status is SourceStatus.PARTIAL
    assert result.products == ["GIJ0001"]


@pytest.mark.asyncio
async def test_torr_keeps_good_card_and_marks_failed_card_partial(monkeypatch):
    from app.sources.torr import TorrSource
    import app.sources.torr as module

    search = '<a href="/ru/catalog/GOOD1">good</a><a href="/ru/catalog/BAD2">bad</a>'
    card = '''<h1 class="product-page__title">Shock absorber</h1>
      <table class="item-page__applicability"><tr><td>HYUNDAI 553101G210</td></tr></table>'''

    class Client:
        async def get(self, url, **kwargs):
            if url == module.CATALOGUE: return Response(text=search, url=url)
            if url.endswith("GOOD1"): return Response(text=card, url=url)
            return Response(status=502, url=url)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None

    monkeypatch.setattr(module, "build_client", lambda *args, **kwargs: Client())
    result = await TorrSource(Settings(_env_file=None), None).lookup("553101G210")
    assert result.status is SourceStatus.PARTIAL
    assert result.products == ["GOOD1"]


@pytest.mark.asyncio
async def test_fap_marks_missing_reference_table_partial(monkeypatch):
    from app.sources.fap import FapSource
    import app.sources.fap as module

    product = {"fapProductCode": "FDP0372", "deleted": 0,
               "ext3": '{"Goods group":"Brake Pad"}'}

    class Client:
        calls = 0
        async def get(self, url, **kwargs):
            self.calls += 1
            if self.calls == 1: return Response(payload=[product], url=url)
            return Response(status=502, payload=[], url=url)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None

    monkeypatch.setattr(module, "build_client", lambda *args, **kwargs: Client())
    result = await FapSource(Settings(_env_file=None), None).lookup("58101H5A25")
    assert result.status is SourceStatus.PARTIAL
    assert result.products == ["FDP0372"]
    assert "не загружено таблиц OE: 1" in (result.message or "")


@pytest.mark.asyncio
async def test_brembo_marks_one_failed_reference_endpoint_partial(monkeypatch):
    from app.sources.brembo import BremboSource
    import app.sources.brembo as module

    home = '<input name="__RequestVerificationToken" value="token">'
    card = '''<div class="product-detail"><app-globalcomparatorcta
      brembo-code="T 85 112" product-sub-type="00083"></app-globalcomparatorcta></div>'''

    class Client:
        async def get(self, url, **kwargs):
            if url.endswith("/europe/ru"): return Response(text=home, url=url)
            return Response(text=card, url=url)
        async def post(self, url, **kwargs):
            if url.endswith("search/searchcode"):
                return Response(payload={"url": "/europe/ru/catalogue/hydraulic/T_85_112"}, url=url)
            if url.endswith("getproductmanufacturerreferences"):
                return Response(payload=[{"brandsName": "VAG", "code": "1K0611701K"}], url=url)
            return Response(status=502, payload=[], url=url)
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return None

    monkeypatch.setattr(module, "build_client", lambda *args, **kwargs: Client())
    result = await BremboSource(Settings(_env_file=None), None).lookup("1K0611701K")
    assert result.status is SourceStatus.PARTIAL
    assert result.products == ["T 85 112"]
    assert "не загружено таблиц ссылок: 1" in (result.message or "")
