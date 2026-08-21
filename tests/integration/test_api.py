"""
Integration tests for TraceGraph AI FastAPI Application.
Run: pytest tests/integration/test_api.py -v
"""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.api.main import app


@pytest.fixture
def client(monkeypatch):
    import app.api.main as main_mod
    from app.ingestor import RequirementIngestor
    from app.llm import MockLLMProvider
    from app.models import Requirement

    monkeypatch.setattr(main_mod, "get_llm_provider", lambda *args, **kwargs: MockLLMProvider())

    async def fake_ingest(self, source_urls, source_text=""):
        assert source_urls == ["https://docs.saleor.io/developer/products"]
        return [Requirement(id="REQ-1", text="Products can be viewed", category="product")]

    monkeypatch.setattr(RequirementIngestor, "run", fake_ingest)
    return TestClient(app)


def test_health_endpoint(client):
    """GET /api/health should return 200 with repo and PR info."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "target_repo" in data
    assert "target_pr" in data


def test_flows_endpoint_fails_closed_without_graph(client):
    """GET /api/flows must not replace an unavailable graph with fixture flows."""
    response = client.get("/api/flows")
    assert response.status_code == 503


def test_ingest_endpoint(client):
    """POST /api/ingest accepts an explicit public source, not seed data."""
    response = client.post("/api/ingest", json={"source_urls": ["https://docs.saleor.io/developer/products"]})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["requirements_ingested"] == 1
    assert data["categories"] == ["product"]


def test_get_report_json_rejects_archived_unverified_report(client):
    """A historical report without graph provenance must not be served."""
    response = client.get("/api/report/6857")
    assert response.status_code in {404, 409}


def test_get_report_markdown_rejects_archived_unverified_report(client):
    """Markdown download follows the same provenance guard as JSON."""
    response = client.get("/api/report/6857?format=markdown")
    assert response.status_code in {404, 409}


def test_report_not_found(client):
    """GET /api/report/99999999 should return 404."""
    response = client.get("/api/report/99999999")
    assert response.status_code == 404


def test_cypher_guard_blocks_mutations(client):
    """POST /api/graph/query should reject mutation queries (CREATE/DELETE/SET/DROP)."""
    mutation_queries = [
        "CREATE (n:TestNode {name: 'hacked'})",
        "MATCH (n) DELETE n",
        "MATCH (n) DETACH DELETE n",
        "MATCH (n:Requirement) SET n.text = 'malicious'",
        "DROP CONSTRAINT req_id",
    ]
    for q in mutation_queries:
        response = client.post("/api/graph/query", json={"query": q})
        assert response.status_code == 400, f"Query '{q}' was not blocked"
        assert "Only read queries" in response.json()["detail"]


def test_index_serves_html(client):
    """GET / should serve the interactive dashboard HTML."""
    response = client.get("/")
    assert response.status_code == 200
    assert "TraceGraph" in response.text
    assert "3-Layer Graph" in response.text
