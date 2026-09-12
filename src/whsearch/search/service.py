from __future__ import annotations

import asyncio
import re
from collections import OrderedDict
from collections.abc import Sequence

from whsearch.domain import SearchQuery, SearchResult
from whsearch.domain.protocols import SearchProvider
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger
from whsearch.retrieval import deduplicate_results, normalize_url
from whsearch.search.query import (
    extract_excluded_terms,
    extract_site_domains,
    normalize_text,
    simplify_query,
    wants_academic,
    wants_news,
    wants_video,
)

_RRF_K = 60


def _result_allowed(url: str, domains: tuple[str, ...]) -> bool:
    if not domains:
        return True
    from urllib.parse import urlparse

    netloc = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    wanted = {d.lower().removeprefix("www.").strip() for d in domains if d and d.strip()}
    return any(netloc == domain or netloc.endswith(f".{domain}") for domain in wanted)


def _passes_exclusions(result: SearchResult, excluded: list[str]) -> bool:
    if not excluded:
        return True
    haystack = f"{result.title} {result.snippet}".lower()
    return not any(term in haystack for term in excluded)


def _with_rank_scores(results: list[SearchResult]) -> list[SearchResult]:
    scored: list[SearchResult] = []
    total = max(len(results), 1)
    for index, result in enumerate(results):
        snippet = _clean_snippet(result.title, result.snippet)
        if result.score is not None:
            if snippet != result.snippet:
                scored.append(
                    SearchResult(
                        title=result.title,
                        url=result.url,
                        snippet=snippet,
                        source_type=result.source_type,
                        score=result.score,
                        metadata=result.metadata,
                    )
                )
            else:
                scored.append(result)
            continue
        # Linear decay 1.0 -> ~0.5 preserves fused ranking for MCP clients.
        score = max(0.5, 1.0 - (index / total) * 0.5)
        scored.append(
            SearchResult(
                title=result.title,
                url=result.url,
                snippet=snippet,
                source_type=result.source_type,
                score=round(score, 3),
                metadata=result.metadata,
            )
        )
    return scored


def _fuse_rrf(lists: list[list[SearchResult]]) -> list[SearchResult]:
    """Reciprocal Rank Fusion across provider lists (keyless, deterministic).

    Ties break by first-seen order so primary providers keep priority,
    preserving the historical primary-first contract. When several
    providers return the same URL, the most informative snippet wins
    (a real description beats a title-echo from a degraded layout).
    """
    scores: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    best: dict[str, SearchResult] = {}
    order = 0
    for results in lists:
        for rank, result in enumerate(results):
            key = normalize_url(result.url)
            scores[key] = scores.get(key, 0.0) + 1.0 / (_RRF_K + rank + 1)
            if key not in first_seen:
                first_seen[key] = order
                best[key] = result
                order += 1
            elif _snippet_quality(result.title, result.snippet) > _snippet_quality(
                best[key].title, best[key].snippet
            ):
                current = best[key]
                best[key] = SearchResult(
                    title=current.title,
                    url=current.url,
                    snippet=result.snippet,
                    source_type=current.source_type,
                    score=current.score,
                    metadata=current.metadata,
                )
    ranked_keys = sorted(scores, key=lambda k: (-scores[k], first_seen[k]))
    return [best[key] for key in ranked_keys]


_NUMBERING = re.compile(r"^\d+[.)]\s+")


def _clean_snippet(title: str, snippet: str) -> str:
    """Strip result numbering (`1. ...`) that leaks in from HTML layouts."""
    cleaned = _NUMBERING.sub("", (snippet or "").strip())
    return cleaned


def _snippet_quality(title: str, snippet: str) -> int:
    """Rank snippet informativeness: real descriptions beat title echoes."""
    cleaned = _clean_snippet(title, snippet)
    if not cleaned:
        return -1
    if cleaned == title.strip() or cleaned == f"{title.strip()} — result for":
        return 0
    if cleaned.startswith(title.strip()) and len(cleaned) <= len(title.strip()) + 40:
        return len(cleaned) // 4
    return len(cleaned)


def _provider_vertical(provider: SearchProvider) -> str:
    return str(getattr(provider, "vertical", "web") or "web").lower()


_logger = get_logger("search")


