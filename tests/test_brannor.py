"""BRANNOR: разбор выдачи «уточните автомобиль» и списка ОЕ (fixtures/SOURCE.md)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.groups import BRAKE_DISCS, BRAKE_PADS
from app.normalize import KIND_OEM, number_key
from app.sources.brannor import BrannorSource, split_brand_number

FIX = pathlib.Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def test_same_card_under_several_cars_is_fetched_once():
    # Выдача повторяет одну карточку для A4, A5, Q5 и SQ5 — адреса разные,
    # артикул один; качать её четыре раза незачем.
    found = BrannorSource.product_links(_read("brannor_search_8K0698451D.html"))
    assert [article for _, article in found] == ["BRP1386A"]


def test_article_is_taken_from_the_url_tail():
    assert BrannorSource.article_from_url(
        "https://brannor.ru/brannor-zadnie-tormoznie-kolodki-dlya-audi-a4-brp1386a") == "BRP1386A"
    assert BrannorSource.article_from_url(
        "https://brannor.ru/toyota/camry/toyota-camry-2006-xv40/") is None
    assert BrannorSource.article_from_url("https://brannor.ru/o-nas") is None


def test_number_with_spaces_is_split_off_the_brand():
    assert split_brand_number("VAG 8K0 698 451D") == ("VAG", "8K0 698 451D")
    assert split_brand_number("MERCEDES BENZ A0044205020") == ("MERCEDES BENZ", "A0044205020")
    assert split_brand_number("8K0698451D") == ("", "8K0698451D")


def test_parses_oe_list_from_the_card():
    src = BrannorSource(get_settings(), None)
    crosses = src.parse_oems(_read("brannor_product_BRP1386A.html"), url="u", product="BRP1386A")
    assert len(crosses) == 14
    assert {c.brand for c in crosses} == {"VAG"}
    assert number_key("8K0698451D") in {number_key(c.number) for c in crosses}
    assert {c.kind for c in crosses} == {KIND_OEM}


def test_covers_pads_and_discs():
    assert BrannorSource.groups == (BRAKE_PADS, BRAKE_DISCS)
