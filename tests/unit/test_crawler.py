"""
Unit tests for AutonomousCrawlerAgent:
- SSRF and domain boundary validation
- Action safety filter (destructive verbs blocked)
- State fingerprint generation
- Exploration policy action prioritization
- Browser-observed transitions and screen relationships
"""

import json
from pathlib import Path

import pytest

from app.crawler import AutonomousCrawlerAgent
from app.models import Page, Transition, UIElement


def test_is_safe_url_allows_whitelisted():
    agent = AutonomousCrawlerAgent(base_url="https://demo.saleor.io/en-US")
    assert agent._is_safe_url("https://demo.saleor.io/en-US/products/apple-juice")
    assert not agent._is_safe_url("http://localhost:8000/dashboard")
    assert not agent._is_safe_url("http://127.0.0.1:8000/api")


def test_is_safe_url_blocks_external_and_ssrf():
    agent = AutonomousCrawlerAgent(base_url="https://demo.saleor.io/en-US")
    assert not agent._is_safe_url("https://attacker.com/malicious")
    assert not agent._is_safe_url("https://demo.saleor.io.attacker.com/malicious")
    assert not agent._is_safe_url("http://169.254.169.254/latest/meta-data")
    assert not agent._is_safe_url("ftp://demo.saleor.io")
    assert not agent._is_safe_url("javascript:alert(1)")


def test_is_safe_action_blocks_destructive_verbs():
    agent = AutonomousCrawlerAgent()
    assert agent._is_safe_action("Add to Cart", "button")
    assert agent._is_safe_action("Select Variant", "combobox")
    assert agent._is_safe_action("Product Details", "link")

    # Destructive actions must be blocked
    assert not agent._is_safe_action("Delete account", "button")
    assert not agent._is_safe_action("Destroy session", "button")
    assert not agent._is_safe_action("Log out", "link")
    assert not agent._is_safe_action("Buy Now", "button")
    assert not agent._is_safe_action("Purchase instantly", "button")


def test_state_fingerprint_deterministic():
    agent = AutonomousCrawlerAgent()
    fp1 = agent._compute_state_fingerprint("https://demo.saleor.io/products", 12, "Product Listing")
    fp2 = agent._compute_state_fingerprint("https://demo.saleor.io/products", 12, "Product Listing")
    fp3 = agent._compute_state_fingerprint("https://demo.saleor.io/cart", 4, "Shopping Cart")

    assert fp1 == fp2
    assert fp1 != fp3
    assert len(fp1) == 8


def test_error_documents_are_not_treated_as_observed_product_screens():
    assert AutonomousCrawlerAgent._is_error_document(404, "Conduit")
    assert AutonomousCrawlerAgent._is_error_document(200, "Page not found · GitHub Pages")
    assert not AutonomousCrawlerAgent._is_error_document(200, "Conduit")


def test_select_next_action_prioritizes_high_value_elements():
    agent = AutonomousCrawlerAgent()
    elements = [
        UIElement(id="UI-1", page_id="P1", selector="footer a", label="About Us", element_type="link"),
        UIElement(id="UI-2", page_id="P1", selector="button.cart", label="View Shopping Cart", element_type="button"),
        UIElement(id="UI-3", page_id="P1", selector="a.terms", label="Terms of Service", element_type="link"),
    ]
    chosen = agent._select_next_action(elements)
    assert chosen is not None
    assert chosen.id == "UI-2"
    assert "Cart" in chosen.label


@pytest.mark.asyncio
async def test_crawler_explore_returns_observed_transitions_and_graph(tmp_path: Path, monkeypatch):
    agent = AutonomousCrawlerAgent(
        base_url="https://demo.saleor.io/en-US", data_dir=tmp_path, allowed_domains=["demo.saleor.io"]
    )

    observed_pages = [Page(id="PAGE-01", url="https://demo.saleor.io/en-US", title="Observed page")]
    observed_elements = [UIElement(id="UI-01", page_id="PAGE-01", selector="button", label="Observed action", element_type="button")]
    observed_transitions = [Transition(id="TRANS-01", from_page_id="PAGE-01", to_page_id="PAGE-01", action_label="Observed action")]

    async def fake_browser(**_kwargs):
        return observed_pages, observed_elements, observed_transitions, {"PAGE-01": ["PAGE-01"]}

    monkeypatch.setattr(agent, "_run_playwright_exploration", fake_browser)
    pages, elements, transitions, screen_graph = await agent.explore()

    assert len(pages) > 0
    assert len(elements) > 0
    assert len(transitions) > 0
    assert isinstance(screen_graph, dict)
    assert "PAGE-01" in screen_graph

    # Verify transitions have valid from/to page references
    for t in transitions:
        assert t.id.startswith("TRANS-")
        assert t.from_page_id
        assert t.to_page_id
        assert t.action_label


