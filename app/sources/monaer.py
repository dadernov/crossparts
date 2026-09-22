"""Monaer offline OE index built from public product cards."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from selectolax.parser import HTMLParser

from ..groups import BRAKE_DISCS, BRAKE_PADS
from ..normalize import KIND_AFTERMARKET, clean_number, number_key
from .base import BaseSource, Cross, SourceResult, SourceStatus

BASE = "https://monaer-russia.ru"
SITEMAP = BASE + "/sitemap-store.xml"

@dataclass(frozen=True)
class MonaerProduct:
    article: str
    url: str
    group: str
    oem_numbers: tuple[str, ...]


def group_from_text(text: str) -> str | None:
    value = text.casefold()
    if "тормозн" not in value:
        return None
    if "колодк" in value:
        return BRAKE_PADS
    if "диск" in value:
        return BRAKE_DISCS
    return None


def parse_product_page(html: str, url: str) -> MonaerProduct | None:
    marker = html.find("var product = ")
    if marker < 0:
        return None
    start = html.find("{", marker)
    depth = 0
    end = -1
    quoted = False
    escaped = False
    for index, char in enumerate(html[start:], start):
        if quoted:
            escaped = char == "\\" and not escaped
            if char == '"' and not escaped:
                quoted = False
            elif char != "\\":
                escaped = False
            continue
        if char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    if end < 0:
        return None
    try:
        product = json.loads(html[start:end])
    except json.JSONDecodeError:
        return None
    if not isinstance(product, dict):
        return None
    article_match = re.search(r"\b[MМ]\d{3,}[A-Z-]*\b", str(product.get("title", "")).upper())
    article = clean_number(article_match.group(0).replace("М", "M")) if article_match else ""
    document = HTMLParser(html)
    group = group_from_text(str(product.get("title", "")) + " " + str(product.get("text", "")))
    oem: list[str] = []
    for node in document.css(".t-store__tabs__item"):
        heading = node.css_first(".t-store__tabs__item-title")
        content = node.css_first(".t-store__tabs__content")
        if heading is None or content is None or "oem" not in heading.text(strip=True).casefold():
            continue
        for raw in re.split(r"[;,\\s]+", content.text(separator=" ", strip=True)):
            number = clean_number(raw)
            if len(number_key(number)) >= 7 and number not in oem:
                oem.append(number)
    if not article or group is None or not oem:
        return None
    return MonaerProduct(article, url, group, tuple(oem))


class SQLiteMonaerIndex:
    def __init__(self, path: Path):
        self.path = path.resolve()

    def lookup(self, query: str, *, groups: set[str], max_products: int) -> tuple[list[str], list[Cross]]:
        if not groups:
            return [], []
        placeholders = ",".join("?" for _ in groups)
        uri = f"file:{self.path.as_posix()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            rows = connection.execute(
                f"""SELECT article, url FROM matches WHERE oe_key = ?
                AND group_key IN ({placeholders}) ORDER BY article LIMIT ?""",
                (number_key(query), *sorted(groups), max_products),
            ).fetchall()
        products = [article for article, _ in rows]
        crosses = [Cross("MONAER", article, KIND_AFTERMARKET, "monaer", article, url)
                   for article, url in rows]
        return products, crosses


def build_sqlite_index(products: list[MonaerProduct], output_path: Path, *, source_hash: str) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary.unlink(missing_ok=True)
    try:
        with sqlite3.connect(temporary) as connection:
            connection.executescript("""
                CREATE TABLE matches (article TEXT NOT NULL, url TEXT NOT NULL,
                  group_key TEXT NOT NULL, oe_key TEXT NOT NULL);
                CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE INDEX idx_monaer_matches ON matches(oe_key, group_key, article);
            """)
            rows = [(product.article, product.url, product.group, number_key(oe))
                    for product in products for oe in product.oem_numbers]
            connection.executemany("INSERT INTO matches VALUES (?, ?, ?, ?)", rows)
            connection.executemany("INSERT INTO metadata VALUES (?, ?)", {
                "schema_version": "1", "products": str(len(products)), "matches": str(len(rows)),
                "sitemap_sha256": source_hash, "source_url": SITEMAP,
            }.items())
        temporary.replace(output_path)
    finally:
        temporary.unlink(missing_ok=True)
    return {"products": len(products), "matches": len(rows), "path": str(output_path)}


class MonaerSource(BaseSource):
    key = "monaer"
    title = "MONAER"
    homepage = BASE + "/catalog"
    verified = True
    groups = (BRAKE_PADS, BRAKE_DISCS)
    note = "Колодки и диски. Локальный индекс публичных карточек Monaer и их OE-номеров."

    def __init__(self, settings, http_factory=None, pool=None, *, index=None):
        super().__init__(settings, http_factory, pool)
        self._index = index

    def _load_index(self):
        if self._index is not None:
            return self._index
        path = Path(self.settings.monaer_index_path) if self.settings.monaer_index_path else None
        if path is None or not path.is_file():
            raise FileNotFoundError("локальный индекс MONAER не настроен")
        self._index = SQLiteMonaerIndex(path)
        return self._index

    async def lookup(self, oe: str) -> SourceResult:
        started = self.timer()
        try:
            products, crosses = await asyncio.to_thread(
                self._load_index().lookup, oe, groups=set(self.groups),
                max_products=self.settings.max_products_per_oe,
            )
        except (OSError, sqlite3.Error) as exc:
            return SourceResult(self.key, SourceStatus.ERROR, message=str(exc)[:300],
                                elapsed_ms=self.elapsed(started), url=SITEMAP)
        return SourceResult(self.key, SourceStatus.OK if products else SourceStatus.NOT_FOUND,
                            products=products, crosses=crosses,
                            elapsed_ms=self.elapsed(started), url=SITEMAP)
