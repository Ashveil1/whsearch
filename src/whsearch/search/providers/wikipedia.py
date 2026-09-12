from __future__ import annotations

import re
from urllib.parse import quote

import httpx

from whsearch.domain import SearchQuery, SearchResult, SourceType
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger

_logger = get_logger("search.wikipedia")

_TAG = re.compile(r"<[^>]+>")


class WikipediaProvider:
    """Keyless reference search via the Wikipedia API; complements web discovery."""

    endpoint = "https://en.wikipedia.org/w/api.php"

    def __init__(self, client: httpx.AsyncClient, *, language: str = "en") -> None:
        if not language.strip():
            raise ValueError("language must not be empty")
        self._client = client
        self._language = language.strip()
        self._endpoint = f"https://{self._language}.wikipedia.org/w/api.php"

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query.text,
            "srlimit": str(min(query.limit, 50)),
            "format": "json",
        }
        try:
            response = await self._client.get(self._endpoint, params=params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            _logger.warning("Wikipedia request failed: %s", exc)
            raise ProviderError(f"Wikipedia request failed: {exc}") from exc

        results: list[SearchResult] = []
        try:
            entries = payload["query"]["search"]
        except (KeyError, TypeError) as exc:
            _logger.warning("Wikipedia returned an unexpected payload")
            raise ProviderError("Wikipedia returned an unexpected payload") from exc
        for entry in entries:
            title = str(entry.get("title", "")).strip()
            if not title:
                continue
            url = f"https://{self._language}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
            snippet = _TAG.sub("", str(entry.get("snippet", ""))).strip()
            results.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source_type=SourceType.DOCUMENTATION,
                )
            )
            if len(results) >= query.limit:
                break
        _logger.debug("Wikipedia search: query=%r returned=%d", query.text, len(results))
        return results
