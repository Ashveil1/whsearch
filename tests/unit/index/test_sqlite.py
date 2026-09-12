import asyncio
from datetime import UTC, datetime

import pytest

from whsearch.domain import Document, Passage
from whsearch.index import SqliteDocumentStore


def _doc(url: str, words: str) -> Document:
    return Document(
        url=url,
        title=f"Title {url}",
        content=f"Content body for {url} with {words} and enough length to be valid.",
        passages=(Passage(text=f"Passage about {words} in {url}", index=0),),
        author="Author",
        published_at=datetime(2024, 1, 2, tzinfo=UTC),
        language="en",
        metadata={"k": "v"},
    )


def test_put_get_roundtrip() -> None:
    async def _main() -> None:
        store = SqliteDocumentStore()
        try:
            await store.put(_doc("https://example.com/a", "quokka"))
            document = await store.get("https://example.com/a")
        finally:
            store.close()
        assert document is not None
        assert document.title == "Title https://example.com/a"
        assert len(document.passages) == 1
        assert document.author == "Author"
        assert document.published_at == datetime(2024, 1, 2, tzinfo=UTC)
        assert document.metadata == {"k": "v"}

    asyncio.run(_main())


def test_get_miss_returns_none() -> None:
    async def _main() -> None:
        store = SqliteDocumentStore()
        try:
            assert await store.get("https://example.com/missing") is None
        finally:
            store.close()

    asyncio.run(_main())


def test_evicts_oldest_beyond_max_entries() -> None:
    async def _main() -> None:
        store = SqliteDocumentStore(max_entries=2)
        try:
            await store.put(_doc("https://example.com/1", "one"))
            await store.put(_doc("https://example.com/2", "two"))
            await store.put(_doc("https://example.com/3", "three"))
            assert await store.get("https://example.com/1") is None
            assert await store.get("https://example.com/2") is not None
            assert await store.get("https://example.com/3") is not None
        finally:
            store.close()

    asyncio.run(_main())


def test_search_passages_finds_cached_text() -> None:
    store = SqliteDocumentStore()
    try:
        asyncio.run(store.put(_doc("https://example.com/a", "quokka")))
        hits = store.search_passages("quokka")
    finally:
        store.close()
    assert [(url, idx) for url, idx, _ in hits] == [("https://example.com/a", 0)]


def test_search_passages_rejects_empty_query_and_bad_limit() -> None:
    store = SqliteDocumentStore()
    try:
        assert store.search_passages("   ") == []
        with pytest.raises(ValueError, match="positive"):
            store.search_passages("x", limit=0)
    finally:
        store.close()


def test_rejects_non_positive_max_entries() -> None:
    with pytest.raises(ValueError, match="positive"):
        SqliteDocumentStore(max_entries=0)
