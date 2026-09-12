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
            cleaned = sentence.strip().replace("|", " ").strip()
            cleaned = re.sub(r"\s+", " ", cleaned)
            # Count real words only: markdown table pipes and stray symbols
            # ("No personal data is stored. |") must not pass the bar.
            real_words = [w for w in cleaned.split() if re.search(r"[A-Za-z0-9ก-๙]", w)]
            if len(real_words) < min_words or len(cleaned) > 500:
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


def build_answer(claims: list[Claim], *, max_claims: int = 5) -> tuple[str, tuple[str, ...]]:
    """Build a deterministic extractive answer from ranked claims.

    Takes claims already sorted (supported first) and returns an
    (answer, citations) pair. Unverified claims are included with a
    hedge so small-budget research still yields a usable summary instead
    of an empty-looking claim dump.
    """
    if max_claims < 1:
        raise ValueError("max_claims must be positive")
    top = [c for c in claims if c.text.strip()][:max_claims]
    if not top:
        return "", ()
    lines: list[str] = []
    citations: list[str] = []
    for index, claim in enumerate(top, start=1):
        for url in claim.sources:
            if url not in citations:
                citations.append(url)
        marker = f"[{index}]"
        if claim.status.value == "supported":
            lines.append(f"{index}. {claim.text} {marker}")
        elif claim.status.value == "contested":
            lines.append(f"{index}. {claim.text} {marker} (contested — sources disagree)")
        else:
            lines.append(f"{index}. {claim.text} {marker} (unverified)")
    header = "Top findings:" if len(top) > 1 else "Top finding:"
    answer = header + "\n" + "\n".join(lines)
    return answer, tuple(citations)
