from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from selectolax.parser import HTMLParser

from app.config import get_settings
from app.normalize import number_key
from app.sources.brembo import BremboSource
from app.sources.brannor import BrannorSource
from app.sources.brixo import BrixoSource
from app.sources.hel import HelSource
from app.sources.hola import HolaSource
from app.sources.jnbk import JnbkSource
from app.sources.kyb import KybSource
from app.sources.luzar import LuzarSource
from app.sources.mintex import MintexSource
from app.sources.nibkru import NibkRuSource
from app.sources.nissens import NissensSource
from app.sources.sbparts import SbPartsSource
from app.sources.trialli import TrialliSource


ROOT = Path(__file__).parents[1] / "fixtures" / "catalogues"
MANIFESTS = [
    ROOT / "jnbk" / "brake_discs" / "manifest.yaml",
    ROOT / "luzar" / "radiators" / "manifest.yaml",
    ROOT / "nissens" / "radiators" / "manifest.yaml",
    ROOT / "hel" / "brake_hoses" / "manifest.yaml",
    ROOT / "kyb" / "shock_absorbers" / "manifest.yaml",
    ROOT / "hola" / "brake_pads" / "manifest.yaml",
    ROOT / "brannor" / "brake_pads" / "manifest.yaml",
    ROOT / "sbparts" / "brake_pads" / "manifest.yaml",
    ROOT / "brembo" / "brake_pads" / "manifest.yaml",
    ROOT / "trialli" / "brake_pads" / "manifest.yaml",
    ROOT / "brixo" / "radiators" / "manifest.yaml",
    ROOT / "nibkru" / "brake_pads" / "manifest.yaml",
    ROOT / "mintex" / "brake_discs" / "manifest.yaml",
]


