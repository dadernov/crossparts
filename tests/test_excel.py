import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import io
from openpyxl import Workbook, load_workbook

from app.excel import build_workbook, read_input

SAMPLE = pathlib.Path("/root/Тест - парсинг кроссов.xlsx")


def _sheet(rows) -> bytes:
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_read_input_finds_header_row():
    data = _sheet([
        ["Наш Артикул", "Номер ОЕ для парсинга кроссов"],
        ["BPF159CG", "58101H5A25"],
        ["BPF394PG", "2L2Z2001BA"],
    ])
    assert [(i["our_sku"], i["oe_number"], i["group"]) for i in read_input(data)] == [
        ("BPF159CG", "58101H5A25", None),
        ("BPF394PG", "2L2Z2001BA", None),
    ]


def test_read_input_stops_at_blank_row_before_other_blocks():
    data = _sheet([
        ["Наш Артикул", "Номер ОЕ"],
        ["A1", "111222"],
        [None, None],
        ["Сайты для парсинга", None],
        ["Brembo", "https://example.com"],
    ])
    items = read_input(data)
    assert [(i["our_sku"], i["oe_number"]) for i in items] == [("A1", "111222")]


def test_read_input_on_the_real_client_file():
    if not SAMPLE.exists():
        return
    items = read_input(SAMPLE.read_bytes())
    assert len(items) == 14
    assert (items[0]["our_sku"], items[0]["oe_number"]) == ("BPF159CG", "58101H5A25")


def test_build_workbook_layout():
    blob = build_workbook([{
        "our_sku": "BPF159CG",
        "oe_number": "58101H5A25",
        "group": "brake_pads",
        "status": "ok",
        "crosses": [
            {"brand": "HYUNDAI", "number": "58101-H5A25", "kind": "oem", "sources": ["sbparts"]},
            {"brand": "NIBK", "number": "PN0537", "kind": "aftermarket", "sources": ["sbparts"]},
        ],
        "source_reports": [{"source": "sbparts", "status": "ok", "crosses": 2}],
    }])
    wb = load_workbook(io.BytesIO(blob))
    assert wb.sheetnames[:3] == ["Вариант 1", "Вариант 2", "Отчёт"]
    v1 = list(wb["Вариант 1"].iter_rows(values_only=True))
    assert v1[0][:5] == ("Наш артикул", "Товарная группа", "Номер ОЕ (запрос)",
                         "Бренд", "Номер кросса")
    assert v1[1][:5] == ("BPF159CG", "Тормозные колодки", "58101H5A25",
                         "HYUNDAI", "58101-H5A25")
    v2 = list(wb["Вариант 2"].iter_rows(values_only=True))
    assert v2[1][1] == "Тормозные колодки"
    assert v2[1][3] == 2
    assert v2[1][4] == "58101-H5A25, PN0537"


def test_unrecognised_group_is_shown_as_sent():
    """Незнакомую группу не выдумываем — показываем как прислали."""
    blob = build_workbook([{
        "our_sku": "X1", "oe_number": "111222",
        "group": None, "group_raw": "Свечи зажигания", "status": "ok",
        "crosses": [{"brand": "NGK", "number": "BKR6E", "kind": "aftermarket",
                     "sources": ["x"]}],
        "source_reports": [],
    }])
    wb = load_workbook(io.BytesIO(blob))
    assert list(wb["Вариант 2"].iter_rows(values_only=True))[1][1] == "Свечи зажигания"
