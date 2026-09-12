import logging

import pytest

from whsearch.config import Settings
from whsearch.observability import configure_logging, get_logger


def test_settings_defaults_are_resource_bounded() -> None:
    settings = Settings()
    assert settings.max_response_bytes > 0
    assert settings.max_search_results <= 100
    assert settings.max_pages_per_task <= 1000


def test_settings_reads_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHSEARCH_MAX_SEARCH_RESULTS", "25")
    monkeypatch.setenv("WHSEARCH_DOMAIN_DELAY", "0.25")
    settings = Settings.from_environment()
    assert settings.max_search_results == 25
    assert settings.per_domain_delay_seconds == 0.25


def test_settings_rejects_invalid_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("WHSEARCH_MAX_SEARCH_RESULTS", "0")
    with pytest.raises(ValueError, match="must be >= 1"):
        Settings.from_environment()


def test_logging_is_idempotent() -> None:
    logger = logging.getLogger("whsearch")
    old_handlers = list(logger.handlers)
    try:
        for handler in old_handlers:
            logger.removeHandler(handler)
        configure_logging("WARNING")
        count = len(logger.handlers)
        configure_logging("WARNING")
        assert len(logger.handlers) == count == 1
        assert get_logger("test").name == "whsearch.test"
    finally:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
        for handler in old_handlers:
            logger.addHandler(handler)