def _manifest(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for relative, expected in data["fixtures"].items():
        assert hashlib.sha256((path.parent / relative).read_bytes()).hexdigest() == expected
    return data


def _pairs(crosses):
    return {
        (cross.brand, number_key(cross.number), cross.kind, cross.source_product)
        for cross in crosses
    }


def _expected(case, field="expected_pairs"):
    return {
        (pair["brand_canonical"], str(pair["number_key"]), pair["kind"], pair["source_product"])
        for pair in case[field]
    }


@pytest.mark.parametrize("manifest_path", MANIFESTS, ids=lambda path: path.parts[-3])
def test_existing_fixture_hashes_and_manifest_contract(manifest_path):
    manifest = _manifest(manifest_path)
    case = manifest["cases"][0]
    assert case["query_key"] == number_key(case["query_raw"])
    assert case["expected_pairs"]
    assert manifest["completeness_scope"]
    assert manifest["review_evidence"]


def test_jnbk_golden_is_exact():
    path = MANIFESTS[0]
    case = _manifest(path)["cases"][0]
    html = (path.parent / "../../../jnbk_product_RN2713.html").read_text()
    crosses = JnbkSource(get_settings(), None).parse_product(
        html, url="fixture", product="RN2713"
    )
    assert _pairs(crosses) == _expected(case)


def test_luzar_golden_is_exact():
    path = MANIFESTS[1]
    case = _manifest(path)["cases"][0]
    html = (path.parent / "../../../luzar_product_LRc0938.html").read_text()
    crosses = LuzarSource(get_settings(), None).parse_oems(
        HTMLParser(html), url="fixture", product="LRc 0938"
    )
    assert _pairs(crosses) == _expected(case)


def test_nissens_golden_is_exact_and_excludes_vehicle_suggestion():
    path = MANIFESTS[2]
    case = _manifest(path)["cases"][0]
    details = (path.parent / "../../../nissens_details_637609.html").read_text()
    search = (path.parent / "../../../nissens_search_8200735038.html").read_text()
    source = NissensSource(get_settings(), None)
    assert [hit["productID"] for hit in source.direct_hits(search)] == ["637609"]
    actual = _pairs(source.parse_oems(details, product="637609"))
    assert actual == _expected(case)
    assert actual.isdisjoint(_expected(case, "forbidden_pairs"))


def test_hel_golden_is_exact():
    path = MANIFESTS[3]
    case = _manifest(path)["cases"][0]
    html = (path.parent / "../../../hel_search_1K0611701.html").read_text()
    crosses, products = HelSource(get_settings(), None).parse_results(html, url="fixture")
    assert products == case["expected_products"]
    assert _pairs(crosses) == _expected(case)


def test_kyb_golden_is_exact():
    import json

    path = MANIFESTS[4]
    case = _manifest(path)["cases"][0]
    payload = json.loads((path.parent / "../../../kyb_cross_4851080378.json").read_text())
    crosses = KybSource(get_settings(), None).parse_cross(payload, url="fixture")
    assert _pairs(crosses) == _expected(case)


def test_hola_golden_is_exact():
    path = MANIFESTS[5]
    case = _manifest(path)["cases"][0]
    search = (path.parent / "../../../hola_search_58101H5A25.html").read_text()
    details = (path.parent / "../../../hola_product_BD836.html").read_text()
    source = HolaSource(get_settings(), None)
    assert source.product_links(search) == [("/production/brake-pads-and-shoes/BD836/", "BD836")]
    assert _pairs(source.parse_numbers(details, url="fixture", product="BD836")) == _expected(case)


def test_brannor_golden_is_exact():
    path = MANIFESTS[6]
    case = _manifest(path)["cases"][0]
    search = (path.parent / "../../../brannor_search_8K0698451D.html").read_text()
    details = (path.parent / "../../../brannor_product_BRP1386A.html").read_text()
    source = BrannorSource(get_settings(), None)
    assert [product for _, product in source.product_links(search)] == ["BRP1386A"]
    assert _pairs(source.parse_oems(details, url="fixture", product="BRP1386A")) == _expected(case)


def test_sbparts_golden_is_exact_and_documents_duplicate_rows():
    import json

    path = MANIFESTS[7]
    case = _manifest(path)["cases"][0]
    search = json.loads((path.parent / "search.json").read_text())
    details = (path.parent / "product_BP11537.html").read_text()
    source = SbPartsSource(get_settings(), None)
    assert source._product_paths(search["products"]) == ["/catalog/BP11537"]
    crosses = [
        *source.make_cross("SB NAGAMOCHI", "BP11537", product="BP11537", url="fixture"),
        *source._parse_analogs(details, "BP11537", "fixture"),
    ]
    assert _pairs(crosses) == _expected(case)
    assert len(crosses) == 82
    assert len(_pairs(crosses)) == 78, "W0 baseline: source contains four duplicate rows"


def test_brembo_golden_is_exact():
    import json

    path = MANIFESTS[8]
    case = _manifest(path)["cases"][0]
    source = BremboSource(get_settings(), None)
    results = (path.parent / "results.html").read_text()
    code = "P 30 122"
    assert source._brembo_codes(results) == [code]
    crosses = [
        *source.make_cross("BREMBO", code, product=code, url="fixture"),
        *source.parse_manufacturer_refs(
            json.loads((path.parent / "manufacturer_P30122.json").read_text()),
            code=code,
            url="fixture",
        ),
        *source.parse_competitor_refs(
            json.loads((path.parent / "competitor_P30122.json").read_text()),
            code=code,
            url="fixture",
        ),
    ]
    assert _pairs(crosses) == _expected(case)


def test_trialli_golden_is_exact():
    path = MANIFESTS[9]
    case = _manifest(path)["cases"][0]
    source = TrialliSource(get_settings(), None)
    search = (path.parent / "search.html").read_text()
    assert len(source.product_paths(search)) == 2
    crosses = []
    products = []
    for product_path in sorted(path.parent.glob("product_*.html")):
        html = product_path.read_text()
        article = source.article_from_html(html)
        products.append(article)
        crosses.extend(source.make_cross("TRIALLI", article, product=article, url="fixture"))
        crosses.extend(source.parse_oems(html, url="fixture", product=article))
    assert products == case["expected_products"]
    assert _pairs(crosses) == _expected(case)


class _JsonResponse:
    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


def test_brixo_radiator_golden_is_exact():
    import json

    path = MANIFESTS[10]
    case = _manifest(path)["cases"][0]
    source = BrixoSource(get_settings(), None)
    search = json.loads((path.parent / "search_8200735038.json").read_text())
    info = json.loads((path.parent / "info_3631-1002.json").read_text())
    assert source.articles(_JsonResponse(search)) == [("3631-1002", "SAKURA")]
    crosses = [
        *source.make_cross("SAKURA", "3631-1002", product="3631-1002", url="fixture"),
        *source.parse_references(info, url="fixture", product="3631-1002"),
    ]
    assert _pairs(crosses) == _expected(case)


def test_nibk_shared_catalogue_golden_is_exact_for_reviewed_card():
    import json

    path = MANIFESTS[11]
    case = _manifest(path)["cases"][0]
    source = NibkRuSource(get_settings(), None)
    search = json.loads((path.parent / "../../../brixo_search_58101H5A25.json").read_text())
    info = json.loads((path.parent / "../../../brixo_info_PN0537.json").read_text())
    assert source.articles(_JsonResponse(search)) == [("PN0537", "NiBK"), ("PN0537S", "NiBK")]
    crosses = [
        *source.make_cross("NiBK", "PN0537", product="PN0537", url="fixture"),
        *source.parse_references(info, url="fixture", product="PN0537"),
    ]
    assert _pairs(crosses) == _expected(case)


def test_mintex_datasheet_golden_is_exact():
    path = MANIFESTS[12]
    case = _manifest(path)["cases"][0]
    html = (path.parent / "../../../brakebook_datasheet_BPD2244.html").read_text()
    crosses = MintexSource(get_settings(), None).parse_datasheet(
        html, url="fixture", product="BPD2244_402"
    )
    assert _pairs(crosses) == _expected(case)