def test_validate_crawl_url_ssrf_protection():
    from app.crawler.security import validate_crawl_url

    # Valid external URL
    v_good = validate_crawl_url("https://demo.saleor.io/en-US")
    assert v_good["valid"] is True

    # Cloud metadata IP blocked
    v_meta = validate_crawl_url("http://169.254.169.254/latest/meta-data")
    assert v_meta["valid"] is False
    assert "blocked" in v_meta["reason"].lower() or "metadata" in v_meta["reason"].lower()

    # Private IP 10.0.0.1 blocked
    v_priv = validate_crawl_url("http://10.0.0.1:8080/admin")
    assert v_priv["valid"] is False

    # Private IP 192.168.1.1 blocked
    v_priv2 = validate_crawl_url("http://192.168.1.1/setup")
    assert v_priv2["valid"] is False

    # Prohibited schemes
    v_file = validate_crawl_url("file:///etc/passwd")
    assert v_file["valid"] is False

    v_js = validate_crawl_url("javascript:alert(1)")
    assert v_js["valid"] is False


@pytest.mark.asyncio
async def test_crawl_session_manager_lifecycle(tmp_path: Path):
    from app.crawler.session_manager import CrawlConfiguration, CrawlSessionManager

    manager = CrawlSessionManager(data_dir=tmp_path)
    config = CrawlConfiguration(
        start_url="https://demo.saleor.io/en-US",
        max_depth=3,
        max_actions=10,
    )

    session = manager.start_crawl_background(config)
    assert session.id.startswith("crawl_")
    assert session.status in ("QUEUED", "RUNNING")

    # Fetch session
    fetched = manager.get_session(session.id)
    assert fetched is not None
    assert fetched.id == session.id

    # Wait for completion or cancel
    await manager.cancel_crawl(session.id)
    assert session.status == "CANCELLED"


def test_crawl_session_list_and_persistence(tmp_path: Path):
    from app.crawler.session_manager import CrawlConfiguration, CrawlSessionManager

    manager = CrawlSessionManager(data_dir=tmp_path)
    sessions = manager.list_sessions()
    assert isinstance(sessions, list)


def test_crawl_session_history_normalises_legacy_naive_timestamps(tmp_path: Path):
    """Persisted sessions from older versions must not break the Sessions API."""
    from app.crawler.session_manager import CrawlSessionManager

    crawl_dir = tmp_path / "artifacts" / "crawls" / "legacy"
    crawl_dir.mkdir(parents=True)
    (crawl_dir / "session.json").write_text(
        json.dumps({
            "id": "legacy",
            "start_url": "https://example.com",
            "started_at": "2025-01-01T00:00:00",
            "configuration": {"start_url": "https://example.com"},
        }),
        encoding="utf-8",
    )

    sessions = CrawlSessionManager(data_dir=tmp_path).list_sessions()
    assert len(sessions) == 1
    assert sessions[0].started_at.tzinfo is not None


def test_timed_out_crawl_keeps_emitted_screens_and_transitions(tmp_path: Path):
    """Partial browser evidence remains inspectable after the worker times out."""
    from app.crawler.session_manager import CrawlConfiguration, CrawlSessionManager

    manager = CrawlSessionManager(data_dir=tmp_path)
    session = manager.create_session(CrawlConfiguration(crawl_id="partial", start_url="https://example.com"))
    session.events = [
        {
            "type": "page_discovered",
            "data": {"page_id": "PAGE-01", "url": "https://example.com", "title": "Home"},
        },
        {
            "type": "page_discovered",
            "data": {"page_id": "PAGE-02", "url": "https://example.com/docs", "title": "Docs"},
        },
        {
            "type": "transition_created",
            "data": {"transition_id": "TRANS-001", "from_page": "PAGE-01", "to_page": "PAGE-02", "action": "Docs"},
        },
    ]
    session.status = "TIMEOUT"

    manager.recover_partial_artifacts(session)

    assert [page.id for page in session.pages] == ["PAGE-01", "PAGE-02"]
    assert [transition.id for transition in session.transitions] == ["TRANS-001"]
    assert session.screen_graph == {"PAGE-01": ["PAGE-02"]}


def test_crawl_configuration_defaults():
    from app.crawler.session_manager import CrawlConfiguration

    config = CrawlConfiguration(start_url="https://demo.saleor.io")
    assert config.max_depth == 4
    assert config.capture_screenshots is True
    assert config.capture_dom is True
    assert config.autonomous is True


def test_agent_limit_matches_documented_maximum_depth():
    assert AutonomousCrawlerAgent.MAX_DEPTH == 6


def test_pipeline_uses_a_unique_crawl_id_and_records_start_before_capture():
    """The pipeline must not mix artifacts across executions of the same PR."""
    pipeline_source = (Path(__file__).parents[2] / "scripts" / "run_pipeline.py").read_text(encoding="utf-8")
    assert 'crawl_id = f"pipeline_{datetime.now(timezone.utc).strftime' in pipeline_source
    assert "started_at=crawl_started_at" in pipeline_source
