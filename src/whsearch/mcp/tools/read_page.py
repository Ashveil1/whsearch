from __future__ import annotations

from whsearch.application import Application
from whsearch.observability import get_logger

_logger = get_logger("mcp.read_page")


async def read_page(app: Application, url: str) -> dict[str, object]:
    document = await app.reader.read(url)
    _logger.debug("read_page tool: url=%r passages=%d", url, len(document.passages))
    return {
        "url": document.url,
        "canonical_url": document.canonical_url,
        "title": document.title,
        "author": document.author,
        "published_at": document.published_at.isoformat() if document.published_at else None,
        "language": document.language,
        "content": document.content,
        "passages": [
            {"index": p.index, "section": p.section, "text": p.text} for p in document.passages
        ],
    }
