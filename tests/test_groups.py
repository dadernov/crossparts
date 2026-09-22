import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from app import groups
from app.excel import read_input

GERAT = pathlib.Path("/root/Парсинг кроссов GERAT - пошагово.xlsx")


def test_resolves_client_group_names():
    assert groups.resolve("Тормозные колодки NEW") == groups.BRAKE_PADS
    assert groups.resolve("Тормозные диски") == groups.BRAKE_DISCS
    assert groups.resolve("Радиаторы основные (Ленточные)") == groups.RADIATORS
    assert groups.resolve("Амортизаторы") == groups.SHOCK_ABSORBERS
    assert groups.resolve("Тормозные шланги") == groups.BRAKE_HOSES


def test_unknown_group_is_not_guessed():
    assert groups.resolve("Свечи зажигания") is None
    assert groups.resolve("") is None


def test_group_title_falls_back_gracefully():
    assert groups.title(groups.BRAKE_PADS) == "Тормозные колодки"
    assert groups.title(None) == "—"


def test_reads_three_column_file_with_groups():
    if not GERAT.exists():
        return
    items = read_input(GERAT.read_bytes())
    assert len(items) == 14
    assert items[0] == {
        "our_sku": "BPF159CG",
        "part_name": "",
        "oe_number": "58101H5A25",
        "group_raw": "Тормозные колодки NEW",
        "group": "brake_pads",
    }
    assert {i["group"] for i in items} == {"brake_pads"}


def test_two_column_file_still_reads():
    old = pathlib.Path("/root/Тест - парсинг кроссов.xlsx")
    if not old.exists():
        return
    items = read_input(old.read_bytes())
    assert len(items) == 14
    assert items[0]["group"] is None


def test_registry_filters_sources_by_group():
    from app.config import get_settings
    from app.sources.registry import SourceRegistry

    reg = SourceRegistry(get_settings())
    pads = {s.key for s in reg.for_group(groups.BRAKE_PADS)}
    shocks = {s.key for s in reg.for_group(groups.SHOCK_ABSORBERS)}
    assert {"sbparts", "brembo", "trialli"} <= pads
    assert "trialli" in shocks
    assert "sbparts" not in shocks, "каталог колодок не должен опрашиваться по амортизаторам"


def test_coverage_reports_every_group():
    from app.config import get_settings
    from app.sources.registry import SourceRegistry

    reg = SourceRegistry(get_settings())
    cov = {c["group"]: c for c in reg.coverage()}
    assert set(cov) == set(groups.all_keys())
    assert "TRIALLI" in cov[groups.BRAKE_HOSES]["implemented"]
    assert "NIBK" in cov[groups.BRAKE_PADS]["blocked"]
    assert "METACO" in cov[groups.RADIATORS]["implemented"]
    assert cov[groups.RADIATORS]["total"] == 7
