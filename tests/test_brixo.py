"""Каталог Brixo (NiBK, SAKURA): разбор ответов открытого JSON-API.

Фикстуры — настоящие ответы `brixogroup.com` (см. fixtures/SOURCE.md).
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.groups import BRAKE_DISCS, BRAKE_PADS, RADIATORS
from app.normalize import KIND_AFTERMARKET, KIND_OEM, number_key
from app.sources.brixo import BrixoSource

FIX = pathlib.Path(__file__).parent / "fixtures"


def _json(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


class _Response:
    """Минимальный дублёр httpx-ответа: адаптеру нужен только ``json()``."""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        if isinstance(self._payload, str):
            raise ValueError("not json")
        return self._payload


def test_reads_articles_with_their_brands():
    src = BrixoSource(get_settings(), None)
    found = src.articles(_Response(_json("brixo_search_58101H5A25.json")))
    assert found == [("PN0537", "NiBK"), ("PN0537S", "NiBK")]


def test_non_json_answer_is_distinguished_from_empty_result():
    # Пустой список — «не найдено», а сломанный ответ — ошибка источника;
    # путать их нельзя, иначе блокировка выглядит как отсутствие номера.
    src = BrixoSource(get_settings(), None)
    assert src.articles(_Response([])) == []
    assert src.articles(_Response("<html>503</html>")) is None
    assert src.articles(_Response({"message": "Unauthenticated."})) is None


def test_parses_brake_pad_references_with_brands():
    src = BrixoSource(get_settings(), None)
    crosses = src.parse_references(_json("brixo_info_PN0537.json"), url="u", product="PN0537")
    assert len(crosses) == 61
    keys = {number_key(c.number) for c in crosses}
    assert {"58101H5A25", "581014LA00", "106400172402"} <= keys
    assert {"KIA", "HYUNDAI", "GEELY"} <= {c.brand for c in crosses}
    assert {c.kind for c in crosses} == {KIND_OEM}


def test_parses_radiator_references():
    src = BrixoSource(get_settings(), None)
    crosses = src.parse_references(_json("brixo_info_3631-1002.json"), url="u")
    keys = {number_key(c.number) for c in crosses}
    assert {"8200735038", "214104453R", "214104AA0A"} <= keys
    assert {"RENAULT", "DACIA", "LADA"} <= {c.brand for c in crosses}


def test_own_article_is_an_aftermarket_cross():
    src = BrixoSource(get_settings(), None)
    assert [c.kind for c in src.make_cross("NiBK", "PN0537")] == [KIND_AFTERMARKET]
    assert [c.kind for c in src.make_cross("SAKURA", "3631-1002")] == [KIND_AFTERMARKET]


def test_card_without_references_yields_nothing():
    src = BrixoSource(get_settings(), None)
    assert src.parse_references({}, url="u") == []
    assert src.parse_references({"references": None}, url="u") == []


def test_covers_pads_discs_and_radiators():
    assert BrixoSource.groups == (BRAKE_PADS, BRAKE_DISCS, RADIATORS)
