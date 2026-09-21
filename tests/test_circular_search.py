import asyncio

import pytest

from app.aggregator import Aggregator
from app.config import Settings
from app.sources.base import Cross, SourceResult, SourceStatus


def result(source, *numbers, status=SourceStatus.OK, kind="oem"):
    return SourceResult(source, status, crosses=[
        Cross("TEST", number, kind, source) for number in numbers
    ])


def setup_search(answers, **settings):
    calls, writes = [], []

    class Source:
        def __init__(self, key):
            self.key = key

        async def lookup(self, number):
            calls.append((self.key, number))
            answer = answers.get((self.key, number))
            if callable(answer):
                return await answer()
            return answer or result(self.key, status=SourceStatus.NOT_FOUND)

    class Registry:
        def resolve(self, keys, group):
            return [Source(key) for key in (keys or ["a", "b"])]

    config = Settings(_env_file=None, circular_search_enabled=True, **settings)
    aggregator = Aggregator(config, Registry(), None)

    async def get(source, number):
        return None

    async def put(source, number, reply):
        writes.append((source, number, reply))

    aggregator._cache_get = get
    aggregator._cache_put = put
    return aggregator, calls, writes


@pytest.mark.asyncio
async def test_hidden_mode_is_disabled_by_default():
    assert Settings(_env_file=None).circular_search_enabled is False
    agg, calls, _ = setup_search({("b", "OE123"): result("b", "ALT123")})
    agg.settings.circular_search_enabled = False
    response = await agg.lookup("OE123")
    assert calls == [("a", "OE123"), ("b", "OE123")]
    assert "circular_search" not in response


@pytest.mark.asyncio
async def test_second_pass_merges_provenance_without_recursing_or_polluting_cache():
    direct = result("b", "ALT123")
    indirect = result("a", "ALT123", "NEW123")
    agg, calls, writes = setup_search({
        ("b", "OE123"): direct, ("a", "ALT123"): indirect,
    })
    response = await agg.lookup("OE123")
    assert calls == [("a", "OE123"), ("b", "OE123"), ("a", "ALT123")]
    assert response["unique_numbers"] == ["ALT123", "NEW123"]
    assert response["crosses"][0]["sources"] == ["a", "b"]
    assert len(response["sources"]) == 2
    assert response["sources"][0]["status"] == "ok"
    assert "ALT123" in response["sources"][0]["message"]
    assert indirect.message is None
    assert next(r for s, n, r in writes if (s, n) == ("a", "OE123")).crosses == []
    assert response["circular_search"]["attempts"][0]["number"] == "ALT123"


@pytest.mark.asyncio
async def test_candidates_are_deduplicated_and_standards_and_input_are_excluded():
    direct = result("b", "OE-123", "ALT-123", "ALT 123", "!!!", "ABC")
    direct.crosses.append(Cross("WVA", "99999", "standard", "b"))
    agg, calls, _ = setup_search({("b", "OE123"): direct})
    await agg.lookup("OE123")
    assert calls[2:] == [("a", "ALT123")]


@pytest.mark.asyncio
async def test_global_and_per_source_budgets_and_source_selection():
    agg, calls, _ = setup_search({("b", "OE123"): result("b", "ALT1", "ALT2", "ALT3")},
                                circular_search_max_queries=3,
                                circular_search_max_queries_per_source=2)
    await agg.lookup("OE123", ["a", "b", "c"], group="brake_pads")
    assert calls[3:] == [("a", "ALT1"), ("c", "ALT1"), ("a", "ALT2")]
    calls.clear()
    await agg.lookup("OE123", ["b"])
    assert calls == [("b", "OE123")]


@pytest.mark.asyncio
async def test_per_source_limit_and_success_on_second_candidate():
    answers = {("b", "OE123"): result("b", "ALT1", "ALT2", "ALT3"),
               ("a", "ALT2"): result("a", "NEW123")}
    agg, calls, _ = setup_search(answers)
    response = await agg.lookup("OE123", ["a", "b", "c"])
    assert calls[3:] == [("a", "ALT1"), ("c", "ALT1"),
                         ("a", "ALT2"), ("c", "ALT2")]
    assert "NEW123" in response["unique_numbers"]


def test_mode_can_be_enabled_through_environment(monkeypatch):
    monkeypatch.setenv("CP_CIRCULAR_SEARCH_ENABLED", "true")
    monkeypatch.setenv("CP_CIRCULAR_SEARCH_MAX_QUERIES", "3")
    config = Settings(_env_file=None)
    assert config.circular_search_enabled is True
    assert config.circular_search_max_queries == 3


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [SourceStatus.BLOCKED, SourceStatus.ERROR])
async def test_unavailable_sources_are_not_retried_and_second_pass_errors_stop(status):
    agg, calls, _ = setup_search({
        ("b", "OE123"): result("b", "ALT1", "ALT2"),
        ("c", "OE123"): result("c", status=status),
        ("a", "ALT1"): result("a", status=status),
    })
    response = await agg.lookup("OE123", ["a", "b", "c"])
    assert calls[3:] == [("a", "ALT1")]
    assert response["circular_search"]["attempts"][0]["status"] == status.value
    assert response["sources"][2]["status"] == status.value


@pytest.mark.asyncio
async def test_deadline_cancels_queries_and_preserves_direct_results():
    cancelled = asyncio.Event()

    async def slow():
        try:
            await asyncio.sleep(10)
        finally:
            cancelled.set()

    agg, calls, _ = setup_search({
        ("b", "OE123"): result("b", "ALT1", "ALT2"), ("a", "ALT1"): slow,
    }, circular_search_timeout=0.02)
    response = await asyncio.wait_for(agg.lookup("OE123"), timeout=1)
    assert cancelled.is_set()
    assert response["unique_numbers"] == ["ALT1", "ALT2"]
    assert calls[2:] == [("a", "ALT1")]
    assert response["circular_search"]["attempts"][0]["status"] == "error"


@pytest.mark.asyncio
async def test_indirect_query_uses_its_own_cache_key_and_respects_cache_bypass():
    agg, calls, _ = setup_search({("b", "OE123"): result("b", "ALT123")})
    reads = []

    async def cached(source, number):
        reads.append((source, number))
        if (source, number) == ("a", "ALT123"):
            return result("a", "CACHED123")

    agg._cache_get = cached
    response = await agg.lookup("OE123")
    assert ("a", "ALT123") in reads
    assert ("a", "ALT123") not in calls
    assert "CACHED123" in response["unique_numbers"]
    reads.clear()
    await agg.lookup("OE123", use_cache=False)
    assert reads == []
    assert ("a", "ALT123") in calls


@pytest.mark.asyncio
async def test_empty_results_and_zero_budget_skip_second_pass():
    agg, calls, _ = setup_search({})
    await agg.lookup("OE123")
    assert len(calls) == 2
    agg, calls, _ = setup_search({("b", "OE123"): result("b", "ALT123")},
                                circular_search_max_queries=0)
    await agg.lookup("OE123")
    assert len(calls) == 2
