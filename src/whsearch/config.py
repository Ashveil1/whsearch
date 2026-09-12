from __future__ import annotations

import os
from dataclasses import dataclass

from whsearch.exceptions import ConfigurationError


@dataclass(frozen=True, slots=True)
class Settings:
    """Runtime limits and network policy for the search engine."""

    user_agent: str = "WHSearch/0.1"
    request_timeout_seconds: float = 15.0
    max_response_bytes: int = 5_000_000
    max_search_results: int = 30
    max_pages_per_task: int = 20
    per_domain_delay_seconds: float = 1.0
    cache_max_bytes: int = 500_000_000
    index_path: str | None = None
    index_max_entries: int = 5000

    @classmethod
    def from_environment(cls) -> Settings:
        defaults = cls()
        return cls(
            user_agent=os.getenv("WHSEARCH_USER_AGENT", defaults.user_agent),
            request_timeout_seconds=_float_env(
                "WHSEARCH_REQUEST_TIMEOUT", defaults.request_timeout_seconds, minimum=1.0
            ),
            max_response_bytes=_int_env(
                "WHSEARCH_MAX_RESPONSE_BYTES", defaults.max_response_bytes, minimum=1_024
            ),
            max_search_results=_int_env(
                "WHSEARCH_MAX_SEARCH_RESULTS", defaults.max_search_results, minimum=1, maximum=100
            ),
            max_pages_per_task=_int_env(
                "WHSEARCH_MAX_PAGES", defaults.max_pages_per_task, minimum=1, maximum=1000
            ),
            per_domain_delay_seconds=_float_env(
                "WHSEARCH_DOMAIN_DELAY", defaults.per_domain_delay_seconds, minimum=0.0
            ),
            cache_max_bytes=_int_env(
                "WHSEARCH_CACHE_MAX_BYTES", defaults.cache_max_bytes, minimum=0
            ),
            index_path=os.getenv("WHSEARCH_INDEX_PATH") or None,
            index_max_entries=_int_env(
                "WHSEARCH_INDEX_MAX_ENTRIES",
                defaults.index_max_entries,
                minimum=1,
                maximum=1_000_000,
            ),
        )


def _int_env(name: str, default: int, *, minimum: int, maximum: int | None = None) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be an integer") from exc
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" and <= {maximum}" if maximum is not None else ""
        raise ConfigurationError(f"{name} must be >= {minimum}{upper}")
    return value


def _float_env(name: str, default: float, *, minimum: float, maximum: float | None = None) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{name} must be a number") from exc
    if value < minimum or (maximum is not None and value > maximum):
        upper = f" and <= {maximum}" if maximum is not None else ""
        raise ConfigurationError(f"{name} must be >= {minimum}{upper}")
    return value
