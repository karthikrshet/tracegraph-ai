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
    def _is_error_document(response_status: int | None, title: str) -> bool:
        """Exclude server error documents from the observed product surface.

        A navigation can succeed at the browser level while returning a 404
        HTML page.  Treating that generic error page as application UI creates
        false blast-radius paths, so error documents are evidence of a failed
        navigation rather than discovered screens.
        """
        if response_status is not None and response_status >= 400:
            return True
        return title.strip().lower() in {"page not found", "page not found · github pages"}

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

    async def run_all_flows(self) -> tuple[list[Page], list[UIElement]]:
        """Convenience method returning Playwright-observed pages and elements."""
        pages, elements, _, _ = await self.explore()
        return pages, elements

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
                        response = await page.goto(target_url, timeout=20000, wait_until="domcontentloaded")
                        try:
                            await page.wait_for_load_state("networkidle", timeout=4000)
                        except Exception:
                            await page.wait_for_timeout(1000)
                    except Exception as nav_err:
                        logger.info("Could not navigate to %s: %s", target_url, nav_err)
                        continue

                    current_url = self._normalise_navigation_url(page.url)
                    title = (await page.title()).strip() or f"{urlparse(current_url).netloc} Page"
                    response_status = response.status if response is not None else None
                    if self._is_error_document(response_status, title):
                        visited_urls.add(current_url)
                        self._emit(
                            "navigation_skipped",
                            f"Skipped error document ({response_status or 'unknown'}): {current_url}",
                            {"url": current_url, "status": response_status, "title": title},
                        )
                        continue
                    if not self._is_safe_url(current_url) or current_url in visited_urls:
                        continue
                    visited_urls.add(current_url)

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
