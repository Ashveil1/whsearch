from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

from whsearch.domain import Document, Passage
from whsearch.observability import get_logger

_logger = get_logger("index.sqlite")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    url TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    author TEXT,
    published_at TEXT,
    language TEXT,
    canonical_url TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS passages (
    doc_url TEXT NOT NULL REFERENCES documents(url) ON DELETE CASCADE,
    idx INTEGER NOT NULL,
    section TEXT,
    text TEXT NOT NULL,
    PRIMARY KEY (doc_url, idx)
);
"""


class SqliteDocumentStore:
    """Bounded SQLite cache of documents with FTS5 passage search.

    Evicts oldest documents first so disk usage stays bounded.
    Falls back to LIKE search when FTS5 is unavailable.
    """

    def __init__(self, path: str | Path = ":memory:", *, max_entries: int = 5000) -> None:
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._path = str(path)
        self._max_entries = max_entries
        self._conn = sqlite3.connect(self._path)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._fts = self._init_fts()

    def _init_fts(self) -> bool:
        try:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS passages_fts USING fts5("
                "text, content='passages', content_rowid='rowid')"
            )
            return True
        except sqlite3.OperationalError:
            _logger.debug("FTS5 unavailable; passage search falls back to LIKE")
            return False

    async def get(self, url: str) -> Document | None:
        row = self._conn.execute(
            "SELECT url, title, content, author, published_at, language,"
            " canonical_url, metadata_json FROM documents WHERE url = ?",
            (url,),
        ).fetchone()
        if row is None:
            return None
        passage_rows = self._conn.execute(
            "SELECT idx, section, text FROM passages WHERE doc_url = ? ORDER BY idx", (url,)
        ).fetchall()
        return Document(
            url=row[0],
            title=row[1],
            content=row[2],
            passages=tuple(Passage(text=t, index=i, section=s) for i, s, t in passage_rows),
            author=row[3],
            published_at=datetime.fromisoformat(row[4]) if row[4] else None,
            language=row[5],
            canonical_url=row[6],
            metadata=json.loads(row[7]),
        )

    async def put(self, document: Document) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO documents"
                " (url, title, content, author, published_at, language,"
                " canonical_url, metadata_json)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    document.url,
                    document.title,
                    document.content,
                    document.author,
                    document.published_at.isoformat() if document.published_at else None,
                    document.language,
                    document.canonical_url,
                    json.dumps(document.metadata),
                ),
            )
            self._conn.execute("DELETE FROM passages WHERE doc_url = ?", (document.url,))
            if self._fts:
                self._conn.execute(
                    "DELETE FROM passages_fts WHERE rowid IN"
                    " (SELECT rowid FROM passages WHERE doc_url = ?)",
                    (document.url,),
                )
            for passage in document.passages:
                rowid = self._conn.execute(
                    "INSERT INTO passages (doc_url, idx, section, text) VALUES (?, ?, ?, ?)",
                    (document.url, passage.index, passage.section, passage.text),
                ).lastrowid
                if self._fts:
                    self._conn.execute(
                        "INSERT INTO passages_fts (rowid, text) VALUES (?, ?)",
                        (rowid, passage.text),
                    )
            self._evict()

    def search_passages(self, query: str, *, limit: int = 20) -> list[tuple[str, int, str]]:
        """Full-text search over cached passages; returns (url, index, text)."""
        if not query.strip():
            return []
        if limit < 1:
            raise ValueError("limit must be positive")
        if self._fts:
            try:
                rows = self._conn.execute(
                    "SELECT p.doc_url, p.idx, p.text FROM passages_fts"
                    " JOIN passages p ON p.rowid = passages_fts.rowid"
                    " WHERE passages_fts MATCH ? LIMIT ?",
                    (query, limit),
                ).fetchall()
            except sqlite3.OperationalError:
                _logger.debug("FTS query failed; falling back to LIKE")
                rows = self._like(query, limit)
        else:
            rows = self._like(query, limit)
        return [(row[0], row[1], row[2]) for row in rows]

    def _like(self, query: str, limit: int) -> list[Any]:
        return self._conn.execute(
            "SELECT doc_url, idx, text FROM passages WHERE text LIKE ? LIMIT ?",
            (f"%{query}%", limit),
        ).fetchall()

    def _evict(self) -> None:
        count = self._conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        overflow = count - self._max_entries
        if overflow <= 0:
            return
        victims: Sequence[str] = [
            row[0]
            for row in self._conn.execute(
                "SELECT url FROM documents ORDER BY rowid ASC LIMIT ?", (overflow,)
            ).fetchall()
        ]
        for url in victims:
            if self._fts:
                self._conn.execute(
                    "DELETE FROM passages_fts WHERE rowid IN"
                    " (SELECT rowid FROM passages WHERE doc_url = ?)",
                    (url,),
                )
            self._conn.execute("DELETE FROM passages WHERE doc_url = ?", (url,))
            self._conn.execute("DELETE FROM documents WHERE url = ?", (url,))
        _logger.debug("evicted %d documents from local index", len(victims))

    def close(self) -> None:
        self._conn.close()
