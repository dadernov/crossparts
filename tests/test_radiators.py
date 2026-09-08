"""Источники по радиаторам: LUZAR и Nissens.

Разметка в фикстурах снята с живых сайтов (см. fixtures/SOURCE.md), поэтому
разбор проверяется по-настоящему и без сети.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from selectolax.parser import HTMLParser

from app.config import get_settings
from app.groups import RADIATORS
from app.normalize import KIND_OEM, number_key
from app.sources.luzar import LuzarSource
from app.sources.nissens import NissensSource, split_call_args

FIX = pathlib.Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


# --------------------------------------------------------------- LUZAR

def test_luzar_reads_article_and_oem_numbers():
    src = LuzarSource(get_settings(), None)
    tree = HTMLParser(_read("luzar_product_LRc0938.html"))
    assert src.article_from_tree(tree) == "LRc 0938"

    crosses = src.parse_oems(tree, url="u", product="LRc 0938")
    assert {c.number for c in crosses} == {"8200735038", "214104453R", "214104AA0A"}
    # Марку авто сайт не проставляет — такие номера остаются ОЕМ без бренда.
    assert {c.brand for c in crosses} == {"OEM"}
    assert {c.kind for c in crosses} == {KIND_OEM}


def test_luzar_takes_only_catalogue_product_links():
    src = LuzarSource(get_settings(), None)
    paths = src.product_paths(
        '<a href="/catalogue/radiatory/radiatory-okhlazhdeniya/radiator-lrc-0938/">товар</a>'
        '<a href="/catalogue/radiatory/radiatory-okhlazhdeniya/radiator-lrc-0938/?x=1">он же</a>'
        '<a href="/catalogue/?q=8200735038">поиск</a>'
        '<a href="/about/">о нас</a>'
    )
    assert paths == ["/catalogue/radiatory/radiatory-okhlazhdeniya/radiator-lrc-0938/"]


def test_luzar_covers_radiators():
    assert LuzarSource.groups == (RADIATORS,)


# ------------------------------------------------------------- Nissens

def test_nissens_splits_js_call_arguments():
    # Скобки и запятые внутри 'LOGAN (2005)' не должны рвать разбор,
    # а хвостовой пробел в '1.2 ' сайт ждёт обратно байт в байт.
    args = split_call_args(
        "this,\n '637609', 12932791, 1276251, 'DACIA', 'LOGAN (2005)', '1.2 ', "
        "'Manual', '-', 'Petrol', 'D4F732/D4F734', false, '637609', 0); return false;"
    )
    assert args[:7] == ["this", "637609", "12932791", "1276251", "DACIA",
                        "LOGAN (2005)", "1.2 "]


def test_nissens_takes_direct_hit_products_only():
    src = NissensSource(get_settings(), None)
    hits = src.direct_hits(_read("nissens_search_8200735038.html"))
    # В ячейке две кнопки: 637609 — прямое попадание, 637612 — просто другая
    # деталь для той же машины, кроссом она не является.
    assert [h["productID"] for h in hits] == ["637609"]
    assert hits[0]["carProductID"] == "12932791"
    assert hits[0]["modelID"] == "1.2 "
    assert hits[0]["engineCode"] == "D4F732/D4F734"
    assert hits[0]["isCore"] == "false"


def test_nissens_parses_oe_numbers_from_card():
    src = NissensSource(get_settings(), None)
    crosses = src.parse_oems(_read("nissens_details_637609.html"), product="637609")
    keys = {number_key(c.number) for c in crosses}
    assert keys == {"8200735038", "8660003459"}
    assert {c.kind for c in crosses} == {KIND_OEM}


def test_nissens_reads_search_form_fields():
    src = NissensSource(get_settings(), None)
    action, fields = src.search_form(
        '<form id="formDoSearch" action="/Product/Search?SearchID=abc" method="post">'
        '<input name="SearchID" value="abc"><input name="PageNo" value="0">'
        '<input name="SearchParameters.OeNumber" value="">'
        '</form>'
    )
    assert action == "/Product/Search?SearchID=abc"
    assert fields == {"SearchID": "abc", "PageNo": "0", "SearchParameters.OeNumber": ""}
