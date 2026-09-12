import pytest

from whsearch.domain import Passage
from whsearch.retrieval import normalize_url, rank_passages


def test_normalize_url_sorts_query_params() -> None:
    assert normalize_url("https://example.com/p?b=2&a=1") == normalize_url(
        "https://example.com/p?a=1&b=2"
    )


def test_normalize_url_adds_root_path() -> None:
    assert normalize_url("https://example.com") == normalize_url("https://example.com/")


def test_rank_passages_rejects_non_positive_limit() -> None:
    with pytest.raises(ValueError, match="positive"):
        rank_passages("query", [Passage("some text here", 0)], limit=0)
