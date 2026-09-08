"""HEL: оригинальные номера читаются прямо из карточки выдачи (fixtures/SOURCE.md)."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.groups import BRAKE_HOSES
from app.normalize import KIND_AFTERMARKET, KIND_OEM
from app.sources.hel import HelSource

FIX = pathlib.Path(__file__).parent / "fixtures"


def test_reads_article_and_oe_numbers_from_the_card():
    src = HelSource(get_settings(), None)
    crosses, products = src.parse_results(
        (FIX / "hel_search_1K0611701.html").read_text(encoding="utf-8", errors="replace"),
        url="u")
    assert products == ["VW-4-409"]
    assert [(c.brand, c.number) for c in crosses] == [
        ("HEL", "VW-4-409"), ("OEM", "1K0611701K"), ("OEM", "1K0611775C")]


def test_own_article_and_oe_numbers_get_different_kinds():
    src = HelSource(get_settings(), None)
    crosses, _ = src.parse_results(
        (FIX / "hel_search_1K0611701.html").read_text(encoding="utf-8", errors="replace"),
        url="u")
    kinds = {c.brand: c.kind for c in crosses}
    assert kinds["HEL"] == KIND_AFTERMARKET
    assert kinds["OEM"] == KIND_OEM


def test_empty_search_page_yields_nothing():
    src = HelSource(get_settings(), None)
    assert src.parse_results("<html><body>Нет товаров</body></html>", url="u") == ([], [])


def test_covers_brake_hoses():
    assert HelSource.groups == (BRAKE_HOSES,)
