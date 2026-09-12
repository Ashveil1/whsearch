from whsearch.search.query import (
    df_for_recency,
    extract_excluded_terms,
    extract_site_domains,
    is_thai_query,
    kl_for_query,
    normalize_text,
    simplify_query,
    wants_academic,
    wants_news,
)


def test_normalize_collapses_whitespace() -> None:
    assert normalize_text("  Elengenix   hunt\nexample.com ") == "Elengenix hunt example.com"


def test_extract_site_domains_splits_operator() -> None:
    domains, remaining = extract_site_domains("site:github.com Elengenix bug bounty")
    assert domains == ["github.com"]
    assert remaining == "Elengenix bug bounty"


def test_extract_site_domains_none() -> None:
    domains, remaining = extract_site_domains("plain query")
    assert domains == []
    assert remaining == "plain query"


def test_extract_excluded_terms() -> None:
    assert extract_excluded_terms("python -tutorial -old") == ["tutorial", "old"]
    assert extract_excluded_terms("no exclusions here") == []


def test_simplify_query_strips_operators() -> None:
    simplified = simplify_query('site:github.com "Elengenix" -old')
    assert simplified == "Elengenix"
    assert "site:" not in simplified


def test_thai_detection_and_region() -> None:
    assert is_thai_query("ผลบอลโลก 2026") is True
    assert is_thai_query("Elengenix hunt") is False
    assert kl_for_query("ผลบอลโลก 2026") == "th-th"
    assert kl_for_query("Elengenix hunt") == "wt-wt"


def test_df_for_recency_mapping() -> None:
    assert df_for_recency(1) == "d"
    assert df_for_recency(7) == "w"
    assert df_for_recency(30) == "m"
    assert df_for_recency(90) == "y"
    assert df_for_recency(None) is None


def test_wants_news_on_keywords_or_recency() -> None:
    assert wants_news("ข่าวล่าสุดวันนี้", None) is True
    assert wants_news("breaking news update", None) is True
    assert wants_news("Elengenix", 7) is True
    assert wants_news("Elengenix", None) is False


def test_wants_academic_on_keywords() -> None:
    assert wants_academic("arxiv paper on retrieval") is True
    assert wants_academic("งานวิจัย retrieval") is True
    assert wants_academic("Elengenix") is False
