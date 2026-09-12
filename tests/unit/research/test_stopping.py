from whsearch.domain import ResearchBudget, StoppingReason
from whsearch.research import RoundStats, stopping_reason


def _stats(**overrides: int) -> RoundStats:
    base = {
        "round_index": 0,
        "new_passages": 10,
        "total_passages": 10,
        "supported_claims": 0,
        "queries_used": 1,
        "pages_used": 2,
    }
    base.update(overrides)
    return RoundStats(**base)


def test_no_stop_when_progressing() -> None:
    assert stopping_reason(_stats(), ResearchBudget()) is None


def test_budget_exhausted_on_queries() -> None:
    budget = ResearchBudget(max_queries=2)
    assert stopping_reason(_stats(queries_used=2), budget) is StoppingReason.BUDGET_EXHAUSTED


def test_budget_exhausted_on_pages() -> None:
    budget = ResearchBudget(max_pages=2)
    assert stopping_reason(_stats(pages_used=2), budget) is StoppingReason.BUDGET_EXHAUSTED


def test_max_rounds_after_final_round() -> None:
    budget = ResearchBudget(max_rounds=1)
    assert stopping_reason(_stats(), budget) is StoppingReason.MAX_ROUNDS


def test_sufficient_evidence_after_second_round() -> None:
    assert (
        stopping_reason(_stats(round_index=1, supported_claims=2), ResearchBudget())
        is StoppingReason.SUFFICIENT_EVIDENCE
    )


def test_no_sufficient_evidence_on_first_round() -> None:
    assert stopping_reason(_stats(round_index=0, supported_claims=5), ResearchBudget()) is None


def test_saturated_when_no_fresh_content() -> None:
    stats = _stats(new_passages=1, total_passages=100)
    assert stopping_reason(stats, ResearchBudget()) is StoppingReason.SATURATED
