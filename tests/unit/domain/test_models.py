import pytest

from whsearch.domain import SearchQuery, SearchResult


def test_search_query_normalizes_whitespace() -> None:
    query = SearchQuery("  hello world  ")
    assert query.text == "hello world"


def test_search_query_rejects_empty_text() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        SearchQuery("   ")


def test_search_query_rejects_invalid_limit() -> None:
    with pytest.raises(ValueError, match="between 1 and 100"):
        SearchQuery("hello", limit=0)


def test_search_result_requires_absolute_http_url() -> None:
    with pytest.raises(ValueError, match=r"absolute HTTP\(S\) URL"):
        SearchResult(title="x", url="/relative")


def test_search_result_accepts_https_url() -> None:
    result = SearchResult(title="Example", url="https://example.com/a")
    assert result.title == "Example"
