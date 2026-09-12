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
_THAI = re.compile(r"[ก-๙]")

# Thai function words stripped from keyword queries (longest first at use).
# Thai has no word spaces, so these are removed as affixes of whitespace
# tokens (e.g. "มีความสามารถอะไรบ้าง" -> "ความสามารถ"), never from inside
# content words. Pure function-word tokens are dropped entirely.
_THAI_STOPWORDS = (
    "อะไรบ้าง",
    "คืออะไร",
    "เมื่อไหร่",
    "เท่าไหร่",
    "หรือไม่",
    "อย่างไร",
    "อะไร",
    "เมื่อไร",
    "ทำไม",
    "ยังไง",
    "เท่าไร",
    "ที่ไหน",
    "บ้าง",
    "คือ",
    "เป็น",
    "อยู่ใน",
    "ของ",
    "และ",
    "กับ",
    "ให้",
    "ได้",
    "นี้",
    "นั้น",
    "หรือ",
    "ไหม",
    "ไหน",
    "ใคร",
    "อยู่",
    "แล้ว",
    "หน่อย",
    "ครับ",
    "ค่ะ",
    "ไว้",
    "กัน",
    "มาก",
    "ใน",
    "ที่",
    "มี",
)


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
    lowered = text.lower()
    if _THAI.search(lowered):
        # Thai combining marks (sara etc.) are not \w, so regex tokenizing
        # would shred words ("คืออะไร" -> "ค", "ออะไร"). Thai uses spaces
        # between phrases, so whitespace chunks keep words intact.
        chunks: list[str] = []
        for raw in lowered.split():
            chunk = raw.strip("?;.,:!\"'()[]{}")
            if len(chunk) > 2 and chunk not in _QUESTION_WORDS and chunk not in chunks:
                chunks.append(chunk)
        return _thai_keywords(" ".join(chunks))
    terms: list[str] = []
    for token in _TOKEN.findall(lowered):
        if len(token) > 2 and token not in _QUESTION_WORDS and token not in terms:
            terms.append(token)
    return " ".join(terms)


def _thai_keywords(text: str) -> str:
    """Reduce Thai keyword queries to content words.

    >>> _thai_keywords("zhypix คืออะไร มีความสามารถอะไรบ้าง")
    'zhypix ความสามารถ'
    """
    kept: list[str] = []
    for token in text.split():
        stripped = _strip_thai_affixes(token)
        if not stripped:
            continue
        # Drop tiny leftover fragments, but never the last surviving term:
        # a rare entity token alone is still a good query.
        if _THAI.search(stripped) and len(stripped) < 3:
            continue
        if stripped not in kept:
            kept.append(stripped)
    if not kept:
        # Everything was a function word: fall back to the longest raw token
        # so the query never becomes empty.
        raw = [t for t in text.split() if len(t) > 2]
        return max(raw, key=len) if raw else text
    return " ".join(kept)


def _strip_thai_affixes(token: str) -> str:
    current = token
    changed = True
    while changed and current:
        changed = False
        for stop in _THAI_STOPWORDS:
            if current == stop:
                return ""
            if current.startswith(stop) and len(current) - len(stop) >= 3:
                current = current[len(stop) :]
                changed = True
                break
            if current.endswith(stop) and len(current) - len(stop) >= 3:
                current = current[: -len(stop)]
                changed = True
                break
    return current
