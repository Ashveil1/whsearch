from whsearch.domain import Claim, ClaimStatus
from whsearch.evidence import SourcedPassage, verify_claims


def _source(url: str, text: str) -> SourcedPassage:
    return SourcedPassage(url=url, title="T", index=0, text=text)


def test_supported_claim_needs_two_independent_domains() -> None:
    claims = [Claim(id="c1", text="Python is a popular programming language")]
    sources = [
        _source("https://example.com/a", "Python is a popular programming language indeed."),
        _source("https://example.org/b", "Python is a popular programming language today."),
    ]
    verified, evidence = verify_claims(claims, sources)
    assert verified[0].status == ClaimStatus.SUPPORTED
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
