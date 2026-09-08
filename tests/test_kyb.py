"""KYB: разбор ответа сервиса кроссировки (fixtures/SOURCE.md)."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.groups import SHOCK_ABSORBERS
from app.normalize import KIND_AFTERMARKET, KIND_OEM, number_key
from app.sources.kyb import KybSource

FIX = pathlib.Path(__file__).parent / "fixtures"


def test_parses_kyb_articles_and_oe_numbers():
    src = KybSource(get_settings(), None)
    payload = json.loads((FIX / "kyb_cross_4851080378.json").read_text(encoding="utf-8"))
    crosses = src.parse_cross(payload, url="u")
    kinds = {(c.brand, c.kind) for c in crosses}
    assert ("KYB", KIND_AFTERMARKET) in kinds
    assert ("TOYOTA", KIND_OEM) in kinds
    assert {c.number for c in crosses if c.brand == "KYB"} == {"339267", "NST5395R"}
    assert number_key("48510-80378") in {number_key(c.number) for c in crosses}


def test_empty_cross_list_gives_nothing():
    src = KybSource(get_settings(), None)
    assert src.parse_cross({"data": {"partNumber": "X", "cross": []}, "err": 0}, url="u") == []
    assert src.parse_cross({}, url="u") == []


def test_row_without_maker_still_yields_the_kyb_article():
    src = KybSource(get_settings(), None)
    crosses = src.parse_cross({"data": {"cross": [{"kyb_pn": "349185", "oe_pn": "4853080605"}]}},
                              url="u")
    assert [(c.brand, c.number) for c in crosses] == [("KYB", "349185")]


def test_covers_shock_absorbers():
    assert KybSource.groups == (SHOCK_ABSORBERS,)
