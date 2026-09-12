from __future__ import annotations

from collections.abc import Iterable
from hashlib import sha256
from urllib.parse import parse_qsl, urldefrag, urlencode, urlsplit, urlunsplit

from whsearch.domain import SearchResult


def normalize_url(url: str) -> str:
    parts = urlsplit(urldefrag(url)[0])
    query = urlencode(sorted(parse_qsl(parts.query, keep_blank_values=True)), doseq=True)
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", query, "")
    )


def deduplicate_results(results: Iterable[SearchResult]) -> list[SearchResult]:
    seen: set[str] = set()
    output: list[SearchResult] = []
    for result in results:
        key = normalize_url(result.url)
        if key in seen:
            continue
        seen.add(key)
        output.append(result)
    return output


def content_hash(text: str) -> str:
    return sha256(" ".join(text.split()).encode("utf-8")).hexdigest()
