# WHSearch

AI-native research search engine built as a lightweight modular monolith.

## Current phase

All phases implemented: foundation, multi-provider web discovery
(DuckDuckGo + Wikipedia fan-out), robots-gated reader, passage retrieval,
adaptive research planning with stopping conditions, claim-level evidence
with source-independence and contradiction checks, MCP search agent
(`search`, `read_page`, `search_and_read`, `research`), bounded
SQLite/FTS5 local index, and explicit research budgets.

## Design rules

- Evidence first: retrieve sources and passages before generating research conclusions.
- Online first: use external discovery initially; keep persistent storage bounded.
- Respect robots.txt, access policies, and conservative per-domain rate limits.
- Domain models and protocols must not depend on HTTP clients, providers, MCP, or extractors.
- MCP is an adapter layer; research/search logic stays in application modules.
- Optional integrations must not be required for importing the core domain.
- Resource limits are explicit so the system remains usable on low-memory machines.

## Planned phases

1. ~~Foundation: contracts, configuration, logging, testing, architecture checks.~~ Done.
2. ~~Web discovery: provider abstraction and DuckDuckGo discovery.~~ Done (+Wikipedia).
3. ~~Web reader: robots policy, fetching, extraction, metadata, passages.~~ Done.
4. ~~Retrieval: passage ranking and deduplication.~~ Done.
5. ~~Research: adaptive query planning and stopping conditions.~~ Done.
6. ~~Evidence: claims, source independence, contradictions, verification.~~ Done.
7. ~~Search agent: orchestration through the MCP tools.~~ Done.
8. ~~Local index: SQLite/FTS5 bounded cache and reusable evidence.~~ Done.
9. ~~Autonomous research budgets and larger-scale discovery.~~ Done (budgets + fan-out).

## Development

Use the repository virtual environment when available:

```bash
.venv/bin/python -m pytest
.venv/bin/python -m compileall -q src tests
.venv/bin/ruff check src tests
```

The quality gate must pass before moving to the next phase.

## Install as an MCP server

Requires Python >= 3.12. After the `whsearch` package is published to PyPI,
no manual install is needed — `uvx` fetches and runs it on first use:

```json
{
  "mcpServers": {
    "whsearch": { "command": "uvx", "args": ["--from", "whsearch[mcp]", "whsearch"] }
  }
}
```

Alternatives:

```bash
uv tool install "whsearch[mcp]" && whsearch   # persistent install via uv
pipx install "whsearch[mcp]" && whsearch      # persistent install via pipx
pip install -e ".[mcp]" && whsearch           # from source
```

`WHSEARCH_INDEX_PATH` enables the persistent local index.

## Optional headless-browser fallback (L3)

Pages that render only via JavaScript (JS-shell SPAs) defeat static
extraction. When the `js` extra is installed, the reader tries headless
Chromium **only** for pages where static extraction yields almost nothing:

```bash
pip install -e ".[mcp,js]" && .venv/bin/playwright install chromium
```

Behavior and limits (all free, no keys):

- L1 trafilatura → L2 embedded JSON/meta → L3 headless, first hit wins.
- L3 triggers only below 200 extracted chars; rendered text must also clear it.
- At most 2 concurrent renders, 15s each, images/fonts/media blocked.
- Missing playwright (or any render failure) degrades silently to static text.
- `WHSEARCH_BROWSER=0` disables it; `WHSEARCH_BROWSER_TIMEOUT` tunes seconds.
- `whsearch://stats` reports `reader.browser_installed/enabled/timeout`.

## License

GPL-3.0-or-later, see `LICENSE`. Copyright (C) 2026 WHSearch contributors.
Per-file copyright holder names were intentionally left generic; update them
to your name before publishing if you are the sole author.
