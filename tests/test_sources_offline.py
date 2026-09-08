"""Разбор реальной разметки jnbk и brakebook по сохранённым фикстурам.

Живые сайты закрыты для нашего IP, но HTML настоящий (см. fixtures/SOURCE.md),
поэтому логика парсинга проверяется полноценно и без сети.
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app.config import get_settings
from app.normalize import KIND_AFTERMARKET, KIND_OEM, number_key
from app.sources.jnbk import JnbkSource
from app.sources.mintex import MintexSource

FIX = pathlib.Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- jnbk

def test_jnbk_parses_cross_reference_block():
    src = JnbkSource(get_settings(), None)
    crosses = src.parse_product(_read("jnbk_product_RN2713.html"), url="u", product="RN2713")
    pairs = {(c.brand, c.number) for c in crosses}
    assert pairs == {
        ("HI-Q", "SD4051"),
        ("TOYOTA", "42431-06050"),
        ("TOYOTA", "42431-06051"),
        ("TOYOTA", "42431-33100"),
    }
    kinds = {c.brand: c.kind for c in crosses}
    assert kinds["TOYOTA"] == KIND_OEM
    assert kinds["HI-Q"] == KIND_AFTERMARKET


def test_jnbk_reads_article_from_title():
    src = JnbkSource(get_settings(), None)
    assert src.article_from_html(_read("jnbk_product_RN2713.html")) == "RN2713"


def test_jnbk_ignores_page_without_cross_block():
    src = JnbkSource(get_settings(), None)
    assert src.parse_product(_read("jnbk_catalogue_cars.html"), url="u") == []


def test_jnbk_extracts_product_links():
    src = JnbkSource(get_settings(), None)
    links = src.result_links(
        '<a href="https://jnbk-brakes.com/catalogue/cars/brake/112694/RN1162V">RN1162V</a>'
        '<a href="/catalogue/cars/brake/112694/RN1162V">dup</a>'
        '<a href="/about">nope</a>'
    )
    assert links == [("/catalogue/cars/brake/112694/RN1162V", "RN1162V")]


# -------------------------------------------------------------- mintex

def test_mintex_parses_oe_reference_table():
    src = MintexSource(get_settings(), None)
    crosses = src.parse_datasheet(_read("brakebook_datasheet_BPD2244.html"), url="u")
    # Внешний <tr> оборачивает внутреннюю таблицу — строки не должны задваиваться.
    assert len(crosses) == len({(c.brand, c.number) for c in crosses}) == 72
    brands = {c.brand for c in crosses}
    assert {"AUDI", "CHRYSLER", "VW", "SKODA", "JEEP"} <= brands
    keys = {number_key(c.number) for c in crosses}
    assert "7B0698151E" in keys and "68144163AA" in keys


def test_mintex_reads_article_from_hidden_field():
    src = MintexSource(get_settings(), None)
    assert src.article_from_html(_read("brakebook_datasheet_BPD2244.html")) == "BPD2244_402"


def test_mintex_finds_viewstate_on_search_page():
    import re
    assert re.search(r'name="javax\.faces\.ViewState"', _read("brakebook_search.html"))


def test_mintex_detects_cloudflare_challenge():
    src = MintexSource(get_settings(), None)
    assert src._is_block(403, "<title>Just a moment...</title>")
    assert src._is_block(200, "Performing security verification")
    assert not src._is_block(200, "<html><body>нормальная страница</body></html>")


def test_mintex_extracts_datasheet_links():
    src = MintexSource(get_settings(), None)
    links = src.datasheet_links(
        '<a href="/bb/mintex/ru/MDB1234_402/datasheet.xhtml">x</a>'
        '<a href="/bb/mintex/ru/other.xhtml">no</a>'
    )
    assert links == [("/bb/mintex/ru/MDB1234_402/datasheet.xhtml", "MDB1234_402")]


# ------------------------------------------------------- антибот-детектор

def test_antibot_detects_localised_cloudflare_challenge():
    """Cloudflare переводит challenge; ловим по структуре, а не по тексту.

    Реальная страница с mintex.brakebook.com приходит с заголовком
    «Один момент…» — англоязычные маркеры её не находили.
    """
    from app.sources.antibot import looks_blocked

    page = _read("cloudflare_challenge_ru.html")
    assert "Один момент" in page, "фикстура должна быть локализованной страницей"
    assert "just a moment" not in page.lower()
    assert looks_blocked(200, page)


def test_antibot_passes_normal_pages():
    from app.sources.antibot import looks_blocked

    assert not looks_blocked(200, _read("jnbk_product_RN2713.html"))
    assert not looks_blocked(200, _read("brakebook_datasheet_BPD2244.html"))
    assert not looks_blocked(200, "<html><body>обычная страница</body></html>")


def test_antibot_flags_blocking_statuses():
    from app.sources.antibot import looks_blocked

    for status in (401, 403, 429, 503):
        assert looks_blocked(status, "<html>ok</html>")
    assert not looks_blocked(200, "<html>ok</html>")


# ------------------------------------------------- переиспользование сессии

def test_clearance_store_reuses_cookies_until_ttl():
    """Challenge стоит ~1.6 МБ трафика — cookies обязаны переиспользоваться."""
    import httpx

    from app.sources.clearance import ClearanceStore

    store = ClearanceStore(ttl_seconds=60)
    assert store.get() == []

    store.put([{"name": "cf_clearance", "value": "abc", "domain": ".brakebook.com", "path": "/"}])
    client = httpx.AsyncClient()
    assert store.apply(client) is True
    assert client.cookies.get("cf_clearance") == "abc"

    store.clear()
    assert store.get() == []
    assert store.apply(httpx.AsyncClient()) is False


def test_clearance_store_expires():
    from app.sources.clearance import ClearanceStore

    store = ClearanceStore(ttl_seconds=0)
    store.put([{"name": "cf_clearance", "value": "abc"}])
    assert store.get() == []


def test_mintex_instance_owns_a_clearance_store():
    from app.config import get_settings
    from app.sources.mintex import MintexSource

    src = MintexSource(get_settings(), None)
    assert src.clearance.get() == []


def test_clearance_cooldown_stops_burning_proxy_traffic():
    """После неудач подряд браузер не должен запускаться снова сразу же."""
    from app.sources.clearance import ClearanceStore

    store = ClearanceStore(cooldown_seconds=300, failures_before_cooldown=2)
    assert not store.in_cooldown()
    store.mark_failure()
    assert not store.in_cooldown(), "одна неудача — ещё не повод сдаваться"
    store.mark_failure()
    assert store.in_cooldown()
    assert 0 < store.cooldown_left() <= 300

    # Успешный прогрев снимает паузу.
    store.put([{"name": "cf_clearance", "value": "x"}])
    assert not store.in_cooldown()
