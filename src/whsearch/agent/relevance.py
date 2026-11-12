"""Conservative, absolute lexical gate for extractive research answers.

This is a noise filter, not semantic relevance or a guarantee of answerability.
It intentionally may discard relevant paraphrases; scores normalized against a
candidate set must not be used as confidence estimates.
"""

from __future__ import annotations

import math
import re
import unicodedata

from whsearch.research.planner import _keywords, _strip_thai_affixes
from whsearch.search.query import simplify_query

_LATIN_OR_NUMBER = re.compile(r"[a-z0-9]+", re.ASCII)
_THAI_RUN = re.compile(r"[\u0e00-\u0e7f]+")


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def _grams(text: str, size: int) -> set[str]:
    return {text[i : i + size] for i in range(len(text) - size + 1)}


def has_answer_overlap(question: str, text: str) -> bool:
    """Require meaningful absolute query overlap before presenting a finding.

    For multi-term Latin queries, at least two and at least half the distinct
    content terms must be present. For Thai-only questions, require a shared
    six-character sequence plus at least 20% of query trigrams, or a full
    four- to five-character single topic. Thai is not segmented here, so this
    deliberately errs toward abstention and can still match common phrases.
    Mixed-script queries require their Latin/number anchors; numeric-only
    anchors additionally require Thai overlap.
    """
    query = _normalize(_keywords(simplify_query(question)))
    candidate = _normalize(text)
    terms = {term for term in _LATIN_OR_NUMBER.findall(query) if len(term) >= 3}
    if terms:
        present = terms & set(_LATIN_OR_NUMBER.findall(candidate))
        required = 1 if len(terms) == 1 else max(2, math.ceil(len(terms) / 2))
        if len(present) < required:
            return False
        # In a Thai query, a year or other number alone is not a topic.
        if any(any(char.isalpha() for char in term) for term in terms):
            return True
        if not _THAI_RUN.search(query):
            return True

    thai_query = [run for run in _THAI_RUN.findall(query) if _strip_thai_affixes(run)]
    thai_candidate = _THAI_RUN.findall(candidate)
    # A short single Thai topic has no six-character n-gram. Permit its exact
    # sequence, with the same caveat that Thai has no explicit word boundaries.
    if not terms and len(thai_query) == 1 and 4 <= len(thai_query[0]) < 6:
        return any(thai_query[0] in run for run in thai_candidate)
    query_trigrams = set().union(*(_grams(run, 3) for run in thai_query))
    candidate_trigrams = set().union(*(_grams(run, 3) for run in thai_candidate))
    query_six = set().union(*(_grams(run, 6) for run in thai_query))
    candidate_six = set().union(*(_grams(run, 6) for run in thai_candidate))
    return bool(
        query_six & candidate_six
        and query_trigrams
        and len(query_trigrams & candidate_trigrams) / len(query_trigrams) >= 0.2
    )
