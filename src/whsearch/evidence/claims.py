from __future__ import annotations

import re
from urllib.parse import urlparse

from whsearch.domain import Claim

_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
_TOKEN = re.compile(r"[\w-]+", re.UNICODE)

_NEGATIONS = frozenset(
    {
        "not",
        "no",
        "never",
        "none",
        "nothing",
        "neither",
        "nor",
        "false",
        "falsely",
        "incorrect",
        "wrong",
        "deny",
        "denies",
        "denied",
        "refute",
        "refutes",
        "contradict",
        "contradicts",
        "however",
        "although",
        "despite",
        "myth",
    }
)


def claim_id(text: str) -> str:
    from whsearch.retrieval import content_hash

    return f"c_{content_hash(text)[:12]}"


def extract_claims(texts: list[str], *, min_words: int = 6, max_claims: int = 50) -> list[Claim]:
    """Split passages into sentence-level candidate claims (deterministic, no LLM)."""
    claims: list[Claim] = []
    seen: set[str] = set()
    for text in texts:
        for sentence in _SENTENCE.split(" ".join(text.split())):
            cleaned = sentence.strip()
            if len(cleaned.split()) < min_words or len(cleaned) > 500:
                continue
            cid = claim_id(cleaned)
            if cid in seen:
                continue
            seen.add(cid)
            claims.append(Claim(id=cid, text=cleaned))
            if len(claims) >= max_claims:
                return claims
    return claims


def find_contradictions(claims: list[Claim], *, min_overlap: float = 0.5) -> list[tuple[str, str]]:
    """Find claim pairs with high term overlap but asymmetric negation cues.

    Heuristic only: flags candidates for review, not logical proof.
    """
    token_sets = [_content_tokens(claim.text) for claim in claims]
    negated = [_has_negation(claim.text) for claim in claims]
    pairs: list[tuple[str, str]] = []
    for i in range(len(claims)):
        for j in range(i + 1, len(claims)):
            if negated[i] == negated[j]:
                continue
            union = token_sets[i] | token_sets[j]
            if not union:
                continue
            overlap = len(token_sets[i] & token_sets[j]) / len(union)
            if overlap >= min_overlap:
                pairs.append((claims[i].id, claims[j].id))
    return pairs


def registrable_domain(url: str) -> str:
    """Best-effort registrable domain used to judge source independence."""
    netloc = urlparse(url).netloc.lower().split("@")[-1].split(":")[0]
    if netloc.startswith("www."):
        netloc = netloc[4:]
    labels = netloc.split(".")
    return ".".join(labels[-2:]) if len(labels) >= 2 else netloc


def independent_source_count(urls: list[str]) -> int:
    return len({registrable_domain(url) for url in urls})


def _content_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _NEGATIONS and len(t) > 2}


def _has_negation(text: str) -> bool:
    return not _NEGATIONS.isdisjoint(_TOKEN.findall(text.lower()))
