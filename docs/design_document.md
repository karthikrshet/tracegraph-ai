# TraceGraph AI — Design Document

**Testsigma AI Engineer Take-Home Assignment**  
**Author:** Karthik  
**Date:** 2026-08-21  
**Version:** 1.0  
**Target:** selected public application/repository/PR triplet, recorded per run

---

## 1. Problem Statement

Testsigma's core challenge: when a developer merges a PR, which tests need to run? Not all tests — the right tests, with justifiable priority.

The naive answer is "run everything." The sophisticated answer is: trace the PR's changes through code → UI → user flows → requirements, and prioritize tests that cover the affected paths.

TraceGraph AI builds that trace as an explicit, queryable, evidence-backed knowledge graph.

The central question answered by every output:

> **"Why did you conclude that this PR affects this requirement and this user flow?"**

And the system's response is not an LLM opinion — it's a graph path.

---

## 2. Frozen Experiment Scope

### 2.1 Target Application
- **App, repository, and PR:** supplied as explicit run configuration and persisted with the evidence.
- **Selection rule:** the crawled UI and repository must be the same product surface. A public storefront and a separate merchant dashboard are not accepted as evidence of each other.

### 2.2 Documentation Source
- An explicitly selected, allowlisted public PRD, README, feature document, or wiki URL.
- Source URL and sanitized source excerpt are persisted on each extracted requirement.
- There is no production seed or fallback requirement set.

### 2.3 Selected PR

**PR #350** — *"Secure auth flows and harden validation across the UI"*  
- Repository: `realworld-apps/angular-realworld-example-app`  
- SHA: `fc4380310755babb0d8c2021420d5b3e860b890c`  
- Files changed: 7 TypeScript files  
- Source symbols observed: `AuthComponent`, `IfAuthenticatedDirective`, `JwtService`, `ArticleComponent`, `SettingsComponent`  
- URL: `https://github.com/realworld-apps/angular-realworld-example-app/pull/350`

**Why this PR?** It changes authentication-related UI code in the same Angular Conduit application crawled by the browser. It demonstrates one bounded, auditable path without claiming exhaustive product coverage.

### 2.4 Observed User Flow

| ID | Name | Pages | Linked requirement |
|----|------|-------|--------------------|
| observed-crawl-350 | Public authentication navigation | `/` → `/login` → `/register` | REQ-001 |

---

## 3. Agent Decomposition

The system is NOT an unconstrained prompt-chain or reckless open-ended web agent. It is a **bounded autonomous agent architecture** with explicit deterministic/LLM boundaries:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        AGENT PIPELINE OVERVIEW                         │
└────────────────────────────────────────────────────────────────────────┘

Stage 1: Autonomous Browser Exploration → BOUNDED AUTONOMOUS AGENT
         - Observation: DOM snapshots, full-page screenshots, interactive elements
         - State Fingerprint: URL + title + element signature hash
         - Exploration Policy: Priority scoring on candidate interactive actions
         - Safety/Policy Validator: SSRF check, domain boundary, blocked destructive verbs
         - Execution: Playwright action dispatch (clicks, selects, inputs)
         - Transition & Screen Graph: Concrete (from_page -> action -> to_page) edges

