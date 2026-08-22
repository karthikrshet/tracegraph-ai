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
                                                               │
                                evidence verifier ──► reviewer-ready QA plan
```

LLM use is bounded to requirement extraction from a delimited, untrusted document payload. It does not decide blast radius or narrate facts beyond the deterministic report template.

### Evidence-grounded QA planning

`GET /api/agents` exposes the authority, tools, deterministic boundary, and human-escalation rule for every pipeline stage. After a report and a completed crawl exist, `GET /api/qa-analysis/<pr>?crawl_id=<id>` performs a second deterministic verification pass. It checks the exact graph-path shape, that every referenced UI element belongs to the selected crawl, that its page still has both captured DOM and screenshot artifacts, and that a test step corresponds to an observed transition.

The dashboard's **QA Intelligence** tab renders only those checks. A claim with missing artifacts is `REJECTED`; a valid path below 0.50 confidence is `NEEDS_REVIEW`; only a verified path with a browser-observed transition can become an `APPROVED` test. It never produces a generic fallback checklist, synthetic test case, or ungrounded success state.

## Complete local runbook

### 1. Prerequisites

| Component | Required for | Notes |
|---|---|---|
| Python 3.10+ | Host CLI pipeline and tests | The CLI owns host Playwright when run outside Docker. |
| Docker Desktop + Compose | Neo4j and local dashboard/API | Use Docker Desktop's Linux engine on Windows. |
| Chromium for Playwright | Real browser crawl | Installed with `python -m playwright install chromium`. |
| One real LLM provider key | Requirement extraction and report narration | OpenAI, Groq, xAI, or Grok-compatible configuration. A mock provider is rejected for an evidence run. |
| GitHub token (recommended) | Public PR retrieval | Avoids public API rate limits; scope it read-only. |

Choose a public application, product document, and GitHub repository that
describe the **same product surface**. Do not reuse archived report files as a
new run's evidence.

### 2. Configure secrets and allowlists

Create a local environment file. It is gitignored and must never be committed.

```bash
cp .env.example .env
```

Set at least the following values in `.env`:

| Setting | Purpose | Example shape |
|---|---|---|
| `NEO4J_PASSWORD` | Password used by the local Neo4j container | Use a unique local secret. |
| `LLM_PROVIDER`, provider key, `LLM_MODEL` | Real extraction/narration provider | `LLM_PROVIDER=groq` plus `GROQ_API_KEY=...` |
| `ALLOWED_CRAWL_DOMAINS` | Comma-separated application hosts approved for crawling | `demo.realworld.show` |
| `ALLOWED_DOCUMENT_DOMAINS` | Comma-separated documentation hosts approved for ingestion | `github.com,raw.githubusercontent.com` |
| `GITHUB_TOKEN` | Optional read-only token for PR retrieval | Leave blank only if public rate limits are acceptable. |
| `TARGET_REPO`, `TARGET_PR` | Optional dashboard defaults | `owner/repository`, `123` |

The crawler validates DNS before navigation and rejects private, loopback,
link-local, metadata, and redirect-to-private destinations. Adding a host to an
allowlist does not disable those checks.

### 3. Start local services

Start Neo4j first. `-d` means detached/background: Compose returns to the shell
while the service keeps running.

```bash
docker compose up -d neo4j
docker compose ps
```

The expected state is `tracegraph-neo4j` with `healthy` status. Then start the
local API/dashboard, which serves the UI on port 8000 and shares the local
`data/` evidence directory with the host:

```bash
docker compose up -d --build api
docker compose ps
```

Open these local-only services:

| URL | Purpose |
|---|---|
| [http://localhost:8000](http://localhost:8000) | TraceGraph dashboard |
| [http://localhost:8000/api/docs](http://localhost:8000/api/docs) | OpenAPI / interactive endpoint docs |
| [http://localhost:7474](http://localhost:7474) | Neo4j Browser (bound to loopback only) |

Useful diagnostics:

```bash
docker compose ps
docker compose logs --tail=100 api
docker compose logs --tail=100 neo4j
```

To stop local services without deleting evidence or Neo4j data, run
`docker compose down`. Do **not** add `-v` unless you intentionally want to
delete the local Neo4j volumes.

### 4. Install host CLI dependencies

Use this when running `scripts/run_pipeline.py` directly from the host. The
dashboard/API container already has its own application dependencies.

```bash
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

### 5. Run one real end-to-end pipeline

The CLI performs five fail-closed stages: ingest selected specification, crawl
the live application, fetch immutable PR code, build Neo4j, and compute the
blast radius. It intentionally uses a narrow 5-page/5-action crawl budget for
an assignment run. If any stage lacks evidence, it exits without a report.

```bash
python scripts/run_pipeline.py \
  --repo OWNER/REPOSITORY \
  --pr 123 \
  --crawl-url https://public-app.example.com/ \
  --spec-url https://docs.example.com/feature
```

The currently documented, real reference combination is:

- Application: `https://demo.realworld.show/`
- Repository: `realworld-apps/angular-realworld-example-app`
- PR: `350`
- Specification: the repository's public README on `raw.githubusercontent.com`

Use a plain URL in the terminal—not Markdown such as `[url](url)`.

#### Windows / Docker Desktop

Before using Compose, start Docker Desktop and wait for **Engine running**. If
`docker version` does not show both `Client` and `Server`, it is not ready or is
configured for Windows containers rather than Linux containers.

