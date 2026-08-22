"""Regression tests for retaining PR/file evidence when coverage is absent."""

from __future__ import annotations

from app.graph import GraphBuilder
from app.models import CodeSymbol, Requirement, UIElement


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class _Session:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def run(self, _query, **_params):
        return _Result(self._rows)


class _Driver:
    def __init__(self, rows):
        self._rows = rows

    def session(self):
        return _Session(self._rows)


def test_blast_radius_keeps_pr_change_row_without_requirement_coverage():
    """No requirement path is an unknown coverage state, not zero code changes."""
    graph = GraphBuilder.__new__(GraphBuilder)
    graph._driver = _Driver([{"file_path": "src/auth.ts", "req_id": None}])

    rows = graph.query_blast_radius(350, repo="owner/repository")

    assert rows == [{"file_path": "src/auth.ts", "req_id": None}]


def test_ui_mapping_rejects_partial_component_name_overlap():
    """ArticleComponent does not prove that a Favorite Article control changed."""
    score, method = GraphBuilder._ui_code_mapping_score(
        UIElement(id="ui-1", page_id="page-1", selector="button", label="Favorite Article", element_type="button"),
        CodeSymbol(
            fqn="article.component.ArticleComponent",
            name="ArticleComponent",
            symbol_type="class",
            file_path="src/features/article/article.component.ts",
            start_line=1,
            end_line=20,
            is_component=True,
        ),
    )

    assert score == 0.0
    assert method == "name_match"


def test_ui_mapping_allows_narrow_auth_entry_alias():
    """Public login/register controls are a documented low-confidence auth surface."""
    score, method = GraphBuilder._ui_code_mapping_score(
        UIElement(id="ui-1", page_id="page-1", selector="a", label="Sign in", element_type="link"),
        CodeSymbol(
            fqn="auth.component.AuthComponent",
            name="AuthComponent",
            symbol_type="class",
            file_path="src/core/auth/auth.component.ts",
            start_line=1,
            end_line=20,
            is_component=True,
        ),
    )

    assert score == 0.7
    assert method == "auth_entry_semantic_match"


def test_requirement_coverage_requires_the_named_action():
    """A generic Article link cannot cover an author-only delete requirement."""
    score = GraphBuilder._requirement_ui_coverage_score(
        Requirement(
            id="REQ-1",
            text="The article page shows a delete control only to its author.",
            category="general",
            source_url="https://example.test/spec",
        ),
        UIElement(id="ui-1", page_id="page-1", selector="a", label="Read Article", element_type="link"),
    )

    assert score == 0.0


def test_requirement_coverage_retains_observed_subset_for_partial_status():
    """A filter control is useful evidence, but does not prove pagination."""
    score = GraphBuilder._requirement_ui_coverage_score(
        Requirement(
            id="REQ-2",
            text="The home page displays a paginated article list that users can filter by tag.",
            category="general",
            source_url="https://example.test/spec",
        ),
        UIElement(
            id="ui-2",
            page_id="page-1",
            selector="a[href='/tag/python']",
            label="Filter by tag",
            element_type="link",
        ),
    )

    assert score > 0.0
