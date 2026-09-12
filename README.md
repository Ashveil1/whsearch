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

Requires Python >= 3.12 on PATH.

Via npx (after the wrapper is published to the npm registry):

```json
{
  "mcpServers": {
    "whsearch": { "command": "npx", "args": ["-y", "@Ashveil1/whsearch"] }
  }
}
```

From source instead:

```bash
pip install -e ".[mcp]"
whsearch
```

The wrapper source lives in `npm/` (`BACKEND_VERSION` there must match
`pyproject.toml`). `WHSEARCH_INDEX_PATH` enables the persistent local index.

## License

GPL-3.0-or-later, see `LICENSE`. Copyright (C) 2026 WHSearch contributors.
Per-file copyright holder names were intentionally left generic; update them
to your name before publishing if you are the sole author.
