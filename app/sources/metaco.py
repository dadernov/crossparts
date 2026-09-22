"""METACO cross-reference index built from the manufacturer's public CSV files.

The official download page publishes separate OEM and replacement lists.  The
adapter reads local, reviewed snapshots: search requests never download a
multi-megabyte catalogue and never depend on the website during a customer
request.  Updating those snapshots is a separate controlled operation.

This candidate is disabled by default and requires an exact source/group/tenant
pilot rule. Production activation still requires the W1 release gates.
"""
from __future__ import annotations

import csv
import hashlib
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from ..groups import BRAKE_DISCS, BRAKE_PADS
from ..normalize import (
    KIND_AFTERMARKET,
    KIND_OEM,
    clean_brand,
    clean_number,
    number_key,
)
from .base import BaseSource, Cross, SourceResult, SourceStatus


DOWNLOADS_URL = "https://metaco.parts/content/downloads"


@dataclass(frozen=True)
class MetacoRow:
    own_brand: str
    own_article: str
    reference_brand: str
    reference_number: str
    description: str
    group: str
    kind: str

    @property
    def product_key(self) -> tuple[str, str]:
        return self.own_brand.casefold(), number_key(self.own_article)


def _clean_cell(value: str) -> str:
    # The OEM CSV prefixes numeric-looking articles with an apostrophe so
    # spreadsheet software will preserve them as text.
    return value.strip().lstrip("'").strip()


def classify_group(description: str) -> str | None:
    text = " ".join(description.casefold().replace("ё", "е").split())
    if text.startswith("колодки тормозные "):
        return BRAKE_PADS
    if text == "диск тормозной" or text.startswith("диск тормозной "):
        return BRAKE_DISCS
    return None


def _read_csv(path: Path, *, kind: str) -> list[MetacoRow]:
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1251")

    rows: list[MetacoRow] = []
    for raw_row in csv.reader(text.splitlines(), delimiter=";"):
        if len(raw_row) < 5:
            continue
        own_brand, own_article, ref_brand, ref_number, description = (
            _clean_cell(value) for value in raw_row[:5]
        )
        if own_brand.casefold() == "бренд" or not all(
            (own_brand, own_article, ref_brand, ref_number, description)
        ):
            continue
        group = classify_group(description)
        if group is None:
            continue
        rows.append(MetacoRow(
            own_brand=own_brand,
            own_article=own_article,
            reference_brand=ref_brand,
            reference_number=ref_number,
            description=description,
            group=group,
            kind=kind,
        ))
    return rows


class MetacoIndex:
    def __init__(self, rows: list[MetacoRow]):
        self.rows = rows
        self._by_product: dict[tuple[str, str], list[MetacoRow]] = defaultdict(list)
        self._by_reference: dict[str, set[tuple[str, str]]] = defaultdict(set)
        for row in rows:
            product = row.product_key
            self._by_product[product].append(row)
            self._by_reference[number_key(row.reference_number)].add(product)
            self._by_reference[number_key(row.own_article)].add(product)

    @classmethod
    def from_files(cls, oem_path: Path, replacements_path: Path) -> "MetacoIndex":
        return cls(
            _read_csv(oem_path, kind=KIND_OEM)
            + _read_csv(replacements_path, kind=KIND_AFTERMARKET)
        )

    def lookup(self, query: str, *, groups: set[str]) -> tuple[list[str], list[Cross]]:
        product_keys = self._by_reference.get(number_key(query), set())
        products: list[str] = []
        crosses: list[Cross] = []
        seen: set[tuple[str, str]] = set()

        for product_key in sorted(product_keys):
            rows = [row for row in self._by_product[product_key] if row.group in groups]
            if not rows:
                continue
            first = rows[0]
            if first.own_article not in products:
                products.append(first.own_article)

            candidates = [
                (first.own_brand, first.own_article, KIND_AFTERMARKET),
                *((row.reference_brand, row.reference_number, row.kind) for row in rows),
            ]
            for brand, number, kind in candidates:
                brand = clean_brand(brand)
                number = clean_number(number)
                # Preserve the same brand+number when two METACO products
                # independently claim it. Aggregator.merge will deduplicate the
                # visible pair while retaining both source_products.
                key = brand, number_key(number), first.own_article
                if key in seen:
                    continue
                seen.add(key)
                crosses.append(Cross(
                    brand=brand,
                    number=number,
                    kind=kind,
                    source="metaco",
                    source_product=first.own_article,
                    url=DOWNLOADS_URL,
                ))
        return products, crosses


