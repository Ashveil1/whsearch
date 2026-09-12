from __future__ import annotations

import re
import unicodedata

_SITE = re.compile(r"\bsite:([^\s\"']+)", re.IGNORECASE)
_EXCLUDE = re.compile(r"(?:^|\s)-([\wก-๙][\wก-๙\-.]*)", re.UNICODE)
_THAI = re.compile(r"[ก-๙]")
_WS = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """NFKC normalize + collapse whitespace (stdlib only, no deps)."""
    return _WS.sub(" ", unicodedata.normalize("NFKC", text)).strip()


def extract_site_domains(text: str) -> tuple[list[str], str]:
    """Split `site:` operators out of raw text.

    Returns (domains, remaining_text). Providers that understand `site:`
    natively still get a working query because the operator is kept for
    them implicitly via the domains allowlist filtering locally.
    """
    domains = [m.group(1).strip().lower().strip(",;") for m in _SITE.finditer(text)]
    domains = [d for d in domains if d]
    remaining = _SITE.sub(" ", text)
    return domains, normalize_text(remaining)


def extract_excluded_terms(text: str) -> list[str]:
    return [m.group(1).lower() for m in _EXCLUDE.finditer(text)]


def simplify_query(text: str) -> str:
    """Fallback query when the first attempt returns nothing.

    Strips operators/quotes so keyless HTML providers get plain keywords.
    """
    cleaned = _SITE.sub(" ", text)
    cleaned = re.sub(r"['\"]", " ", cleaned)
    cleaned = re.sub(r"(?:^|\s)-[\S]+", " ", cleaned)
    cleaned = re.sub(r"\b(and|or|not)\b", " ", cleaned, flags=re.IGNORECASE)
    return normalize_text(cleaned)


def is_thai_query(text: str) -> bool:
    return _THAI.search(text) is not None


def kl_for_query(text: str) -> str:
    """DuckDuckGo region: Thailand for Thai queries, world otherwise."""
    return "th-th" if is_thai_query(text) else "wt-wt"


def df_for_recency(recency_days: int | None) -> str | None:
    """Map recency hint to DuckDuckGo `df` (day/week/month). Ignored if unknown."""
    if recency_days is None:
        return None
    if recency_days <= 1:
        return "d"
    if recency_days <= 7:
        return "w"
    if recency_days <= 31:
        return "m"
    return "y"


_NEWS_HINTS = frozenset(
    {
        "news", "latest", "breaking", "today", "headline", "headlines",
        "ข่าว", "ล่าสุด", "ด่วน", "วันนี้",
    }
)

_ACADEMIC_HINTS = frozenset(
    {
        "paper", "papers", "arxiv", "doi", "journal", "study", "studies",
        "research", "dataset", "preprint", "peer-reviewed",
        "งานวิจัย", "เปเปอร์", "วารสาร",
    }
)

_VIDEO_HINTS = frozenset(
    {
        "youtube", "youtu.be", "video", "videos", "clip", "clips",
        "vlog", "livestream", "trailer", "mv", "ep.",
        "วิดีโอ", "วีดีโอ", "คลิป", "ยูทูบ", "ยูทูป", "ดูย้อนหลัง",
    }
)

_VIDEO_DOMAINS = frozenset({"youtube.com", "youtu.be"})


def _contains_hint(text: str, hints: frozenset[str]) -> bool:
    lowered = text.lower()
    return any(h in lowered for h in hints)


def wants_news(text: str, recency_days: int | None) -> bool:
    if recency_days is not None:
        return True
    return _contains_hint(text, _NEWS_HINTS)


def wants_academic(text: str) -> bool:
    return _contains_hint(text, _ACADEMIC_HINTS)


def wants_video(text: str, domains: tuple[str, ...] = ()) -> bool:
    if any(
        d.lower().removeprefix("www.").strip() in _VIDEO_DOMAINS
        or d.lower().strip().endswith(".youtube.com")
        for d in domains
        if d.strip()
    ):
        return True
    return _contains_hint(text, _VIDEO_HINTS)
