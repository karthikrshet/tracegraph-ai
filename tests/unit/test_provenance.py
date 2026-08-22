import json
from pathlib import Path

import pytest

from app.graph import GraphBuilder
from app.models import CodeSymbol, Requirement, UIElement
from app.provenance import build_run_manifest


def _write(path: Path, content: str = "evidence") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_manifest_hashes_dom_and_screenshot_evidence(tmp_path: Path):
    crawl_id = "crawl-1"
    crawl_dir = tmp_path / "artifacts" / "crawls" / crawl_id
    for name in ("session.json", "pages.jsonl", "elements.jsonl", "transitions.jsonl", "screen_graph.json"):
        _write(crawl_dir / name)
    _write(crawl_dir / "screenshots" / "PAGE-01.png")
    _write(crawl_dir / "dom" / "PAGE-01.html")
    _write(tmp_path / "requirements.jsonl")
    base = "pr_owner_repo_7"
    for suffix in ("metadata.json", "changes.jsonl", "code_files.jsonl", "code_symbols.jsonl"):
        _write(tmp_path / f"{base}_{suffix}")
    report = tmp_path / "blast_radius_pr_7.md"
    _write(report)

    manifest_path = build_run_manifest(
        data_dir=tmp_path,
        crawl_id=crawl_id,
        app_url="https://example.com",
        spec_url="https://example.com/README.md",
        repo="owner/repo",
        pr_number=7,
        pr_head_sha="abc123",
        report_path=report,
        node_counts={},
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert f"artifacts/crawls/{crawl_id}/screenshots/PAGE-01.png" in manifest["artifacts"]
    assert f"artifacts/crawls/{crawl_id}/dom/PAGE-01.html" in manifest["artifacts"]


def test_manifest_rejects_crawl_without_browser_artifacts(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="screenshot and DOM"):
        build_run_manifest(
            data_dir=tmp_path,
            crawl_id="missing",
            app_url="https://example.com",
            spec_url="https://example.com/README.md",
            repo="owner/repo",
            pr_number=7,
            pr_head_sha="abc123",
            report_path=tmp_path / "report.md",
            node_counts={},
        )


def test_conservative_cross_layer_matchers_reject_unrelated_pagination_control():
    pagination = UIElement(id="UI-1", page_id="PAGE-1", selector="button", label="1", element_type="button")
    auth_symbol = CodeSymbol(
        name="AuthComponent", fqn="auth.AuthComponent", file_path="src/app/core/auth/auth.component.ts",
        symbol_type="class", start_line=1, end_line=10,
    )
    pagination_requirement = Requirement(
        id="REQ-1",
        text="The home page displays a paginated list of articles with page navigation controls.",
        category="general",
    )

    assert GraphBuilder._ui_code_mapping_score(pagination, auth_symbol)[0] == 0.0
    assert GraphBuilder._requirement_ui_coverage_score(pagination_requirement, pagination) == 0.0


def test_auth_synonyms_produce_explicit_coverage_evidence():
    sign_in = UIElement(id="UI-2", page_id="PAGE-1", selector="a", label="Sign in", element_type="link")
    auth_symbol = CodeSymbol(
        name="AuthComponent", fqn="auth.AuthComponent", file_path="src/app/core/auth/auth.component.ts",
        symbol_type="class", start_line=1, end_line=10,
    )
    auth_requirement = Requirement(
        id="REQ-2",
        text="Users can authenticate through a login page.",
        category="general",
    )

    assert GraphBuilder._ui_code_mapping_score(sign_in, auth_symbol) == (0.55, "file_path_semantic_match")
    assert GraphBuilder._requirement_ui_coverage_score(auth_requirement, sign_in) >= 0.3
