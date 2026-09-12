from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from urllib.parse import urlparse


class SourceType(StrEnum):
    WEB = "web"
    NEWS = "news"
    ACADEMIC = "academic"
    DOCUMENTATION = "documentation"
    VIDEO = "video"
    LOCAL = "local"


class ClaimStatus(StrEnum):
    SUPPORTED = "supported"
    CONTESTED = "contested"
    UNVERIFIED = "unverified"


class StoppingReason(StrEnum):
    SUFFICIENT_EVIDENCE = "sufficient_evidence"
    SATURATED = "saturated"
    BUDGET_EXHAUSTED = "budget_exhausted"
    MAX_ROUNDS = "max_rounds"


@dataclass(frozen=True, slots=True)
class SearchQuery:
    text: str
    limit: int = 10
    recency_days: int | None = None
    domains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        text = self.text.strip()
        if not text:
            raise ValueError("search query must not be empty")
        if not 1 <= self.limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if self.recency_days is not None and self.recency_days < 0:
            raise ValueError("recency_days must be non-negative")
        object.__setattr__(self, "text", text)


@dataclass(frozen=True, slots=True)
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source_type: SourceType = SourceType.WEB
    score: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("search result URL must be an absolute HTTP(S) URL")
        if self.score is not None and not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class Passage:
    text: str
    index: int
    section: str | None = None
    score: float | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("passage text must not be empty")
        if self.index < 0:
            raise ValueError("passage index must be non-negative")


@dataclass(frozen=True, slots=True)
class Document:
    url: str
    title: str
    content: str
    passages: tuple[Passage, ...] = ()
    author: str | None = None
    published_at: datetime | None = None
    language: str | None = None
    canonical_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("document URL must be an absolute HTTP(S) URL")
        if not self.content.strip():
            raise ValueError("document content must not be empty")


@dataclass(frozen=True, slots=True)
class Claim:
    id: str
    text: str
    status: ClaimStatus = ClaimStatus.UNVERIFIED
    support_count: int = 0
    sources: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("claim id must not be empty")
        if not self.text.strip():
            raise ValueError("claim text must not be empty")
        if self.support_count < 0:
            raise ValueError("support_count must be non-negative")


@dataclass(frozen=True, slots=True)
class Evidence:
    claim_id: str
    url: str
    title: str
    passage_index: int
    passage_text: str
    score: float

    def __post_init__(self) -> None:
        parsed = urlparse(self.url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("evidence URL must be an absolute HTTP(S) URL")
        if not self.passage_text.strip():
            raise ValueError("evidence passage text must not be empty")
        if self.passage_index < 0:
            raise ValueError("passage index must be non-negative")
        if not 0.0 <= self.score <= 1.0:
            raise ValueError("score must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ResearchBudget:
    max_queries: int = 8
    max_pages: int = 20
    max_rounds: int = 3

    def __post_init__(self) -> None:
        if not 1 <= self.max_queries <= 100:
            raise ValueError("max_queries must be between 1 and 100")
        if not 1 <= self.max_pages <= 1000:
            raise ValueError("max_pages must be between 1 and 1000")
        if not 1 <= self.max_rounds <= 10:
            raise ValueError("max_rounds must be between 1 and 10")


@dataclass(frozen=True, slots=True)
class ResearchReport:
    question: str
    claims: tuple[Claim, ...] = ()
    evidence: tuple[Evidence, ...] = ()
    sources: tuple[str, ...] = ()
    rounds: int = 0
    stopped_reason: StoppingReason = StoppingReason.BUDGET_EXHAUSTED
    answer: str = ""
    answer_citations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.question.strip():
            raise ValueError("research question must not be empty")
        if self.rounds < 0:
            raise ValueError("rounds must be non-negative")
