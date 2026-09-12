from __future__ import annotations

import re

from whsearch.domain import SearchQuery

_QUESTION_WORDS = frozenset(
    {
        "what",
        "which",
        "who",
        "whom",
        "whose",
        "when",
        "where",
        "why",
        "how",
        "is",
        "are",
        "was",
        "were",
        "do",
        "does",
        "did",
        "can",
        "could",
        "should",
        "would",
        "will",
        "the",
        "a",
        "an",
        "of",
        "in",
        "on",
        "for",
        "to",
        "and",
        "or",
        "vs",
    }
)

_SPLIT = re.compile(r"[?;]+|\s+and\s+|\s+vs\.?\s+", re.IGNORECASE)
_TOKEN = re.compile(r"[\w-]+", re.UNICODE)


def plan_queries(question: str, *, max_queries: int = 4) -> list[SearchQuery]:
    """Decompose a research question into a bounded set of sub-queries.

    Deterministic heuristic: the full question first, then each sub-question
    split on sentence/conjunction boundaries, then a keyword-compressed query.
    Near-duplicates are removed case-insensitively.
    """
    if max_queries < 1:
        raise ValueError("max_queries must be positive")
    cleaned = " ".join(question.split())
    if not cleaned:
        raise ValueError("research question must not be empty")

    candidates: list[str] = []
    seen: set[str] = set()

    def _add(text: str) -> None:
        key = text.lower()
        if len(text) >= 4 and key not in seen:
            seen.add(key)
            candidates.append(text)

    _add(cleaned)
    for part in _SPLIT.split(cleaned):
        _add(part.strip(" ,.:-"))
    _add(_keywords(cleaned))
    return [SearchQuery(text, limit=10) for text in candidates[:max_queries]]


def _keywords(text: str) -> str:
    terms: list[str] = []
    for token in _TOKEN.findall(text.lower()):
        if len(token) > 2 and token not in _QUESTION_WORDS and token not in terms:
            terms.append(token)
    return " ".join(terms)
