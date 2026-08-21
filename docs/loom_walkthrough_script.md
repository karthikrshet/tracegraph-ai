# TraceGraph AI Loom walkthrough (7 minutes)

Record only after a complete real run. Do not show archived sample output, fixture data, or a report whose `metrics.evidence_mode` is not `neo4j_graph_traversal`.

## 0:00–0:45 — problem and contract

“TraceGraph answers a narrow question: which observed product behavior is at risk from this PR, and what exact evidence connects them? It has no offline impact mode. If a crawl, GitHub fetch, document fetch, or Neo4j is missing, the run stops rather than making up an answer.”

## 0:45–2:00 — selected evidence

Show the chosen application URL, public documentation URL, public repository, and PR. Confirm the UI and repository are the same product surface. In the dashboard, show the allowlisted URL validation, the bounded crawl configuration, and the completed crawl session. Open one screenshot and download—not render—one captured DOM artifact.

Show the extracted requirement table. Point out its source URL and source text. Explain that the document text is sanitized and delimited before LLM extraction; the LLM does not determine impact.

## 2:00–3:15 — graph construction

Show the PR on GitHub, then the build operation. Explain the layers:

- Requirements from the selected public document.
- Pages, elements, and transitions observed by Playwright.
- PR changes, immutable-head source files, and parsed symbols from GitHub.

Show Neo4j node counts. State that changed files without identifiable changed declarations remain unmapped review items; they are not forced to a UI element.

## 3:15–4:45 — one report path

Open the generated report and select one impacted requirement. Follow its actual path in the graph: PR change → source symbol → observed UI element → page → observed flow → requirement. Explain that the confidence is a deterministic product of per-hop evidence weights, not an LLM self-assessment.

If there are no impact paths, say so. This is an admissible result; it means the captured evidence did not prove a link.

## 4:45–5:30 — ambiguity and absence

Show the coverage matrix. `COVERED` means at least two observed matching elements; `PARTIAL` means one. `UNVERIFIED` means the bounded crawl did not find proof. The current system does not emit `ABSENT`: that status requires a future exhaustive-coverage certificate. Point out any unmapped changed files and the corresponding human-review recommendation.

## 5:30–6:20 — validation

Run:

```bash
python -m pytest tests -q
python scripts/run_eval.py --report data/blast_radius_pr_<n>.json --ground-truth reviewed_truth.json
```

Explain that the evaluation truth set is independently reviewed for this exact run; no hard-coded F1 score is reported.

## 6:20–7:00 — scope and next steps

“I went deep on fail-closed evidence collection, absence semantics, and deterministic graph traversal. I cut authenticated crawling, compiler-level import/call graph analysis, and exhaustive coverage certification. With another week, I would add TypeScript LSP tracing, authenticated crawl support with isolated secrets, and a reviewed multi-run evaluation set.”
