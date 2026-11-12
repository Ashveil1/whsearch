from whsearch.domain import Claim, ClaimStatus
from whsearch.evidence import SourcedPassage, verify_claims


def _source(url: str, text: str) -> SourcedPassage:
    return SourcedPassage(url=url, title="T", index=0, text=text)


def test_lexical_match_needs_two_independent_domains() -> None:
    claims = [Claim(id="c1", text="Python is a popular programming language")]
    sources = [
        _source("https://example.com/a", "Python is a popular programming language indeed."),
        _source("https://example.org/b", "Python is a popular programming language today."),
    ]
    verified, evidence = verify_claims(claims, sources)
    assert verified[0].status == ClaimStatus.LEXICAL_MATCH
    assert verified[0].support_count == 2
    assert len(evidence) == 2


def test_single_source_claim_stays_unverified() -> None:
    claims = [Claim(id="c1", text="Python is a popular programming language")]
    sources = [_source("https://example.com/a", "Python is a popular programming language.")]
    verified, _ = verify_claims(claims, sources)
    assert verified[0].status == ClaimStatus.UNVERIFIED


def test_contradicted_claim_is_contested() -> None:
    claims = [
        Claim(id="c1", text="Python is a popular programming language"),
        Claim(id="c2", text="Python is not a popular programming language"),
    ]
    sources = [
        _source("https://example.com/a", "Python is a popular programming language."),
        _source("https://example.org/b", "Python is not a popular programming language."),
    ]
    verified, _ = verify_claims(claims, sources)
    assert {c.status for c in verified} == {ClaimStatus.CONTESTED}


def test_best_relative_match_is_not_automatically_evidence() -> None:
    claim = Claim(id="c", text="Mars rover studies geology on the red planet")
    sources = [_source("https://example.com/weather", "The weather on Mars is very cold today.")]
    claims, evidence = verify_claims([claim], sources)
    assert claims[0].sources == ()
    assert claims[0].support_count == 0
    assert evidence == []


def test_exact_claim_source_takes_priority_over_other_lexical_match() -> None:
    text = "Mars rover studies geology on the red planet"
    sources = [
        _source("https://other.com/", ("Mars rover studies geology on the red " * 20)),
        _source("https://origin.com/", "Background words. " + text + "."),
    ]
    claims, evidence = verify_claims([Claim("c", text)], sources, top_k=1)
    assert claims[0].sources == ("https://origin.com/",)
    assert [item.url for item in evidence] == ["https://origin.com/"]
