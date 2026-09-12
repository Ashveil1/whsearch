from __future__ import annotations

import math
import re
from collections.abc import Iterable

from whsearch.domain import Passage

_TOKEN = re.compile(r"[\w-]+", re.UNICODE)
_THAI = re.compile(r"[ก-๙]")

_STRIP_PUNCT = "?;.,:!\"'()[]{}"


def _tokens(text: str) -> list[str]:
    """Tokenize with Thai awareness.

    Thai combining marks (sara) are not ``\\w``, so regex tokenizing shreds
    words ("คืออะไร" -> "ค", "ออะไร") and lets spam match garbage
    fragments. Thai uses spaces between phrases, so Thai chunks stay whole
    while latin chunks keep regex splitting.
    """
    out: list[str] = []
    for chunk in text.split():
        if _THAI.search(chunk):
            cleaned = chunk.strip(_STRIP_PUNCT).lower()
            if cleaned:
                out.append(cleaned)
        else:
            out.extend(_TOKEN.findall(chunk.lower()))
    return out

_K1 = 1.2
_B = 0.75


def rank_passages(query: str, passages: Iterable[Passage], *, limit: int = 20) -> list[Passage]:
    """Rank passages with BM25 (stdlib-only, no embeddings or keys).

    Scores are normalized to 0..1 by the top BM25 in the set so the
    Evidence contract (score in range) keeps holding. A small phrase
    bonus preserves exact-match preference.
    """
    if limit < 1:
        raise ValueError("limit must be positive")
    items = [p for p in passages if p.text.strip()]
    if not items:
        return []
    terms = _tokens(query)
    if not terms:
        return list(items)[:limit]

    docs = [_tokens(p.text) for p in items]
    lengths = [len(d) or 1 for d in docs]
    avgdl = sum(lengths) / len(lengths)
    doc_freq: dict[str, int] = {}
    for doc in docs:
        for term in set(doc):
            doc_freq[term] = doc_freq.get(term, 0) + 1
    total_docs = len(docs)
    query_lower = query.lower().strip()

    raw: list[float] = []
    for item in items:
        tokens = _tokens(item.text)
        freq: dict[str, int] = {}
        for token in tokens:
            freq[token] = freq.get(token, 0) + 1
        dl = len(tokens) or 1
        score = 0.0
        for term in set(terms):
            df = doc_freq.get(term, 0)
            if df == 0:
                continue
            idf = math.log((total_docs - df + 0.5) / (df + 0.5) + 1.0)
            tf = freq.get(term, 0)
            denom = tf + _K1 * (1 - _B + _B * dl / avgdl)
            score += idf * (tf * (_K1 + 1) / denom) if denom else 0.0
        if query_lower and query_lower in item.text.lower():
            score += 0.5
        raw.append(score)

    peak = max(raw) if raw else 0.0
    scored: list[Passage] = []
    for passage, value in zip(items, raw, strict=True):
        normalized = (value / peak) if peak > 0 else 0.0
        scored.append(
            Passage(
                text=passage.text,
                index=passage.index,
                section=passage.section,
                score=min(1.0, max(0.0, normalized)),
            )
        )
    scored.sort(key=lambda item: (item.score or 0.0, -item.index), reverse=True)
    return scored[:limit]
