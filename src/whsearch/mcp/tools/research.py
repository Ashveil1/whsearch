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
    budget = ResearchBudget(max_queries=max_queries, max_pages=max_pages, max_rounds=max_rounds)
    report = await app.research_agent.research(question, budget, recency_days=recency_days)
    budget = ResearchBudget(max_queries=max_queries, max_pages=max_pages, max_rounds=max_rounds)
    report = await app.research_agent.research(question, budget)
    _logger.debug(
        "research tool: question=%r claims=%d rounds=%d reason=%s",
        question,
        len(report.claims),
        report.rounds,
        report.stopped_reason.value,
    )
    return {
        "question": report.question,
        "answer": report.answer,
        "answer_citations": list(report.answer_citations),
        "stopped_reason": report.stopped_reason.value,
        "rounds": report.rounds,
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
            }
            for item in report.evidence
        ],
    }
