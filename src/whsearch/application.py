from __future__ import annotations

from types import TracebackType
from typing import Self

import httpx

from whsearch.agent import ResearchAgent
from whsearch.config import Settings
from whsearch.domain.protocols import DocumentReader, DocumentStore, SearchProvider
from whsearch.index import SqliteDocumentStore
from whsearch.infrastructure.http import HttpClientFactory
from whsearch.reader import ReaderService, RobotsPolicy
from whsearch.reader.browser import BrowserRenderer, is_browser_available
from whsearch.search import SearchService
from whsearch.search.providers.duckduckgo import DuckDuckGoProvider
from whsearch.search.providers.duckduckgo_html import DuckDuckGoHtmlProvider
from whsearch.search.providers.googlenews import GoogleNewsProvider
from whsearch.search.providers.openalex import OpenAlexProvider
from whsearch.search.providers.wikipedia import WikipediaProvider


class Application:
    """Composition root. Business modules remain independent of this wiring."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        settings: Settings | None = None,
        provider: SearchProvider | None = None,
        extra_providers: list[SearchProvider] | None = None,
        reader: DocumentReader | None = None,
        store: DocumentStore | None = None,
    ) -> None:
        self.settings = settings or Settings.from_environment()
        self.client = client
        robots = RobotsPolicy(client, self.settings.user_agent)
        browser: BrowserRenderer | None = None
        if self.settings.browser_enabled and is_browser_available():
            browser = BrowserRenderer(timeout_seconds=self.settings.browser_timeout_seconds)
        self.reader: DocumentReader = reader or ReaderService(
            client,
            robots,
            max_bytes=self.settings.max_response_bytes,
            user_agent=self.settings.user_agent,
            browser=browser,
        )
        providers = [provider or DuckDuckGoProvider(client)]
        if extra_providers:
            providers.extend(extra_providers)
        primary, *rest = providers
        self.search = SearchService(
            primary, extra_providers=rest, max_results=self.settings.max_search_results
        )
        if store is not None:
            self.store: DocumentStore | None = store
        elif self.settings.index_path:
            self.store = SqliteDocumentStore(
                self.settings.index_path, max_entries=self.settings.index_max_entries
            )
        else:
            self.store = None
        self.research_agent = ResearchAgent(self.search, self.reader, store=self.store)

    async def aclose(self) -> None:
        if isinstance(self.store, SqliteDocumentStore):
            self.store.close()
        aclose = getattr(self.reader, "aclose", None)
        if callable(aclose):
            await aclose()
        await self.client.aclose()

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.aclose()


async def create_application(settings: Settings | None = None) -> Application:
    resolved = settings or Settings.from_environment()
    client = HttpClientFactory(timeout=resolved.request_timeout_seconds).create()
    return Application(
        client,
        settings=resolved,
        extra_providers=[
            DuckDuckGoHtmlProvider(client),
            WikipediaProvider(client, language="en"),
            WikipediaProvider(client, language="th"),
            GoogleNewsProvider(client),
            OpenAlexProvider(client),
        ],
    )
