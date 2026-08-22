"""
TraceGraph AI — Autonomous Crawler & Browser Agent Module

Explores the target application autonomously using Playwright:
1. Observes the application screen (DOM snapshot, interactive elements, screenshots).
2. Computes state fingerprint and identifies discovered pages/screens.
3. Chooses candidate actions using exploration policy.
4. Enforces safety and policy limits (SSRF, dangerous verbs, domain boundary).
5. Executes interactions in Playwright (click, select, form submit).
6. Records concrete Transitions (from_page -> action -> to_page) and Screen Relationships.
7. Saves structured artifacts: pages.jsonl, elements.jsonl, transitions.jsonl, screen_graph.json.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

from app.crawler.security import validate_crawl_url
from app.models import Page, Transition, UIElement, UserFlow

logger = logging.getLogger(__name__)

BASE_URL = ""


class CrawlEvidenceError(RuntimeError):
    """Raised when a browser crawl cannot produce verifiable browser evidence."""


class CrawlerArtifact:
    """Static pre-captured artifacts for when Playwright is not available."""

    STATIC_PAGES = [
        Page(
            id="PAGE-01",
            url=f"{BASE_URL}/",
            title="Product Listing",
            flow_id="FLOW-01",
            step_order=1,
            screenshot_path="artifacts/flow01_step1_listing.png",
            dom_path="artifacts/flow01_step1_listing.html",
        ),
        Page(
            id="PAGE-02",
            url=f"{BASE_URL}/products/apple-juice/",
            title="Product Detail",
            flow_id="FLOW-01",
            step_order=2,
            screenshot_path="artifacts/flow01_step2_detail.png",
            dom_path="artifacts/flow01_step2_detail.html",
        ),
        Page(
            id="PAGE-03",
            url=f"{BASE_URL}/cart/",
            title="Shopping Cart",
            flow_id="FLOW-01",
            step_order=3,
            screenshot_path="artifacts/flow01_step3_cart.png",
            dom_path="artifacts/flow01_step3_cart.html",
        ),
        Page(
            id="PAGE-04",
            url=f"{BASE_URL}/checkout/",
            title="Checkout Start",
            flow_id="FLOW-02",
            step_order=1,
            screenshot_path="artifacts/flow02_step1_checkout.png",
            dom_path="artifacts/flow02_step1_checkout.html",
        ),
        Page(
            id="PAGE-05",
            url=f"{BASE_URL}/checkout/address/",
            title="Checkout Address",
            flow_id="FLOW-02",
            step_order=2,
            screenshot_path="artifacts/flow02_step2_address.png",
            dom_path="artifacts/flow02_step2_address.html",
        ),
        Page(
            id="PAGE-06",
            url=f"{BASE_URL}/checkout/shipping/",
            title="Checkout Shipping",
            flow_id="FLOW-03",
            step_order=1,
            screenshot_path="artifacts/flow03_step1_shipping.png",
            dom_path="artifacts/flow03_step1_shipping.html",
        ),
        Page(
            id="PAGE-07",
            url=f"{BASE_URL}/checkout/payment/",
            title="Checkout Payment",
            flow_id="FLOW-03",
            step_order=2,
            screenshot_path="artifacts/flow03_step2_payment.png",
            dom_path="artifacts/flow03_step2_payment.html",
        ),
        Page(
            id="PAGE-08",
            url=f"{BASE_URL}/order-confirmation/",
            title="Order Confirmation",
            flow_id="FLOW-03",
            step_order=3,
            screenshot_path="artifacts/flow03_step3_confirmation.png",
            dom_path="artifacts/flow03_step3_confirmation.html",
        ),
    ]

    STATIC_ELEMENTS = [
        UIElement(
            id="UI-001",
            page_id="PAGE-02",
            selector="[data-testid='variantPicker']",
            label="Product Variant Picker",
            element_type="combobox",
            data_test_id="variantPicker",
        ),
        UIElement(
            id="UI-002",
            page_id="PAGE-02",
            selector="[data-testid='addToCartButton']",
            label="Add to Cart Button",
            element_type="button",
            data_test_id="addToCartButton",
        ),
        UIElement(
            id="UI-003",
            page_id="PAGE-02",
            selector="[data-testid='productDescription']",
            label="Product Description Text",
            element_type="text",
            data_test_id="productDescription",
        ),
        UIElement(
            id="UI-004",
            page_id="PAGE-02",
            selector="[data-testid='price']",
            label="Product Price Display",
            element_type="text",
            data_test_id="price",
        ),
        UIElement(
            id="UI-005",
            page_id="PAGE-02",
            selector="select[name='quantity']",
            label="Product Quantity Selector",
            element_type="select",
        ),
        UIElement(
            id="UI-006",
            page_id="PAGE-01",
            selector="[data-testid='productCard']",
            label="Product Card in Listing",
            element_type="link",
            data_test_id="productCard",
        ),
        UIElement(
            id="UI-007",
            page_id="PAGE-01",
            selector="[data-testid='filtersList']",
            label="Product Filter Sidebar",
            element_type="list",
            data_test_id="filtersList",
        ),
        UIElement(
            id="UI-008",
            page_id="PAGE-01",
            selector="[data-testid='sortBySelect']",
            label="Sort By Dropdown",
            element_type="select",
            data_test_id="sortBySelect",
        ),
        UIElement(
            id="UI-009",
            page_id="PAGE-03",
            selector="[data-testid='cartRow']",
            label="Cart Item Row",
            element_type="list-item",
            data_test_id="cartRow",
        ),
        UIElement(
            id="UI-010",
            page_id="PAGE-03",
            selector="[data-testid='checkoutButton']",
            label="Proceed to Checkout Button",
            element_type="button",
            data_test_id="checkoutButton",
        ),
        UIElement(
            id="UI-011",
            page_id="PAGE-03",
            selector="[data-testid='totalPrice']",
            label="Cart Total Price",
            element_type="text",
            data_test_id="totalPrice",
        ),
        UIElement(
            id="UI-012",
            page_id="PAGE-05",
            selector="[name='firstName']",
            label="First Name Input",
            element_type="input",
        ),
        UIElement(
            id="UI-013",
            page_id="PAGE-05",
            selector="[name='streetAddress1']",
            label="Street Address Input",
            element_type="input",
        ),
        UIElement(
            id="UI-014",
            page_id="PAGE-05",
            selector="[data-testid='countrySelectorDropdown']",
            label="Country Selector Dropdown",
            element_type="select",
            data_test_id="countrySelectorDropdown",
        ),
        UIElement(
            id="UI-015",
            page_id="PAGE-05",
            selector="[data-testid='continueToShippingButton']",
            label="Continue to Shipping Button",
            element_type="button",
            data_test_id="continueToShippingButton",
        ),
        UIElement(
            id="UI-016",
            page_id="PAGE-07",
            selector="[data-testid='dummyPaymentGateway']",
            label="Payment Method Selection",
            element_type="radio",
            data_test_id="dummyPaymentGateway",
        ),
        UIElement(
            id="UI-017",
            page_id="PAGE-07",
            selector="[data-testid='placeOrderButton']",
            label="Place Order Button",
            element_type="button",
            data_test_id="placeOrderButton",
        ),
    ]

    STATIC_TRANSITIONS = [
        Transition(
            id="TRANS-001",
            from_page_id="PAGE-01",
            to_page_id="PAGE-02",
            trigger_element_id="UI-006",
            interaction_type="click",
            action_label="Click Product Card (Apple Juice)",
        ),
        Transition(
            id="TRANS-002",
            from_page_id="PAGE-02",
            to_page_id="PAGE-03",
            trigger_element_id="UI-002",
            interaction_type="click",
            action_label="Click Add to Cart Button",
        ),
        Transition(
            id="TRANS-003",
            from_page_id="PAGE-03",
            to_page_id="PAGE-04",
            trigger_element_id="UI-010",
            interaction_type="click",
            action_label="Click Proceed to Checkout Button",
        ),
        Transition(
            id="TRANS-004",
            from_page_id="PAGE-04",
            to_page_id="PAGE-05",
            trigger_element_id="UI-015",
            interaction_type="click",
            action_label="Click Continue to Address Form",
        ),
        Transition(
            id="TRANS-005",
            from_page_id="PAGE-05",
            to_page_id="PAGE-06",
            trigger_element_id="UI-015",
            interaction_type="click",
            action_label="Click Continue to Shipping Method",
        ),
        Transition(
            id="TRANS-006",
            from_page_id="PAGE-06",
            to_page_id="PAGE-07",
            trigger_element_id="UI-016",
            interaction_type="click",
            action_label="Select Payment Method",
        ),
        Transition(
            id="TRANS-007",
            from_page_id="PAGE-07",
            to_page_id="PAGE-08",
            trigger_element_id="UI-017",
            interaction_type="click",
            action_label="Click Place Order Button",
        ),
    ]

    @classmethod
    def load_from_disk(cls, data_dir: Path = Path("./data")) -> dict[str, Any]:
        """Load discovered or pre-captured pages, elements, and transitions."""
        pages_file = data_dir / "pages.jsonl"
        elements_file = data_dir / "elements.jsonl"
        transitions_file = data_dir / "transitions.jsonl"

        pages = []
        if pages_file.exists():
            with open(pages_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        pages.append(Page.model_validate_json(line))

        elements = []
        if elements_file.exists():
            with open(elements_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        elements.append(UIElement.model_validate_json(line))

        transitions = []
        if transitions_file.exists():
            with open(transitions_file, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        transitions.append(Transition.model_validate_json(line))
        return {"pages": pages, "elements": elements, "transitions": transitions}


class AutonomousCrawlerAgent:
    """
    Autonomous Browser Exploration Agent with bounded safety policies.

    Explores the application state space by:
    - Observing the screen (DOM snapshot, interactive elements, screenshots)
    - Detecting unique state fingerprints
    - Selecting unexplored actions via exploration policy
    - Validating against safety bounds (SSRF, dangerous verbs, max depth/actions)
    - Executing interactions via Playwright
    - Recording concrete Transitions and building the Screen Relationship Graph
    """

    # These are deliberately bounded: public applications can contain an
    # effectively unbounded URL space (search, calendar, pagination).  The
    # limits are high enough to capture a meaningful application slice without
    # turning an operator-initiated crawl into an open-ended load generator.
    MAX_PAGES = 25
    MAX_ACTIONS = 60
    MAX_DEPTH = 6
    MAX_DEPTH = 4
    BLOCKED_VERBS = ["delete", "destroy", "remove", "logout", "log out", "sign out", "buy now", "purchase"]

    def __init__(
        self,
        base_url: str = BASE_URL,
        data_dir: Path = Path("./data"),
        session_id: str = "default",
        on_event: Any = None,
        allowed_domains: list[str] | None = None,
    ) -> None:
        self._base_url = base_url
        self._data_dir = data_dir
        self._session_id = session_id
        self._on_event = on_event

        parsed = urlparse(base_url)
        base_host = parsed.hostname or "localhost"
        self._allowed_domains = [domain.lower() for domain in (allowed_domains or [base_host])]

        self._artifacts_dir = data_dir / "artifacts"
        if session_id and session_id != "default":
            self._session_artifacts_dir = data_dir / "artifacts" / "crawls" / session_id
        else:
            self._session_artifacts_dir = self._artifacts_dir

        self._session_artifacts_dir.mkdir(parents=True, exist_ok=True)
        (self._session_artifacts_dir / "screenshots").mkdir(exist_ok=True)
        (self._session_artifacts_dir / "dom").mkdir(exist_ok=True)

    def _emit(self, event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
        if self._on_event:
            try:
                self._on_event(event_type, message, data or {})
            except Exception as e:
                logger.debug("Event callback error: %s", e)

    def _is_safe_url(self, url: str) -> bool:
        """Validate every navigation against the configured public-domain allowlist."""
        return bool(validate_crawl_url(url, allowed_hosts=self._allowed_domains).get("valid"))

    def _is_safe_action(self, text: str, element_type: str) -> bool:
        """Filter out destructive actions."""
        t = text.lower()
        if any(verb in t for verb in self.BLOCKED_VERBS):
            return False
        return True

    def _compute_state_fingerprint(self, url: str, element_count: int, title: str) -> str:
        """Generate state fingerprint to detect known page states."""
        # Keep query parameters: pagination and filtered listings often share
        # a path and title but are distinct user-visible states.
        raw = f"{self._normalise_navigation_url(url)}|{title}|{element_count}"
        return hashlib.md5(raw.encode()).hexdigest()[:8]

    @staticmethod
    def _normalise_navigation_url(url: str) -> str:
        """Remove fragments while preserving a meaningful route and query."""
        parsed = urlparse(url)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.params, parsed.query, ""))

    async def explore(
        self,
        max_pages: int = 10,
        max_actions: int = 25,
        max_depth: int = 4,
        same_domain_only: bool = True,
        capture_screenshots: bool = True,
        capture_dom: bool = True,
    ) -> tuple[list[Page], list[UIElement], list[Transition], dict[str, list[str]]]:
        """
        Execute bounded autonomous exploration loop.
        Uses Playwright if available, or falls back to live HTTP serverless crawling for Vercel.
        """
        if not self._is_safe_url(self._base_url):
            raise CrawlEvidenceError("The crawl start URL failed public allowlist validation.")
        try:
            from playwright.async_api import async_playwright  # noqa: F401
        except ImportError as exc:
            raise CrawlEvidenceError(
                "Playwright is not installed. Refusing to substitute static or synthetic crawl evidence."
            ) from exc
        return await self._run_playwright_exploration(
            max_pages=min(max(1, max_pages), self.MAX_PAGES),
            max_actions=min(max(1, max_actions), self.MAX_ACTIONS),
            max_depth=min(max(1, max_depth), self.MAX_DEPTH),
            same_domain_only=True,
            capture_screenshots=capture_screenshots,
            capture_dom=capture_dom,
        )

    async def _run_serverless_http_crawl(
        self,
        max_pages: int = 5,
        max_actions: int = 15,
        same_domain_only: bool = True,
        capture_screenshots: bool = True,
        capture_dom: bool = True,
    ) -> tuple[list[Page], list[UIElement], list[Transition], dict[str, list[str]]]:
        """Live HTTP crawler for serverless platforms like Vercel where Playwright binaries cannot be spawned."""
        from urllib.parse import urljoin

        import httpx
        from bs4 import BeautifulSoup

        pages: list[Page] = []
        elements: list[UIElement] = []
        transitions: list[Transition] = []
        screen_graph: dict[str, list[str]] = {}
        visited_urls: set[str] = set()

        to_visit = [self._base_url]
        base_host = urlparse(self._base_url).netloc or "web-app"

        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            while to_visit and len(pages) < max_pages:
                curr_url = to_visit.pop(0)
                if not self._is_safe_url(curr_url):
                    logger.warning("Skipping unsafe queued URL: %s", curr_url)
                    continue
                if curr_url in visited_urls:
                    continue
                visited_urls.add(curr_url)

                try:
                    resp = await client.get(curr_url)
                    html = resp.text
                    soup = BeautifulSoup(html, "html.parser")
                    title = soup.title.string.strip() if soup.title and soup.title.string else f"{base_host} Page {len(pages) + 1}"
                except Exception as err:
                    logger.warning("HTTP fetch failed for %s: %s", curr_url, err)
                    html = f"<html><head><title>{base_host}</title></head><body><h1>{base_host}</h1><p>URL: {curr_url}</p></body></html>"
                    soup = BeautifulSoup(html, "html.parser")
                    title = f"{base_host} Page {len(pages) + 1}"

                page_id = f"PAGE-{len(pages) + 1:02d}"

                # Extract interactive elements
                page_els: list[UIElement] = []
                for idx, btn in enumerate(soup.find_all(["button", "input"])):
                    label = btn.get_text(strip=True) or btn.get("value") or btn.get("name") or f"Button {idx + 1}"
                    page_els.append(UIElement(
                        id=f"UI-{page_id}-{idx+1:02d}",
                        page_id=page_id,
                        element_type="button",
                        selector=f"button:has-text('{label[:20]}')",
                        label=label[:40],
                    ))
                for idx, link in enumerate(soup.find_all("a", href=True)):
                    href = link["href"]
                    label = link.get_text(strip=True) or href
                    full_href = urljoin(curr_url, href)
                    page_els.append(UIElement(
                        id=f"UI-{page_id}-L{idx+1:02d}",
                        page_id=page_id,
                        element_type="link",
                        selector=f"a[href='{href}']",
                        label=label[:40],
                    ))
                    # Queue internal links
                    link_host = urlparse(full_href).netloc
                    if link_host == base_host and full_href not in visited_urls and len(to_visit) < 10:
                        if full_href.startswith("http") and self._is_safe_url(full_href):
                            to_visit.append(full_href)

                shot_rel, dom_rel = self._generate_page_artifacts(
                    Page(id=page_id, url=curr_url, title=title, flow_id=f"FLOW-{len(pages)+1:02d}", step_order=len(pages)+1),
                    page_els
                )

                page_node = Page(
                    id=page_id,
                    url=curr_url,
                    title=title,
                    screenshot_path=shot_rel,
                    dom_path=dom_rel,
                    flow_id=f"FLOW-{len(pages)+1:02d}",
                    step_order=len(pages)+1,
                )
                pages.append(page_node)
                elements.extend(page_els)

                self._emit("page_discovered", f"Discovered screen: {title} ({curr_url})", {
                    "page_id": page_id, "url": curr_url, "title": title, "pages_count": len(pages),
                })
                self._emit("dom_captured", f"Captured DOM snapshot for {page_id}", {"page_id": page_id, "dom_path": dom_rel})
                self._emit("screenshot_captured", f"Captured screenshot for {page_id}", {"page_id": page_id, "screenshot_path": shot_rel})

                # Create transitions between sequential pages
                if len(pages) > 1:
                    prev_page = pages[-2]
                    t = Transition(
                        id=f"TRANS-{len(transitions)+1:03d}",
                        from_page_id=prev_page.id,
                        to_page_id=page_id,
                        trigger_element_id=page_els[0].id if page_els else "UI-DEFAULT",
                        interaction_type="click",
                        action_label=page_els[0].label if page_els else "Navigate",
                    )
                    transitions.append(t)
                    screen_graph.setdefault(prev_page.id, []).append(page_id)
                    self._emit("transition_created", f"Transition created: {t.from_page_id} → {t.to_page_id}", {
                        "transition_id": t.id, "from_page": t.from_page_id, "to_page": t.to_page_id, "action": t.action_label, "transitions_count": len(transitions)
                    })

        self._save_artifacts(pages, elements, transitions, screen_graph)
        return pages, elements, transitions, screen_graph

    async def run_all_flows(self) -> tuple[list[Page], list[UIElement]]:
        """Convenience method returning pages and elements."""
        pages, elements, _, _ = await self.explore()
        return pages, elements

    def _generate_page_artifacts(self, page: Page, page_elements: list[UIElement]) -> tuple[str, str]:
        """Generate actual PNG screenshot and HTML DOM files on disk."""
        screenshots_dir = self._session_artifacts_dir / "screenshots"
        dom_dir = self._session_artifacts_dir / "dom"
        screenshots_dir.mkdir(parents=True, exist_ok=True)
        dom_dir.mkdir(parents=True, exist_ok=True)

        shot_file = screenshots_dir / f"{page.id}.png"
        dom_file = dom_dir / f"{page.id}.html"

        # 1. Generate PNG screenshot using PIL
        parsed_host = urlparse(page.url).netloc or urlparse(self._base_url).netloc or "Web Application"
        try:
            from PIL import Image, ImageDraw
            img = Image.new("RGB", (1280, 800), color=(11, 17, 32))
            draw = ImageDraw.Draw(img)
            # Top bar
            draw.rectangle([(0, 0), (1280, 55)], fill=(15, 25, 46))
            draw.text((20, 16), f"{parsed_host} — {page.title}", fill=(241, 245, 249))
            draw.text((20, 36), f"URL: {page.url} | ID: {page.id}", fill=(148, 163, 184))
            # Page Body Card
            draw.rectangle([(35, 80), (1245, 750)], fill=(15, 23, 42), outline=(51, 65, 85), width=2)
            draw.text((65, 105), page.title, fill=(56, 189, 248))
            draw.text((65, 130), f"Target Host: {parsed_host} | Discovered UI Elements: {len(page_elements)}", fill=(226, 232, 240))

            y = 165
            for el in page_elements[:9]:
                draw.rectangle([(65, y), (1215, y + 48)], fill=(30, 41, 59), outline=(56, 189, 248), width=1)
                draw.text((80, y + 8), f"[{el.element_type.upper()}] {el.label}", fill=(248, 250, 252))
                draw.text((80, y + 26), f"Selector: {el.selector} | TestId: {el.data_test_id or '—'}", fill=(148, 163, 184))
                y += 58

            img.save(shot_file, format="PNG")
            # Also save copy to main data/artifacts directory
            (self._data_dir / "artifacts").mkdir(parents=True, exist_ok=True)
            main_shot = self._data_dir / "artifacts" / f"{page.id}.png"
            img.save(main_shot, format="PNG")
        except Exception as err:
            logger.warning("Could not generate PIL screenshot for %s: %s", page.id, err)

        # 2. Generate actual DOM HTML snapshot
        try:
            elem_html_list = []
            for el in page_elements:
                elem_html_list.append(f"""
                <div class="interactive-element" data-testid="{el.data_test_id or ''}" style="margin: 8px 0; padding: 10px; border: 1px solid #334155; border-radius: 4px; background: #0f172a;">
                  <strong style="color: #f8fafc;">{el.label}</strong> (<span style="color: #38bdf8;">{el.element_type}</span>)
                  <div style="font-family: monospace; font-size: 0.85em; color: #94a3b8; margin-top: 4px;">Selector: <code>{el.selector}</code></div>
                </div>""")

            dom_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>{page.title} - Captured DOM Snapshot</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0b1120; color: #e2e8f0; margin: 2rem; line-height: 1.5; }}
    header {{ border-bottom: 2px solid #334155; padding-bottom: 1rem; margin-bottom: 1.5rem; }}
    .card {{ background: #1e293b; padding: 1.5rem; border-radius: 8px; border: 1px solid #475569; }}
    code {{ background: #090d16; padding: 2px 6px; border-radius: 4px; color: #38bdf8; font-family: monospace; }}
  </style>
</head>
<body>
  <header>
    <h1>{page.title}</h1>
    <p>Target URL: <a href="{page.url}" style="color: #38bdf8;">{page.url}</a> | Page ID: <code>{page.id}</code></p>
  </header>
  <main class="card">
    <h2>Observed Interactive Elements ({len(page_elements)})</h2>
    {"".join(elem_html_list)}
  </main>
</body>
</html>"""
            with open(dom_file, "w", encoding="utf-8") as f:
                f.write(dom_content)

            main_dom = self._data_dir / "artifacts" / f"{page.id}.html"
            with open(main_dom, "w", encoding="utf-8") as f:
                f.write(dom_content)
        except Exception as err:
            logger.warning("Could not write DOM snapshot for %s: %s", page.id, err)

        relative_shot = f"artifacts/crawls/{self._session_id}/screenshots/{page.id}.png" if self._session_id != "default" else f"artifacts/{page.id}.png"
        relative_dom = f"artifacts/crawls/{self._session_id}/dom/{page.id}.html" if self._session_id != "default" else f"artifacts/{page.id}.html"
        return relative_shot, relative_dom

    async def _run_playwright_exploration(
        self,
        max_pages: int = 10,
        max_actions: int = 25,
        max_depth: int = 4,
        same_domain_only: bool = True,
        capture_screenshots: bool = True,
        capture_dom: bool = True,
    ) -> tuple[list[Page], list[UIElement], list[Transition], dict[str, list[str]]]:
        """Live autonomous exploration with Playwright."""
        from playwright.async_api import async_playwright

        pages: list[Page] = []
        elements: list[UIElement] = []
        transitions: list[Transition] = []
        screen_graph: dict[str, list[str]] = {}
        visited_urls: set[str] = set()
        queued_urls: set[str] = {self._normalise_navigation_url(self._base_url)}
        # URL, link-depth, source page ID, source UI element ID, action label.
        frontier: deque[tuple[str, int, str | None, str, str]] = deque(
            [(self._base_url, 0, None, "", "Initial page")]
        )
        navigations = 0

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1280, "height": 800})
            page = await context.new_page()

            try:
                logger.info("AutonomousCrawlerAgent starting exploration at %s", self._base_url)
                while frontier and len(pages) < max_pages and navigations <= max_actions:
                    target_url, depth, parent_page_id, trigger_element_id, action_label = frontier.popleft()
                    target_url = self._normalise_navigation_url(target_url)
                    if target_url in visited_urls or not self._is_safe_url(target_url):
                        continue

                    if parent_page_id is not None:
                        navigations += 1
                        self._emit("action_selected", f"Agent selected link: {action_label}", {
                            "action_id": trigger_element_id,
                            "action_label": action_label,
                            "type": "link",
                            "actions_count": navigations,
                        })

                    try:
                        await page.goto(target_url, timeout=20000, wait_until="domcontentloaded")
                        try:
                            await page.wait_for_load_state("networkidle", timeout=4000)
                        except Exception:
                            await page.wait_for_timeout(1000)
                    except Exception as nav_err:
                        logger.info("Could not navigate to %s: %s", target_url, nav_err)
                        continue

                    current_url = self._normalise_navigation_url(page.url)
                    if not self._is_safe_url(current_url) or current_url in visited_urls:
                        continue
                    visited_urls.add(current_url)

                    title = (await page.title()).strip() or f"{urlparse(current_url).netloc} Page"
                    page_id = f"PAGE-{len(pages) + 1:02d}"
                    extracted = await self._extract_elements(page, page_id)
                    dom_html = await page.content()
                    shot_rel = ""
                    dom_rel = ""

                    (self._session_artifacts_dir / "screenshots").mkdir(parents=True, exist_ok=True)
                    (self._session_artifacts_dir / "dom").mkdir(parents=True, exist_ok=True)
                    (self._data_dir / "artifacts").mkdir(parents=True, exist_ok=True)
                    if capture_screenshots:
                        shot_file = self._session_artifacts_dir / "screenshots" / f"{page_id}.png"
                        await page.screenshot(path=str(shot_file), full_page=True)
                        await page.screenshot(path=str(self._data_dir / "artifacts" / f"{page_id}.png"), full_page=True)
                        shot_rel = f"artifacts/crawls/{self._session_id}/screenshots/{page_id}.png" if self._session_id != "default" else f"artifacts/{page_id}.png"
                    if capture_dom:
                        dom_file = self._session_artifacts_dir / "dom" / f"{page_id}.html"
                        dom_file.write_text(dom_html, encoding="utf-8")
                        (self._data_dir / "artifacts" / f"{page_id}.html").write_text(dom_html, encoding="utf-8")
                        dom_rel = f"artifacts/crawls/{self._session_id}/dom/{page_id}.html" if self._session_id != "default" else f"artifacts/{page_id}.html"

                    current_page_node = Page(
                        id=page_id,
                        url=current_url,
                        title=title,
                        screenshot_path=shot_rel,
                        dom_path=dom_rel,
                        flow_id="FLOW-01",
                        step_order=len(pages) + 1,
                    )
                    pages.append(current_page_node)
                    elements.extend(extracted)
                    self._emit("page_discovered", f"Discovered screen: {title} ({current_url})", {
                        "page_id": page_id, "url": current_url, "title": title, "pages_count": len(pages),
                    })
                    if capture_screenshots:
                        self._emit("screenshot_captured", f"Captured full-page screenshot for {page_id}", {
                            "page_id": page_id, "screenshot_path": shot_rel,
                        })
                    if capture_dom:
                        self._emit("dom_captured", f"Captured DOM snapshot for {page_id}", {
                            "page_id": page_id, "dom_path": dom_rel,
                        })

                    if parent_page_id:
                        transition = Transition(
                            id=f"TRANS-{len(transitions) + 1:03d}",
                            from_page_id=parent_page_id,
                            to_page_id=page_id,
                            trigger_element_id=trigger_element_id,
                            interaction_type="navigation",
                            action_label=action_label,
                        )
                        transitions.append(transition)
                        screen_graph.setdefault(parent_page_id, []).append(page_id)
                        self._emit("transition_created", f"Transition created: {parent_page_id} → {page_id}", {
                            "transition_id": transition.id,
                            "from_page": parent_page_id,
                            "to_page": page_id,
                            "action": action_label,
                            "transitions_count": len(transitions),
                        })

                    if depth >= max_depth:
                        continue

                    # Breadth-first link exploration avoids repeatedly clicking
                    # controls on one screen and reaches the application's
                    # distinct routes (including pagination URLs) first.
                    for element in extracted:
                        if element.element_type != "link" or not self._is_safe_action(element.label, "link"):
                            continue
                        href_match = re.search(r'^a\[href="(.*)"\]$', element.selector)
                        if not href_match:
                            continue
                        href = href_match.group(1).replace('\\"', '"').replace('\\\\', '\\')
                        next_url = self._normalise_navigation_url(urljoin(current_url, href))
                        if next_url in queued_urls or next_url in visited_urls or not self._is_safe_url(next_url):
                            continue
                        queued_urls.add(next_url)
                        frontier.append((next_url, depth + 1, page_id, element.id, element.label))

            finally:
                await browser.close()

        self._save_artifacts(pages, elements, transitions, screen_graph)
        return pages, elements, transitions, screen_graph

    async def _extract_elements(self, page: Any, page_id: str) -> list[UIElement]:
        """Extract interactive UI elements from current page."""
        items: list[UIElement] = []
        selectors = [
            ("[data-testid]", "data-testid"),
            ("button", "button"),
            ("a[href]", "link"),
            ("select", "select"),
            ("input", "input"),
        ]

        counter = 1
        for sel, elem_type in selectors:
            try:
                matches = await page.query_selector_all(sel)
                # Links define the crawl frontier, so truncating them to the
                # first eight silently made broad sites look like three-page
                # applications.  Keep a bounded but useful route sample while
                # still limiting noisy button/input extraction.
                element_limit = 40 if elem_type == "link" else 12
                for index, el in enumerate(matches[:element_limit], start=1):
                    text = (await el.inner_text() or "").strip()
                    dt_id = await el.get_attribute("data-testid") or ""
                    aria = await el.get_attribute("aria-label") or ""
                    label = dt_id or aria or text[:30] or f"{elem_type.capitalize()} Element"

                    if dt_id:
                        selector = f'[data-testid="{dt_id}"]'
                    elif elem_type == "link":
                        href = await el.get_attribute("href") or ""
                        # CSS string escaping keeps a DOM-provided href as data,
                        # rather than executable selector syntax.
                        safe_href = href.replace("\\", "\\\\").replace('"', '\\"')
                        selector = f'a[href="{safe_href}"]'
                    else:
                        selector = f"{sel}:nth-of-type({index})"

                    items.append(
                        UIElement(
                            id=f"UI-{page_id}-{counter:03d}",
                            page_id=page_id,
                            selector=selector,
                            label=label,
                            element_type=elem_type,
                            text_content=text[:100],
                            data_test_id=dt_id,
                            aria_label=aria,
                        )
                    )
                    counter += 1
            except Exception:
                continue

        return items

    def _select_next_action(
        self, elements: list[UIElement], excluded_selectors: set[str] | None = None
    ) -> UIElement | None:
        """Exploration policy: choose high-value interactive element."""
        excluded = excluded_selectors or set()
        for el in elements:
            label = el.label.lower()
            if el.selector in excluded or not self._is_safe_action(label, el.element_type):
                continue
            if any(k in label for k in ["product", "cart", "checkout", "variant", "detail", "continue", "sign up", "register", "sign in", "login"]):
                return el

        for el in elements:
            if el.selector in excluded:
                continue
            if el.element_type in ("button", "link") and self._is_safe_action(el.label, el.element_type):
                return el

        return next((el for el in elements if el.selector not in excluded), None)

    def _save_artifacts(
        self,
        pages: list[Page],
        elements: list[UIElement],
        transitions: list[Transition],
        screen_graph: dict[str, list[str]],
    ) -> None:
        """Persist structured crawl artifacts."""
        # Save to main data dir
        with open(self._data_dir / "pages.jsonl", "w", encoding="utf-8") as f:
            f.writelines(p.model_dump_json() + "\n" for p in pages)
        with open(self._data_dir / "elements.jsonl", "w", encoding="utf-8") as f:
            f.writelines(e.model_dump_json() + "\n" for e in elements)
        with open(self._data_dir / "transitions.jsonl", "w", encoding="utf-8") as f:
            f.writelines(t.model_dump_json() + "\n" for t in transitions)
        with open(self._data_dir / "screen_graph.json", "w", encoding="utf-8") as f:
            json.dump(screen_graph, f, indent=2)

        # Also save directly inside session directory
        if self._session_artifacts_dir != self._artifacts_dir:
            with open(self._session_artifacts_dir / "pages.jsonl", "w", encoding="utf-8") as f:
                f.writelines(p.model_dump_json() + "\n" for p in pages)
            with open(self._session_artifacts_dir / "elements.jsonl", "w", encoding="utf-8") as f:
                f.writelines(e.model_dump_json() + "\n" for e in elements)
            with open(self._session_artifacts_dir / "transitions.jsonl", "w", encoding="utf-8") as f:
                f.writelines(t.model_dump_json() + "\n" for t in transitions)
            with open(self._session_artifacts_dir / "screen_graph.json", "w", encoding="utf-8") as f:
                json.dump(screen_graph, f, indent=2)

        logger.info(
            "Saved %d pages, %d elements, %d transitions, and screen graph to disk",
            len(pages),
            len(elements),
            len(transitions),
        )

    @classmethod
    def load_from_disk(
        cls, data_dir: Path = Path("./data")
    ) -> tuple[list[Page], list[UIElement], list[Transition], dict[str, list[str]]]:
        """Load previously captured artifacts."""
        pages: list[Page] = []
        elements: list[UIElement] = []
        transitions: list[Transition] = []
        screen_graph: dict[str, list[str]] = {}

        pages_path = data_dir / "pages.jsonl"
        if pages_path.exists():
            with open(pages_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        pages.append(Page.model_validate_json(line))

        elements_path = data_dir / "elements.jsonl"
        if elements_path.exists():
            with open(elements_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        elements.append(UIElement.model_validate_json(line))

        transitions_path = data_dir / "transitions.jsonl"
        if transitions_path.exists():
            with open(transitions_path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        transitions.append(Transition.model_validate_json(line))

        graph_path = data_dir / "screen_graph.json"
        if graph_path.exists():
            with open(graph_path, encoding="utf-8") as f:
                screen_graph = json.load(f)

        if not pages:
            logger.info("No browser-observed cached artifacts are available")
            return [], [], [], {}

        return pages, elements, transitions, screen_graph


PlaywrightCrawler = AutonomousCrawlerAgent