class SearchService:
    """Application service that hides provider selection from callers."""

    def __init__(
        self,
        provider: SearchProvider,
        *,
        extra_providers: Sequence[SearchProvider] = (),
        max_results: int = 30,
        cache_size: int = 128,
    ) -> None:
        if max_results < 1:
            raise ValueError("max_results must be positive")
        if cache_size < 0:
            raise ValueError("cache_size must be non-negative")
        self._providers = [provider, *extra_providers]
        self._max_results = max_results
        self._cache: OrderedDict[tuple[object, ...], list[SearchResult]] = OrderedDict()
        self._cache_size = cache_size

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]:
        site_domains, remaining = extract_site_domains(query.text)
        merged_domains = tuple(dict.fromkeys([*query.domains, *site_domains]))
        cleaned = normalize_text(remaining) or normalize_text(query.text)
        excluded = extract_excluded_terms(query.text)
        effective = SearchQuery(
            cleaned,
            limit=query.limit,
            recency_days=query.recency_days,
            domains=merged_domains,
        )
        try:
            results = await self._execute(effective, excluded)
        except ProviderError:
            cached = self._cached(effective)
            if cached is not None:
                _logger.debug("search served from cache after failure: query=%r", query.text)
                return cached
            raise
        if not results:
            simplified = simplify_query(cleaned)
            if simplified and simplified.lower() != cleaned.lower():
                retry = SearchQuery(
                    simplified,
                    limit=query.limit,
                    recency_days=query.recency_days,
                    domains=merged_domains,
                )
                results = await self._execute(retry, excluded)
        if results:
            self._remember(effective, list(results))
        return results

    def _select_providers(self, query: SearchQuery) -> list[SearchProvider]:
        selected: list[SearchProvider] = []
        use_news = wants_news(query.text, query.recency_days)
        use_academic = wants_academic(query.text)
        use_video = wants_video(query.text, query.domains)
        for provider in self._providers:
            vertical = _provider_vertical(provider)
            if vertical == "news" and not use_news:
                continue
            if vertical == "academic" and not use_academic:
                continue
            if vertical == "video" and not use_video:
                continue
            selected.append(provider)
        return selected or list(self._providers)

    async def _execute(
        self, query: SearchQuery, excluded: list[str]
    ) -> list[SearchResult]:
        providers = self._select_providers(query)
        if len(providers) == 1:
            # Preserve single-provider error contract (original error propagates).
            results = list(await providers[0].search(query))
            unique = deduplicate_results(results)
            filtered = [
                r
                for r in unique
                if _result_allowed(r.url, query.domains) and _passes_exclusions(r, excluded)
            ]
            ranked = _with_rank_scores(filtered)
            capped = list(ranked)[: min(query.limit, self._max_results)]
            _logger.debug(
                "search completed: query=%r unique=%d returned=%d",
                query.text,
                len(unique),
                len(capped),
            )
            return capped
        return await self._fan_out(providers, query, excluded)

    async def _fan_out(
        self, providers: list[SearchProvider], query: SearchQuery, excluded: list[str]
    ) -> list[SearchResult]:
        settled = await asyncio.gather(
            *(provider.search(query) for provider in providers),
            return_exceptions=True,
        )
        lists: list[list[SearchResult]] = []
        failures = 0
        merged_count = 0
        for provider, outcome in zip(providers, settled, strict=True):
            if isinstance(outcome, Exception):
                failures += 1
                _logger.warning("search provider %s failed: %s", type(provider).__name__, outcome)
                continue
            if isinstance(outcome, BaseException):  # pragma: no cover - cancellations propagate
                raise outcome
            items = list(outcome)
            merged_count += len(items)
            lists.append(items)
        if not lists and failures:
            raise ProviderError(f"all {failures} search providers failed")
        fused = _fuse_rrf(lists)
        filtered = [
            r
            for r in fused
            if _result_allowed(r.url, query.domains) and _passes_exclusions(r, excluded)
        ]
        ranked = _with_rank_scores(filtered)
        capped = list(ranked)[: min(query.limit, self._max_results)]
        _logger.debug(
            "search fan-out completed: query=%r providers=%d merged=%d returned=%d",
            query.text,
            len(providers),
            merged_count,
            len(capped),
        )
        return capped

    def _cache_key(self, query: SearchQuery) -> tuple[object, ...]:
        return (query.text.lower(), query.limit, query.recency_days, tuple(query.domains))

    def _cached(self, query: SearchQuery) -> list[SearchResult] | None:
        key = self._cache_key(query)
        cached = self._cache.get(key)
        if cached is None:
            return None
        self._cache.move_to_end(key)
        return list(cached)

    def _remember(self, query: SearchQuery, results: list[SearchResult]) -> None:
        if self._cache_size == 0 or not results:
            return
        key = self._cache_key(query)
        self._cache[key] = list(results)
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
