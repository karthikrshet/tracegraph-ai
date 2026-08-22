"""Verified public inputs that make manual TraceGraph evaluation repeatable.

These are **configuration shortcuts**, not persisted crawl, requirement, graph,
or report data. Selecting one in the dashboard only fills the four inputs a
user would otherwise type. Every run still fetches the live URL, reads the
public document, retrieves the PR at its current immutable head SHA, and
creates new evidence artifacts.

The profiles are deliberately small. A single Neo4j index represents one
explicit evidence run, so operators must run profiles one at a time rather
than combining unrelated products in one graph.
"""

from __future__ import annotations

from typing import Final

from pydantic import BaseModel, Field, HttpUrl


class ExampleProfile(BaseModel):
    """A real, publicly reachable application / document / PR triplet."""

    id: str = Field(pattern=r"^[a-z0-9-]+$")
    name: str
    description: str
    application_url: HttpUrl
    documentation_url: HttpUrl
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    pr_number: int = Field(gt=0)
    pr_url: HttpUrl
    constraints: str


# Verified 2026-08-23 through the public GitHub REST API and public HTTP
# endpoints. Do not add a profile merely because its URLs look plausible.
EXAMPLE_PROFILES: Final[tuple[ExampleProfile, ...]] = (
    ExampleProfile(
        id="realworld-angular-pr-350",
        name="Conduit (Angular) — PR #350",
        description="Authentication UI hardening in the open-source RealWorld Conduit application.",
        application_url="https://demo.realworld.show/",
        documentation_url="https://raw.githubusercontent.com/realworld-apps/angular-realworld-example-app/main/README.md",
        repository="realworld-apps/angular-realworld-example-app",
        pr_number=350,
        pr_url="https://github.com/realworld-apps/angular-realworld-example-app/pull/350",
        constraints="Recommended assignment demonstration. Public unauthenticated pages are crawlable; authenticated-only assertions require a separately authorized test account.",
    ),
    ExampleProfile(
        id="react-admin-pr-11339",
        name="React Admin — PR #11339",
        description="Accessibility change for sorted data-table headers in the public React Admin demo.",
        application_url="https://marmelab.com/react-admin-demo/",
        documentation_url="https://raw.githubusercontent.com/marmelab/react-admin/master/README.md",
        repository="marmelab/react-admin",
        pr_number=11339,
        pr_url="https://github.com/marmelab/react-admin/pull/11339",
        constraints="The public demo is a current deployment, not a historical PR preview. Treat a missing source-to-UI mapping as UNVERIFIED, not as a failed requirement.",
    ),
    ExampleProfile(
        id="calcom-pr-14000",
        name="Cal.com — PR #14000",
        description="Organisation event-type locking in the public Cal.com scheduling product.",
        application_url="https://app.cal.com/",
        documentation_url="https://raw.githubusercontent.com/calcom/cal.diy/main/README.md",
        repository="calcom/cal.diy",
        pr_number=14000,
        pr_url="https://github.com/calcom/cal.diy/pull/14000",
        constraints="The public crawl reaches the login surface only. The organisation feature itself needs an authorized test account, so any protected-path impact remains UNVERIFIED.",
    ),
)


def list_example_profiles() -> list[ExampleProfile]:
    """Return a copy-safe, ordered list for the dashboard/API."""
    return list(EXAMPLE_PROFILES)
