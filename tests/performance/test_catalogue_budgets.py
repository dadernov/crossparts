from __future__ import annotations

import statistics
import time
from pathlib import Path

import pytest

from app.config import Settings
from app.sources.base import SourceStatus
from app.sources.metaco import MetacoSource, SQLiteMetacoIndex, build_sqlite_index


FIXTURES = Path(__file__).parents[1] / "fixtures" / "catalogues" / "metaco"


def test_metaco_fixture_lookup_p95_stays_inside_pure_parse_budget(tmp_path):
    fixture = FIXTURES / "brake_discs"
    database = tmp_path / "metaco.sqlite3"
    build_sqlite_index(fixture / "oem.csv", fixture / "replacements.csv", database)
    index = SQLiteMetacoIndex(database)

    samples = []
    for _ in range(120):
        started = time.perf_counter()
        products, crosses = index.lookup(
            "1K0615301AA", groups={"brake_pads", "brake_discs"}
        )
        samples.append((time.perf_counter() - started) * 1000)
    p95 = sorted(samples)[int(len(samples) * 0.95) - 1]

    assert products == ["3050-016"]
    assert len(crosses) == 17
    assert statistics.median(samples) < 25
    assert p95 < 100


@pytest.mark.asyncio
async def test_metaco_runtime_lookup_runs_off_the_event_loop(tmp_path):
    fixture = FIXTURES / "brake_discs"
    database = tmp_path / "metaco.sqlite3"
    build_sqlite_index(fixture / "oem.csv", fixture / "replacements.csv", database)
    source = MetacoSource(Settings(_env_file=None, metaco_index_path=str(database)))

    result = await source.lookup("1K0615301AA")
    assert result.status is SourceStatus.OK
    assert result.products == ["3050-016"]

