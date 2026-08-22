# TraceGraph AI Loom walkthrough (7–8 minutes)

Record this only after a complete, fresh, evidence-backed run. Do not show fixture data, an archived report from a different crawl, a failed crawl as proof, or credentials.

## Pre-recording checklist

1. Start the local stack and wait for both services to be healthy:

   ```powershell
   docker compose up -d neo4j api
   docker compose ps
   Invoke-WebRequest http://localhost:8000/api/health
   ```

2. Open `http://localhost:8000` and select one public application, its matching public documentation/README, repository, and a real PR.
3. Use a **COMPLETED** crawl with captured DOM and screenshots. Failed, timed-out, cancelled, or empty crawls are not valid evidence.
4. Keep `.env`, API keys, Neo4j credentials, and raw response headers out of the recording.
5. If using the provided RealWorld demonstration, use the same crawl, README, repository, and PR throughout the recording.

## 0:00–0:45 — Problem and safety contract

> “TraceGraph answers one narrow question: which observed product behavior is at risk from a real pull request, and what evidence connects them? It fails closed. If the browser crawl, document ingestion, GitHub evidence, or Neo4j graph is unavailable, it does not produce a best-guess impact report.”

Point out that public targets are validated server-side and crawling is bounded by screen, depth, action, and time limits.

## 0:45–1:45 — Select evidence sources

Show the target application URL, the public documentation/README URL (or pasted product text), the GitHub repository, and the real PR number.

> “The product document, live UI, and repository must refer to the same product surface. The system records source provenance; it does not use a seed requirement catalogue.”

In **Specification**, ingest the selected document. Show the extracted requirements, their source URL, testability score, and initial `UNVERIFIED` coverage. Explain that the LLM extracts candidates from sanitized, delimited document content; it does not decide the blast radius.

## 1:45–3:00 — Crawl and inspect real browser evidence

In **Web Crawler**, validate the target and run a bounded crawl. Show the live event stream until the run is **COMPLETED**.

In **Crawl Sessions**:

1. Identify the completed session and its discovered page/transition counts.
2. Open **Screens** and show one captured screenshot.
3. Open **Transitions** and show one browser-observed navigation.
4. Click **Use for Graph** for this exact completed session.

> “The crawler records DOM, screenshot, element, and transition artifacts. The graph cannot be built from a failed, timed-out, or empty crawl.”

## 3:00–4:10 — Build the three-layer graph

Click **Re-Index Graph** with the matching repository and PR selected. Show the resulting node counts and open **3-Layer Graph**.

> “The graph has three layers: requirements from the product source; observed pages, UI elements, and transitions from Playwright; and immutable PR files and parsed symbols from GitHub. The visual graph groups repeated visible controls—for example, ‘Sign in — 7 observed selectors’—only for readability. The individual selectors remain preserved in Neo4j evidence.”

Show the left-to-right path: PR → changed file/symbol → UI control → page → observed flow → requirement. Do not claim a connection that the graph does not display.

## 4:10–5:15 — Deterministic blast radius

Open **Blast Radius** and show the report.

> “This report is graph-derived. The UI count is the actual number of browser-observed selector instances, while repeated visible controls are grouped in the table and summary so a QA lead does not see misleading duplicates. Confidence comes from deterministic hop weights, not an LLM self-score.”

Choose one affected requirement and follow its evidence chain. If no graph path exists, state that the result is `INSUFFICIENT_EVIDENCE`, not ‘no risk.’

## 5:15–6:10 — QA Intelligence and human review

Open **QA Intelligence**, select the same completed crawl, and click **Verify & Generate Plan**.

> “The evidence verifier confirms the exact graph path, crawl ownership, DOM and screenshot artifacts, and an observed transition. The test generator only emits candidates supported by that evidence. The reviewer approves, rejects, or marks them `NEEDS_REVIEW`; it never invents a generic test checklist.”

Show one status, including any `NEEDS_REVIEW`, `REJECTED`, or unknowns. Explain why a human must decide it.

## 6:10–6:50 — Ambiguity and absence

Open **4-State Matrix**.

> “`COVERED` has at least two matching observed UI elements. `PARTIAL` has one. `UNVERIFIED` means this bounded crawl did not prove coverage. The schema supports `ABSENT`, but this prototype deliberately does not infer absence without an exhaustive-coverage certificate—so an unfound requirement is not falsely called absent.”

Mention unmapped code files or low-confidence mappings, if present, as explicit human-review work rather than hidden limitations.

## 6:50–7:40 — Evaluation, scope, and next week

Show the terminal and run the reproducible checks:

```powershell
python -m pytest -q
python scripts/run_eval.py --report data/blast_radius_pr_<n>.json --ground-truth reviewed_truth.json
```

Close with:

> “I chose depth in evidence-backed crawling, conservative cross-layer mapping, Neo4j traversal, and fail-closed QA verification. I cut authenticated crawling, compiler-level TypeScript call/import tracing, exhaustive-coverage certification, and a large reviewed evaluation corpus. With another week, I would add TypeScript LSP tracing, isolated authenticated crawl support, and a multi-run independently reviewed evaluation set.”

## Submission description

Use this description beside the Loom link:

> TraceGraph AI demonstrates a fresh, provenance-backed run from public product documentation through Playwright crawl artifacts, Neo4j graph construction, deterministic PR blast-radius analysis, and evidence-gated QA test planning. It intentionally refuses unsupported claims and documents its remaining scope limits.
