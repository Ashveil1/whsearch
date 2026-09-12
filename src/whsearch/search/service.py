from __future__ import annotations

import asyncio
from collections.abc import Sequence

from whsearch.domain import SearchQuery, SearchResult
from whsearch.domain.protocols import SearchProvider
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger
from whsearch.retrieval import deduplicate_results

_logger = get_logger("search")


class SearchService:
    """Application service that hides provider selection from callers."""

    def __init__(
        self,
        provider: SearchProvider,
        *,
        extra_providers: Sequence[SearchProvider] = (),
        max_results: int = 30,
    ) -> None:
        if max_results < 1:
            raise ValueError("max_results must be positive")
        self._providers = [provider, *extra_providers]
        self._max_results = max_results

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        if len(self._providers) == 1:
            results = await self._providers[0].search(query)
            unique = deduplicate_results(results)
            capped = list(unique)[: min(query.limit, self._max_results)]
            _logger.debug(
                "search completed: query=%r provider=%d unique=%d returned=%d",
                query.text,
                len(results),
                len(unique),
                len(capped),
            )
            return capped
        return await self._fan_out(query)

    async def _fan_out(self, query: SearchQuery) -> list[SearchResult]:
        settled = await asyncio.gather(
            *(provider.search(query) for provider in self._providers),
            return_exceptions=True,
        )
        merged: list[SearchResult] = []
        failures = 0
        for provider, outcome in zip(self._providers, settled, strict=True):
            if isinstance(outcome, Exception):
                failures += 1
                _logger.warning("search provider %s failed: %s", type(provider).__name__, outcome)
                continue
            if isinstance(outcome, BaseException):  # pragma: no cover - cancellations propagate
                raise outcome
            merged.extend(outcome)
        if not merged and failures:
            raise ProviderError(f"all {failures} search providers failed")
        unique = deduplicate_results(merged)
        capped = list(unique)[: min(query.limit, self._max_results)]
        _logger.debug(
            "search fan-out completed: query=%r providers=%d merged=%d returned=%d",
            query.text,
            len(self._providers),
            len(merged),
            len(capped),
        )
        return capped
