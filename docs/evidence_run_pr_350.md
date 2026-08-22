# Evidence Run — RealWorld Angular PR #350

This is the final, provenance-backed sample output for the selected narrow
slice. It was produced on 2026-08-22 from a live browser crawl, the public
Angular RealWorld README, an immutable public GitHub PR revision, and a Neo4j
traversal. It is not fixture, mock, or synthetic runtime output.

## Inputs

- Application: `https://demo.realworld.show/`
- Public specification: `https://raw.githubusercontent.com/realworld-apps/angular-realworld-example-app/main/README.md`
- Repository: `realworld-apps/angular-realworld-example-app`
- Pull request: [#350 — Secure auth flows and harden validation across the UI](https://github.com/realworld-apps/angular-realworld-example-app/pull/350)
- Immutable PR head: `fc4380310755babb0d8c2021420d5b3e860b890c`
- Completed crawl session: `crawl_20260822_192039`
- Generated report: [`data/blast_radius_pr_350.md`](../data/blast_radius_pr_350.md)

The browser session was bounded to 20 states, 40 candidate actions, and depth
4. It completed normally; its persisted records identify every page, selector,
transition, DOM path, and screenshot path used by the graph build.

## Captured Evidence

| Evidence | Count |
| --- | ---: |
| Completed live pages/screens | 20 |
| DOM snapshots | 20 |
| PNG screenshots | 20 |
| Browser-observed UI elements | 463 |
| Observed transitions | 19 |
| Extracted requirements | 3 |
| Changed code files | 7 |
| Parsed source symbols | 5 |

The crawl covered the public home, sign-in, sign-up, article, profile, and tag
surfaces. It intentionally did not authenticate or execute destructive actions.

## Blast-Radius Result

**Overall risk: LOW.** Neo4j found 50 browser-observed selector instances,
grouped into two distinct impacted control labels, one affected observed flow,
and one partially covered requirement at risk. The average impact-path confidence is about 42%:
`AuthComponent` is connected to sign-in/sign-up controls through a deterministic
file-path semantic match, not a direct template selector or test-ID link.

Verified representative path:

```text
PR #350
  → src/app/core/auth/auth.component.ts
  → AuthComponent (file-scope mapping)
  → Sign in on / (deterministic semantic mapping)
  → Observed crawl: demo.realworld.show
  → REQ-001: public authentication screens
```

### What QA Should Test First

1. From the public home, article, and profile surfaces, open **Sign in** and
   **Sign up**; verify navigation and the displayed authentication form.
2. Manually test article deletion confirmation with an authorized author
   account; the public crawl did not observe that protected control.
3. Manually triage the six changed files without a verified browser mapping,
   including article deletion, settings, JWT, authenticated-directive, and
   configuration code.

### Known Coverage Limits

- `REQ-001` is **PARTIAL**: sign-in/sign-up were observed, while authenticated
  logout was not.
- `REQ-002` (pagination and filtering) and `REQ-003` (author-only deletion)
  are **UNVERIFIED**, not absent: the crawl did not prove every required
  control or use an author account.
- The report does not claim coverage of authenticated settings/logout behavior
  or article deletion.
- Repeated controls across pages are preserved as selector instances in the
  graph and grouped by the dashboard/report renderer for QA readability.

## Reproduce

Use a Playwright-capable Docker or dedicated browser-worker deployment,
configure public allowlists, Neo4j, and a real LLM provider, then run:

```powershell
python scripts/run_pipeline.py `
  --repo realworld-apps/angular-realworld-example-app `
  --pr 350 `
  --crawl-url https://demo.realworld.show/ `
  --spec-url https://raw.githubusercontent.com/realworld-apps/angular-realworld-example-app/main/README.md
```

Each run creates a new timestamped crawl identity. Neo4j is deliberately an
active-run index, rebuilt from the selected evidence; persisted browser, PR,
requirement, report, and manifest artifacts retain their own provenance and are
never replaced with fallback/demo output.
