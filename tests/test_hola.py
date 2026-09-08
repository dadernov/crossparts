"""HOLA: разбор выдачи поиска по чужому номеру и карточки (fixtures/SOURCE.md)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.groups import BRAKE_DISCS, BRAKE_HOSES, BRAKE_PADS, SHOCK_ABSORBERS
from app.normalize import KIND_OEM, number_key
from app.sources.hola import HolaSource

FIX = pathlib.Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


def test_takes_article_out_of_product_link():
    src = HolaSource(get_settings(), None)
    found = src.product_links(_read("hola_search_58101H5A25.html"))
    assert found == [("/production/brake-pads-and-shoes/BD836/", "BD836")]


def test_section_links_are_not_products():
    src = HolaSource(get_settings(), None)
    assert src.product_links(
        '<a href="/production/shock-absorbers/">раздел</a>'
        '<a href="/production/">каталог</a>'
    ) == []


def test_parses_oe_numbers_with_brands():
    src = HolaSource(get_settings(), None)
    crosses = src.parse_numbers(_read("hola_product_BD836.html"), url="u", product="BD836")
    assert len(crosses) == 14
    assert {c.brand for c in crosses} == {"HYUNDAI", "KIA"}
    assert number_key("58101H5A25") in {number_key(c.number) for c in crosses}
    assert {c.kind for c in crosses} == {KIND_OEM}


def test_tab_header_with_the_same_attribute_is_not_mistaken_for_the_table():
    # На заголовке вкладки висит тот же data-tabs-value, и в документе он выше.
    src = HolaSource(get_settings(), None)
    html = ('<div class="tabs__head-item" data-tabs-value="numbers">Номера</div>'
            '<div class="tabs__content-item" data-tabs-value="numbers">'
            '<table><tr><td>KIA</td><td class="right">581014LA00</td></tr></table></div>')
    assert [(c.brand, c.number) for c in src.parse_numbers(html, url="u")] == \
        [("KIA", "581014LA00")]


def test_covers_four_groups():
    assert HolaSource.groups == (BRAKE_PADS, BRAKE_DISCS, BRAKE_HOSES, SHOCK_ABSORBERS)
