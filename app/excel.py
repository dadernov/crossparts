"""Reading the client's input workbook and writing the result workbook.

The output mirrors the two layouts the client sketched in the test file:

* «Вариант 1» — one row per cross:  наш артикул | бренд | номер | источники
* «Вариант 2» — one row per SKU:    наш артикул | все кроссы через запятую
"""
from __future__ import annotations

import io
import re

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from . import groups as product_groups
from .normalize import KIND_AFTERMARKET, KIND_OEM, clean_number, number_key

SKU_HEADERS = ("наш артикул", "артикул", "our sku", "sku")
OE_HEADERS = ("номер ое", "номер оe", "оригинальный номер", "oe", "oem", "номер для парсинга")
GROUP_HEADERS = ("тормозная группа", "товарная группа", "группа", "product group")
NAME_HEADERS = ("наименование детали", "наименование", "название детали", "название", "part name")

_HEADER_HINT = re.compile(r"артикул|номер|sku|oe|oem", re.IGNORECASE)
_BRANNOR_VEHICLE_CODE = re.compile(r"^[A-Z]{2}\d{2}$")


def _norm_header(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def read_input(data: bytes) -> list[dict]:
    """Extract ``[{our_sku, oe_number, group, group_raw}, …]`` from a workbook.

    Поддерживает оба формата заказчика: старый на две колонки и новый на три,
    где между артикулом и номером стоит товарная группа. Заголовок ищется по
    названию; если его нет — берутся первые колонки по порядку.
    """
    wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    ws = wb[wb.sheetnames[0]]
    rows = [list(r) for r in ws.iter_rows(values_only=True)]
    wb.close()

    sku_col, oe_col, group_col, name_col, start = 0, 1, None, None, 0
    for idx, row in enumerate(rows[:30]):
        headers = [_norm_header(c) for c in row]
        found_sku = next((i for i, h in enumerate(headers)
                          if h and any(h.startswith(p) for p in SKU_HEADERS)), None)
        found_oe = next((i for i, h in enumerate(headers)
                         if h and any(p in h for p in OE_HEADERS)), None)
        found_group = next((i for i, h in enumerate(headers)
                            if h and any(p in h for p in GROUP_HEADERS)), None)
        found_name = next((i for i, h in enumerate(headers)
                           if h and any(p in h for p in NAME_HEADERS)), None)
        if found_oe is not None and found_sku != found_oe:
            sku_col, oe_col, start = found_sku, found_oe, idx + 1
            group_col = found_group if found_group not in (found_sku, found_oe) else None
            name_col = found_name if found_name not in (found_sku, found_oe) else None
            break

    items: list[dict] = []
    for row in rows[start:]:
        if not row:
            continue
        sku = clean_number(str(row[sku_col])) if sku_col is not None and len(row) > sku_col and row[sku_col] else ""
        oe = clean_number(str(row[oe_col])) if len(row) > oe_col and row[oe_col] else ""
        group_raw = ""
        part_name = ""
        if group_col is not None and len(row) > group_col and row[group_col]:
            group_raw = str(row[group_col]).strip()
        if name_col is not None and len(row) > name_col and row[name_col]:
            part_name = str(row[name_col]).strip()
        if not oe:
            # Stop at the first gap after data started — the client's sheet keeps
            # unrelated blocks (site list, output samples) below the input table.
            if items and ws.title != "Загрузить этот лист":
                break
            continue
        if _HEADER_HINT.search(oe) and not any(ch.isdigit() for ch in oe):
            continue
        items.append({
            "our_sku": sku,
            "part_name": part_name,
            "oe_number": oe,
            "group_raw": group_raw,
            "group": product_groups.resolve(group_raw),
        })
    return items


HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(color="FFFFFF", bold=True)


def _style_header(ws, width_map: dict[int, int]) -> None:
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(vertical="center")
    for col, width in width_map.items():
        ws.column_dimensions[get_column_letter(col)].width = width
    ws.freeze_panes = "A2"


def build_workbook(items: list[dict], *, include_our_sku: bool = True) -> bytes:
    """Build the two layouts from the client's reference workbook.

    A single-number lookup has no customer SKU, so its download omits that
    otherwise empty column. Batch exports keep the original layouts.
    """
    wb = Workbook()

    ws1 = wb.active
    ws1.title = "Вариант 1"
    headers1 = ["Номер ОЕ (запрос)", "Бренд аналога", "Номер аналога", "Раздел", "Источники"]
    if include_our_sku:
        headers1.insert(0, "Наш номер")
    ws1.append(headers1)
    _style_header(
        ws1,
        {1: 18, 2: 20, 3: 24, 4: 26, 5: 18, 6: 24}
        if include_our_sku else {1: 20, 2: 24, 3: 26, 4: 18, 5: 24},
    )
    kind_ru = {KIND_OEM: "OEM", KIND_AFTERMARKET: "Афтермаркет", "standard": "Стандарт"}
    for item in items:
        for cross in _export_crosses(item.get("crosses", [])):
            row = [
                item.get("oe_number", ""),
                cross["brand"],
                number_key(cross["number"]),
                kind_ru.get(cross.get("kind"), cross.get("kind", "")),
                ", ".join(cross.get("sources", [])),
            ]
            if include_our_sku:
                row.insert(0, item.get("our_sku", ""))
            ws1.append(row)

    ws2 = wb.create_sheet("Вариант 2")
    headers2 = ["Товарная группа", "Номер ОЕ (запрос)", "Кол-во", "ОЕМ/Афтермаркет", "Все кроссы"]
    if include_our_sku:
        headers2.insert(0, "Наш артикул")
    ws2.append(headers2)
    _style_header(
        ws2,
        {1: 18, 2: 24, 3: 20, 4: 10, 5: 20, 6: 100}
        if include_our_sku else {1: 24, 2: 20, 3: 10, 4: 20, 5: 100},
    )
    for item in items:
        for kind, label in ((KIND_OEM, "ОЕМ"), (KIND_AFTERMARKET, "АФТЕРМАРКЕТ"), ("standard", "СТАНДАРТ")):
            numbers = _unique([c for c in _export_crosses(item.get("crosses", []))
                               if c.get("kind") == kind])
            if not numbers:
                continue
            row = [
                _group_title(item), item.get("oe_number", ""), len(numbers), label,
                ", ".join(numbers),
            ]
            if include_our_sku:
                row.insert(0, item.get("our_sku", ""))
            ws2.append(row)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_fitment_workbook(result: dict) -> bytes:
    """Export one exact product card and all of its vehicle applications."""
    wb = Workbook()
    product = wb.active
    product.title = "Деталь"
    product.append(["Поле", "Значение"])
    _style_header(product, {1: 28, 2: 80})
    fields = (
        ("Бренд", result.get("brand")), ("Артикул", result.get("number")),
        ("Название", result.get("title")),
        ("Сторона установки", result.get("installation_position")),
        ("Тип амортизатора", result.get("damper_type")),
        ("Исполнение / крепление", result.get("damper_kind")),
        ("Источник", result.get("source")), ("Карточка источника", result.get("source_url")),
        ("Проверено", result.get("checked_at")),
    )
    for label, value in fields:
        product.append([label, value or ""])

    fitment = wb.create_sheet("Применяемость")
    fitment.append([
        "Бренд детали", "Артикул", "Марка автомобиля", "Модель", "Поколение",
        "Модификация", "Двигатель", "Мощность, кВт", "Мощность, лс", "Объём, см³",
        "Период выпуска", "Год с", "Год по", "Месяц с", "Месяц по",
        "Выпускается", "Кузов", "Трансмиссия", "Ось", "Ограничения",
        "Статус проверки", "Источник", "Карточка источника",
    ])
    _style_header(fitment, {
        1: 16, 2: 18, 3: 20, 4: 28, 5: 18, 6: 36, 7: 18, 8: 16,
        9: 16, 10: 16, 11: 20, 12: 12, 13: 12, 14: 12, 15: 12, 16: 14,
        17: 18, 18: 18, 19: 18, 20: 48, 21: 18, 22: 14, 23: 50,
    })
    for row in result.get("applications") or []:
        fitment.append([
            result.get("brand", ""), result.get("number", ""), row.get("make", ""),
            row.get("model", ""), row.get("generation", ""), row.get("modification", ""),
            row.get("engine_code", ""), row.get("power_kw", ""), row.get("power_hp", ""),
            row.get("engine_cc", ""), row.get("raw_period", ""), row.get("year_from"),
            row.get("year_to"), row.get("month_from"), row.get("month_to"),
            "Да" if row.get("end_is_open") else "Нет", row.get("body", ""),
            row.get("transmission", ""), row.get("axle", ""),
            " | ".join(row.get("restrictions") or []), row.get("verification_status", ""),
            result.get("source", ""), result.get("source_url", ""),
        ])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def build_fitment_job_workbook(results: list[dict]) -> bytes:
    """Export a batch without losing source, part identity or restrictions."""
    wb = Workbook()
    summary = wb.active
    summary.title = "Детали"
    summary.append(["Бренд", "Артикул", "Группа", "Статус", "Название",
                    "Строк применяемости", "Источник", "Карточка", "Сообщение"])
    _style_header(summary, {1: 16, 2: 20, 3: 20, 4: 14, 5: 42, 6: 20, 7: 14, 8: 50, 9: 40})
    applications = wb.create_sheet("Применяемость")
    applications.append([
        "Бренд детали", "Артикул", "Марка автомобиля", "Модель", "Поколение",
        "Модификация", "Двигатель", "Мощность, кВт", "Мощность, лс",
        "Объём, см³", "Период", "Год с", "Год по", "Месяц с", "Месяц по",
        "Открытый период", "Кузов", "Трансмиссия", "Ось", "Ограничения",
        "Статус проверки", "Источник", "Карточка",
    ])
    _style_header(applications, {i: 18 for i in range(1, 24)})
    applications.column_dimensions["D"].width = 30
    applications.column_dimensions["F"].width = 44
    applications.column_dimensions["T"].width = 50
    applications.column_dimensions["W"].width = 50
    for result in results:
        summary.append([
            result.get("brand", ""), result.get("number", ""), result.get("group", ""),
            result.get("status", ""), result.get("title", ""),
            len(result.get("applications") or []), result.get("source", ""),
            result.get("source_url", ""), result.get("message", ""),
        ])
        for row in result.get("applications") or []:
            applications.append([
                result.get("brand", ""), result.get("number", ""), row.get("make", ""),
                row.get("model", ""), row.get("generation", ""), row.get("modification", ""),
                row.get("engine_code", ""), row.get("power_kw", ""), row.get("power_hp", ""),
                row.get("engine_cc", ""), row.get("raw_period", ""), row.get("year_from"),
                row.get("year_to"), row.get("month_from"), row.get("month_to"),
                "Да" if row.get("end_is_open") else "Нет", row.get("body", ""),
                row.get("transmission", ""), row.get("axle", ""),
                " | ".join(row.get("restrictions") or []), row.get("verification_status", ""),
                result.get("source", ""), result.get("source_url", ""),
            ])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _group_title(item: dict) -> str:
    """Показываем распознанную группу, а нераспознанную — как прислали."""
    key = item.get("group")
    if key:
        return product_groups.title(key)
    return item.get("group_raw") or "—"


def _unique(crosses: list[dict]) -> list[str]:
    from .normalize import number_key

    seen, out = set(), []
    for c in crosses:
        k = number_key(c["number"])
        if k not in seen:
            seen.add(k)
            out.append(number_key(c["number"]))
    return out


def _export_crosses(crosses: list[dict]) -> list[dict]:
    """Hide the old BRANNOR vehicle-page false positives from historical jobs.

    The source now blocks them before saving. This guard also keeps old jobs
    (created before the fix) clean when the client downloads them again.
    """
    return [
        c for c in crosses
        if not (
            c.get("brand") == "BRANNOR"
            and "brannor" in c.get("sources", [])
            and _BRANNOR_VEHICLE_CODE.fullmatch(number_key(c.get("number", "")))
        )
    ]


def build_template() -> bytes:
    """A ready-to-fill client workbook, not merely a format description."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Загрузить этот лист"
    ws.append(["Наш артикул", "Наименование детали", "Товарная группа", "Номер ОЕ"])
    _style_header(ws, {1: 20, 2: 38, 3: 28, 4: 24})
    instructions = wb.create_sheet("Инструкция")
    instructions.append(["Заполните первый лист со второй строки. Обязателен только «Номер ОЕ»."])
    instructions.append(["Пример (не участвует в обработке):"])
    instructions.append(["Наш артикул", "Наименование детали", "Товарная группа", "Номер ОЕ"])
    instructions.append(["BPF159CG", "Колодки тормозные передние", "Тормозные колодки", "58101H5A25"])
    instructions.column_dimensions["A"].width = 85
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
