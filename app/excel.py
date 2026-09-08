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
from .normalize import KIND_AFTERMARKET, KIND_OEM, clean_number

SKU_HEADERS = ("наш артикул", "артикул", "our sku", "sku")
OE_HEADERS = ("номер ое", "номер оe", "оригинальный номер", "oe", "oem", "номер для парсинга")
GROUP_HEADERS = ("тормозная группа", "товарная группа", "группа", "product group")

_HEADER_HINT = re.compile(r"артикул|номер|sku|oe|oem", re.IGNORECASE)


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

    sku_col, oe_col, group_col, start = 0, 1, None, 0
    for idx, row in enumerate(rows[:30]):
        headers = [_norm_header(c) for c in row]
        found_sku = next((i for i, h in enumerate(headers)
                          if h and any(h.startswith(p) for p in SKU_HEADERS)), None)
        found_oe = next((i for i, h in enumerate(headers)
                         if h and any(p in h for p in OE_HEADERS)), None)
        found_group = next((i for i, h in enumerate(headers)
                            if h and any(p in h for p in GROUP_HEADERS)), None)
        if found_sku is not None and found_oe is not None and found_sku != found_oe:
            sku_col, oe_col, start = found_sku, found_oe, idx + 1
            group_col = found_group if found_group not in (found_sku, found_oe) else None
            break

    items: list[dict] = []
    for row in rows[start:]:
        if not row:
            continue
        sku = clean_number(str(row[sku_col])) if len(row) > sku_col and row[sku_col] else ""
        oe = clean_number(str(row[oe_col])) if len(row) > oe_col and row[oe_col] else ""
        group_raw = ""
        if group_col is not None and len(row) > group_col and row[group_col]:
            group_raw = str(row[group_col]).strip()
        if not oe:
            # Stop at the first gap after data started — the client's sheet keeps
            # unrelated blocks (site list, output samples) below the input table.
            if items:
                break
            continue
        if _HEADER_HINT.search(oe) and not any(ch.isdigit() for ch in oe):
            continue
        items.append({
            "our_sku": sku,
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


def build_workbook(items: list[dict], meta: dict | None = None) -> bytes:
    """``items`` are dicts with our_sku / oe_number / crosses / source_reports."""
    wb = Workbook()

    ws1 = wb.active
    ws1.title = "Вариант 1"
    ws1.append(["Наш артикул", "Товарная группа", "Номер ОЕ (запрос)",
                "Бренд", "Номер кросса", "Тип", "Источники"])
    _style_header(ws1, {1: 18, 2: 24, 3: 20, 4: 24, 5: 26, 6: 14, 7: 22})
    kind_ru = {KIND_OEM: "OEM", KIND_AFTERMARKET: "Афтермаркет", "standard": "Стандарт"}
    for item in items:
        for cross in item.get("crosses", []):
            ws1.append([
                item.get("our_sku", ""),
                _group_title(item),
                item.get("oe_number", ""),
                cross["brand"],
                cross["number"],
                kind_ru.get(cross.get("kind"), cross.get("kind", "")),
                ", ".join(cross.get("sources", [])),
            ])

    ws2 = wb.create_sheet("Вариант 2")
    ws2.append(["Наш артикул", "Товарная группа", "Номер ОЕ (запрос)", "Кол-во", "Все кроссы"])
    _style_header(ws2, {1: 18, 2: 24, 3: 20, 4: 10, 5: 160})
    for item in items:
        numbers = _unique(item.get("crosses", []))
        ws2.append([
            item.get("our_sku", ""),
            _group_title(item),
            item.get("oe_number", ""),
            len(numbers),
            ", ".join(numbers),
        ])

    ws3 = wb.create_sheet("Отчёт")
    ws3.append(["Наш артикул", "Товарная группа", "Номер ОЕ", "Статус",
                "Всего кроссов", "По источникам", "Комментарии"])
    _style_header(ws3, {1: 18, 2: 24, 3: 20, 4: 14, 5: 16, 6: 40, 7: 70})
    for item in items:
        reports = item.get("source_reports", [])
        per_source = ", ".join(
            f"{r['source']}: {r.get('crosses', 0)}" for r in reports
        )
        notes = "; ".join(
            f"{r['source']} — {r['status']}" + (f" ({r['message']})" if r.get("message") else "")
            for r in reports if r["status"] != "ok"
        )
        ws3.append([
            item.get("our_sku", ""),
            _group_title(item),
            item.get("oe_number", ""),
            item.get("status", ""),
            len(item.get("crosses", [])),
            per_source,
            notes,
        ])

    if meta:
        ws4 = wb.create_sheet("Параметры")
        ws4.append(["Параметр", "Значение"])
        _style_header(ws4, {1: 28, 2: 60})
        for k, v in meta.items():
            ws4.append([str(k), str(v)])

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


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
            out.append(c["number"])
    return out
