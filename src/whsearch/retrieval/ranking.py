from __future__ import annotations

import re
from collections.abc import Iterable

from whsearch.domain import Passage

_TOKEN = re.compile(r"[\w-]+", re.UNICODE)


def rank_passages(query: str, passages: Iterable[Passage], *, limit: int = 20) -> list[Passage]:
    """Rank passages with a deterministic lightweight lexical scorer."""
    if limit < 1:
        raise ValueError("limit must be positive")
    terms = set(_TOKEN.findall(query.lower()))
    if not terms:
        return list(passages)[:limit]

    scored: list[Passage] = []
    for passage in passages:
        tokens = _TOKEN.findall(passage.text.lower())
        if not tokens:
            continue
        token_set = set(tokens)
        overlap = len(terms & token_set) / len(terms)
        phrase_bonus = 0.2 if query.lower().strip() in passage.text.lower() else 0.0
        scored.append(
            Passage(
                text=passage.text,
                index=passage.index,
                section=passage.section,
                score=min(1.0, overlap + phrase_bonus),
            )
        )
    scored.sort(key=lambda item: (item.score or 0.0, -item.index), reverse=True)
    return scored[:limit]
