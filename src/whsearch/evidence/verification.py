from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from whsearch.domain import Claim, ClaimStatus, Evidence
from whsearch.observability import get_logger
from whsearch.retrieval import rank_passages

from .claims import find_contradictions, independent_source_count, registrable_domain

_logger = get_logger("evidence")


@dataclass(frozen=True, slots=True)
class SourcedPassage:
    url: str
    title: str
    index: int
    text: str
    section: str | None = None
    published_at: datetime | None = None
    truncated: bool = False


_THAI_RUN = re.compile(r"[\u0e00-\u0e7f]+")
_WORD = re.compile(r"[^\W_]+", re.UNICODE)


def _normalized_text(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).casefold().replace("|", " ").split())


def _lexical_units(text: str) -> set[str]:
    """Comparable full words and Thai trigrams, not semantic tokens."""
    text = unicodedata.normalize("NFC", text).casefold()
    units = set(_WORD.findall(_THAI_RUN.sub(" ", text)))
    for match in _THAI_RUN.finditer(text):
        run = match.group()
        if len(run) < 3:
            units.add(run)
        else:
            units.update(run[i : i + 3] for i in range(len(run) - 2))
    return units


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

    LEXICAL_MATCH: >= min_support passages from >= min_independent_domains domains.
    Lexical overlap is not evidence of entailment or truth.
    CONTESTED: a heuristic contradiction involves the claim (takes precedence).
    Otherwise UNVERIFIED.
    """
    from whsearch.domain import Passage

    passages = [Passage(text=s.text, index=i) for i, s in enumerate(sources)]
    source_units = [_lexical_units(source.text) for source in sources]
    source_texts = [_normalized_text(source.text) for source in sources]
    contradicted: set[str] = set()
    for left, right in find_contradictions(claims):
        contradicted.add(left)
        contradicted.add(right)

    verified: list[Claim] = []
    evidence: list[Evidence] = []
    for claim in claims:
        ranked = rank_passages(claim.text, passages, limit=max(1, len(passages)))
        claim_units = _lexical_units(claim.text)
        # Relative BM25 alone promotes the best unrelated source to 1.0. A
        # separate absolute overlap gate prevents that source being presented
        # as a lexical match. This still does not establish entailment.
        exact_text = _normalized_text(claim.text)
        exact = [p for p in ranked if exact_text and exact_text in source_texts[p.index]]
        exact_indices = {p.index for p in exact}
        matched = exact + [
            p
            for p in ranked
            if p.index not in exact_indices
            and (p.score or 0.0) >= min_score
            and claim_units
            and len(claim_units & source_units[p.index]) / len(claim_units) >= 0.65
        ]
        # First choose one passage per domain so a large site cannot crowd
        # all other sources out of the small evidence window.
        supporting = []
        domains_seen: set[str] = set()
        for passage in matched:
            domain = registrable_domain(sources[passage.index].url)
            if domain not in domains_seen:
                supporting.append(passage)
                domains_seen.add(domain)
                if len(supporting) >= top_k:
                    break
        if len(supporting) < top_k:
            chosen = {p.index for p in supporting}
            supporting.extend(p for p in matched if p.index not in chosen)
            supporting = supporting[:top_k]
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
                    section=source.section,
                    published_at=source.published_at,
                    truncated=source.truncated,
                )
            )
        if claim.id in contradicted:
            status = ClaimStatus.CONTESTED
        elif len(supporting) >= min_support and domains >= min_independent_domains:
            status = ClaimStatus.LEXICAL_MATCH
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
        "examined %d claims: %d lexical matches, %d contested",
        len(verified),
        sum(1 for c in verified if c.status == ClaimStatus.LEXICAL_MATCH),
        sum(1 for c in verified if c.status == ClaimStatus.CONTESTED),
    )
    return verified, evidence
