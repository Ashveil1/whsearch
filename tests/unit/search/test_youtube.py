import asyncio
import json

import httpx
import pytest

from whsearch.domain import SearchQuery, SearchResult
from whsearch.exceptions import ProviderError
from whsearch.search.providers.youtube import YouTubeProvider, parse_search_results

SEARCH_HTML = (
    "<html><body><script>var ytInitialData = "
    + json.dumps(
        {
            "contents": {
                "twoColumnSearchResultsRenderer": {
                    "primaryContents": {
                        "sectionListRenderer": {
                            "contents": [
                                {
                                    "itemSectionRenderer": {
                                        "contents": [
                                            {
                                                "videoRenderer": {
                                                    "videoId": "abc123",
                                                    "title": {"runs": [{"text": "Cute Cats"}]},
                                                    "ownerText": {"runs": [{"text": "Cat TV"}]},
                                                    "publishedTimeText": {
                                                "simpleText": "2 days ago"
                                            },
                                                    "lengthText": {"simpleText": "10:24"},
                                                    "viewCountText": {"simpleText": "1M views"},
                                                    "detailedMetadataSnippets": [
                                                        {
                                                            "snippetText": {
                                                                "runs": [
                                                                {
                                                                    "text": "Cats playing daily."
                                                                }
                                                            ]
                                                            }
                                                        }
                                                    ],
                                                }
                                            },
                                            {"channelRenderer": {"channelId": "UC1"}},
                                            {
                                                "videoRenderer": {
                                                    "videoId": "def456",
                                                    "title": {"runs": [{"text": "Dogs"}]},
                                                    "longBylineText": {
                                                "runs": [{"text": "Dog TV"}]
                                            },
                                                }
                                            },
                                            {
                                                "videoRenderer": {
                                                    "title": {"runs": [{"text": "No ID"}]}
                                                }
                                            },
                                        ]
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        }
    )
    + ";</script></body></html>"
)


def test_parse_search_results_extracts_videos_only() -> None:
    entries = parse_search_results(SEARCH_HTML)
    assert [e["video_id"] for e in entries] == ["abc123", "def456"]
    assert entries[0]["url"] == "https://www.youtube.com/watch?v=abc123"
    assert entries[0]["channel"] == "Cat TV"
    assert entries[0]["snippet"] == "Cats playing daily."
    assert entries[0]["duration"] == "10:24"
    assert entries[1]["snippet"] == "Dogs — Dog TV"


def test_parse_search_results_missing_payload() -> None:
    assert parse_search_results("<html></html>") == []
    assert parse_search_results("var ytInitialData = {oops;</script>") == []


def test_youtube_provider_returns_video_results() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        assert "youtube.com" in request.url.host
        return httpx.Response(200, text=SEARCH_HTML)

    async def _run() -> list[SearchResult]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
            return await YouTubeProvider(client).search(SearchQuery("cats", limit=5))

    results = asyncio.run(_run())
    assert len(results) == 2
    assert results[0].source_type.value == "video"
    assert results[0].metadata["video_id"] == "abc123"


def test_youtube_provider_http_error() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    async def _run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as client:
            with pytest.raises(ProviderError):
                await YouTubeProvider(client).search(SearchQuery("x", limit=2))

    asyncio.run(_run())
