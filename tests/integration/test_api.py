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
    from app.graph import GraphUnavailableError
    from app.ingestor import RequirementIngestor
    from app.models import Requirement

    class TestLLM:
        """Non-network test double; ingestion itself is stubbed below."""

    monkeypatch.setattr(main_mod, "get_llm_provider", lambda *args, **kwargs: TestLLM())

    class UnavailableGraph:
        def cypher_query(self, *_args, **_kwargs):
            raise GraphUnavailableError("Test graph intentionally unavailable")

        def close(self):
            return None

    # Integration API tests assert fail-closed behavior without depending on
    # whether a developer happens to have Neo4j running locally.
    monkeypatch.setattr(main_mod, "get_graph", lambda: UnavailableGraph())

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


def test_custom_public_host_is_validated_and_scoped_per_request(client, monkeypatch):
    """A custom target is allowed only after the normal validation gate passes."""
    import app.api.main as main_mod
    from app.config import Settings

    monkeypatch.setattr(
        main_mod,
        "get_settings",
        lambda: Settings(allowed_crawl_domains="", allow_custom_crawl_hosts=True),
    )

    def fake_validate(url, allowed_hosts):
        if "academy.codemyfyp.com" in allowed_hosts:
            return {"valid": True, "hostname": "academy.codemyfyp.com", "resolved_ips": ["203.0.113.8"]}
        return {"valid": False, "reason": "Host is not configured", "resolved_ips": []}

    monkeypatch.setattr(main_mod, "validate_crawl_url", fake_validate)
    response = client.post(
        "/api/crawl/validate-url",
        json={"url": "https://academy.codemyfyp.com", "allow_custom_public_host": True},
    )

    assert response.status_code == 200
    assert response.json()["valid"] is True


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


def test_ingest_rejects_mock_provider(client, monkeypatch):
    """The API must not turn a mock provider into apparent product evidence."""
    import app.api.main as main_mod
    from app.llm import MockLLMProvider

    monkeypatch.setattr(main_mod, "get_llm_provider", lambda *args, **kwargs: MockLLMProvider())
    response = client.post("/api/ingest", json={"source_urls": ["https://docs.saleor.io/developer/products"]})
    assert response.status_code == 503


def test_requirements_do_not_use_coverage_from_a_different_source(client, monkeypatch, tmp_path):
    """REQ identifiers are not globally meaningful across separate ingestions."""
    import app.api.main as main_mod
    from app.config import Settings
    from app.models import CoverageStatus, Requirement

    class GraphWithStaleRequirement:
        available = True

        def get_requirement_coverage_statuses(self, requirements):
            # The API must safely merge only statuses returned for matching
            # sources; an unmatched ID stays UNVERIFIED.
            assert requirements[0].source_url == "https://example.com/current-readme"
            return {}

        def close(self):
            return None

    settings = Settings(data_dir=tmp_path)
    (tmp_path / "requirements.jsonl").write_text(
        Requirement(
            id="REQ-001",
            text="Current product requirement",
            category="general",
            source_url="https://example.com/current-readme",
            coverage_status=CoverageStatus.UNVERIFIED,
        ).model_dump_json() + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(main_mod, "get_settings", lambda: settings)
    monkeypatch.setattr(main_mod, "get_graph", lambda: GraphWithStaleRequirement())

    response = client.get("/api/requirements")
    assert response.status_code == 200
    assert response.json()["requirements"][0]["coverage_status"] == "UNVERIFIED"


def test_requirements_endpoint_returns_an_empty_collection_on_first_run(client, monkeypatch, tmp_path):
    """A fresh deployment should not log a 404 just because nothing was ingested yet."""
    import app.api.main as main_mod
    from app.config import Settings

    monkeypatch.setattr(main_mod, "get_settings", lambda: Settings(data_dir=tmp_path))

    response = client.get("/api/requirements")

    assert response.status_code == 200
    assert response.json() == {"requirements": [], "count": 0}


def test_crawl_session_reads_require_production_auth(client, monkeypatch):
    """Crawl metadata and artifacts must not be anonymously visible in production."""
    import app.api.main as main_mod
    from app.config import Settings

    monkeypatch.setattr(main_mod, "get_settings", lambda: Settings(app_env="production", api_bearer_token="test-token"))
    response = client.get("/api/crawl/sessions")
    assert response.status_code == 401


def test_serverless_runtime_rejects_live_browser_crawls(client, monkeypatch, tmp_path):
    """A Vercel function must fail closed instead of pretending it ran Playwright."""
    import app.api.main as main_mod
    from app.config import Settings

    monkeypatch.setenv("VERCEL", "1")
    monkeypatch.setattr(main_mod, "get_settings", lambda: Settings(data_dir=tmp_path))

    response = client.post("/api/crawl", json={"url": "https://academy.codemyfyp.com"})

    assert response.status_code == 503
    assert "Vercel serverless runtime" in response.json()["detail"]


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
