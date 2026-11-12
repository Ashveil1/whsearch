# WHSearch

WHSearch is an alpha-stage MCP server for web discovery, reading, and
extractive research. It combines keyless search providers with a
robots-gated HTML reader and an optional SQLite cache.

**Use results as leads, not verified answers.** External pages are untrusted
content, including text that purports to instruct an AI. The research tool is
extractive and uses lexical matching, not logical entailment or fact-checking.
Always review cited passages and original sources before relying on a claim.

## MCP tools

- `search`: discover results from web, Wikipedia, and intent-selected news,
  academic, or video providers. Providers are best-effort and may change or
  become unavailable.
- `read_page`: fetch an HTML page after robots checks. Output is truncated to
  20,000 content characters and 20 passages, each at most 2,000 characters.
  The result includes the final URL, metadata, and passage sections.
- `search_and_read`: search and read pages concurrently. The default output
  includes relevant passages. `max_chars=0` returns metadata only. Limits are
  enforced server-side. A domain filter can be supplied; redirects are checked
  against it before results are returned, but it is not a network firewall.
- `research`: perform budgeted search/read rounds, including heuristic
  follow-up queries based on retrieved text. Output includes claim-level
  passages, section names, publication dates, truncation flags, and numbered
  source citations. `max_pages` is capped by
  `WHSEARCH_MAX_PAGES`; the budget counts read attempts, not just successes.
  The report includes effective budgets, attempts, and query/read error counts.
  A query is a logical search; provider fan-out and simplified retries may
  make more than one upstream request per query. Follow-up queries preserve
  the original `site:` constraint.

A claim marked `lexical_match` has overlapping wording in multiple domains;
this **does not establish support, source independence, or truth**. A
`contested` label is a heuristic warning, not a definitive contradiction.
A claim can be inaccurate even when no warning appears. `unverified` means
there was insufficient lexical overlap. The legacy `supported` status is
reserved for externally verified evidence and is not produced by the current
heuristic verifier. These labels are a breaking change for clients that used
`"supported"` for lexical matches.

`recency_days` is best-effort: dated pages older than the cutoff are dropped,
while undated pages are retained. The publication date can itself be wrong.
Research stop reasons describe the actual stopping condition; budget
exhaustion is not treated as proof of saturation or sufficient evidence.

Search results include `metadata.whsearch` with provider names, partial provider
failures and whether a bounded-age cached result was used after a failure.
A search score is a ranking indicator, not a calibrated probability; an
evidence score is relative BM25 similarity, not a measure of truth. The answer
uses a conservative absolute lexical-overlap gate and cites passages containing
the extracted wording; approximate lexical matches remain in the evidence
list. If no claim passes the gate with a traceable original passage, the answer
is empty. This heuristic can still return irrelevant text with matching keywords,
and can reject useful paraphrases or short Thai queries. An empty answer does
not prove that no answer exists. Exact quotation does not prove that a source
is correct or that it answers the question.

`whsearch://stats` describes configured limits and `whsearch://health` is a
liveness signal, not a check that upstream providers are working.

## Installation

Requires Python 3.12 or newer and MCP SDK 1.30 or newer (below 2.0). From source:

```bash
pip install -e ".[mcp]"
whsearch
```

MCP client configuration from a local checkout:

```json
{
  "mcpServers": {
    "whsearch": {
      "command": "uvx",
      "args": ["--from", "/absolute/path/to/whsearch[mcp]", "whsearch"]
    }
  }
}
```

A package name may be used with `uvx` only after publishing to PyPI.

## Network and resource safety

The standard application client resolves each connection and connects only to
checked public IP addresses, including for redirects. It bounds both compressed
and decompressed response bytes for providers and the reader, supports identity,
gzip and deflate, rejects other content encodings, and does not retain cookies.
Environment HTTP proxies are disabled: an untrusted proxy would otherwise bypass
the address check.
The reader checks robots on every page redirect, fails closed for unavailable
robots policies, and paces requests per origin within an application instance.
Robots redirects fail closed. The public-network guard applies to the client
created by `create_application`; applications injecting their own `httpx`
client are responsible for equivalent protection.

