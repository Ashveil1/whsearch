from whsearch.domain import Claim
from whsearch.evidence import build_answer


def _claim(cid: str, text: str, status: str = "unverified") -> Claim:
    from whsearch.domain import ClaimStatus

    return Claim(
        id=cid,
        text=text,
        status=ClaimStatus(status),
        support_count=2,
        sources=("https://example.com/a", "https://example.org/b"),
    )


def test_build_answer_marks_supported_plainly() -> None:
    answer, citations = build_answer([_claim("c1", "Spain won the final.", "supported")])
    assert answer.startswith("Top finding:")
    assert "[1]" in answer
    assert "(unverified)" not in answer and "contested" not in answer
    assert set(citations) == {"https://example.com/a", "https://example.org/b"}


def test_build_answer_hedges_unverified_and_contested() -> None:
    answer, _ = build_answer(
        [
            _claim("c1", "First claim here.", "unverified"),
            _claim("c2", "Second claim here.", "contested"),
        ]
    )
    assert answer.startswith("Top findings:")
    assert "(unverified)" in answer
    assert "contested" in answer


def test_build_answer_empty_claims() -> None:
    answer, citations = build_answer([])
    assert answer == ""
    assert citations == ()


def test_build_answer_caps_claims_and_dedupes_citations() -> None:
    claims = [_claim(f"c{i}", f"Claim number {i} here today.") for i in range(10)]
    answer, citations = build_answer(claims, max_claims=3)
    assert "[3]" in answer and "[4]" not in answer
    assert len(set(citations)) == 2
