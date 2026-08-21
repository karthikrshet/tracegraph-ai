"""
TraceGraph AI — Shared Data Models

All domain entities (nodes + edges) that flow through the pipeline.
Each model maps 1:1 to a Neo4j node or relationship type.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

# ─────────────────────────────────────────────
#  Enumerations
# ─────────────────────────────────────────────


class CoverageStatus(str, Enum):
    COVERED = "COVERED"
    PARTIAL = "PARTIAL"
    UNVERIFIED = "UNVERIFIED"
    ABSENT = "ABSENT"


class ConfidenceTier(str, Enum):
    HIGH = "HIGH"  # 0.90 – 1.00
    MEDIUM = "MEDIUM"  # 0.70 – 0.89
    LOW = "LOW"  # 0.40 – 0.69
    UNVERIFIED = "UNVERIFIED"  # 0.00 – 0.39

    @classmethod
    def from_score(cls, score: float) -> ConfidenceTier:
        if score >= 0.90:
            return cls.HIGH
        elif score >= 0.70:
            return cls.MEDIUM
        elif score >= 0.40:
            return cls.LOW
        return cls.UNVERIFIED


class EvidenceType(str, Enum):
    SEMANTIC_MATCH = "semantic_match"
    NAME_MATCH = "name_match"
    COMPONENT_REFERENCE = "component_reference"
    AST_IMPORT = "ast_import"
    MANUAL = "manual"


class ChangeType(str, Enum):
    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"
    RENAMED = "renamed"


# ─────────────────────────────────────────────
#  Layer 1: Requirements
# ─────────────────────────────────────────────


class Requirement(BaseModel):
    """Parsed from product documentation / PRD."""

    id: str
    text: str
    category: str  # e.g. "product", "cart", "checkout", "auth"
    source_url: str = ""
    source_text: str = ""  # verbatim source paragraph
    testability_score: float = Field(0.0, ge=0.0, le=1.0)
    coverage_status: CoverageStatus = CoverageStatus.UNVERIFIED
    extracted_at: datetime = Field(default_factory=datetime.utcnow)


# ─────────────────────────────────────────────
#  Layer 2: UI / DOM
# ─────────────────────────────────────────────


class UIElement(BaseModel):
    """An interactable DOM element captured during crawl."""

    id: str
    page_id: str
    selector: str  # CSS selector
    label: str  # human-readable semantic label (LLM-assigned)
    element_type: str  # button, input, link, form, etc.
    text_content: str = ""
    aria_label: str = ""
    data_test_id: str = ""  # data-test-id attribute if present
    bounding_box: dict[str, float] = Field(default_factory=dict)
    is_interactive: bool = True
    captured_at: datetime = Field(default_factory=datetime.utcnow)


class Page(BaseModel):
    """A captured page state from the crawler."""

    id: str
    url: str
    title: str
    screenshot_path: str = ""
    dom_path: str = ""  # path to saved DOM snapshot
    flow_id: str = ""
    step_order: int = 0
    captured_at: datetime = Field(default_factory=datetime.utcnow)


class Transition(BaseModel):
    """Navigation between pages triggered by a UI element."""

    id: str
    from_page_id: str
    to_page_id: str
    trigger_element_id: str = ""
    interaction_type: str = "click"  # click, form_submit, navigation
    action_label: str = ""
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class UserFlow(BaseModel):
    """A named user journey composed of pages + transitions."""

    id: str
    name: str
    description: str
    steps: list[str] = Field(default_factory=list)  # ordered page IDs
    requirement_ids: list[str] = Field(default_factory=list)


# ─────────────────────────────────────────────
#  Layer 3: Code
# ─────────────────────────────────────────────


class CodeFile(BaseModel):
    """A source file in the repository."""

    path: str  # repo-relative path
    language: str  # typescript, javascript, python, etc.
    component_name: str = ""  # inferred React component name if applicable
    last_modified: str = ""
    size_bytes: int = 0


class CodeSymbol(BaseModel):
    """A function, class, constant, or component extracted via AST."""

    fqn: str  # fully-qualified name: e.g. "Attributes.DropdownRow"
    name: str
    symbol_type: str  # function, class, arrow_function, component, hook
    file_path: str
    start_line: int
    end_line: int
    exported: bool = False
    is_component: bool = False  # React component heuristic
    is_hook: bool = False  # starts with "use"


# ─────────────────────────────────────────────
#  Cross-layer Edges (as evidence bundles)
# ─────────────────────────────────────────────


class Evidence(BaseModel):
    """Provenance record attached to any cross-layer edge."""

    evidence_type: EvidenceType
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    confidence_tier: ConfidenceTier = ConfidenceTier.UNVERIFIED
    source_ref: str = ""  # file:line or url
    source_text: str = ""
    matcher: str = ""  # method used (e.g. "embedding", "name_match")
    observed_at: datetime = Field(default_factory=datetime.utcnow)

    def model_post_init(self, __context: Any) -> None:
        self.confidence_tier = ConfidenceTier.from_score(self.confidence)


class RequirementUIEdge(BaseModel):
    """COVERS edge: Requirement → UIElement."""

    requirement_id: str
    ui_element_id: str
    evidence: Evidence


class UICodeEdge(BaseModel):
    """IMPLEMENTED_BY edge: UIElement → CodeSymbol."""

    ui_element_id: str
    code_symbol_fqn: str
    evidence: Evidence


class FlowRequirementEdge(BaseModel):
    """REQUIRES edge: UserFlow → Requirement."""

    flow_id: str
    requirement_id: str


# ─────────────────────────────────────────────
#  PR Analysis
# ─────────────────────────────────────────────


class PullRequest(BaseModel):
    """GitHub Pull Request metadata."""

    number: int
    title: str
    author: str
    body: str = ""
    base_branch: str = "main"
    head_sha: str = ""
    merged_at: datetime | None = None
    html_url: str = ""


class PRChange(BaseModel):
    """A single file changed in a PR."""

    id: str
    pr_number: int
    file_path: str
    change_type: ChangeType
    additions: int = 0
    deletions: int = 0
    patch: str = ""  # raw diff patch
    changed_symbols: list[str] = Field(default_factory=list)  # detected symbol names


# ─────────────────────────────────────────────
#  Blast Radius Report
# ─────────────────────────────────────────────


class ImpactedItem(BaseModel):
    """One item in the blast-radius output."""

    item_type: str  # "UIElement" | "UserFlow" | "Requirement"
    item_id: str
    label: str
    risk_level: str  # HIGH | MEDIUM | LOW
    confidence: float
    confidence_tier: ConfidenceTier
    evidence_chain: list[
        str
    ]  # human-readable path e.g. ["PR#6857", "DropdownRow.tsx", "Add to Cart"]
    raw_path: list[dict[str, str]] = Field(default_factory=list)  # graph node hops


class BlastRadiusReport(BaseModel):
    """Full blast-radius report for a PR."""

    pr_number: int
    pr_title: str
    pr_url: str
    author: str = "contributor"
    overall_risk: str  # HIGH | MEDIUM | LOW | NONE
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    changed_files: list[str]
    impacted_ui_elements: list[ImpactedItem]
    impacted_flows: list[ImpactedItem]
    impacted_requirements: list[ImpactedItem]
    absent_requirements: list[str]  # requirements with no UI coverage that PR may affect
    summary: str = ""  # LLM-generated human-readable summary
    recommendation: str = ""  # LLM-generated QA recommendation
    metrics: dict[str, Any] = Field(default_factory=dict)
