"""Evaluator correctness tests; fixture quality scores are intentionally not thresholds."""

from dataclasses import replace

import pytest

from benchmarks.evaluate import (
    evaluate_research,
    evaluate_retrieval,
    load_dataset,
    score_research,
)
from whsearch.domain import Claim, ClaimStatus, Evidence, ResearchReport


def test_retrieval_metrics_use_labels_and_ranking() -> None:
    case = load_dataset()["retrieval"][0]
    result = evaluate_retrieval(case)
    ranked = result["ranked_indices"]
    first_rank = ranked.index(case["relevant"][0]) + 1
    assert result["reciprocal_rank"] == 1 / first_rank
    assert result["hit_at_1"] == float(first_rank == 1)
    assert result["recall_at_3"] == float(first_rank <= 3)


@pytest.mark.anyio
async def test_research_fixture_and_absent_case() -> None:
    dataset = load_dataset()
    relevant = await evaluate_research(dataset["research"][0])
    absent = await evaluate_research(dataset["research"][3])
    assert relevant["top_answer_correct"] is True
    assert relevant["citation_structure_valid"]
    assert absent["abstained"]
    assert absent["top_answer_correct"] is None


def test_citation_structure_detects_wrong_claim_url_and_passage() -> None:
    case = load_dataset()["research"][0]
    text = case["gold_claims"][0]
    url = case["relevant_urls"][0]
    claim = Claim(id="one", text=text, status=ClaimStatus.UNVERIFIED, sources=(url,))
    evidence = Evidence(
        claim_id="one", url=url, title="Python", passage_index=0, passage_text=text, score=1.0
    )
    report = ResearchReport(
        question=case["question"],
        claims=(claim,),
        evidence=(evidence,),
        answer=f"Top finding:\n1. {text} [1] (unverified)",
        answer_citations=(url,),
    )
    assert score_research(case, report)["citation_structure_valid"]
    broken = replace(report, answer_citations=("https://weather.example/article",))
    assert not score_research(case, broken)["citation_structure_valid"]
    broken = replace(
        report,
        evidence=(
            Evidence(
                claim_id="one",
                url=url,
                title="Python",
                passage_index=0,
                passage_text="invented evidence",
                score=1.0,
            ),
        ),
    )
    assert not score_research(case, broken)["citation_structure_valid"]


def test_citation_must_quote_claim_not_merely_reference_real_passage() -> None:
    case = load_dataset()["research"][0]
    url = case["relevant_urls"][0]
    invented = "Python is an invented claim with no corresponding passage."
    real_passage = case["documents"][0]["passages"][0]
    claim = Claim("one", invented, sources=(url,))
    evidence = Evidence("one", url, "Python", 0, real_passage, 1.0)
    report = ResearchReport(
        question=case["question"],
        claims=(claim,),
        evidence=(evidence,),
        answer=f"Top finding:\n1. {invented} [1] (unverified)",
        answer_citations=(url,),
    )
    assert not score_research(case, report)["citation_structure_valid"]
