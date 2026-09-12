from pathlib import Path

SRC = Path(__file__).parents[2] / "src" / "whsearch"
DOMAIN = SRC / "domain"


def test_domain_has_no_infrastructure_dependencies() -> None:
    forbidden = (
        "whsearch.infrastructure",
        "whsearch.search",
        "whsearch.reader",
        "whsearch.mcp",
    )
    for path in DOMAIN.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(module in text for module in forbidden), path


def test_domain_has_no_optional_runtime_dependencies() -> None:
    forbidden = ("httpx", "trafilatura", "mcp", "bs4")
    for path in DOMAIN.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert not any(f"import {module}" in text for module in forbidden), path
