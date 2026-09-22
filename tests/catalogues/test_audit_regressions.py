import importlib
import json
from pathlib import Path

import pytest
from app.config import Settings
from app.sources.base import SourceStatus
from app.sources.ate import AteSource
from app.sources.febest import FebestSource
from app.sources.lynxauto import LynxautoSource
from app.sources.registry import CANDIDATES
from app.normalize import KIND_AFTERMARKET, KIND_OEM, classify_reference_brand

@pytest.mark.parametrize('name,klass', [('ate','AteSource'),('zimmermann','ZimmermannSource'),('febest','FebestSource'),('fap','FapSource')])
@pytest.mark.parametrize('status,payload', [(500,{}),(502,[]),(200,{'error':'temporarily unavailable'}),(200,None)])
@pytest.mark.asyncio
async def test_bad_upstream_cannot_become_cacheable_not_found(monkeypatch,name,klass,status,payload):
    module=importlib.import_module('app.sources.'+name)
    class Response:
        status_code=status
        text=json.dumps(payload)
        url='https://fixture.invalid/'
        def json(self):return payload
    class Client:
        async def get(self,*args,**kwargs):return Response()
        async def post(self,*args,**kwargs):return Response()
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
    monkeypatch.setattr(module,'build_client',lambda *a,**k:Client())
    result=await getattr(module,klass)(Settings(_env_file=None),None).lookup('58101H5A25')
    assert result.status in {SourceStatus.ERROR,SourceStatus.BLOCKED}
    assert not result.crosses

@pytest.mark.parametrize('description',['Brake Hose Holder','Brake Disc Protective Plate','Accessory Kit, disc brake pads'])
def test_ate_rejects_related_accessories(description):
    assert AteSource.article_group({'genericArticles':[{'genericArticleDescription':description}]}) is None

@pytest.mark.parametrize('description',['shock absorber boot','shock absorber mounting','shock absorber bushing','shock absorber bump stopper'])
def test_febest_rejects_shock_accessories(description):
    assert not FebestSource.is_shock({'description':description})

@pytest.mark.parametrize('description',['Опора амортизатора','Пыльник амортизатора','Кронштейн тормозного шланга','Ремкомплект тормозных колодок'])
def test_lynx_rejects_related_accessories(description):
    assert LynxautoSource.product_group(f'<div class="pcard-name"><h1>{description}</h1></div>') is None

def test_candidate_metadata_matches_registered_coverage():
    data=json.loads((Path(__file__).parents[2]/'app/sources/catalog.json').read_text())
    by_key={item['key']:item for item in data['sites']}
    for source in CANDIDATES:
        assert source.key in by_key,source.key
        assert set(by_key[source.key]['groups'])==set(source.groups),source.key


def test_brembo_direct_hose_card_is_not_an_empty_search():
    from app.sources.brembo import BremboSource
    html = '<div class="product-detail"><app-globalcomparatorcta brembo-code="T 85 112" product-sub-type="00083"></app-globalcomparatorcta></div>'
    assert BremboSource._brembo_codes(html)==['T 85 112']
    assert BremboSource._brembo_codes(html.replace('00083','99999'))==[]
    assert BremboSource._brembo_codes(html.replace('product-detail','recommendations'))==[]


def test_masterkit_navigation_does_not_classify_unrelated_product():
    from app.sources.masterkit import MasterkitSource
    html='<nav>Тормозные колодки</nav><h1>Амортизатор</h1>'
    assert not MasterkitSource.is_brake_pad(html)
    html+='<div class="partsInfoPropertiesRow"><span class="partsInfoPropertiesRowProperty">Товарная группа:</span><span>амортизаторы</span></div>'
    assert not MasterkitSource.is_brake_pad(html)


@pytest.mark.parametrize('name,klass',[('lynxauto','LynxautoSource'),('torr','TorrSource')])
@pytest.mark.parametrize('status',[500,502])
@pytest.mark.asyncio
async def test_html_catalogue_server_error_is_not_cacheable(monkeypatch,name,klass,status):
    module=importlib.import_module('app.sources.'+name)
    class Response:
        status_code=status
        text='<h1>Service unavailable</h1>'
        url='https://fixture.invalid/'
    class Client:
        async def get(self,*a,**kw):return Response()
        async def __aenter__(self):return self
        async def __aexit__(self,*a):pass
    monkeypatch.setattr(module,'build_client',lambda *a,**kw:Client())
    result=await getattr(module,klass)(Settings(_env_file=None),None).lookup('123')
    assert result.status is SourceStatus.ERROR


def test_metaco_reference_kind_overrides_file_for_known_vehicle_brands():
    assert classify_reference_brand("Mercedes Benz", KIND_AFTERMARKET) == KIND_OEM
    assert classify_reference_brand("VAG", KIND_AFTERMARKET) == KIND_OEM
    assert classify_reference_brand("ATE", KIND_OEM) == KIND_AFTERMARKET
    assert classify_reference_brand("UNKNOWN SUPPLIER", KIND_AFTERMARKET) == KIND_AFTERMARKET


@pytest.mark.parametrize("brand", ["HYUNDAI-KIA", "CITROEN-PEUGEOT", "CHERY"])
def test_metaco_compound_and_regional_vehicle_brands_are_oem(brand):
    assert classify_reference_brand(brand, KIND_AFTERMARKET) == KIND_OEM
