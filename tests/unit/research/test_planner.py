import pytest

from whsearch.research import plan_queries


def test_plan_starts_with_full_question() -> None:
    queries = plan_queries("What is Python programming?")
    assert queries[0].text == "What is Python programming?"


def test_plan_splits_conjunctions() -> None:
    queries = plan_queries("Python threading and asyncio", max_queries=5)
    texts = [q.text for q in queries]
    assert "Python threading and asyncio" in texts
    assert "Python threading" in texts
    assert "asyncio" in texts


def test_plan_respects_max_queries() -> None:
    queries = plan_queries("Python threading and asyncio", max_queries=2)
    assert len(queries) == 2


def test_plan_rejects_empty_question() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        plan_queries("   ")


def test_plan_rejects_non_positive_max() -> None:
    with pytest.raises(ValueError, match="positive"):
        plan_queries("Python", max_queries=0)
