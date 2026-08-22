"""Regression tests for retaining PR/file evidence when coverage is absent."""

from __future__ import annotations

from app.graph import GraphBuilder


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
