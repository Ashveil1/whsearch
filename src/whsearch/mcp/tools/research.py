from __future__ import annotations

from whsearch.application import Application
from whsearch.domain import ResearchBudget
from whsearch.observability import get_logger

_logger = get_logger("mcp.research")


async def research(
    app: Application,
    question: str,
    max_queries: int = 8,
    max_pages: int = 20,
    max_rounds: int = 3,
    recency_days: int | None = None,
) -> dict[str, object]:
    requested = ResearchBudget(max_queries=max_queries, max_pages=max_pages, max_rounds=max_rounds)
    budget = ResearchBudget(
        max_queries=requested.max_queries,
        max_pages=min(requested.max_pages, app.settings.max_pages_per_task),
        max_rounds=requested.max_rounds,
    )
    report = await app.research_agent.research(question, budget, recency_days=recency_days)
    _logger.debug(
        "research tool: question=%r claims=%d rounds=%d reason=%s",
        question,
        len(report.claims),
        report.rounds,
        report.stopped_reason.value,
    )
    return {
        "question": report.question,
        "evidence_method": (
            "Lexical matches and contradiction flags are heuristic; they do not verify truth."
        ),
        "answer": report.answer,
        "answer_citations": list(report.answer_citations),
        "stopped_reason": report.stopped_reason.value,
        "rounds": report.rounds,
        "queries_used": report.queries_used,
        "pages_attempted": report.pages_attempted,
        "search_errors": report.search_errors,
        "read_errors": report.read_errors,
        "effective_budget": {
            "max_queries": budget.max_queries,
            "max_pages": budget.max_pages,
            "max_rounds": budget.max_rounds,
        },
        "sources": list(report.sources),
        "claims": [
            {
                "id": claim.id,
                "text": claim.text,
                "status": claim.status.value,
                "support_count": claim.support_count,
                "sources": list(claim.sources),
            }
            for claim in report.claims
        ],
        "evidence": [
            {
                "claim_id": item.claim_id,
                "url": item.url,
                "title": item.title,
                "passage_index": item.passage_index,
                "passage_text": item.passage_text,
                "score": item.score,
                "score_type": "relative_bm25",
                "relation": "lexical_match",
                "section": item.section,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "truncated": item.truncated,
            }
            for item in report.evidence
        ],
    }
