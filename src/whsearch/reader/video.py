from __future__ import annotations

import json
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

_PLAYER_RESPONSE = re.compile(r"var ytInitialPlayerResponse = (\{.*?\});</script>", re.DOTALL)
_CHAPTER = re.compile(r"^\(?(\d{1,2}:\d{2}(?::\d{2})?)\)?\s*[-–—:]?\s*(.+)$")
_VIDEO_HOSTS = {"www.youtube.com", "youtube.com", "m.youtube.com", "youtu.be"}


def is_video_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if parsed.netloc.lower() not in _VIDEO_HOSTS:
        return False
    if parsed.netloc.lower() == "youtu.be":
        return bool(parsed.path.strip("/"))
    path = parsed.path
    if path.startswith(("/watch", "/shorts/", "/live/", "/embed/")):
        return True
    return path == "/watch" or "v=" in parsed.query


def extract_video_id(url: str) -> str | None:
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    if parsed.netloc.lower() == "youtu.be":
        return parsed.path.strip("/").split("/")[0] or None
    for prefix in ("/shorts/", "/live/", "/embed/"):
        if parsed.path.startswith(prefix):
            return parsed.path[len(prefix):].split("/")[0] or None
    return parse_qs(parsed.query).get("v", [None])[0]


def parse_watch_page(html: str) -> dict[str, str]:
    """Extract video metadata + description from a watch page (no key).

    Returns {} when the player payload is absent (consent wall, removal).
    """
    match = _PLAYER_RESPONSE.search(html)
    if not match:
        return {}
    try:
        payload = json.loads(match.group(1))
    except ValueError:
        return {}
    details = payload.get("videoDetails")
    if not isinstance(details, dict):
        return {}
    microformat = payload.get("microformat", {})
    renderer = microformat.get("playerMicroformatRenderer", {}) if isinstance(
        microformat, dict
    ) else {}
    return {
        "video_id": str(details.get("videoId", "")),
        "title": str(details.get("title", "")),
        "author": str(details.get("author", "")),
        "channel_id": str(details.get("channelId", "")),
        "description": str(details.get("shortDescription", "")),
        "length_seconds": str(details.get("lengthSeconds", "")),
        "views": str(details.get("viewCount", "")),
        "publish_date": str(renderer.get("publishDate", "") or renderer.get("uploadDate", "")),
    }


def description_passages(description: str) -> list[tuple[str | None, str]]:
    """Split a description into (section, text) with chapters as sections.

    Lines like `00:00 Intro` become the section for following text, so a
    multimodal caller knows *where* in the video to look.
    """
    lines = [line.strip() for line in description.splitlines()]
    lines = [line for line in lines if line]
    sections: list[tuple[str | None, str]] = []
    current_section: str | None = None
    buffer: list[str] = []

    def _flush() -> None:
        if buffer:
            sections.append((current_section, " ".join(buffer)))
            buffer.clear()

    for line in lines:
        chapter = _CHAPTER.match(line)
        if chapter and len(chapter.group(2).strip()) >= 2:
            _flush()
            current_section = f"{chapter.group(1)} {chapter.group(2).strip()}"
            continue
        buffer.append(line)
        if sum(len(part) for part in buffer) >= 800:
            _flush()
    _flush()
    return sections


def parse_publish_date(value: str) -> datetime | None:
    if not value or not value.strip():
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