These measures do not make arbitrary web content safe. For untrusted inputs,
run WHSearch with a non-privileged user, filesystem restrictions, and an egress
firewall that blocks private networks and metadata services. MCP calls in one
server process share an application, bounded robots cache,
per-origin pacing and connection pool, with at most eight concurrent tool calls.
Use an external rate limiter across multiple processes or hosts. Per-operation,
provider, reader and task deadlines limit asynchronous waits; synchronous HTML
parsing and other CPU-bound code are not preempted by asyncio deadlines. A task
that times out returns an error rather than a partial research report. Default
warning logs omit search query text and HTTP exception URLs; debug logging can
include queries and page URLs, so use it only in trusted environments.

Key settings:

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `WHSEARCH_CA_FILE` | unset | Optional PEM CA bundle for HTTPS verification (replaces default trust roots) |
| `WHSEARCH_MAX_PAGES` | `20` | Maximum pages per MCP task |
| `WHSEARCH_MAX_RESPONSE_BYTES` | `5000000` | HTTP raw and decoded response limit |
| `WHSEARCH_REQUEST_TIMEOUT` | `15` | HTTP operation timeout in seconds |
| `WHSEARCH_READ_TIMEOUT` | `60` | Reader asynchronous deadline in seconds |
| `WHSEARCH_PROVIDER_TIMEOUT` | `30` | Search-provider asynchronous deadline in seconds |
| `WHSEARCH_TASK_TIMEOUT` | `120` | MCP tool deadline, including time waiting for a slot |
| `WHSEARCH_DOMAIN_DELAY` | `1` | Minimum interval between reader requests to an origin, in seconds |
| `WHSEARCH_INDEX_PATH` | unset | Enable the persistent SQLite cache |
| `WHSEARCH_INDEX_MAX_ENTRIES` | `5000` | Maximum cached documents |
| `WHSEARCH_INDEX_TTL_SECONDS` | `86400` | Maximum cache age; zero disables cache hits |
| `WHSEARCH_CACHE_MAX_BYTES` | `500000000` | Logical document and passage text budget |
| `WHSEARCH_BROWSER` | `0` | Opt in to experimental browser fallback |

The cache byte budget counts stored document and passage text, not SQLite
metadata, free pages, FTS indexes, or the WAL. It is **not** a hard disk quota;
use filesystem quotas and monitoring for that. Legacy cache records without a
fetch time are expired and the FTS index is rebuilt during migration. Search
results may be served from an in-memory cache for up to five minutes only after
provider failure; the result metadata marks this as stale.

## Experimental browser fallback

Install with `pip install -e ".[mcp,js]"` and install Playwright Chromium.
Browser fallback is **off by default**. `WHSEARCH_BROWSER=1` explicitly enables
it; `WHSEARCH_BROWSER_TIMEOUT` and `WHSEARCH_CHROMIUM_PATH` configure it.
Chromium's sandbox is requested, but browser navigation and JavaScript
subrequests do **not** use the checked HTTP network backend or per-redirect
robots gate. Do not enable it for untrusted pages unless the browser runs in a
separately isolated environment with an effective egress firewall. There is no
complete browser network isolation provided by this package.

## Video and file formats

YouTube watch pages are read using metadata and descriptions; chapter lines
are exposed where available. This is **not a transcript**, and captions are
not fetched. The reader accepts HTML/XHTML, not PDF or other file formats.

## Development

```bash
pip install -e ".[test,mcp]" ruff mypy
python -m pytest
ruff check src tests benchmarks
python -m mypy src tests benchmarks
python -m compileall -q src tests benchmarks
python -m benchmarks.evaluate --summary-only
```

See [benchmarks/README.md](benchmarks/README.md) for the synthetic Thai–English
quality fixture, scoring limitations and observed baseline. Provider fixtures and unit tests run offline. Real-provider quality, upstream
availability, multilingual retrieval, and end-to-end research accuracy require
separate evaluation; passing tests is not a claim that the results are correct.

## License

GPL-3.0-or-later, see `LICENSE`. Copyright (C) 2026 WHSearch contributors.
