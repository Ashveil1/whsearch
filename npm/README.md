# @Ashveil1/whsearch (npx wrapper)

Zero-config launcher for the whsearch MCP server. Node only starts the
process; the server itself is Python and speaks MCP over stdio.

## Use

```json
{
  "mcpServers": {
    "whsearch": { "command": "npx", "args": ["-y", "@Ashveil1/whsearch"] }
  }
}
```

Requires Python >= 3.12 on PATH. On first run the launcher pip-installs the
pinned `whsearch[mcp]` backend automatically.

## Environment overrides

- `WHSEARCH_PY` — Python executable to use.
- `WHSEARCH_PACKAGE` — pip spec for the backend (default: pinned release).
- `WHSEARCH_DEV_PATH` — path to a source checkout; uses `<path>/src` directly
  instead of installing (local development).
- `WHSEARCH_INDEX_PATH` — enables the persistent SQLite/FTS5 local index.
- `WHSEARCH_LOG_LEVEL` — server log level.

## Versioning

`BACKEND_VERSION` in `launcher.js`, `version` in this `package.json`, and
`version` in the root `pyproject.toml` must be bumped together.
