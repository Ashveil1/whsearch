# Offline quality fixture and live smoke

```bash
pip install -e '.[test,mcp]'
python -m benchmarks.evaluate                 # summary + per-case results as JSON
python -m benchmarks.evaluate --summary-only
python -m benchmarks.evaluate --dataset benchmarks/data/quality_holdout.json
python -m benchmarks.evaluate --dataset path/to/quality.json
```

This is a **small, synthetic, hand-labelled offline regression fixture**, not a
representative benchmark or an estimate of real-world accuracy. Its labels are
examples, not facts about real entities. It uses 14 passage-ranking cases
(English, Thai, mixed script, distractors, paraphrase, numbers) and 6 ResearchAgent
cases (4 answerable, 2 unanswerable). A separate, similarly small synthetic
challenge set (`quality_holdout.json`) has 5 passage and 7 research cases; it
was added after the changes and is **not** an independent real-world test.
The research cases use an injected fixed
search-result list and fixture reader, so they evaluate the agent from those
inputs, not live discovery or HTTP. Scores are diagnostic; CI runs the benchmark
without thresholds so existing weaknesses remain visible rather than being hidden
by adjusted expectations.

Definitions:

* **Hit@1**, **MRR**, and **Recall@3** are calculated from labelled passage
  indices in each ranking case. MRR is the mean reciprocal rank of the first
  relevant passage. Recall@3 is the proportion of labelled relevant passages
  among the first three, averaged over cases.
* **Answerable top-1 hit** is the fraction of answerable cases where the first
  answer line exactly matches a labelled gold claim; **unanswerable abstention**
  is the fraction of unanswerable cases with no answer lines. An empty answer on
  an answerable case is a miss, not a successful abstention.
* **Answer-line precision** counts answer lines whose text exactly matches a
  labelled gold claim, divided by all answer lines (micro-average).
  **Citation topical precision** counts markers on such lines pointing to a
  labelled relevant URL, divided by all markers (micro-average). Zero
  denominators are reported as `null`. These exact-match labels can miss valid
  paraphrases and do not establish entailment or truth.
* **Citation structure valid cases** checks marker indices, links from answer
  lines to a subset of their claims' source URLs and matching evidence entries,
  that each cited URL has a passage containing the extracted claim after
  case/whitespace/Unicode normalization, and that evidence passage text is a
  prefix of the original fixture passage. An empty
  answer is structurally valid by vacuity. This is a traceability check, **not**
  a test of factual grounding, factual accuracy, or source independence.

Before these changes, on Python 3.12.8, the original fixture produced Hit@1
**12/14**, MRR **0.9286**, answerable top-1 **4/4**, unanswerable abstention
**1/2**, answer-line and citation topical precision **4/7**, and citation
structure valid **6/6**. After the lexical gate and citation changes, on the
same fixture it produces Hit@1 **13/14**, MRR **0.9643**, Recall@3 **1.0**,
answerable top-1 **4/4**, unanswerable abstention **2/2**, answer-line and
citation topical precision **4/4**, and citation structure valid **6/6**.
The paraphrase passage case still misses rank 1. The fixture informed these
changes, so this is not an independent estimate of improvement.

On the separate synthetic challenge set, Hit@1 is **4/5**, MRR **0.9**,
Recall@3 **1.0**, answerable top-1 **3/4**, unanswerable abstention **2/3**,
answer-line and citation topical precision **3/4**, and citation structure
valid **7/7**. A keyword-heavy job advertisement is incorrectly selected as a
finding, and a useful paraphrased answer is missed. These failures illustrate
that lexical filtering does not determine whether a passage answers the
question. Both sets are much too small for general quality claims. Add larger,
held-out, independently annotated realistic examples before drawing conclusions.

## Optional live MCP smoke

```bash
python -m benchmarks.live_smoke
# If your environment requires a custom trusted CA bundle:
WHSEARCH_CA_FILE=/path/to/trusted-ca-bundle.pem python -m benchmarks.live_smoke
```

This launches the actual MCP stdio server, fetches a public GitHub page, and
calls search, search-and-read, and research using the default provider set.
It makes external requests and reports individual tool results rather than
asserting availability; it is not a CI quality test. `WHSEARCH_CA_FILE` supplies
a PEM CA bundle **instead of** the default trust roots; only use a bundle you
trust. Certificate and hostname verification remain enabled, and the normal
SSRF/DNS and robots protections are not bypassed. The process exit code alone
is not a success signal: inspect each JSON result and `research.search_errors`.

Observed in the restricted Arena sandbox on 2026-11-12 with the system CA bundle:
GitHub `read_page` succeeded via MCP stdio; all four default DuckDuckGo and
Wikipedia provider instances failed with connection errors (outbound access is
restricted to a small host allowlist). Consequently search and search-and-read
returned tool errors; research returned an empty answer with `search_errors=1`.
This does not establish whether those providers work on an unrestricted network.
The separate offline MCP protocol fixture tests all four tools through the real
application with mocked HTTP responses; it does not test external connectivity.
