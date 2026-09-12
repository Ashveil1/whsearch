from __future__ import annotations

import asyncio

from whsearch.domain import (
    Claim,
    Document,
    ResearchBudget,
    ResearchReport,
    SearchQuery,
    StoppingReason,
)
from whsearch.domain.protocols import DocumentReader, DocumentStore
from whsearch.evidence import SourcedPassage, extract_claims, verify_claims
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger
from whsearch.research import RoundStats, plan_queries, stopping_reason
from whsearch.retrieval import content_hash
from whsearch.search import SearchService

_logger = get_logger("agent")

_STATUS_ORDER = {"supported": 0, "contested": 1, "unverified": 2}


class ResearchAgent:
    """Orchestrates plan → search → read → verify loops under an explicit budget."""

    def __init__(
        self,
        search: SearchService,
        reader: DocumentReader,
        *,
        store: DocumentStore | None = None,
        read_concurrency: int = 5,
    ) -> None:
        if read_concurrency < 1:
            raise ValueError("read_concurrency must be positive")
        self._search = search
        self._reader = reader
        self._store = store
        self._read_concurrency = read_concurrency

    async def research(self, question: str, budget: ResearchBudget | None = None) -> ResearchReport:
        active = budget or ResearchBudget()
        cleaned = " ".join(question.split())
        if not cleaned:
            raise ValueError("research question must not be empty")

        queries = plan_queries(cleaned, max_queries=active.max_queries)
        seen_urls: set[str] = set()
        # Identical text repeats within one page collapse; the same text on
        # different pages is kept as independent attestation for verification.
        seen_passages: set[tuple[str, str]] = set()
        sourced: list[SourcedPassage] = []
        candidates: dict[str, str] = {}
        claims: list[Claim] = []
        queries_used = 0
        pages_used = 0
        rounds = 0
        reason: StoppingReason | None = None

        for round_index in range(active.max_rounds):
            round_queries = queries[queries_used : active.max_queries]
            if not round_queries:
                reason = StoppingReason.SATURATED
                break
            rounds = round_index + 1
            fresh = await self._run_round(
                round_queries, seen_urls, sourced, seen_passages, candidates, active, pages_used
            )
            queries_used += len(round_queries)
            pages_used += fresh[1]
            claims = self._verify(candidates, sourced)
            stats = RoundStats(
                round_index=round_index,
                new_passages=fresh[0],
                total_passages=len(sourced),
                supported_claims=sum(1 for c in claims if c.status.value == "supported"),
                queries_used=queries_used,
                pages_used=pages_used,
            )
            reason = stopping_reason(stats, active)
            _logger.debug(
                "round %d: queries=%d pages=%d passages=%d claims=%d reason=%s",
                rounds,
                queries_used,
                pages_used,
                len(sourced),
                len(claims),
                reason,
            )
            if reason is not None:
                break

        ordered = sorted(claims, key=lambda c: (_STATUS_ORDER[c.status.value], -c.support_count))
        final_claims, final_evidence = verify_claims(ordered, sourced)
        return ResearchReport(
            question=cleaned,
            claims=tuple(final_claims),
            evidence=tuple(final_evidence),
            sources=tuple(dict.fromkeys(s.url for s in sourced)),
            rounds=rounds,
            stopped_reason=reason or StoppingReason.MAX_ROUNDS,
        )

    @staticmethod
    def _verify(candidates: dict[str, str], sourced: list[SourcedPassage]) -> list[Claim]:
        claims = [Claim(id=cid, text=text) for cid, text in candidates.items()]
        verified, _ = verify_claims(claims, sourced)
        return verified

    async def _run_round(
        self,
        round_queries: list[SearchQuery],
        seen_urls: set[str],
        sourced: list[SourcedPassage],
        seen_passages: set[tuple[str, str]],
        candidates: dict[str, str],
        budget: ResearchBudget,
        pages_used: int,
    ) -> tuple[int, int]:
        """Execute one round; returns (new_passage_count, pages_read)."""
        targets: list[tuple[str, str]] = []
        for query in round_queries:
            try:
                results = await self._search.search(query)
            except ProviderError as exc:
                _logger.warning("search failed for %r: %s", query.text, exc)
                continue
            for result in results:
                if result.url in seen_urls:
                    continue
                seen_urls.add(result.url)
                targets.append((result.url, result.title))
                if pages_used + len(targets) >= budget.max_pages:
                    break
            if pages_used + len(targets) >= budget.max_pages:
                break

        semaphore = asyncio.Semaphore(min(self._read_concurrency, len(targets) or 1))

        async def _read(url: str) -> Document | None:
            async with semaphore:
                cached = await self._cached(url)
                if cached is not None:
                    return cached
                try:
                    document = await self._reader.read(url)
                except Exception as exc:
                    _logger.debug("page unreadable: url=%r error=%s", url, exc)
                    return None
                await self._cached_put(document)
                return document

        documents = await asyncio.gather(*(_read(url) for url, _ in targets))
        fresh = 0
        fresh_texts: list[str] = []
        for (url, _), document in zip(targets, documents, strict=True):
            if document is None:
                continue
            for passage in document.passages:
                digest = content_hash(passage.text)
                if (url, digest) in seen_passages:
                    continue
                seen_passages.add((url, digest))
                fresh += 1
                fresh_texts.append(passage.text)
                sourced.append(
                    SourcedPassage(
                        url=url, title=document.title, index=passage.index, text=passage.text
                    )
                )
        for claim in extract_claims(fresh_texts):
            candidates.setdefault(claim.id, claim.text)
        return fresh, sum(1 for document in documents if document is not None)

    async def _cached(self, url: str) -> Document | None:
        if self._store is None:
            return None
        try:
            return await self._store.get(url)
        except Exception as exc:
            _logger.debug("index lookup failed for %r: %s", url, exc)
            return None

    async def _cached_put(self, document: Document) -> None:
        if self._store is None:
            return
        try:
            await self._store.put(document)
        except Exception as exc:
            _logger.debug("index write failed for %r: %s", document.url, exc)
