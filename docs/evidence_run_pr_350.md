# Evidence Run — RealWorld Angular PR #350

This is the tracked, provenance-verified sample output for the selected narrow
slice. It was generated on 2026-08-22 from a live browser crawl, the public
README, an immutable GitHub PR revision, and a Neo4j traversal. It is not
fixture or mock output.

## Inputs

- Application: `https://demo.realworld.show/`
- Public specification: `https://raw.githubusercontent.com/realworld-apps/angular-realworld-example-app/main/README.md`
- Repository: `realworld-apps/angular-realworld-example-app`
- Pull request: [#350 — Secure auth flows and harden validation across the UI](https://github.com/realworld-apps/angular-realworld-example-app/pull/350)
- Immutable PR head: `fc4380310755babb0d8c2021420d5b3e860b890c`
- Crawl session: `pipeline_20260822_124930_pr_350`
- Evidence manifest: `data/run_manifests/pipeline_20260822_124930_pr_350_pr_350.json`

## Observed Evidence

| Evidence | Count |
| --- | ---: |
| Live pages/screens | 5 |
| DOM snapshots | 5 |
| PNG screenshots | 5 |
| UI elements | 96 |
| Observed transitions | 4 |
| Extracted requirements | 3 |
| Changed code files | 7 |
| Source symbols | 5 |

The crawl visited the public home, sign-in, sign-up, profile, and article
screens. The 21-entry manifest hashes every structured crawl artifact, each
DOM snapshot, each screenshot, the requirements, GitHub PR artifacts, and the
generated report. Verification found no missing or altered file.

## Blast-Radius Result

**Overall risk: LOW.** The graph found 16 browser-observed UI elements, one
affected flow, and one requirement at risk. The paths are intentionally low
confidence (about 49%): `AuthComponent` was connected to sign-in and sign-up
controls through a deterministic auth-file semantic match, rather than a
source-level selector or test-ID match.

Verified path:

```text
PR #350
  → src/app/core/auth/auth.component.ts
  → AuthComponent (file_scope_fallback)
  → Sign in on / (file_path_semantic_match)
  → Observed crawl: demo.realworld.show
  → REQ-001: dedicated authentication screens
```

### What QA Should Test First

1. Open the public **Sign in** and **Sign up** screens from home, profile, and
   article pages; verify route navigation and form validation.
2. Check the public article’s **Favorite Article** control, because the PR also
   changes `article.component.ts` and the crawl observed this control.
3. Manually triage the changed settings, JWT service, and authenticated
   directive files that produced no high-confidence UI path in this bounded
   public crawl.

### Requirements With Bounded-Crawl Gaps

- `REQ-003` (author-only comment deletion) is **UNVERIFIED**, not absent. The
  public crawl cannot authenticate as a comment author, so it cannot make a
  claim about that conditional UI.

## Reproduce

Use a Playwright-capable Docker/worker deployment and configure the public
allowlists, Neo4j, and a real LLM provider. The command fails without evidence;
it does not substitute a report.

```powershell
python scripts/run_pipeline.py `
  --repo realworld-apps/angular-realworld-example-app `
  --pr 350 `
  --crawl-url https://demo.realworld.show/ `
  --spec-url https://raw.githubusercontent.com/realworld-apps/angular-realworld-example-app/main/README.md
```

The run produces a new, timestamped crawl ID, so artifacts from prior runs
cannot mix with the result. Neo4j is rebuilt as an active-run index, while the
browser/code/requirement artifacts and their manifest remain immutable on disk.
