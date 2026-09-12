from __future__ import annotations

from dataclasses import dataclass

from whsearch.domain import ResearchBudget, StoppingReason


@dataclass(frozen=True, slots=True)
class RoundStats:
    round_index: int
    new_passages: int
    total_passages: int
    supported_claims: int
    queries_used: int
    pages_used: int


def stopping_reason(
    stats: RoundStats,
    budget: ResearchBudget,
    *,
    min_new_ratio: float = 0.15,
    min_supported_claims: int = 2,
) -> StoppingReason | None:
    """Decide whether the research loop should stop after a round."""
    if stats.queries_used >= budget.max_queries or stats.pages_used >= budget.max_pages:
        return StoppingReason.BUDGET_EXHAUSTED
    if stats.round_index + 1 >= budget.max_rounds:
        return StoppingReason.MAX_ROUNDS
    if stats.supported_claims >= min_supported_claims and stats.round_index >= 1:
        return StoppingReason.SUFFICIENT_EVIDENCE
    if stats.total_passages > 0:
        ratio = stats.new_passages / stats.total_passages
        if ratio < min_new_ratio:
            return StoppingReason.SATURATED
    return None
