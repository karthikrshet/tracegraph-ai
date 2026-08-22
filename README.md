# TraceGraph AI

TraceGraph AI is a narrow, evidence-first prototype for the Testsigma AI Engineer take-home. It builds a Neo4j graph from three real inputs:

1. an explicitly selected public product document;
2. a bounded Playwright crawl of an explicitly allowlisted public application; and
3. a real public GitHub pull request and its changed source files.

It then reports only impact paths that Neo4j can traverse: `PR change → changed symbol → observed UI → observed flow → requirement`. It does not return fixture flows, fabricate screenshots, or produce an offline “best guess” report.

## Current scope and honesty

The prototype deliberately goes deep on provenance, safe collection, and deterministic traversal. It is not a general production crawler.

- The application URL, document URL, and code repository must describe the same product surface. The historical Saleor storefront/dashboard pairing is not a valid end-to-end evidence chain; select a repository with a public, corresponding UI before recording the final assignment run.
- Browser crawling defaults to 20 screens, 40 navigations, depth 4, and 300 seconds; server-enforced ceilings are 25 screens, 60 navigations, depth 6, and 600 seconds. A bounded crawl can yield `COVERED`, `PARTIAL`, or `UNVERIFIED`; it never claims `ABSENT` without a separately recorded exhaustive-coverage certificate.
- Code extraction is deterministic source parsing plus changed-declaration matching. Changes inside an existing function can be reported as an unmapped changed file rather than falsely assigned to a symbol.
- Neo4j is a dedicated active-run index: re-indexing deliberately replaces its TraceGraph nodes, while immutable DOM, screenshot, requirement, PR, report, and manifest artifacts remain on disk. This prevents same-named page nodes from separate runs contaminating a report.
- Neo4j, Playwright, GitHub, and the selected document are required for a report. A missing dependency returns an error/503; it is not replaced with demo data.

## Security model

- Crawl and document URLs are server-side allowlisted and DNS-resolved; loopback, private, link-local, metadata, and redirect-to-private targets are rejected. In development, the dashboard can explicitly approve the entered public hostname for that single crawl; it does not create a persistent or unrestricted allowlist entry. Production disables this option by default and requires authenticated API access before an operator enables `ALLOW_CUSTOM_CRAWL_HOSTS=true`.
- Crawl budgets are server-enforced, navigation is same-domain, and destructive actions are filtered.
- GitHub accepts only `owner/repository`, uses immutable PR head SHA for file retrieval, and fails closed on API errors.
- Untrusted captured HTML is served as a downloadable text attachment with `nosniff`; it is never executed under the dashboard origin. Dashboard rendering escapes all crawl/report strings.
- Cypher is parameterized internally. The exposed explorer accepts a single read-only `MATCH … RETURN` query and blocks mutation/procedure keywords.
- Production mode requires `API_BEARER_TOKEN` for state-changing operations, uses explicit CORS origins, and requires a non-empty Neo4j password. Put the dashboard/API behind your normal authenticated reverse proxy before exposing read endpoints or captured artifacts.

If this repository was ever configured with a real provider key, revoke and rotate that key. `.env.example` intentionally contains no credentials.

## Architecture

```text
public spec ──► deterministic fetch/sanitize + LLM extraction ──► Requirement
live browser ─► Playwright observation ─────────────────────────► Page/UIElement/Transition
GitHub PR ────► immutable source fetch + parser ────────────────► PRChange/CodeFile/CodeSymbol
                                                               │
                                                       Neo4j evidence graph
                                                               │
                                                    deterministic blast radius
```

LLM use is bounded to requirement extraction from a delimited, untrusted document payload. It does not decide blast radius or narrate facts beyond the deterministic report template.

## Run it

Prerequisites: Python 3.10+, Docker with Compose, a Playwright-capable host, an OpenAI-compatible API key for real requirement extraction, and optionally a GitHub token to avoid public API rate limits.

```bash
cp .env.example .env
# Set NEO4J_PASSWORD, OPENAI_API_KEY (or another supported provider),
# ALLOWED_CRAWL_DOMAINS, ALLOWED_DOCUMENT_DOMAINS, and a GitHub token if needed.

docker compose up -d neo4j
python -m pip install -e ".[dev]"
python -m playwright install chromium

python scripts/run_pipeline.py \
  --repo OWNER/REPOSITORY \
  --pr 123 \
  --crawl-url https://public-app.example.com/ \
  --spec-url https://docs.example.com/feature
```

The command exits without a report if any evidence source is unavailable. A successful run writes `data/blast_radius_pr_<number>.json` and Markdown alongside the raw, run-specific crawl/code artifacts.

To use the dashboard:

```bash
uvicorn app.api.main:app --reload --port 8000
```

Start with a live crawl and an explicit documentation URL. Select the same crawl ID when building the graph; the API rejects graph builds with missing requirements, incomplete crawl data, missing code evidence, or unavailable Neo4j.

### Deployment boundary

The full evidence pipeline requires the Docker API runtime (or an equivalent dedicated worker) because it owns a Playwright browser, server-sent crawl progress, writable artifact storage, and Neo4j connectivity. A Vercel deployment can host the dashboard and read-only API preview, but it intentionally returns **Worker required** for a live crawl rather than fabricating DOM, screenshot, or session evidence. Use the Docker deployment for the Loom and final evidence run.

## Evaluation

Tests exercise parsers, SSRF defenses, API guards, safe failure modes, and deterministic report assembly:

```bash
python -m pytest tests -q
```

Evaluate a generated, provenance-verified JSON report only against a separately human-reviewed JSON file of this form:

```json
{"impacted_requirement_ids": ["REQ-001", "REQ-004"]}
```

```bash
python scripts/run_eval.py --report data/blast_radius_pr_123.json --ground-truth reviewed_truth.json
```

No hard-coded precision/recall score is claimed by the repository. The evaluation output is meaningful only for the exact captured run and independent human labels.

## Graph model

`Requirement`, `Page`, `UIElement`, `UserFlow`, `CodeFile`, `CodeSymbol`, `PullRequest`, and `PRChange` are graph nodes. Provenance-bearing relationships include `COVERS`, `IMPLEMENTED_BY`, `PART_OF`, `STEP_IN`, `DEFINED_IN`, `TOUCHES`, `MODIFIES`, and `PART_OF_PR`.

Absence is a state, not a missing edge: `UNVERIFIED` means the bounded crawl did not find evidence; `ABSENT` is reserved for a future exhaustive-coverage certificate. This prevents “not observed” from being misreported as “not built.”

See [the design document](docs/design_document.md) for the agent boundaries, schema rationale, confidence handling, evaluation protocol, scope, and next-week priorities.
