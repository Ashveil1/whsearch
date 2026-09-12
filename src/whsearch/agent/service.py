from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from whsearch.domain import (
    Claim,
    Document,
    Passage,
    ResearchBudget,
    ResearchReport,
    SearchQuery,
    SearchResult,
    StoppingReason,
)
from whsearch.domain.protocols import DocumentReader, DocumentStore
from whsearch.evidence import SourcedPassage, build_answer, extract_claims, verify_claims
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger
from whsearch.research import RoundStats, plan_queries, stopping_reason
from whsearch.retrieval import content_hash, rank_passages
from whsearch.search import SearchService

_logger = get_logger("agent")

_STATUS_ORDER = {"supported": 0, "contested": 1, "unverified": 2}


def relevance_scores(question: str, claims: list[Claim]) -> dict[str, float]:
    """BM25 relevance of each claim to the research question.

    IDF does the rare-entity boost automatically: a distinctive token
    like `zhypix` outweighs a corpus-frequent word like `ความสามารถ`,
    so entity-bearing claims outrank spam within the same status group.
    """
    if not claims:
        return {}
    passages = [Passage(text=claim.text, index=index) for index, claim in enumerate(claims)]
    ranked = rank_passages(question, passages, limit=len(passages))
    return {claims[item.index].id: (item.score or 0.0) for item in ranked}


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

    async def research(
        self,
        question: str,
        budget: ResearchBudget | None = None,
        *,
        recency_days: int | None = None,
    ) -> ResearchReport:
        active = budget or ResearchBudget()
        if recency_days is not None and recency_days < 0:
            raise ValueError("recency_days must be non-negative")
        cleaned = " ".join(question.split())
        if not cleaned:
            raise ValueError("research question must not be empty")

        planned = plan_queries(cleaned, max_queries=active.max_queries)
        queries = (
            planned
            if recency_days is None
            else [
                SearchQuery(
                    q.text, limit=q.limit, recency_days=recency_days, domains=q.domains
                )
                for q in planned
            ]
        )
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

        relevance = relevance_scores(cleaned, claims)
        ordered = sorted(
            claims,
            key=lambda c: (
                _STATUS_ORDER[c.status.value],
                -relevance.get(c.id, 0.0),
                -c.support_count,
            ),
        )
        final_claims, final_evidence = verify_claims(ordered, sourced)
        answer, answer_citations = build_answer(final_claims)
        final_reason = reason or StoppingReason.MAX_ROUNDS
        # Friendlier completion signal: budget hit with actual evidence is
        # normal completion (saturated), not a scary exhaustion. Only keep
        # BUDGET_EXHAUSTED when nothing was retrieved at all.
        if final_reason is StoppingReason.BUDGET_EXHAUSTED and sourced:
            supported = sum(1 for c in final_claims if c.status.value == "supported")
            final_reason = (
                StoppingReason.SUFFICIENT_EVIDENCE
                if supported >= 2
                else StoppingReason.SATURATED
            )
        return ResearchReport(
            question=cleaned,
            claims=tuple(final_claims),
            evidence=tuple(final_evidence),
            sources=tuple(dict.fromkeys(s.url for s in sourced)),
            rounds=rounds,
            stopped_reason=final_reason,
            answer=answer,
            answer_citations=tuple(answer_citations),
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
        """Execute one round; returns (new_passage_count, pages_read).

        Targets are interleaved round-robin across sub-queries so one
        noisy query (e.g. a full Thai question matching spam) cannot eat
        the whole page budget before the keyword query is even read.
        """
        per_query: list[list[SearchResult]] = []
        for query in round_queries:
            try:
                results = await self._search.search(query)
            except ProviderError as exc:
                _logger.warning("search failed for %r: %s", query.text, exc)
                continue
            per_query.append(list(results))
        targets: list[tuple[str, str]] = []
        for depth in range(max((len(items) for items in per_query), default=0)):
            for items in per_query:
                if depth >= len(items):
                    continue
                result = items[depth]
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
        cutoff: datetime | None = None
        for query in round_queries:
            if query.recency_days is not None:
                candidate = datetime.now(UTC) - timedelta(days=query.recency_days)
                if cutoff is None or candidate > cutoff:
                    cutoff = candidate
                break
        fresh = 0
        fresh_texts: list[str] = []
        for (url, _), document in zip(targets, documents, strict=True):
            if document is None:
                continue
            if cutoff is not None and document.published_at is not None:
                published = document.published_at
                if published.tzinfo is None:
                    published = published.replace(tzinfo=UTC)
                if published < cutoff:
                    _logger.debug("page filtered by recency: url=%r", url)
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
