from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from whsearch.application import Application
from whsearch.domain import SearchQuery
from whsearch.exceptions import AISearchError
from whsearch.observability import get_logger

_logger = get_logger("mcp.search_and_read")


def _fresh_enough(published_at: object, recency_days: int | None) -> bool:
    """Recency filter: dated pages older than the cutoff are dropped.

    Undated pages are kept (absence of evidence is not evidence of staleness)
    so the filter never blanks the whole result set for lack of metadata.
    """
    if recency_days is None or not isinstance(published_at, datetime):
        return True
    published = published_at
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    cutoff = datetime.now(UTC) - timedelta(days=recency_days)
    return published >= cutoff


async def search_and_read(
    app: Application,
    query: str,
    limit: int = 5,
    *,
    max_chars: int = 8000,
    include_passages: bool = True,
    max_passages: int = 5,
    recency_days: int | None = None,
) -> list[dict[str, object]]:
    """Search the web and read the returned pages with bounded output.

    Content is truncated to `max_chars` so a single call can never blow up
    the MCP response (previously 200KB+). Set `include_passages=False` for
    content-only output, or use `max_chars=0` for metadata-only.
    `recency_days` drops dated pages older than the cutoff (undated kept).
    """
    if max_chars < 0:
        raise ValueError("max_chars must be non-negative")
    if max_passages < 1:
        raise ValueError("max_passages must be positive")
    if recency_days is not None and recency_days < 0:
        raise ValueError("recency_days must be non-negative")
    results = await app.search.search(
        SearchQuery(query, limit=limit, recency_days=recency_days)
    )
    bounded = list(results)[: app.settings.max_pages_per_task]
    semaphore = asyncio.Semaphore(max(1, min(len(bounded) or 1, app.settings.max_pages_per_task)))

    async def _read_one(url: str, title: str, snippet: str) -> dict[str, object] | None:
        item: dict[str, object] = {"title": title, "url": url, "snippet": snippet}
        async with semaphore:
            try:
                document = await app.reader.read(url)
            except AISearchError as exc:
                item["readable"] = False
                item["error"] = type(exc).__name__
                _logger.debug("page unreadable: url=%r error=%s", url, exc)
            except Exception as exc:  # pragma: no cover - defensive: one page never fails the batch
                item["readable"] = False
                item["error"] = type(exc).__name__
                _logger.exception("unexpected read failure: url=%r", url)
            else:
                if not _fresh_enough(document.published_at, recency_days):
                    _logger.debug("page filtered by recency: url=%r", url)
                    return None
                full = document.content or ""
                total_chars = len(full)
                if max_chars == 0:
                    item["content"] = ""
                elif total_chars > max_chars:
                    item["content"] = full[:max_chars]
                else:
                    item["content"] = full
                item["readable"] = True
                item["truncated"] = total_chars > max_chars
                item["total_chars"] = total_chars
                if include_passages:
                    item["passages"] = [
                        {"index": p.index, "section": p.section, "text": p.text[:2000]}
                        for p in document.passages[:max_passages]
                    ]
                    item["passage_count"] = len(document.passages)
                if document.published_at is not None:
                    item["published_at"] = document.published_at.isoformat()
                if document.author:
                    item["author"] = document.author
                if document.language:
                    item["language"] = document.language
        return item

    # gather preserves input order, so output matches search ranking.
    # None entries are recency-filtered pages.
    pages = await asyncio.gather(
        *(_read_one(result.url, result.title, result.snippet) for result in bounded)
    )
    output = [page for page in pages if page is not None]
    _logger.debug(
        "search_and_read completed: query=%r pages=%d readable=%d",
        query,
        len(output),
        sum(1 for item in output if item.get("readable") is True),
    )
    return output
