from __future__ import annotations

from dataclasses import dataclass

from whsearch.domain import Claim, ClaimStatus, Evidence
from whsearch.observability import get_logger
from whsearch.retrieval import rank_passages

from .claims import find_contradictions, independent_source_count

_logger = get_logger("evidence")


@dataclass(frozen=True, slots=True)
class SourcedPassage:
    url: str
    title: str
    index: int
    text: str


def verify_claims(
    claims: list[Claim],
    sources: list[SourcedPassage],
    *,
    min_score: float = 0.5,
    top_k: int = 3,
    min_support: int = 2,
    min_independent_domains: int = 2,
) -> tuple[list[Claim], list[Evidence]]:
    """Attach lexical evidence to claims and label support status.

    SUPPORTED: >= min_support passages from >= min_independent_domains domains.
    CONTESTED: a heuristic contradiction involves the claim (takes precedence).
    Otherwise UNVERIFIED.
    """
    from whsearch.domain import Passage

    passages = [Passage(text=s.text, index=i) for i, s in enumerate(sources)]
    contradicted: set[str] = set()
    for left, right in find_contradictions(claims):
        contradicted.add(left)
        contradicted.add(right)

    verified: list[Claim] = []
    evidence: list[Evidence] = []
    for claim in claims:
        ranked = rank_passages(claim.text, passages, limit=top_k * 2)
        supporting = [p for p in ranked if (p.score or 0.0) >= min_score][:top_k]
        urls = [sources[p.index].url for p in supporting]
        domains = independent_source_count(urls)
        for passage in supporting:
            source = sources[passage.index]
            evidence.append(
                Evidence(
                    claim_id=claim.id,
                    url=source.url,
                    title=source.title,
                    passage_index=source.index,
                    passage_text=source.text,
                    score=passage.score or 0.0,
                )
            )
        if claim.id in contradicted:
            status = ClaimStatus.CONTESTED
        elif len(supporting) >= min_support and domains >= min_independent_domains:
            status = ClaimStatus.SUPPORTED
        else:
            status = ClaimStatus.UNVERIFIED
        verified.append(
            Claim(
                id=claim.id,
                text=claim.text,
                status=status,
                support_count=len(supporting),
                sources=tuple(urls),
            )
        )
    _logger.debug(
        "verified %d claims: %d supported, %d contested",
        len(verified),
        sum(1 for c in verified if c.status == ClaimStatus.SUPPORTED),
        sum(1 for c in verified if c.status == ClaimStatus.CONTESTED),
    )
    return verified, evidence
