from __future__ import annotations

import json
import re

import httpx

from whsearch.domain import SearchQuery, SearchResult, SourceType
from whsearch.exceptions import ProviderError
from whsearch.observability import get_logger

_logger = get_logger("search.youtube")

_ENDPOINT = "https://www.youtube.com/results"
_INITIAL_DATA = re.compile(r"var ytInitialData = (\{.*?\});</script>", re.DOTALL)


class YouTubeProvider:
    """Keyless video search via YouTube's own search page (no key, no proxy).

    Parses the server-rendered `ytInitialData` payload instead of relying
    on third-party Invidious/Piped instances. Used only for video-intent
    queries (see `wants_video`).
    """

    vertical = "video"

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

    async def search(self, query: SearchQuery) -> list[SearchResult]:
        try:
            response = await self._client.get(
                _ENDPOINT,
                params={"search_query": query.text},
                headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)"},
            )
            response.raise_for_status()
            items = parse_search_results(response.text)
        except (httpx.HTTPError, ValueError) as exc:
            _logger.warning("YouTube request failed: %s", exc)
            raise ProviderError(f"YouTube request failed: {exc}") from exc

        results: list[SearchResult] = []
        for entry in items:
            results.append(
                SearchResult(
                    title=entry["title"],
                    url=entry["url"],
                    snippet=entry["snippet"][:500],
                    source_type=SourceType.VIDEO,
                    metadata={
                        "video_id": entry["video_id"],
                        "channel": entry["channel"],
                        "published": entry["published"],
                        "duration": entry["duration"],
                        "views": entry["views"],
                    },
                )
            )
            if len(results) >= query.limit:
                break
        _logger.debug("YouTube search: query=%r returned=%d", query.text, len(results))
        return results


def parse_search_results(html: str) -> list[dict[str, str]]:
    """Extract video entries from a YouTube search results page."""
    match = _INITIAL_DATA.search(html)
    if not match:
        return []
    try:
        payload = json.loads(match.group(1))
    except ValueError:
        return []
    try:
        sections = payload["contents"]["twoColumnSearchResultsRenderer"]["primaryContents"][
            "sectionListRenderer"
        ]["contents"]
    except (KeyError, TypeError):
        return []
    entries: list[dict[str, str]] = []
    for section in sections:
        if not isinstance(section, dict):
            continue
        for item in section.get("itemSectionRenderer", {}).get("contents", []):
            video = item.get("videoRenderer") if isinstance(item, dict) else None
            if not isinstance(video, dict):
                continue
            video_id = str(video.get("videoId", ""))
            if not video_id:
                continue
            title = _runs_text(video.get("title", {}))
            channel = _runs_text(
                video.get("ownerText", {}) or video.get("longBylineText", {})
            )
            description = _description_snippet(video)
            snippet = description or (f"{title} — {channel}" if channel else title)
            entries.append(
                {
                    "video_id": video_id,
                    "title": title or video_id,
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "channel": channel,
                    "snippet": snippet,
                    "published": _simple_text(video.get("publishedTimeText", {})),
                    "duration": _simple_text(video.get("lengthText", {}) or {}),
                    "views": _simple_text(video.get("viewCountText", {})),
                }
            )
    return entries


def _runs_text(node: object) -> str:
    if not isinstance(node, dict):
        return ""
    runs = node.get("runs")
    if not isinstance(runs, list):
        return ""
    return " ".join(str(run.get("text", "")) for run in runs if isinstance(run, dict)).strip()


def _simple_text(node: object) -> str:
    if isinstance(node, dict):
        text = node.get("simpleText")
        if isinstance(text, str):
            return text.strip()
    return ""


def _description_snippet(video: dict[str, object]) -> str:
    snippets = video.get("detailedMetadataSnippets")
    if not isinstance(snippets, list):
        return ""
    parts: list[str] = []
    for snippet in snippets:
        if not isinstance(snippet, dict):
            continue
        text = _runs_text(snippet.get("snippetText", {}))
        if text:
            parts.append(text)
    return " ".join(parts).strip()