In Windows Command Prompt, the command must be one line because `\` is a Bash
continuation character:

```cmd
docker compose up -d neo4j
python scripts/run_pipeline.py --repo realworld-apps/angular-realworld-example-app --pr 350 --crawl-url https://demo.realworld.show/ --spec-url https://raw.githubusercontent.com/realworld-apps/angular-realworld-example-app/main/README.md
```

In PowerShell, use a backtick for multiline input:

```powershell
python scripts/run_pipeline.py `
  --repo realworld-apps/angular-realworld-example-app `
  --pr 350 `
  --crawl-url https://demo.realworld.show/ `
  --spec-url https://raw.githubusercontent.com/realworld-apps/angular-realworld-example-app/main/README.md
```

### 6. Use the dashboard workflow

1. Open [http://localhost:8000](http://localhost:8000).
2. In **Web Crawler**, validate a public target, run a bounded crawl, and inspect
   the saved screenshots, downloaded DOM snapshots, and transitions.
3. In **Specification**, enter either one approved public documentation URL or
   pasted requirement text, then ingest it. The dashboard never displays a seed
   requirements table on a first run.
4. Select the same completed crawl and use **Apply to Graph**, then build the
   three-layer graph for the repository and PR.
5. In **Blast Radius**, request the provenance-verified report. A graph,
   completed crawl, public spec, immutable GitHub evidence, and real LLM
   configuration are all required.
6. In **QA Intelligence**, choose the completed crawl used by the report.
   The evidence verifier checks graph hops, stored DOM/screenshots, and observed
   transitions before producing reviewer-ready tests.

The dashboard can also be started from the host instead of Compose:

```bash
uvicorn app.api.main:app --reload --port 8000
```

For this host mode, `.env` must use `NEO4J_URI=bolt://localhost:7687`. The
Compose API uses `bolt://neo4j:7687` internally and configures that for you.

### 7. HTTP API

In development, endpoints are available on the local dashboard/API. In staging
or production, operational endpoints require `Authorization: Bearer
<API_BEARER_TOKEN>`. Endpoint schemas and request bodies are available at
[`/api/docs`](http://localhost:8000/api/docs).

| Endpoint | What it does |
|---|---|
| `GET /api/health` | Checks API reachability and configured repository/PR defaults. |
| `GET /api/agents`, `GET /api/agents/{name}` | Shows the bounded authority and failure behavior of each agent stage. |
| `POST /api/ingest` | Extracts requirements from approved public documentation or pasted text. |
| `POST /api/crawl/validate-url`, `POST /api/crawl` | Validates a target then starts a real browser crawl. |
| `GET /api/crawl/sessions`, `/api/crawl/{id}/pages`, `/transitions` | Lists persisted sessions and captured evidence. |
| `POST /api/crawl/{id}/apply-to-graph` | Stages exactly one completed crawl for graph construction. |
| `POST /api/analyze-code`, `POST /api/build-graph` | Retrieves immutable PR evidence and builds the three-layer graph. |
| `POST /api/analyze-pr/{pr}` and `GET /api/report/{pr}` | Creates or reads a provenance-verified blast-radius report. |
| `GET /api/qa-analysis/{pr}?crawl_id={id}` | Verifies report/crawl evidence and generates only grounded QA cases. |
| `GET /api/graph/nodes`, `/api/graph/visualize`, `/api/requirements`, `/api/flows` | Reads the active graph and coverage results. |
| `POST /api/graph/query` | Runs a single guarded read-only Cypher query. |

Example read-only checks:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/agents
curl "http://localhost:8000/api/report/350?repo=realworld-apps/angular-realworld-example-app"
curl "http://localhost:8000/api/qa-analysis/350?crawl_id=YOUR_COMPLETED_CRAWL_ID&repo=realworld-apps/angular-realworld-example-app"
```

### 8. Evidence output and verification

Each successful run writes immutable, run-specific evidence under `data/`:

| Path | Contents |
|---|---|
| `data/artifacts/crawls/<crawl-id>/` | Crawl session metadata, full-page screenshots, and DOM snapshots. |
| `data/pr_<normalized-repo>_<pr>_*.jsonl` | Retrieved immutable PR metadata, changed files, code files, and parsed symbols. |
| `data/requirements.jsonl` | Requirements from the most recently selected public source. |
| `data/blast_radius_pr_<pr>.json` and `.md` | Deterministic graph-traversal report. |
| `data/run_manifests/<run>.json` | Hashes and provenance references for the exact evidence run. |

The reference evidence record is [docs/evidence_run_pr_350.md](docs/evidence_run_pr_350.md). It documents an actual completed run; rerunning the pipeline creates a new crawl ID and manifest rather than overwriting its provenance.

### 9. Troubleshooting

| Symptom | Meaning and resolution |
|---|---|
| `localhost:8000 refused to connect` | Neo4j alone is running. Start the dashboard/API with `docker compose up -d --build api`, then inspect `docker compose logs --tail=100 api`. |
| `dockerDesktopLinuxEngine ... file not found` | Docker Desktop is stopped. Start it and wait for `docker version` to show a Server section. |
| `BrowserType.launch: Executable doesn't exist` | The API image is missing its matching Playwright browser bundle. Pull the latest code, then rebuild/start it with `docker compose up -d --build api`; do not treat the failed crawl as evidence. |
| `Host ... is not in the configured allowlist` | Add only the intended public host to `ALLOWED_CRAWL_DOMAINS` in `.env`, then re-run the CLI or restart the API. Private and metadata IP protections remain active. |
| `Missing option --repo` or `--repo is not recognized` | A Bash `\` was pasted into Command Prompt. Use the one-line CMD command above or PowerShell backticks. |
| `Worker required` on Vercel | Expected: Vercel serverless cannot run a durable Playwright crawl. Use the Docker deployment or a dedicated browser worker. |
| No report / `409` | Treat it as an evidence gate. Check the selected document, completed crawl, Neo4j health, GitHub retrieval, and real LLM configuration; do not substitute output. |

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