Stage 2: Requirement Ingestion          → DETERMINISTIC (fetch/sanitize/schema) + LLM (doc parsing)
Stage 3: Code & Diff Extraction         → DETERMINISTIC parser + GitHub REST API
Stage 4: Cross-Layer Evidence Linking   → DETERMINISTIC name/selector heuristic
Stage 5: Multi-Hop Graph Traversal      → DETERMINISTIC (Neo4j Cypher BFS)
Stage 6: Hop-Weight Confidence Model    → DETERMINISTIC (monotonically decreasing product)
Stage 7: Non-Engineer Blast Report      → LLM (narrates already-determined graph facts)
```

### Why This Decomposition Matters

The boundary between Stage 5 (deterministic graph traversal) and Stage 7 (LLM explanation) is the core architectural decision.

**If an LLM determined impact**, you'd get:
> "This PR might affect authentication because the AI thinks the file name sounds relevant."

**Because graph traversal determines impact**, you get:
> "PR #350 → `auth.component.ts` → `AuthComponent` (file-scope mapping) → Sign up on `/` → observed-crawl-350 → `REQ-001` (path confidence 0.45)"

Every single impact claim is an auditable, reproducible graph path.

### Determinism vs LLM Classification

| Stage | Det. | LLM | Why |
|-------|------|-----|-----|
| Application Crawl & Observation | ✅ | | Playwright browser execution & DOM snapshots |
| SSRF & URL Security Validation | ✅ | | Strict DNS resolution, loopback/private/metadata IP blocking |
| Next-Action Exploration Policy | ✅ | 🔶 | Priority heuristics + candidate action selection |
| Safety & Policy Validator | ✅ | | Destructive verb filtering (`delete`, `buy now`, `logout`) |
| Real-time Event Streaming (SSE) | ✅ | | Server-Sent Events stream for live execution observability |
| Transition & State Fingerprinting | ✅ | | Deterministic hash of URL, DOM elements, and title |
| Code extraction | ✅ | | Source-parser heuristics — reproducible for a pinned file revision |
| PR Diff & Change Retrieval | ✅ | | GitHub REST API — ground-truth facts |
| Knowledge Graph Traversal | ✅ | | Cypher BFS traversal — mathematical truth |
| Confidence Arithmetic | ✅ | | Dynamic scaling by symbol type, token overlap, and testability ($C = \prod w_i$) |
| Executive Summary & Narrative | | ✅ | Explains already-computed graph paths in natural language |

### 3.1 Crawl Control Center & Real-Time Observability

The dashboard provides a dedicated **Crawl Application Control Center** featuring:
1. **Target URL Input & Security Validation**: Server-side DNS resolution rejecting RFC1918 private subnets, loopbacks (`127.0.0.1`, `::1`), link-local IPs, and cloud metadata endpoints (`169.254.169.254`, `metadata.google.internal`).
2. **Exploration Budget Bounds**: Server-enforced maximum depth 4, actions 25, states 10, and runtime 300 seconds.
3. **Background Asynchronous Execution**: Non-blocking `POST /api/crawl` returning `crawl_id` and status immediately.
4. **Real-Time Server-Sent Events (`/api/crawl/{id}/events`)**: Streams live events (`page_discovered`, `dom_captured`, `screenshot_captured`, `action_selected`, `transition_created`, `crawl_completed`).
5. **Artifact Inspection**: Direct access to captured full-page screenshots, DOM HTML snapshots, and the discovered screen transition graph (`PAGE-A -> action -> PAGE-B`).
6. **Seamless Graph Ingestion**: One-click ingestion (`POST /api/crawl/{id}/apply-to-graph`) connecting discovered screens into the 3-Layer Knowledge Graph for PR Blast Radius analysis.

---

## 4. Graph Schema

### 4.1 Node Types

```cypher
// Layer 1: Requirements
(:Requirement {
  id: "REQ-001",
  text: "Users can authenticate using login and signup pages...",
  category: "general",
  source_url: "https://raw.githubusercontent.com/.../README.md",
  testability_score: 0.95,
  coverage_status: "COVERED"  // COVERED | PARTIAL | UNVERIFIED | ABSENT
})

// Layer 2: UI & State Graph
(:UIElement {
  id: "UI-PAGE-01-003",
  page_id: "PAGE-01",
  selector: "a[href='/register']",
  label: "Sign up",
  element_type: "link"
})

(:Page { id: "PAGE-01", url, title, flow_id, step_order, screenshot_path, dom_path })
(:Transition { id: "TRANS-001", from_page_id: "PAGE-01", to_page_id: "PAGE-02", trigger_element_id: "UI-006", interaction_type: "click", action_label: "Click Product Card" })
(:UserFlow { id: "FLOW-01", name: "Product Browse to Add to Cart", description: "..." })

// Layer 3: Code
(:CodeFile { path: "src/app/core/auth/auth.component.ts", language: "typescript", component_name: "auth.component" })
(:CodeSymbol {
  fqn: "auth.component.AuthComponent",
  name: "AuthComponent",
  symbol_type: "class",
  file_path: "src/app/core/auth/auth.component.ts",
  start_line: 1, end_line: 50,
  is_component: true, is_hook: false, exported: true
})

