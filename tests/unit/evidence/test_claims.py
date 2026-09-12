from whsearch.domain import Claim
from whsearch.evidence import (
    extract_claims,
    find_contradictions,
    independent_source_count,
    registrable_domain,
)


def test_extract_claims_splits_sentences() -> None:
    claims = extract_claims(
        ["Python is a popular programming language. It supports many programming paradigms widely."]
    )
    assert [c.text for c in claims] == [
        "Python is a popular programming language.",
        "It supports many programming paradigms widely.",
    ]


def test_extract_claims_filters_short_sentences() -> None:
    assert extract_claims(["Hi there."] ) == []


def test_extract_claims_deduplicates() -> None:
    texts = [
        "Python is a popular programming language.",
        "Python is a popular programming language.",
    ]
    assert len(extract_claims(texts)) == 1


def test_find_contradictions_flags_negation_asymmetry() -> None:
    claims = [
        Claim(id="a", text="Python is a popular programming language"),
        Claim(id="b", text="Python is not a popular programming language"),
    ]
    assert find_contradictions(claims) == [("a", "b")]


def test_find_contradictions_ignores_unrelated_claims() -> None:
    claims = [
        Claim(id="a", text="Python is a popular programming language"),
        Claim(id="b", text="The weather in Lisbon is sunny today"),
    ]
    assert find_contradictions(claims) == []


def test_registrable_domain_strips_www_and_port() -> None:
    assert registrable_domain("https://www.example.com:8080/a") == "example.com"


def test_independent_source_count_groups_subdomains() -> None:
    urls = ["https://a.example.com/1", "https://b.example.com/2", "https://other.org/3"]
    assert independent_source_count(urls) == 2
