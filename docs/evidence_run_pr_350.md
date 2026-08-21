# Evidence Run — RealWorld Angular PR #350

This is the sample output for the selected narrow slice. It was produced from
browser artifacts, a public README, an immutable GitHub PR revision, and a
Neo4j traversal; it is not fixture output.

## Inputs

- Application: `https://angular.realworld.io/`
- Public specification: `https://raw.githubusercontent.com/realworld-apps/angular-realworld-example-app/main/README.md`
- Repository: `realworld-apps/angular-realworld-example-app`
- Pull request: [#350 — Secure auth flows and harden validation across the UI](https://github.com/realworld-apps/angular-realworld-example-app/pull/350)
- Immutable head: `fc4380310755babb0d8c2021420d5b3e860b890c`
- Crawl session: `cli_pr_350`

## Observed evidence

| Evidence | Count |
| --- | ---: |
| Pages/screens | 3 |
| DOM snapshots | 3 |
| PNG screenshots | 3 |
| UI elements | 27 |
| Transitions | 5 |
| Extracted requirements | 3 |
| Changed code files | 7 |
| Source symbols | 5 |

The crawl captured the public home, `/login`, and `/register` screens. The
graph contained 3 requirements, 3 pages, 27 UI elements, 1 observed flow, 7
code files, 5 code symbols, 7 PR changes, and 1 pull request.

## Blast-radius result

**Overall risk: LOW.** The system found 8 browser-observed UI links, one
affected flow, and one requirement link. The lower confidence is intentional:
the changed `AuthComponent` was mapped at **file scope** (the PR modifies an
existing class rather than declaring a new symbol in its patch), and its links
to Sign in/Sign up were found by a deterministic auth-path semantic heuristic.

Verified path:

```text
PR #350
  → src/app/core/auth/auth.component.ts
  → AuthComponent (file_scope_fallback)
  → Sign up on / (file_path_semantic_match)
  → Observed crawl: angular.realworld.io
  → REQ-001: login/signup authentication
```

QA should exercise public sign-in/sign-up navigation and form validation
first, then have a human review the six remaining changed files that did not
produce an end-to-end UI path. Two README requirements (article ownership and
feed filtering) remained **UNVERIFIED** because this bounded crawl did not
observe them; this is not reported as product-wide absence.

## Reproducibility

The generated run manifest at
`data/run_manifests/cli_pr_350_pr_350.json` records SHA-256 digests for every
referenced crawl artifact, requirements artifact, GitHub artifact, and report.
Run the following after configuring the matching allowlists and Neo4j:

```powershell
python scripts/run_pipeline.py `
  --repo realworld-apps/angular-realworld-example-app `
  --pr 350 `
  --crawl-url https://angular.realworld.io/ `
  --spec-url https://raw.githubusercontent.com/realworld-apps/angular-realworld-example-app/main/README.md
```

If GitHub rate-limits a subsequent run, `--reuse-verified-code` is explicit
and only accepts persisted metadata with the exact immutable head SHA; it does
not call a fake or generic fallback. `--reuse-crawl-id cli_pr_350` similarly
requires a completed, URL-matching browser session.