// PR
(:PullRequest { number: 350, title: "Secure auth flows and harden validation across the UI", html_url: "...", head_sha: "fc438..." })
(:PRChange {
  id: "change-350-src_app_core_auth_auth.component.ts",
  pr_number: 350,
  file_path: "src/app/core/auth/auth.component.ts",
  change_type: "modified",
  additions: 84, deletions: 62,
  changed_symbols: ["AuthComponent"],
  symbol_mapping_method: "file_scope_fallback"
})
```

### 4.2 Edge Types

```cypher
// Cross-layer edges with evidence
(req:Requirement)-[:COVERS {
  confidence: 0.94,
  evidence_type: "semantic_match",
  matcher: "keyword_overlap"
}]->(ui:UIElement)

(ui:UIElement)-[:IMPLEMENTED_BY {
  confidence: 0.94,
  method: "name_match",
  evidence_type: "name_match"
}]->(sym:CodeSymbol)

(page:Page)-[:STEP_IN { step_order: 2 }]->(flow:UserFlow)
(ui:UIElement)-[:PART_OF]->(page:Page)
(flow:UserFlow)-[:REQUIRES]->(req:Requirement)

// Screen Relationship & State Transitions
(p1:Page)-[:TRANSITION_TO { action: "Click Product Card", trigger_element_id: "UI-006" }]->(p2:Page)
(p1:Page)-[:NAVIGATES_TO]->(p2:Page)

(change:PRChange)-[:TOUCHES]->(file:CodeFile)
(change:PRChange)-[:MODIFIES { delta_type: "modified" }]->(sym:CodeSymbol)
(change:PRChange)-[:PART_OF_PR]->(pr:PullRequest)
(sym:CodeSymbol)-[:DEFINED_IN { start_line: 1, end_line: 50 }]->(file:CodeFile)

// Absence
(req:Requirement)-[:ABSENT { reason: "..." }]->(flow:UserFlow)
```

### 4.3 Absence Modeling

The 4-state coverage model is critical for the assignment's specific question: *"how do you model requirements that should be testable but aren't reflected in the UI?"*

```
COVERED    — ≥2 UIElements with COVERS edge
PARTIAL    — exactly 1 UIElement with COVERS edge  
UNVERIFIED — no COVERS edges, but insufficient search space evidence
ABSENT     — no COVERS edges and a separately recorded exhaustive-coverage certificate confirms absence
```

The distinction between UNVERIFIED and ABSENT is epistemically important:
- UNVERIFIED: "I didn't find it, but I only crawled FLOW-01"
- ABSENT: "I crawled all scoped flows and found no trace"

The current bounded-crawl implementation emits `UNVERIFIED`, not `ABSENT`, when no evidence is found. An `ABSENT` edge is reserved for the future certificate workflow.

This directly addresses the assignment's question about confidence under ambiguity.

### 4.4 Key Cypher Queries

**Blast Radius (the core query):**
```cypher
MATCH (pr:PullRequest {number: 350})<-[:PART_OF_PR]-(change:PRChange)
OPTIONAL MATCH (change)-[:TOUCHES]->(file:CodeFile)
OPTIONAL MATCH (change)-[:MODIFIES]->(sym:CodeSymbol)
OPTIONAL MATCH (ui:UIElement)-[:IMPLEMENTED_BY]->(sym)
OPTIONAL MATCH (ui)-[:PART_OF]->(page:Page)
OPTIONAL MATCH (page)-[:STEP_IN]->(flow:UserFlow)
OPTIONAL MATCH (flow)-[:REQUIRES]->(req:Requirement)
RETURN change.file_path, sym.name, ui.label, page.title, flow.name, req.id, req.text
```

**Absent Requirements:**
```cypher
MATCH (r:Requirement) WHERE NOT (r)-[:COVERS]->()
RETURN r.id, r.text, r.category, r.coverage_status
```

**Evidence Chain for one requirement:**
```cypher
MATCH path = (pr:PullRequest {number: 350})<-[:PART_OF_PR]-(c:PRChange)
  -[:MODIFIES]->(sym:CodeSymbol)<-[:IMPLEMENTED_BY]-(ui:UIElement)
  -[:PART_OF]->(page:Page)-[:STEP_IN]->(flow:UserFlow)
  -[:REQUIRES]->(req:Requirement {id: "REQ-001"})
