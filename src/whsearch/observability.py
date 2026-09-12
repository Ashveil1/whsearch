from __future__ import annotations

import logging
import os

LOGGER_NAME = "whsearch"


def configure_logging(level: str | None = None) -> None:
    """Configure one predictable stderr handler for CLI/MCP hosts."""
    root = logging.getLogger(LOGGER_NAME)
    configured_level = level if level is not None else os.getenv("WHSEARCH_LOG_LEVEL")
    root.setLevel(_parse_level(configured_level or "INFO"))
    if root.handlers:
        return

    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)


def get_logger(component: str) -> logging.Logger:
    return logging.getLogger(f"{LOGGER_NAME}.{component}")


def _parse_level(value: str) -> int:
    level = getattr(logging, value.upper(), None)
    if not isinstance(level, int):
        raise ValueError(f"invalid log level: {value}")
    return level