class SQLiteMetacoIndex:
    """Read-only runtime view of an offline-built METACO index."""

    def __init__(self, path: Path):
        self.path = path.resolve()

    def lookup(self, query: str, *, groups: set[str]) -> tuple[list[str], list[Cross]]:
        if not groups:
            return [], []
        placeholders = ",".join("?" for _ in groups)
        uri = f"file:{self.path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            product_rows = connection.execute(
                f"""
                SELECT DISTINCT product_key
                FROM catalogue
                WHERE (reference_key = ? OR own_article_key = ?)
                  AND group_key IN ({placeholders})
                ORDER BY product_key
                """,
                (number_key(query), number_key(query), *sorted(groups)),
            ).fetchall()
            if not product_rows:
                return [], []
            product_keys = [row[0] for row in product_rows]
            product_placeholders = ",".join("?" for _ in product_keys)
            rows = connection.execute(
                f"""
                SELECT own_brand, own_article, reference_brand, reference_number,
                       description, group_key, kind
                FROM catalogue
                WHERE product_key IN ({product_placeholders})
                  AND group_key IN ({placeholders})
                ORDER BY product_key, reference_brand, reference_key
                """,
                (*product_keys, *sorted(groups)),
            ).fetchall()
        parsed = [MetacoRow(*row) for row in rows]
        return MetacoIndex(parsed).lookup(query, groups=groups)


def build_sqlite_index(oem_path: Path, replacements_path: Path, output_path: Path) -> dict:
    """Build an immutable runtime index and atomically replace ``output_path``."""
    sources = (
        (oem_path.resolve(), KIND_OEM),
        (replacements_path.resolve(), KIND_AFTERMARKET),
    )
    rows = [row for path, kind in sources for row in _read_csv(path, kind=kind)]
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.executescript("""
                PRAGMA journal_mode=OFF;
                PRAGMA synchronous=FULL;
                CREATE TABLE catalogue (
                    product_key TEXT NOT NULL,
                    own_brand TEXT NOT NULL,
                    own_article TEXT NOT NULL,
                    own_article_key TEXT NOT NULL,
                    reference_brand TEXT NOT NULL,
                    reference_number TEXT NOT NULL,
                    reference_key TEXT NOT NULL,
                    description TEXT NOT NULL,
                    group_key TEXT NOT NULL,
                    kind TEXT NOT NULL
                );
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            connection.executemany(
                """
                INSERT INTO catalogue VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    (
                        "|".join(row.product_key),
                        row.own_brand,
                        row.own_article,
                        number_key(row.own_article),
                        row.reference_brand,
                        row.reference_number,
                        number_key(row.reference_number),
                        row.description,
                        row.group,
                        row.kind,
                    )
                    for row in rows
                ),
            )
            hashes = {
                f"input_{index}_sha256": hashlib.sha256(path.read_bytes()).hexdigest()
                for index, (path, _) in enumerate(sources, start=1)
            }
            metadata = {
                "schema_version": "1",
                "rows": str(len(rows)),
                **hashes,
            }
            connection.executemany(
                "INSERT INTO metadata(key, value) VALUES (?, ?)", metadata.items()
            )
            connection.executescript("""
                CREATE INDEX idx_catalogue_reference
                    ON catalogue(reference_key, group_key, product_key);
                CREATE INDEX idx_catalogue_own_article
                    ON catalogue(own_article_key, group_key, product_key);
                CREATE INDEX idx_catalogue_product
                    ON catalogue(product_key, group_key);
                ANALYZE;
            """)
        os.replace(temporary, output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {
        "path": str(output_path),
        "rows": len(rows),
        "size_bytes": output_path.stat().st_size,
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        **hashes,
    }


class MetacoSource(BaseSource):
    key = "metaco"
    title = "METACO"
    homepage = "https://metaco.parts/category"
    verified = False
    groups = (BRAKE_PADS, BRAKE_DISCS)
    note = "Pilot W1: локальный индекс из официальных OEM и cross-list CSV; выключен."

    def __init__(self, settings, http_factory=None, pool=None, *, index=None):
        super().__init__(settings, http_factory, pool)
        self._index = index

    def _load_index(self) -> MetacoIndex:
        if self._index is not None:
            return self._index
        configured = getattr(self.settings, "metaco_index_path", "")
        path = Path(configured) if configured else None
        if path is None or not path.is_file():
            raise FileNotFoundError("локальный индекс METACO не настроен")
        self._index = SQLiteMetacoIndex(path)
        return self._index

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        try:
            import asyncio

            index = self._load_index()
            products, crosses = await asyncio.to_thread(
                index.lookup, oe, groups=set(self.groups)
            )
        except (OSError, UnicodeError, csv.Error, sqlite3.Error) as exc:
            return SourceResult(
                self.key,
                SourceStatus.ERROR,
                message=str(exc)[:300],
                elapsed_ms=self.elapsed(started),
                url=DOWNLOADS_URL,
            )
        return SourceResult(
            self.key,
            SourceStatus.OK if products else SourceStatus.NOT_FOUND,
            crosses=crosses,
            products=products,
            elapsed_ms=self.elapsed(started),
            url=DOWNLOADS_URL,
        )