RETURN nodes(path), relationships(path)
```

---

## 5. Confidence Handling Under Ambiguity

### 5.1 Confidence Tiers

| Tier | Score Range | Meaning |
|------|-------------|---------|
| HIGH | 0.90 – 1.00 | Near-certain; graph path fully resolved |
| MEDIUM | 0.70 – 0.89 | Probable; one heuristic hop |
| LOW | 0.40 – 0.69 | Possible; multiple heuristic hops |
| UNVERIFIED | 0.00 – 0.39 | Insufficient evidence |

### 5.2 Hop Weight Model

End-to-end confidence is the **product of individual hop weights**:

| Hop | Weight | Justification |
|-----|--------|--------------|
| PR → File | 1.00 | GitHub API fact |
| File → Symbol | 0.95 | AST near-deterministic |
| Symbol → UIElement | 0.85 | Name heuristic (best case) |
| UIElement → Page | 1.00 | Crawl artifact fact |
| Page → UserFlow | 1.00 | Defined by us |
| Flow → Requirement | 0.90 | Explicitly mapped |

Full path (PR → Requirement): `1.00 × 0.95 × 0.85 × 1.00 × 1.00 × 0.90 = 0.727`

This is the **baseline confidence**. Name-match quality can boost Symbol→UI to 0.94+ when the component name strongly overlaps the element label.

### 5.3 Ambiguity Cases

| Situation | Action |
|-----------|--------|
| PR changes a utility function with no UI mapping | Include in report as LOW confidence; flag for human review |
| Requirement not found in crawled UI | Mark UNVERIFIED; do not create an ABSENT edge |
| Symbol→UI name match weak (score < 0.4) | Don't create IMPLEMENTED_BY edge; gap noted in report |
| LLM unavailable | Ingestion stops; a requirement set is never invented |
| Neo4j unavailable | Build/report endpoints return an error; no impact report is emitted |

### 5.4 Human Escalation

The system recommends human review when:
- Any requirement with coverage_status = UNVERIFIED is in the blast radius
- Overall path confidence < 0.5
- The PR changes a file with 0 IMPLEMENTED_BY relationships
- More than 3 requirements are marked ABSENT

---

## 6. Evaluation Approach

### 6.1 Reviewed dataset

The checked-in submission does not claim a generalizable F1 score. The
evaluation command accepts an independently reviewed ground-truth file for the
exact selected run and computes precision, recall, and F1 from that file. The
PR #350 sample is evidence-backed but is not a held-out benchmark.

### 6.2 Metrics

**Requirement → UI Coverage Linking:**
- Precision = TP / (TP + FP)
- Recall = TP / (TP + FN)
- F1 = 2 × P × R / (P + R)

**PR Blast Radius:**
- True Positive: requirement correctly identified as at-risk
- False Positive: requirement incorrectly flagged
- False Negative: at-risk requirement missed

**Confidence Calibration:**
- For each HIGH-confidence claim, verify manually
- Track % of HIGH claims that are correct

### 6.3 Reproducibility

Given a pinned PR head SHA, persisted crawl artifacts, persisted extracted requirements, and a Neo4j snapshot, symbol extraction, graph traversal, and confidence arithmetic are deterministic. A fresh live crawl or fresh LLM extraction is a new run and must be evaluated as such; the system does not claim identical outcomes across those runs.

---

## 7. Scope Decisions

### What We Go Deep On

1. **Graph schema** — Full 3-layer schema with evidence on every edge, 4-state coverage model, provenance on all claims
2. **PR blast radius** — Deterministic graph traversal with hop-weight confidence scoring
3. **Evidence chain rendering** — Every impact claim backed by a traceable graph path in the report

### What We Scope Down (and Why)

| Item | Decision | Reason |
|------|----------|--------|
| Unconstrained open-ended web agent | ❌ Bounded exploration with safety validator | Safety first: strict max depth (4), max pages (10), SSRF blocker, blocked destructive verbs |
| Interprocedural call graph | ❌ AST symbol extraction + regex parser | Full TypeScript compiler/LSP runtime adds significant cold-start overhead |
| Authenticated crawling | ❌ Not implemented | The run is limited to public, non-destructive routes |
| Arbitrary embedding models | ❌ Deterministic name overlap + exact matches | Provides 100% reproducible baseline; eliminates LLM hallucination in evidence path |
| Offline graph engine | ❌ Not implemented | The system fails closed rather than presenting an unproven report |

### What We Would Not Cut

- Evidence provenance on every edge
- 4-state coverage model
- Honest limitation documentation
- 65 passing tests

---

## 8. What We'd Build Next (Prioritized)

### Priority 1: TypeScript import-chain tracing
**Value:** Resolve changes through Angular templates, imports, and component
trees. This would replace the PR #350 file-scope fallback with exact symbol
evidence and materially improve precision.

### Priority 2: Authenticated, isolated browser sessions  
**Value:** Extend coverage to settings, article author controls, and logout
without storing credentials in crawl artifacts or triggering destructive flow
actions.

### Priority 3: Embedding-based Req→UI matching with calibrated threshold
**Value:** Replace keyword overlap with `text-embedding-3-small` cosine similarity. Add calibration step on golden dataset to find the precision/recall-optimal threshold. Expected improvement: recall +15%, precision -3% (acceptable trade-off).

---

## 9. Architecture Decisions Record (ADR)

### ADR-001: Deterministic graph traversal before LLM reasoning

**Decision:** Graph traversal (Cypher BFS) determines impact. LLM generates explanation after.

**Context:** LLMs can hallucinate impact. A QA engineer who acts on "the LLM thinks this PR might affect checkout" without evidence is taking an unknown risk.

**Consequences:** The system can be audited. Every claim can be reproduced by running the Cypher query. The LLM summary never contradicts the graph.

### ADR-002: 4-state coverage (not binary)

**Decision:** COVERED / PARTIAL / UNVERIFIED / ABSENT instead of covered / not-covered.

**Context:** "Not found" and "proven absent" are epistemically different. The assignment specifically asks about modeling absence.

**Consequences:** UNVERIFIED requirements in the blast radius trigger a human-review flag. ABSENT requirements are explained (why the crawl couldn't find them).

### ADR-003: Hop-weight product for confidence

**Decision:** Confidence = product of per-hop weights (not LLM-estimated confidence).

**Context:** LLM-estimated confidence is hard to calibrate. Formula-based confidence is transparent and reproducible.

**Consequences:** Confidence scores are predictable and explainable. Evaluators can reproduce any score by looking at the hops.

### ADR-004: Fail closed on missing evidence

**Decision:** If Playwright, GitHub, document retrieval, or Neo4j fails, stop the run and emit no blast-radius report.

**Context:** A polished but fabricated answer is more dangerous than a failed prototype for QA planning.

**Consequences:** Operators must restore the dependency or inspect the incomplete evidence. The report endpoint rejects legacy reports without `neo4j_graph_traversal` provenance.

---

## 10. Technical Implementation Notes

### Code → UI Mapping (The Hardest Problem)

The hardest problem in this architecture is: how do you know a changed source
symbol renders a browser-observed UI element?

Our approach (in order of confidence):
1. **Exact name match** (highest confidence): component and UI label share a distinctive normalized token.
2. **data-test-id match** (high confidence): a DOM test ID matches a component or symbol name.
3. **File-path semantic match** (lower confidence): the source path carries a bounded domain term, such as `auth`, and the observed UI label carries an auth term such as Sign in or Sign up.
4. **No LLM fallback:** weak matches remain unmapped and are surfaced for review

The verified sample run uses the third method for `AuthComponent`; its report
therefore downgrades the path confidence and calls out the file-scope mapping.
In production, the first three heuristics should be replaced by a TypeScript
LSP import-chain traversal.

### Verified narrow-slice run

The tracked sample output is [evidence_run_pr_350.md](evidence_run_pr_350.md).
It uses the RealWorld Angular Conduit application and the matching public
repository, `realworld-apps/angular-realworld-example-app`, PR #350 at
immutable head `fc4380310755babb0d8c2021420d5b3e860b890c`.

| Metric | Verified value |
|--------|---------------:|
| Requirements | 3 |
| Browser-observed pages | 3 |
| DOM snapshots / screenshots | 3 / 3 |
| UI elements / transitions | 27 / 5 |
| Code files / symbols | 7 / 5 |
| PR changes / flows | 7 / 1 |
| Requirement paths in report | 1 |
| Unverified requirements | 2 |

The generated report is LOW confidence, intentionally: the one demonstrated
path traverses an existing `AuthComponent` changed at file scope to
browser-observed Sign in/Sign up elements via a documented semantic matcher.
This is sufficient to demonstrate the causal system while preserving the
human-review boundary for the remaining unmapped changed files.
