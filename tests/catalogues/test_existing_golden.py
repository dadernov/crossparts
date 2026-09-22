from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
import yaml
from selectolax.parser import HTMLParser

from app.config import get_settings
from app.normalize import number_key
from app.sources.brannor import BrannorSource
from app.sources.hel import HelSource
from app.sources.hola import HolaSource
from app.sources.jnbk import JnbkSource
from app.sources.kyb import KybSource
from app.sources.luzar import LuzarSource
from app.sources.nissens import NissensSource


ROOT = Path(__file__).parents[1] / "fixtures" / "catalogues"
MANIFESTS = [
    ROOT / "jnbk" / "brake_discs" / "manifest.yaml",
    ROOT / "luzar" / "radiators" / "manifest.yaml",
    ROOT / "nissens" / "radiators" / "manifest.yaml",
    ROOT / "hel" / "brake_hoses" / "manifest.yaml",
    ROOT / "kyb" / "shock_absorbers" / "manifest.yaml",
    ROOT / "hola" / "brake_pads" / "manifest.yaml",
    ROOT / "brannor" / "brake_pads" / "manifest.yaml",
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
