from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from .models import Document, SearchQuery, SearchResult


class SearchProvider(Protocol):
    """Contract implemented by every search backend."""

    async def search(self, query: SearchQuery) -> Sequence[SearchResult]: ...


class DocumentReader(Protocol):
    """Contract implemented by every document reader."""

    async def read(self, url: str) -> Document: ...


class DocumentStore(Protocol):
    """Persistence boundary; concrete storage stays outside the domain."""

    async def get(self, url: str) -> Document | None: ...

    async def put(self, document: Document) -> None: ...
