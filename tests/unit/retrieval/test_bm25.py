import pytest

from whsearch.domain import Passage
from whsearch.retrieval import rank_passages


def test_bm25_prefers_matching_passage() -> None:
    passages = [
        Passage("The weather is sunny.", 0),
        Passage("Python is a popular programming language.", 1),
    ]
    ranked = rank_passages("Python programming", passages)
    assert ranked[0].index == 1
    assert ranked[0].score == 1.0


def test_bm25_scores_bounded_zero_to_one() -> None:
    passages = [Passage(f"Document number {i} about testing.", i) for i in range(5)]
    ranked = rank_passages("testing document", passages)
    assert len(ranked) == 5
    assert all(p.score is not None and 0.0 <= p.score <= 1.0 for p in ranked)


def test_bm25_empty_passages() -> None:
    assert rank_passages("query", []) == []


def test_bm25_empty_query_returns_input_order() -> None:
    passages = [Passage("Some text here.", 0), Passage("Other text here.", 1)]
    assert [p.index for p in rank_passages("   ", passages)] == [0, 1]


def test_bm25_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        rank_passages("query", [Passage("text here.", 0)], limit=0)


def test_bm25_term_frequency_matters() -> None:
    passages = [
        Passage("Python mentioned once here.", 0),
        Passage("Python Python Python everywhere here.", 1),
    ]
    ranked = rank_passages("Python", passages)
    assert ranked[0].index == 1


def test_bm25_thai_tokens_stay_whole() -> None:
    from whsearch.retrieval.ranking import _tokens

    assert _tokens("Zhypix คืออะไร มีความสามารถอะไรบ้าง?") == [
        "zhypix",
        "คืออะไร",
        "มีความสามารถอะไรบ้าง",
    ]


def test_bm25_thai_entity_beats_spam() -> None:
    passages = [
        Passage("ที่ บริษัทระบุไว้ว่า ต้องการ ผู้เข้าสมัคร ที่มีคุณสมบัติ อะไรบ้าง", 0),
        Passage("Zhypix is an all-in-one autonomous companion for Android", 1),
    ]
    ranked = rank_passages("Zhypix คืออะไร มีความสามารถอะไรบ้าง?", passages)
    assert ranked[0].index == 1
