from __future__ import annotations

import asyncio
import math
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from whsearch.agent.relevance import has_answer_overlap
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
from whsearch.evidence.verification import _normalized_text
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger
from whsearch.research import RoundStats, plan_queries, stopping_reason
from whsearch.research.planner import _keywords
from whsearch.retrieval import content_hash, rank_passages
from whsearch.search import SearchService
from whsearch.search.query import extract_site_domains, simplify_query
from whsearch.search.service import _result_allowed

_logger = get_logger("agent")

_STATUS_ORDER = {"supported": 0, "lexical_match": 1, "contested": 2, "unverified": 3}


def relevance_scores(question: str, claims: list[Claim]) -> dict[str, float]:
    """BM25 relevance of each claim to the research question.

    IDF does the rare-entity boost automatically: a distinctive token
    like `zhypix` outweighs a corpus-frequent word like `ความสามารถ`,
    so entity-bearing claims outrank spam within the same status group.
    """
    if not claims:
        return {}
    passages = [Passage(text=claim.text, index=index) for index, claim in enumerate(claims)]
    query = _keywords(simplify_query(question))
    if not query:
        return {claim.id: 0.0 for claim in claims}
    ranked = rank_passages(query, passages, limit=len(passages))
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
        if len(cleaned) > 2000:
            raise ValueError("research question must be at most 2000 characters")

        planned = plan_queries(cleaned, max_queries=active.max_queries)
        site_domains, _ = extract_site_domains(cleaned)
        domains = tuple(site_domains)
        # Preserve the original site's constraint for every planned and
        # evidence-derived query, not only the first query.
        queries = [
            SearchQuery(
                q.text,
                limit=q.limit,
                recency_days=recency_days,
                domains=tuple(dict.fromkeys([*q.domains, *domains])),
            )
            for q in planned
        ]
        seen_urls: set[str] = set()
        # Identical text repeats within one page collapse; the same text on
        # different pages is retained as separate lexical evidence, not proof of independence.
        seen_passages: set[tuple[str, str]] = set()
        sourced: list[SourcedPassage] = []
        candidates: dict[str, str] = {}
        claims: list[Claim] = []
        queries_used = 0
        pages_used = 0
        search_errors = 0
        read_errors = 0
        rounds = 0
        reason: StoppingReason | None = None

        for round_index in range(active.max_rounds):
            remaining_rounds = active.max_rounds - round_index
            remaining_queries = len(queries) - queries_used
            per_round = max(1, math.ceil(remaining_queries / remaining_rounds))
            round_queries = queries[queries_used : queries_used + per_round]
            if not round_queries:
                reason = StoppingReason.NO_MORE_QUERIES
                break
            rounds = round_index + 1
            remaining_pages = active.max_pages - pages_used
            round_page_limit = pages_used + math.ceil(remaining_pages / remaining_rounds)
            round_budget = ResearchBudget(
                max_queries=active.max_queries,
                max_pages=round_page_limit,
                max_rounds=active.max_rounds,
            )
            fresh = await self._run_round(
                round_queries,
                seen_urls,
                sourced,
                seen_passages,
                candidates,
                round_budget,
                pages_used,
                cleaned,
            )
            queries_used += len(round_queries)
            pages_used += fresh[1]
            search_errors += fresh[2]
            read_errors += fresh[3]
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
            # Use a relevant, unresolved claim as a follow-up query, without
            # inventing facts. Reserve the remaining budget for later rounds.
            if len(queries) < active.max_queries and round_index + 1 < active.max_rounds:
                scores = relevance_scores(cleaned, claims)
                seen_queries = {q.text.casefold() for q in queries}
                for claim in sorted(claims, key=lambda c: -scores.get(c.id, 0.0)):
                    text = claim.text.strip()[:200]
                    if has_answer_overlap(cleaned, text) and text.casefold() not in seen_queries:
                        queries.append(
                            SearchQuery(text, limit=10, recency_days=recency_days, domains=domains)
                        )
                        break

        relevance = relevance_scores(cleaned, claims)
        ordered = sorted(
            claims,
            key=lambda c: (
                -relevance.get(c.id, 0.0),
                _STATUS_ORDER[c.status.value],
                -c.support_count,
            ),
        )
        final_claims, final_evidence = verify_claims(ordered, sourced)
        # Relative BM25 scores always make the best weak match look like 1.0.
        # Gate answer candidates with an absolute lexical heuristic instead;
        # the full claims/evidence remain available for inspection.
        relevant_claims = []
        for claim in final_claims:
            if not has_answer_overlap(cleaned, claim.text):
                continue
            # Cite only passages containing the extracted claim; approximate
            # lexical matches remain visible in the evidence list but should
            # not masquerade as the origin of this exact wording.
            text = _normalized_text(claim.text)
            origin_urls = tuple(
                dict.fromkeys(
                    item.url
                    for item in final_evidence
                    if item.claim_id == claim.id and text in _normalized_text(item.passage_text)
                )
            )
            if origin_urls:
                relevant_claims.append(replace(claim, sources=origin_urls))
        answer, answer_citations = build_answer(relevant_claims)
        final_reason = reason or StoppingReason.MAX_ROUNDS
        return ResearchReport(
            question=cleaned,
            claims=tuple(final_claims),
            evidence=tuple(final_evidence),
            sources=tuple(dict.fromkeys(s.url for s in sourced)),
            rounds=rounds,
            queries_used=queries_used,
            pages_attempted=pages_used,
            search_errors=search_errors,
            read_errors=read_errors,
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
        question: str,
    ) -> tuple[int, int, int, int]:
        """Execute a round; return passages, attempts, search errors, read errors.

        Targets are interleaved round-robin across sub-queries so one
        noisy query (e.g. a full Thai question matching spam) cannot eat
        the whole page budget before the keyword query is even read.
        """
        per_query: list[list[SearchResult]] = []
        search_errors = 0
        for query in round_queries:
            try:
                results = await self._search.search(query)
            except ProviderError as exc:
                search_errors += 1
                _logger.warning("search failed: %s", type(exc).__name__)
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
            if not _result_allowed(document.url, round_queries[0].domains):
                _logger.debug("redirected page is outside the domain filter: url=%r", url)
                continue
            if cutoff is not None and document.published_at is not None:
                published = document.published_at
                if published.tzinfo is None:
                    published = published.replace(tzinfo=UTC)
                if published < cutoff:
                    _logger.debug("page filtered by recency: url=%r", url)
                    continue
            relevant_query = _keywords(simplify_query(question))
            ranked_passages = rank_passages(relevant_query, document.passages[:2000], limit=100)
            for passage in ranked_passages:
                if len(sourced) >= 1000:
                    break
                source_url = document.url
                text = passage.text[:2000]
                digest = content_hash(text)
                if (source_url, digest) in seen_passages:
                    continue
                seen_passages.add((source_url, digest))
                fresh += 1
                fresh_texts.append(text)
                sourced.append(
                    SourcedPassage(
                        url=source_url,
                        title=document.title,
                        index=passage.index,
                        text=text,
                        section=passage.section,
                        published_at=document.published_at,
                        truncated=len(passage.text) > len(text),
                    )
                )
        for claim in extract_claims(fresh_texts):
            if len(candidates) >= 50:
                break
            candidates.setdefault(claim.id, claim.text)
        return fresh, len(targets), search_errors, sum(doc is None for doc in documents)

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
