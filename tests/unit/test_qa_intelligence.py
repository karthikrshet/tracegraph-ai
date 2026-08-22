"""Contract tests for evidence-only QA planning.

The objects here are intentionally minimal test fixtures. Production output is
always sourced from a persisted crawl session and a graph-traversal report.
"""

from pathlib import Path

from app.crawler.session_manager import CrawlConfiguration, CrawlSession
from app.models import BlastRadiusReport, ConfidenceTier, ImpactedItem, Page, Transition, UIElement
from app.qa_intelligence import QAIntelligenceEngine


def _session(tmp_path: Path, *, with_artifacts: bool = True) -> CrawlSession:
    crawl_id = "evidence-run-1"
    root = tmp_path / "artifacts" / "crawls" / crawl_id
    if with_artifacts:
        (root / "screenshots").mkdir(parents=True)
        (root / "dom").mkdir(parents=True)
        (root / "screenshots" / "page-home.png").write_bytes(b"real-browser-artifact-test")
        (root / "dom" / "page-home.html").write_text("<main>Observed page</main>", encoding="utf-8")
    return CrawlSession(
        id=crawl_id,
        start_url="https://example.test/",
        status="COMPLETED",
        configuration=CrawlConfiguration(crawl_id=crawl_id, start_url="https://example.test/"),
        pages=[
            Page(
                id="page-home",
                url="https://example.test/",
                title="Home",
                screenshot_path=f"artifacts/crawls/{crawl_id}/screenshots/page-home.png",
                dom_path=f"artifacts/crawls/{crawl_id}/dom/page-home.html",
            ),
            Page(id="page-next", url="https://example.test/next", title="Next"),
        ],
        elements=[
            UIElement(
                id="ui-next",
                page_id="page-home",
                selector="a[href='/next']",
                label="Next",
                element_type="link",
            )
        ],
        transitions=[
            Transition(
                id="transition-next",
                from_page_id="page-home",
                to_page_id="page-next",
                trigger_element_id="ui-next",
                action_label="Next",
            )
        ],
    )


def _report(confidence: float = 0.92) -> BlastRadiusReport:
    ui_path = [
        {"type": "PullRequest", "id": "PR-7"},
        {"type": "CodeFile", "id": "src/page.ts"},
        {"type": "CodeSymbol", "id": "goNext"},
        {"type": "UIElement", "id": "ui-next"},
    ]
    requirement_path = [
        *ui_path,
        {"type": "Page", "id": "page-home"},
        {"type": "UserFlow", "id": "flow-1"},
        {"type": "Requirement", "id": "REQ-1"},
    ]
    return BlastRadiusReport(
        pr_number=7,
        pr_title="Navigate safely",
        pr_url="https://github.com/example/repo/pull/7",
        overall_risk="MEDIUM",
        changed_files=["src/page.ts"],
        impacted_ui_elements=[
            ImpactedItem(
                item_type="UIElement",
                item_id="ui-next",
                label="Next",
                risk_level="MEDIUM",
                confidence=confidence,
                confidence_tier=ConfidenceTier.from_score(confidence),
                evidence_chain=["PR-7", "src/page.ts", "goNext", "ui-next"],
                raw_path=ui_path,
            )
        ],
        impacted_flows=[],
        impacted_requirements=[
            ImpactedItem(
                item_type="Requirement",
                item_id="REQ-1",
                label="People can navigate to the next page",
                risk_level="MEDIUM",
                confidence=confidence,
                confidence_tier=ConfidenceTier.from_score(confidence),
                evidence_chain=["PR-7", "src/page.ts", "goNext", "ui-next", "REQ-1"],
                raw_path=requirement_path,
            )
        ],
        absent_requirements=[],
        metrics={"evidence_mode": "neo4j_graph_traversal", "symbols_count": 1, "graph_paths_traversed": 2},
    )


def test_generates_an_approved_test_only_for_verified_artifacts(tmp_path: Path) -> None:
    analysis = QAIntelligenceEngine(tmp_path).analyze(_report(), _session(tmp_path), "example/repo")

    assert [verdict.status for verdict in analysis.verification] == ["VERIFIED", "VERIFIED"]
    assert len(analysis.generated_tests) == 1
    test = analysis.generated_tests[0]
    assert test.status == "APPROVED"
    assert test.ui_element_id == "ui-next"
    assert "transition-next" in test.expected_result


def test_rejects_claims_when_required_browser_artifacts_are_missing(tmp_path: Path) -> None:
    analysis = QAIntelligenceEngine(tmp_path).analyze(_report(), _session(tmp_path, with_artifacts=False), "example/repo")

    assert all(verdict.status == "REJECTED" for verdict in analysis.verification)
    assert analysis.generated_tests == []
    assert "No QA test was generated" in analysis.what_we_dont_know[-1]


def test_low_confidence_claims_require_a_human_reviewer(tmp_path: Path) -> None:
    analysis = QAIntelligenceEngine(tmp_path).analyze(_report(confidence=0.49), _session(tmp_path), "example/repo")

    assert all(verdict.status == "NEEDS_REVIEW" for verdict in analysis.verification)
    assert analysis.generated_tests[0].status == "NEEDS_REVIEW"
    assert "human QA reviewer" in analysis.generated_tests[0].reviewer_notes[-1]
