import asyncio
from collections.abc import Callable

import httpx

from whsearch.domain import Document
from whsearch.reader import ReaderService, RobotsPolicy
from whsearch.reader.video import (
    description_passages,
    extract_video_id,
    is_video_url,
    parse_publish_date,
    parse_watch_page,
)

WATCH_HTML = (
    "<html><head><title>Watch</title></head><body><script>"
    "var ytInitialPlayerResponse = {"
    '"videoDetails":{"videoId":"abc123","title":"Cute Cats",'
    '"author":"Cat TV","channelId":"UC1",'
    '"shortDescription":"Cats playing.\\n00:00 Intro\\nPlay time here.\\n10:24 Outro",'
    '"lengthSeconds":"624","viewCount":"1000000"},'
    '"microformat":{"playerMicroformatRenderer":{"publishDate":"2026-09-01"}}'
    "};</script></body></html>"
)


def test_is_video_url() -> None:
    assert is_video_url("https://www.youtube.com/watch?v=abc123") is True
    assert is_video_url("https://youtu.be/abc123") is True
    assert is_video_url("https://www.youtube.com/shorts/abc123") is True
    assert is_video_url("https://www.youtube.com/results?search_query=x") is False
    assert is_video_url("https://example.com/watch?v=x") is False


def test_extract_video_id() -> None:
    assert extract_video_id("https://www.youtube.com/watch?v=abc123") == "abc123"
    assert extract_video_id("https://youtu.be/abc123") == "abc123"
    assert extract_video_id("https://www.youtube.com/shorts/abc123") == "abc123"
    assert extract_video_id("https://example.com/") is None


def test_parse_watch_page_metadata() -> None:
    meta = parse_watch_page(WATCH_HTML)
    assert meta["video_id"] == "abc123"
    assert meta["title"] == "Cute Cats"
    assert meta["author"] == "Cat TV"
    assert meta["publish_date"] == "2026-09-01"
    assert parse_publish_date(meta["publish_date"]) is not None


def test_parse_watch_page_missing() -> None:
    assert parse_watch_page("<html></html>") == {}


def test_description_passages_use_chapters_as_sections() -> None:
    sections = description_passages("Cats playing.\n00:00 Intro\nPlay time here.\n10:24 Outro")
    # Trailing chapter without following text carries no claim and is dropped.
    assert sections[0] == (None, "Cats playing.")
    assert sections[1][0] == "00:00 Intro"
    assert "Play time here." in sections[1][1]
    assert len(sections) == 2


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_reader_builds_video_document_from_watch_page() -> None:
    def _handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nAllow: /")
        return httpx.Response(200, headers={"content-type": "text/html"}, text=WATCH_HTML)

    async def _run() -> Document:
        async with _client(_handler) as client:
            service = ReaderService(client, RobotsPolicy(client, "t"))
            return await service.read("https://www.youtube.com/watch?v=abc123")

    document = asyncio.run(_run())
    assert document.title == "Cute Cats"
    assert document.author == "Cat TV"
    assert document.metadata["video_id"] == "abc123"
    assert any(p.section == "00:00 Intro" for p in document.passages)
