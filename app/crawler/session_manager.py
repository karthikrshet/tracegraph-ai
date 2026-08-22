"""
TraceGraph AI — Crawl Session & Real-Time Event Manager
Manages background autonomous crawl executions, event streams, and artifact persistence.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, AsyncGenerator

from pydantic import BaseModel, Field

from app.models import Page, Transition, UIElement

logger = logging.getLogger(__name__)


class CrawlConfiguration(BaseModel):
    crawl_id: str = ""
    start_url: str = ""
    max_depth: int = Field(default=3, ge=1, le=4)
    max_actions: int = Field(default=20, ge=1, le=25)
    max_states: int = Field(default=10, ge=1, le=10)
    max_runtime_seconds: int = Field(default=180, ge=10, le=300)
    same_domain_only: bool = True
    capture_screenshots: bool = True
    capture_dom: bool = True
    autonomous: bool = True
    headless: bool = True
    allowed_domains: list[str] = Field(default_factory=list)


class CrawlEvent(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    type: str  # page_discovered, action_selected, transition_created, etc.
    message: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class CrawlSession(BaseModel):
    id: str
    start_url: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    status: str = "QUEUED"  # QUEUED, RUNNING, PAUSED, COMPLETED, FAILED, CANCELLED, TIMEOUT
    configuration: CrawlConfiguration
    pages_discovered: int = 0
    elements_discovered: int = 0
    actions_executed: int = 0
    transitions_discovered: int = 0
    states_discovered: int = 0
    current_url: str = ""
    current_action: str = ""
    current_page_title: str = ""
    error: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)
    pages: list[Page] = Field(default_factory=list)
    elements: list[UIElement] = Field(default_factory=list)
    transitions: list[Transition] = Field(default_factory=list)
    screen_graph: dict[str, list[str]] = Field(default_factory=dict)
    artifacts_dir: str = ""


class CrawlSessionManager:
    """Singleton session manager handling active crawl workers, live SSE feeds, and history."""

    _instance: CrawlSessionManager | None = None

    def __init__(self, data_dir: Path = Path("./data")) -> None:
        self._data_dir = data_dir
        self._sessions: dict[str, CrawlSession] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._event_queues: dict[str, list[asyncio.Queue[dict[str, Any]]]] = {}
        self._load_persisted_sessions()

    @classmethod
    def get_instance(cls, data_dir: Path = Path("./data")) -> CrawlSessionManager:
        if cls._instance is None:
            cls._instance = cls(data_dir=data_dir)
        return cls._instance

    def _load_persisted_sessions(self) -> None:
        """Load past sessions from disk."""
        crawls_dir = self._data_dir / "artifacts" / "crawls"
        if not crawls_dir.exists():
            return
        for session_dir in crawls_dir.iterdir():
            if session_dir.is_dir():
                meta_file = session_dir / "session.json"
                if meta_file.exists():
                    try:
                        with open(meta_file, encoding="utf-8") as f:
                            data = json.load(f)
                            session = CrawlSession.model_validate(data)
                            self._sessions[session.id] = session
                    except Exception as e:
                        logger.debug("Could not load session from %s: %s", meta_file, e)

    def get_session(self, crawl_id: str) -> CrawlSession | None:
        return self._sessions.get(crawl_id)

    def list_sessions(self) -> list[CrawlSession]:
        return sorted(self._sessions.values(), key=lambda s: s.started_at, reverse=True)

    def create_session(self, config: CrawlConfiguration) -> CrawlSession:
        crawl_id = config.crawl_id or f"crawl_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        config.crawl_id = crawl_id
        session_dir = self._data_dir / "artifacts" / "crawls" / crawl_id
        session_dir.mkdir(parents=True, exist_ok=True)
        (session_dir / "screenshots").mkdir(exist_ok=True)
        (session_dir / "dom").mkdir(exist_ok=True)

        session = CrawlSession(
            id=crawl_id,
            start_url=config.start_url,
            configuration=config,
            artifacts_dir=str(session_dir),
            status="QUEUED",
        )
        self._sessions[crawl_id] = session
        self._event_queues[crawl_id] = []
        self._save_session_metadata(session)
        return session

    def emit_event(self, crawl_id: str, event_type: str, message: str, data: dict[str, Any] | None = None) -> None:
        session = self._sessions.get(crawl_id)
        evt_dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "message": message,
            "data": data or {},
        }
        if session:
            session.events.append(evt_dict)
            if len(session.events) > 500:
                session.events = session.events[-500:]

        queues = self._event_queues.get(crawl_id, [])
        for q in queues:
            try:
                q.put_nowait(evt_dict)
            except Exception:
                pass

    async def subscribe_events(self, crawl_id: str) -> AsyncGenerator[str, None]:
        """Subscribe to live Server-Sent Events (SSE)."""
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._event_queues.setdefault(crawl_id, []).append(queue)

        # Emit initial current state
        session = self._sessions.get(crawl_id)
        if session:
            init_evt = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "type": "session_init",
                "message": f"Connected to crawl {crawl_id}",
                "data": {
                    "status": session.status,
                    "pages": session.pages_discovered,
                    "actions": session.actions_executed,
                    "transitions": session.transitions_discovered,
                },
            }
            yield f"data: {json.dumps(init_evt)}\n\n"

        try:
            while True:
                evt = await queue.get()
                yield f"data: {json.dumps(evt)}\n\n"
                if evt.get("type") in ("crawl_completed", "crawl_failed", "crawl_cancelled", "crawl_timeout"):
                    break
        finally:
            if crawl_id in self._event_queues and queue in self._event_queues[crawl_id]:
                self._event_queues[crawl_id].remove(queue)

    def start_crawl_background(self, config: CrawlConfiguration) -> CrawlSession:
        session = self.create_session(config)
        task = asyncio.create_task(self._execute_crawl(session))
        self._tasks[session.id] = task
        return session

    async def cancel_crawl(self, crawl_id: str) -> bool:
        session = self._sessions.get(crawl_id)
        if not session:
            return False
        task = self._tasks.get(crawl_id)
        if task and not task.done():
            task.cancel()
        session.status = "CANCELLED"
        session.completed_at = datetime.now(timezone.utc)
        self.emit_event(crawl_id, "crawl_cancelled", "Crawl cancelled by user request")
        self._save_session_metadata(session)
        return True

    async def _execute_crawl(self, session: CrawlSession) -> None:
        """Run the autonomous exploration worker loop."""
        crawl_id = session.id
        config = session.configuration
        session.status = "RUNNING"
        session.started_at = datetime.now(timezone.utc)
        self.emit_event(crawl_id, "crawl_started", f"Started autonomous crawl on {config.start_url}")

        from app.crawler import AutonomousCrawlerAgent
        agent = AutonomousCrawlerAgent(
            base_url=config.start_url,
            data_dir=self._data_dir,
            session_id=crawl_id,
            on_event=lambda t, m, d: self._handle_agent_event(crawl_id, t, m, d),
            allowed_domains=config.allowed_domains,
        )

        try:
            pages, elements, transitions, screen_graph = await asyncio.wait_for(
                agent.explore(
                    max_pages=min(config.max_states, config.max_depth * 2),
                    max_actions=config.max_actions,
                    same_domain_only=True,
                    capture_screenshots=config.capture_screenshots,
                    capture_dom=config.capture_dom,
                ),
                timeout=config.max_runtime_seconds,
            )
            session.pages = pages
            session.elements = elements
            session.transitions = transitions
            session.screen_graph = screen_graph
            session.pages_discovered = len(pages)
            session.elements_discovered = len(elements)
            session.transitions_discovered = len(transitions)
            session.states_discovered = len(pages)
            session.actions_executed = len(transitions)
            session.status = "COMPLETED"
            session.completed_at = datetime.now(timezone.utc)

            self.emit_event(
                crawl_id,
                "crawl_completed",
                f"Crawl completed successfully: {len(pages)} pages, {len(transitions)} transitions",
                {
                    "pages": len(pages),
                    "elements": len(elements),
                    "transitions": len(transitions),
                    "states": len(pages),
                },
            )
        except asyncio.TimeoutError:
            session.status = "TIMEOUT"
            session.completed_at = datetime.now(timezone.utc)
            session.error = f"Exceeded maximum runtime of {config.max_runtime_seconds} seconds"
            self.emit_event(crawl_id, "crawl_timeout", session.error)
        except asyncio.CancelledError:
            session.status = "CANCELLED"
            session.completed_at = datetime.now(timezone.utc)
            self.emit_event(crawl_id, "crawl_cancelled", "Crawl cancelled")
        except Exception as e:
            logger.exception("Crawl execution error for %s: %s", crawl_id, e)
            session.status = "FAILED"
            session.completed_at = datetime.now(timezone.utc)
            session.error = str(e)
            self.emit_event(crawl_id, "crawl_failed", f"Crawl failed: {e}", {"error": str(e)})
        finally:
            self._save_session_metadata(session)

    def _handle_agent_event(self, crawl_id: str, event_type: str, message: str, data: dict[str, Any]) -> None:
        session = self._sessions.get(crawl_id)
        if session:
            if "url" in data:
                session.current_url = data["url"]
            if "action_label" in data:
                session.current_action = data["action_label"]
            if "title" in data:
                session.current_page_title = data["title"]
            if "pages_count" in data:
                session.pages_discovered = data["pages_count"]
            if "actions_count" in data:
                session.actions_executed = data["actions_count"]
            if "transitions_count" in data:
                session.transitions_discovered = data["transitions_count"]

        self.emit_event(crawl_id, event_type, message, data)

    def _save_session_metadata(self, session: CrawlSession) -> None:
        """Persist session summary to disk."""
        try:
            session_dir = Path(session.artifacts_dir)
            session_dir.mkdir(parents=True, exist_ok=True)
            meta_path = session_dir / "session.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                f.write(session.model_dump_json(indent=2))
        except Exception as e:
            logger.warning("Could not persist session metadata: %s", e)
