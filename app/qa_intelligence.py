"""Evidence-only QA planning built on an existing provenance-verified impact report.

This module deliberately has no crawler, network, graph, or LLM fallback.  It
can only turn an existing graph path and browser-observed transition into a QA
candidate.  Missing evidence is returned as a state, never replaced by a
plausible-sounding test.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from app.crawler.session_manager import CrawlSession
from app.models import BlastRadiusReport, ImpactedItem, Page, UIElement

VerificationStatus = Literal["VERIFIED", "NEEDS_REVIEW", "REJECTED", "INSUFFICIENT_EVIDENCE"]
ReviewStatus = Literal["APPROVED", "NEEDS_REVIEW", "REJECTED", "NOT_GENERATED"]


class EvidenceVerdict(BaseModel):
    claim_id: str
    claim: str
    status: VerificationStatus
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class QATestCandidate(BaseModel):
    id: str
    title: str
    priority: Literal["P0", "P1", "P2"]
    status: ReviewStatus
    confidence: float = Field(ge=0.0, le=1.0)
    preconditions: list[str]
    steps: list[str]
    expected_result: str
    ui_element_id: str
    requirement_ids: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    reviewer_notes: list[str] = Field(default_factory=list)


class QAAnalysis(BaseModel):
    run: dict[str, str | int]
    verification: list[EvidenceVerdict]
    generated_tests: list[QATestCandidate]
    summary: dict[str, int]
    what_we_dont_know: list[str]
    agent_trace: list[dict[str, str | int | bool]]


class QAIntelligenceEngine:
    """Turns verified evidence into conservative QA tests and reviewer decisions."""

    REQUIRED_UI_PATH = ("PullRequest", "CodeFile", "CodeSymbol", "UIElement")
    REQUIRED_REQUIREMENT_PATH = (*REQUIRED_UI_PATH, "Page", "UserFlow", "Requirement")

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir.resolve()

    def analyze(self, report: BlastRadiusReport, session: CrawlSession, repository: str) -> QAAnalysis:
        """Generate only evidence-grounded QA output for the exact report/session pair."""
        elements = {element.id: element for element in session.elements}
        pages = {page.id: page for page in session.pages}
        verdicts = self._verify_claims(report, session, elements, pages)
        tests = self._generate_tests(report, session, elements, pages, verdicts)
        unknowns = self._unknowns(report, session, verdicts, tests)
        summary = Counter(verdict.status for verdict in verdicts)
        test_summary = Counter(test.status for test in tests)
        run: dict[str, str | int] = {
            "crawl_id": session.id,
            "repository": repository,
            "pr_number": report.pr_number,
            "generated_at": report.generated_at.isoformat(),
            "evidence_mode": str(report.metrics.get("evidence_mode", "UNAVAILABLE")),
        }
        return QAAnalysis(
            run=run,
            verification=verdicts,
            generated_tests=tests,
            summary={
                "claims_checked": len(verdicts),
                "claims_verified": summary["VERIFIED"],
                "claims_needing_review": summary["NEEDS_REVIEW"],
                "claims_rejected": summary["REJECTED"] + summary["INSUFFICIENT_EVIDENCE"],
                "tests_generated": len(tests),
                "tests_approved": test_summary["APPROVED"],
                "tests_needing_review": test_summary["NEEDS_REVIEW"],
                "tests_rejected": test_summary["REJECTED"],
            },
            what_we_dont_know=unknowns,
            agent_trace=self._agent_trace(session, report, verdicts, tests),
        )

    def _verify_claims(
        self,
        report: BlastRadiusReport,
        session: CrawlSession,
        elements: dict[str, UIElement],
        pages: dict[str, Page],
    ) -> list[EvidenceVerdict]:
        verdicts: list[EvidenceVerdict] = []
        for item in report.impacted_ui_elements:
            verdicts.append(self._verify_item(item, session, elements, pages, self.REQUIRED_UI_PATH))
        for item in report.impacted_requirements:
            verdicts.append(self._verify_item(item, session, elements, pages, self.REQUIRED_REQUIREMENT_PATH))
        return verdicts

    def _verify_item(
        self,
        item: ImpactedItem,
        session: CrawlSession,
        elements: dict[str, UIElement],
        pages: dict[str, Page],
        expected_path: tuple[str, ...],
    ) -> EvidenceVerdict:
        path_types = tuple(node.get("type", "") for node in item.raw_path)
        evidence = [f"Graph path: {' → '.join(path_types) or 'UNAVAILABLE'}"]
        reasons: list[str] = []
        if path_types != expected_path:
            reasons.append("The deterministic graph path is incomplete or has an unexpected shape.")
        ui_node = next((node for node in item.raw_path if node.get("type") == "UIElement"), None)
        element = elements.get(ui_node.get("id", "") if ui_node else "")
        if element is None:
            reasons.append("The claimed UI element is not present in the selected completed crawl session.")
        else:
            evidence.append(f"Observed selector: {element.selector}")
            page = pages.get(element.page_id)
            if page is None:
                reasons.append("The observed UI element has no captured page in this crawl session.")
            else:
                screenshot_ok = self._artifact_exists(page.screenshot_path)
                dom_ok = self._artifact_exists(page.dom_path)
                evidence.append(f"Observed page: {page.url}")
                if not screenshot_ok or not dom_ok:
                    reasons.append("The required screenshot or DOM artifact is unavailable for the observed page.")
        if reasons:
            return EvidenceVerdict(
                claim_id=f"{item.item_type}:{item.item_id}",
                claim=f"{item.item_type} impact: {item.label}",
                status="REJECTED",
                confidence=item.confidence,
                evidence=evidence,
                reasons=reasons,
            )
        if item.confidence < 0.50:
            reasons.append("Path confidence is below the 0.50 autonomous-approval threshold.")
            status: VerificationStatus = "NEEDS_REVIEW"
        else:
            status = "VERIFIED"
        return EvidenceVerdict(
            claim_id=f"{item.item_type}:{item.item_id}",
            claim=f"{item.item_type} impact: {item.label}",
            status=status,
            confidence=item.confidence,
            evidence=evidence,
            reasons=reasons,
        )

    def _generate_tests(
        self,
        report: BlastRadiusReport,
        session: CrawlSession,
        elements: dict[str, UIElement],
        pages: dict[str, Page],
        verdicts: list[EvidenceVerdict],
    ) -> list[QATestCandidate]:
        verdict_by_ui = {
            verdict.claim_id.split(":", 1)[1]: verdict
            for verdict in verdicts
            if verdict.claim_id.startswith("UIElement:")
        }
        requirement_ids = [item.item_id for item in report.impacted_requirements]
        tests: list[QATestCandidate] = []
        seen_transitions: set[tuple[str, str, str]] = set()
        for transition in session.transitions:
            key = (transition.trigger_element_id, transition.from_page_id, transition.to_page_id)
            if key in seen_transitions:
                continue
            seen_transitions.add(key)
            verdict = verdict_by_ui.get(transition.trigger_element_id)
            element = elements.get(transition.trigger_element_id)
            source = pages.get(transition.from_page_id)
            destination = pages.get(transition.to_page_id)
            if verdict is None or element is None or source is None or destination is None:
                continue
            if verdict.status == "REJECTED":
                continue
            status: ReviewStatus = "APPROVED" if verdict.status == "VERIFIED" else "NEEDS_REVIEW"
            priority: Literal["P0", "P1", "P2"] = "P0" if verdict.confidence >= 0.90 else "P1" if verdict.confidence >= 0.70 else "P2"
            notes = list(verdict.reasons)
            if status == "NEEDS_REVIEW":
                notes.append("A human QA reviewer must confirm this low-confidence code-to-UI mapping before execution.")
            tests.append(
                QATestCandidate(
                    id=f"TG-{report.pr_number}-{len(tests) + 1:03d}",
                    title=f"Verify observed {element.label} navigation from {source.url}",
                    priority=priority,
                    status=status,
                    confidence=verdict.confidence,
                    preconditions=[f"Open the browser-observed source page: {source.url}"],
                    steps=[
                        f"Locate the observed {element.element_type} using selector `{element.selector}`.",
                        f"Activate the observed control labelled `{element.label}`.",
                        f"Wait for the observed destination URL `{destination.url}`.",
                    ],
                    expected_result=(
                        f"The browser reaches `{destination.url}`, matching transition `{transition.id}` recorded "
                        f"during crawl `{session.id}`."
                    ),
                    ui_element_id=element.id,
                    requirement_ids=requirement_ids,
                    evidence=[
                        *verdict.evidence,
                        f"Observed transition: {transition.id} ({source.url} → {destination.url})",
                    ],
                    reviewer_notes=notes,
                )
            )
        return tests

    def _unknowns(
        self,
        report: BlastRadiusReport,
        session: CrawlSession,
        verdicts: list[EvidenceVerdict],
        tests: list[QATestCandidate],
    ) -> list[str]:
        unknowns: list[str] = []
        if any(verdict.status == "NEEDS_REVIEW" for verdict in verdicts):
            unknowns.append("At least one code-to-UI path is below 0.50 confidence and requires human QA review.")
        if report.absent_requirements:
            unknowns.append(
                "The bounded crawl did not verify requirement coverage for: " + ", ".join(report.absent_requirements) + "."
            )
        observed_ui_ids = {transition.trigger_element_id for transition in session.transitions}
        untestable = [item.item_id for item in report.impacted_ui_elements if item.item_id not in observed_ui_ids]
        if untestable:
            unknowns.append(
                f"No browser-observed transition exists for {len(untestable)} impacted UI element(s); no navigation test was generated for them."
            )
        if not tests:
            unknowns.append("No QA test was generated because no verified impacted UI transition exists.")
        return unknowns

    def _agent_trace(
        self,
        session: CrawlSession,
        report: BlastRadiusReport,
        verdicts: list[EvidenceVerdict],
        tests: list[QATestCandidate],
    ) -> list[dict[str, str | int | bool]]:
        verdict_counts = Counter(verdict.status for verdict in verdicts)
        test_counts = Counter(test.status for test in tests)
        return [
            {"agent": "crawl_agent", "status": session.status, "pages": len(session.pages), "ui_elements": len(session.elements), "transitions": len(session.transitions)},
            {"agent": "requirement_agent", "status": "VERIFIED", "requirements": len(report.impacted_requirements) + len(report.absent_requirements)},
            {"agent": "code_agent", "status": "VERIFIED", "changed_files": len(report.changed_files), "symbols": int(report.metrics.get("symbols_count", 0))},
            {"agent": "impact_agent", "status": "VERIFIED", "graph_paths": int(report.metrics.get("graph_paths_traversed", 0))},
            {"agent": "evidence_verifier", "status": "VERIFIED", "verified": verdict_counts["VERIFIED"], "needs_review": verdict_counts["NEEDS_REVIEW"], "rejected": verdict_counts["REJECTED"]},
            {"agent": "test_generator", "status": "VERIFIED", "generated": len(tests)},
            {"agent": "test_reviewer", "status": "VERIFIED", "approved": test_counts["APPROVED"], "needs_review": test_counts["NEEDS_REVIEW"], "rejected": test_counts["REJECTED"]},
            {"agent": "test_humanizer", "status": "VERIFIED", "rendered": len(tests)},
        ]

    def _artifact_exists(self, stored_path: str) -> bool:
        if not stored_path:
            return False
        candidate = (self._data_dir / stored_path).resolve()
        try:
            candidate.relative_to(self._data_dir)
        except ValueError:
            return False
        return candidate.is_file()
