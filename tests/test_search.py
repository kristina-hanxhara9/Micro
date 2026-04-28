import pytest

from src.models import BingResult
from src.plugins.search import SearchDispatcher


class FakeEngine:
    def __init__(self, name: str, results: list[BingResult] | None = None, raise_on_call: bool = False):
        self.name = name
        self._results = results or []
        self._raise = raise_on_call
        self.calls = 0

    async def search(self, query: str, count: int = 5) -> list[BingResult]:
        self.calls += 1
        if self._raise:
            raise RuntimeError("boom")
        return self._results


@pytest.mark.asyncio
async def test_dispatcher_uses_primary_when_it_returns_results():
    primary = FakeEngine("p", [BingResult(title="t", url="https://p.com", snippet="s")])
    secondary = FakeEngine("s", [BingResult(title="t", url="https://s.com", snippet="s")])
    dispatcher = SearchDispatcher(primary=primary, secondary=secondary)
    results, engine = await dispatcher.search("foo")
    assert engine == "p"
    assert len(results) == 1
    assert secondary.calls == 0


@pytest.mark.asyncio
async def test_dispatcher_falls_back_when_primary_empty():
    primary = FakeEngine("p", [])
    secondary = FakeEngine("s", [BingResult(title="t", url="https://s.com", snippet="s")])
    dispatcher = SearchDispatcher(primary=primary, secondary=secondary)
    results, engine = await dispatcher.search("foo")
    assert engine == "s"
    assert len(results) == 1


@pytest.mark.asyncio
async def test_dispatcher_falls_back_when_primary_raises():
    primary = FakeEngine("p", raise_on_call=True)
    secondary = FakeEngine("s", [BingResult(title="t", url="https://s.com", snippet="s")])
    dispatcher = SearchDispatcher(primary=primary, secondary=secondary)
    results, engine = await dispatcher.search("foo")
    assert engine == "s"
    assert len(results) == 1


@pytest.mark.asyncio
async def test_dispatcher_returns_empty_when_all_fail():
    primary = FakeEngine("p", [])
    secondary = FakeEngine("s", [])
    dispatcher = SearchDispatcher(primary=primary, secondary=secondary)
    results, engine = await dispatcher.search("foo")
    assert engine == "none"
    assert results == []
