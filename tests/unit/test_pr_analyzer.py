"""
Tests for the PR Analyzer (blast-radius) subsystem.
Run: pytest tests/unit/test_pr_analyzer.py -v

These tests use a MockGraph that returns pre-canned path data
so Neo4j is not required for unit testing.
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.llm import MockLLMProvider
from app.pr_analyzer import HOP_WEIGHTS, PRAnalyzer, _risk_level, compute_path_confidence

# ─── Mock Graph ───────────────────────────────────────────────────────


def make_mock_graph(path_rows: list[dict]) -> MagicMock:
    mock = MagicMock()
    mock.query_blast_radius.return_value = path_rows
    mock.query_absent_requirements.return_value = []
    return mock


# ─── Sample path rows (mimicking PR #6857 traversal) ──────────────────

SAMPLE_PATHS = [
    {
        "file_path": "src/components/Attributes/DropdownRow.tsx",
        "change_type": "modified",
        "changed_symbols": ["DropdownRow", "toOptions", "mergeOptions"],
        "symbol_name": "DropdownRow",
        "symbol_fqn": "DropdownRow.DropdownRow",
        "is_component": True,
        "ui_element_id": "UI-001",
        "ui_element_label": "Product Attribute Dropdown",
        "page_id": "PAGE-02",
        "page_title": "Product Detail",
        "flow_id": "FLOW-01",
        "flow_name": "Product Browse to Add to Cart",
        "req_id": "REQ-003",
        "req_text": "Product attribute dropdowns must show available values and allow users to search/filter options",
        "req_coverage_status": "COVERED",
    },
    {
        "file_path": "src/components/Attributes/SwatchRow.tsx",
        "change_type": "modified",
        "changed_symbols": ["SwatchRow"],
        "symbol_name": "SwatchRow",
        "symbol_fqn": "SwatchRow.SwatchRow",
        "is_component": True,
        "ui_element_id": "UI-004",
        "ui_element_label": "Color Swatch Attribute Selector",
        "page_id": "PAGE-02",
        "page_title": "Product Detail",
        "flow_id": "FLOW-01",
        "flow_name": "Product Browse to Add to Cart",
        "req_id": "REQ-012",
        "req_text": "Swatch attribute dropdowns must display color previews",
        "req_coverage_status": "COVERED",
    },
]


# ─── Tests ────────────────────────────────────────────────────────────


def test_compute_path_confidence_single_hop():
    """Single hop confidence should equal the hop weight."""
    conf = compute_path_confidence(["pr_to_file"])
    assert conf == HOP_WEIGHTS["pr_to_file"]


def test_compute_path_confidence_multi_hop():
    """Multi-hop confidence should decrease with each hop."""
    single = compute_path_confidence(["pr_to_file"])
    multi = compute_path_confidence(["pr_to_file", "file_to_symbol", "symbol_to_ui"])
    assert multi < single, "Multi-hop confidence must be less than single-hop"


def test_compute_path_confidence_range():
    """Path confidence must always be between 0 and 1."""
    hops = [
        "pr_to_file",
        "file_to_symbol",
        "symbol_to_ui",
        "ui_to_page",
        "page_to_flow",
        "flow_to_requirement",
    ]
    conf = compute_path_confidence(hops)
    assert 0.0 < conf <= 1.0


def test_risk_level_thresholds():
    """Risk levels must match confidence tier thresholds."""
    assert _risk_level(0.95) == "HIGH"
    assert _risk_level(0.80) == "MEDIUM"
    assert _risk_level(0.55) == "LOW"
    assert _risk_level(0.20) == "LOW"  # Unverified still shows as LOW


@pytest.mark.asyncio
async def test_analyze_returns_report(tmp_path):
    """analyze() should return a BlastRadiusReport with correct pr_number."""
    mock_graph = make_mock_graph(SAMPLE_PATHS)
    analyzer = PRAnalyzer(graph=mock_graph, llm=MockLLMProvider(), data_dir=tmp_path)

    report = await analyzer.analyze(
        6857,
        "Give each attribute dropdown its own cache",
        "https://github.com/saleor/saleor-dashboard/pull/6857",
    )

    assert report.pr_number == 6857
    assert report.pr_title == "Give each attribute dropdown its own cache"


@pytest.mark.asyncio
async def test_analyze_detects_ui_elements(tmp_path):
    """Should detect impacted UI elements from graph paths."""
    mock_graph = make_mock_graph(SAMPLE_PATHS)
    analyzer = PRAnalyzer(graph=mock_graph, llm=MockLLMProvider(), data_dir=tmp_path)

    report = await analyzer.analyze(6857, "PR Title", "https://github.com/test/pr/6857")
    assert len(report.impacted_ui_elements) >= 1


@pytest.mark.asyncio
async def test_analyze_detects_flows(tmp_path):
    """Should detect impacted user flows."""
    mock_graph = make_mock_graph(SAMPLE_PATHS)
    analyzer = PRAnalyzer(graph=mock_graph, llm=MockLLMProvider(), data_dir=tmp_path)

    report = await analyzer.analyze(6857, "PR Title", "https://github.com/test/pr/6857")
    assert len(report.impacted_flows) >= 1


@pytest.mark.asyncio
async def test_analyze_detects_requirements(tmp_path):
    """Should detect impacted requirements."""
    mock_graph = make_mock_graph(SAMPLE_PATHS)
    analyzer = PRAnalyzer(graph=mock_graph, llm=MockLLMProvider(), data_dir=tmp_path)

    report = await analyzer.analyze(6857, "PR Title", "https://github.com/test/pr/6857")
    assert len(report.impacted_requirements) >= 1
    req_ids = [r.item_id for r in report.impacted_requirements]
    assert "REQ-003" in req_ids or "REQ-012" in req_ids


@pytest.mark.asyncio
async def test_report_saved_to_disk(tmp_path):
    """Report should be saved as JSON and Markdown."""
    mock_graph = make_mock_graph(SAMPLE_PATHS)
    analyzer = PRAnalyzer(graph=mock_graph, llm=MockLLMProvider(), data_dir=tmp_path)

    await analyzer.analyze(6857, "PR Title", "https://github.com/test/pr/6857")

    json_file = tmp_path / "blast_radius_pr_6857.json"
    md_file = tmp_path / "blast_radius_pr_6857.md"
    assert json_file.exists(), "JSON report not saved"
    assert md_file.exists(), "Markdown report not saved"


@pytest.mark.asyncio
async def test_markdown_report_contains_evidence(tmp_path):
    """Markdown report must contain evidence chain section."""
    mock_graph = make_mock_graph(SAMPLE_PATHS)
    analyzer = PRAnalyzer(graph=mock_graph, llm=MockLLMProvider(), data_dir=tmp_path)

    await analyzer.analyze(6857, "PR Title", "https://github.com/test/pr/6857")

    md_content = (tmp_path / "blast_radius_pr_6857.md").read_text(encoding="utf-8")
    assert "Evidence Chains" in md_content or "Evidence" in md_content
    assert "PR #6857" in md_content


@pytest.mark.asyncio
async def test_empty_paths_no_crash(tmp_path):
    """Empty graph traversal should produce a valid report without crashing."""
    mock_graph = make_mock_graph([])
    analyzer = PRAnalyzer(graph=mock_graph, llm=MockLLMProvider(), data_dir=tmp_path)

    report = await analyzer.analyze(9999, "Empty PR", "https://github.com/test/pr/9999")
    assert report.pr_number == 9999
    assert report.overall_risk == "NONE"
    assert report.impacted_ui_elements == []
    assert report.impacted_requirements == []


@pytest.mark.asyncio
async def test_metrics_populated(tmp_path):
    """Report metrics dict should be populated."""
    mock_graph = make_mock_graph(SAMPLE_PATHS)
    analyzer = PRAnalyzer(graph=mock_graph, llm=MockLLMProvider(), data_dir=tmp_path)

    report = await analyzer.analyze(6857, "PR Title", "https://github.com/test/pr/6857")
    assert "total_changed_files" in report.metrics
    assert "impacted_requirements" in report.metrics
    assert report.metrics["impacted_requirements"] >= 1
