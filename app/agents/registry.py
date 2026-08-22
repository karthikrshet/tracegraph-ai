"""Explicit agent boundaries; agents do not have authority to create facts."""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentDefinition(BaseModel):
    """Public contract for one bounded reasoning stage."""

    name: str
    purpose: str
    input_schema: str
    output_schema: str
    tools: list[str] = Field(default_factory=list)
    deterministic: bool
    requires_evidence: bool = True
    failure_behavior: str
    human_escalation: str


_AGENTS = (
    AgentDefinition(
        name="crawl_agent",
        purpose="Plans bounded safe navigation and records browser-observed artifacts.",
        input_schema="Validated public URL and crawl limits",
        output_schema="CrawlSession with pages, elements, transitions, DOM and screenshots",
        tools=["Playwright", "SSRF validator"],
        deterministic=True,
        failure_behavior="CRAWL_UNAVAILABLE; no browser evidence is substituted.",
        human_escalation="Blocked authentication, destructive action, or exhausted crawl budget.",
    ),
    AgentDefinition(
        name="requirement_agent",
        purpose="Extracts testable requirement candidates from a public source with provenance.",
        input_schema="Public documentation URL or pasted product text",
        output_schema="Requirement records with verbatim source evidence and testability",
        tools=["Safe document fetch", "LLM extraction"],
        deterministic=False,
        failure_behavior="REQUIREMENTS_UNAVAILABLE or UNVERIFIED; no fabricated requirements.",
        human_escalation="Source is ambiguous, inaccessible, or contains insufficient product intent.",
    ),
    AgentDefinition(
        name="code_agent",
        purpose="Retrieves immutable PR evidence and extracts source symbols using parsers.",
        input_schema="GitHub repository, PR number, immutable head SHA",
        output_schema="PR metadata, changed files, patches, AST symbols",
        tools=["GitHub API", "Tree-sitter"],
        deterministic=True,
        failure_behavior="PR_EVIDENCE_UNAVAILABLE; no inferred files or symbols.",
        human_escalation="GitHub retrieval fails or a changed file cannot be parsed.",
    ),
    AgentDefinition(
        name="mapping_agent",
        purpose="Builds conservative code-to-UI candidates from real selectors, labels and source paths.",
        input_schema="Observed UI elements and parsed code symbols",
        output_schema="Graph IMPLEMENTED_BY relationships with method and confidence",
        tools=["Deterministic token and path matcher"],
        deterministic=True,
        failure_behavior="UNVERIFIED mapping; no semantic guess is promoted to a fact.",
        human_escalation="Mapping has weak confidence or lacks a direct selector/test-ID anchor.",
    ),
    AgentDefinition(
        name="impact_agent",
        purpose="Traverses the evidence graph to determine candidate blast radius.",
        input_schema="Current graph relationships and immutable PR evidence",
        output_schema="BlastRadiusReport with raw graph paths and confidence arithmetic",
        tools=["Neo4j"],
        deterministic=True,
        failure_behavior="GRAPH_UNAVAILABLE; no offline best-guess report.",
        human_escalation="Changed file has no verified route to browser-observed UI.",
    ),
    AgentDefinition(
        name="evidence_verifier",
        purpose="Rejects QA claims whose graph path, crawl entity, selector, or artifacts cannot be verified.",
        input_schema="Provenance-verified report and matching completed crawl session",
        output_schema="Claim verdicts: VERIFIED, NEEDS_REVIEW, REJECTED, or INSUFFICIENT_EVIDENCE",
        tools=["Artifact existence checks", "Path-shape validator"],
        deterministic=True,
        failure_behavior="INSUFFICIENT_EVIDENCE; no claim is accepted.",
        human_escalation="Confidence below policy threshold or incomplete evidence chain.",
    ),
    AgentDefinition(
        name="test_generator",
        purpose="Creates regression-test candidates only from verified browser transitions and impacted UI.",
        input_schema="Verified claim verdicts and observed crawl transitions",
        output_schema="Traceable QA test candidates with concrete routes, selectors, and PR evidence",
        tools=["Deterministic test planner"],
        deterministic=True,
        failure_behavior="NOT_GENERATED when no observed interaction supports a test.",
        human_escalation="A candidate lacks an observed destination or has weak impact confidence.",
    ),
    AgentDefinition(
        name="test_reviewer",
        purpose="Checks generated test traceability, observability, evidence completeness and duplication.",
        input_schema="QA test candidates and evidence verdicts",
        output_schema="APPROVED, NEEDS_REVIEW, or REJECTED test decisions",
        tools=["Deterministic policy rules"],
        deterministic=True,
        failure_behavior="REJECTED or NEEDS_REVIEW; no unsupported test is approved.",
        human_escalation="Any candidate below the confidence threshold or with a missing artifact.",
    ),
    AgentDefinition(
        name="test_humanizer",
        purpose="Renders approved or review-required technical tests in QA-friendly language without changing facts.",
        input_schema="Reviewed traceable QA tests",
        output_schema="Human-readable steps and expected browser-observed outcomes",
        tools=["Deterministic renderer"],
        deterministic=True,
        failure_behavior="NOT_GENERATED when there is no reviewed test.",
        human_escalation="Review-required tests remain labelled for human QA validation.",
    ),
)


def list_agents() -> list[AgentDefinition]:
    """Return stable public metadata for every bounded pipeline stage."""
    return list(_AGENTS)


def get_agent(name: str) -> AgentDefinition | None:
    """Find one agent contract by its stable public name."""
    return next((agent for agent in _AGENTS if agent.name == name), None)
