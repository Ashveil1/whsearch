import asyncio
from collections.abc import Sequence

import httpx

from whsearch.application import Application
from whsearch.config import Settings
from whsearch.domain import SearchQuery, SearchResult
from whsearch.exceptions import ConfigurationError


class StubProvider:
    def __init__(self, results: Sequence[SearchResult]) -> None:
        self._results = list(results)

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        return self._results


def test_configuration_error_is_value_error_compatible() -> None:
    assert issubclass(ConfigurationError, ValueError)


def test_application_wires_settings_into_services() -> None:
    settings = Settings(
        user_agent="TestAgent/1.0",
        max_search_results=1,
        max_response_bytes=1_000_000,
        max_pages_per_task=4,
    )
    provider = StubProvider(
        [
            SearchResult(title="A", url="https://example.com/a"),
            SearchResult(title="B", url="https://example.com/b"),
        ]
    )
    client = httpx.AsyncClient()
    app = Application(client, settings=settings, provider=provider)
    try:
        assert app.settings is settings
        assert app.settings.max_pages_per_task == 4
        results = asyncio.run(app.search.search(SearchQuery("hello", limit=10)))
        assert [r.url for r in results] == ["https://example.com/a"]
    finally:
        asyncio.run(app.aclose())


def test_application_supports_context_manager() -> None:
    async def _main() -> None:
        client = httpx.AsyncClient()
        async with Application(client, provider=StubProvider([])) as app:
            assert app.settings.max_search_results >= 1

    asyncio.run(_main())
