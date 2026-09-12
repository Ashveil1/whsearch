from __future__ import annotations

import httpx

from whsearch.domain import SearchQuery, SearchResult, SourceType
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger

_logger = get_logger("search.openalex")

_ENDPOINT = "https://api.openalex.org/works"


class OpenAlexProvider:
    """Keyless academic search via OpenAlex (no key, generous free quota)."""

    vertical = "academic"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        params = {
            "search": query.text,
            "per-page": str(min(max(query.limit, 1), 25)),
        }
        try:
            response = await self._client.get(
                _ENDPOINT,
                params=params,
                headers={"User-Agent": "WHSearch/0.1 (mailto:whsearch@localhost)"},
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            _logger.warning("OpenAlex request failed: %s", exc)
            raise ProviderError(f"OpenAlex request failed: {exc}") from exc

        items = payload.get("results", []) if isinstance(payload, dict) else []
        results: list[SearchResult] = []
        for entry in items:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or entry.get("display_name") or "").strip()
            if not title:
                continue
            doi = str(entry.get("doi") or "").strip()
            work_id = str(entry.get("id") or "").strip()
            url = doi if doi.startswith("http") else work_id
            if not url.startswith(("http://", "https://")):
                continue
            location = entry.get("primary_location") or {}
            source = (location.get("source") or {}).get("display_name", "") if isinstance(
                location, dict
            ) else ""
            date = str(entry.get("publication_date", ""))
            cited = entry.get("cited_by_count", 0)
            abstract = _reconstruct_abstract(entry.get("abstract_inverted_index"))
            parts = [p for p in [source, date, f"cited {cited}x" if cited else ""] if p]
            snippet = title
            if parts:
                snippet = f"{title} — {', '.join(parts)}"
            if abstract:
                snippet = f"{snippet}. {abstract}"[:500]
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet[:500],
                    source_type=SourceType.ACADEMIC,
                    metadata={"publication_date": date, "source": source} if date else {},
                )
            )
            if len(results) >= query.limit:
                break
        _logger.debug("OpenAlex search: query=%r returned=%d", query.text, len(results))
        return results


def _reconstruct_abstract(index: object, *, max_words: int = 40) -> str:
    if not isinstance(index, dict) or not index:
        return ""
    try:
        positions: list[tuple[int, str]] = []
        for word, pos_list in index.items():
            if not isinstance(pos_list, list):
                continue
            for pos in pos_list:
                if isinstance(pos, int):
                    positions.append((pos, str(word)))
        positions.sort()
        words = [w for _, w in positions[:max_words]]
        return " ".join(words)
    except (AttributeError, TypeError):
        return ""
