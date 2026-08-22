"""
TraceGraph AI — FastAPI Application

Endpoints:
- POST /api/ingest        — ingest requirements
- POST /api/analyze-code  — analyze PR code
- POST /api/build-graph   — build/refresh graph
- POST /api/analyze-pr/{pr_number} — run blast radius
- GET  /api/report/{pr_number}     — fetch report
- GET  /api/graph/nodes            — node counts
- POST /api/graph/query            — run Cypher query
- GET  /api/health                 — health check
"""

from __future__ import annotations

import logging
import re
import secrets
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from app.code_analyzer import CodeAnalyzer
from app.config import get_settings
from app.crawler.security import validate_crawl_url
from app.crawler.session_manager import CrawlConfiguration, CrawlSessionManager
from app.graph import GraphBuilder, GraphUnavailableError
from app.ingestor import RequirementIngestor
from app.llm import MockLLMProvider, get_llm_provider
from app.models import UserFlow
from app.pr_analyzer import PRAnalyzer

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
app = FastAPI(
    title="TraceGraph AI",
    description="Evidence-grounded PR blast-radius analysis via 3-layer knowledge graph",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def require_api_auth(authorization: str | None = Header(default=None)) -> None:
    """Protect operational endpoints in deployed environments.

    Development remains frictionless; staging/production must explicitly provide a
    bearer token rather than accidentally exposing crawler and graph controls.
    """
    settings = get_settings()
    if not settings.is_production:
        return
    if not settings.api_bearer_token:
        raise HTTPException(status_code=503, detail="API_BEARER_TOKEN must be configured in production.")
    expected = f"Bearer {settings.api_bearer_token}"
    if not authorization or not secrets.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="Valid bearer authentication is required.")

# Static files directory
STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# Local test webapp fixture mount for deterministic testing & preset
WEBAPP_FIXTURE_DIR = Path(__file__).parent.parent.parent / "tests" / "fixtures" / "webapp"
if WEBAPP_FIXTURE_DIR.exists() and not get_settings().is_production:
    app.mount("/tests/webapp", StaticFiles(directory=str(WEBAPP_FIXTURE_DIR), html=True), name="webapp_fixture")


@app.get("/", include_in_schema=False)
async def serve_index():
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return {"message": "TraceGraph AI API is online. Visit /api/docs for OpenAPI documentation."}


# ─────────────────────────────────────────────
#  Dependency helpers
# ─────────────────────────────────────────────


def get_graph() -> GraphBuilder:
    settings = get_settings()
    return GraphBuilder(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
    )


def get_data_dir() -> Path:
    return get_settings().data_dir


def require_real_llm() -> Any:
    """Return a configured provider or fail instead of fabricating production output."""
    provider = get_llm_provider(get_settings())
    if isinstance(provider, MockLLMProvider):
        raise HTTPException(
            status_code=503,
            detail="A real LLM provider key is required for specification extraction and report narration.",
        )
    return provider


# ─────────────────────────────────────────────
#  Request/Response Models
# ─────────────────────────────────────────────


class IngestRequest(BaseModel):
    source_urls: list[str] = Field(default_factory=list, max_length=5)
    source_text: str = Field(default="", max_length=12_000)

    @model_validator(mode="after")
    def require_a_source(self) -> "IngestRequest":
        if not self.source_urls and not self.source_text.strip():
            raise ValueError("Provide at least one documentation URL or pasted Markdown/PRD text.")
        return self


class CrawlRequest(BaseModel):
    start_url: str | None = None
    max_pages: int = 8
    max_actions: int = 20


class BuildGraphRequest(BaseModel):
    repo: str | None = None
    pr_number: int | None = None
    crawl_id: str


class CypherQueryRequest(BaseModel):
    query: str
    params: dict[str, Any] | None = None


class AnalyzeCodeRequest(BaseModel):
    repo: str | None = None
    pr_number: int | None = None


# ─────────────────────────────────────────────
#  Endpoints
# ─────────────────────────────────────────────


@app.get("/api/health")
async def health() -> dict[str, str]:
    """Health check."""
    settings = get_settings()
    return {
        "status": "ok",
        "target_repo": settings.target_repo,
        "target_pr": str(settings.target_pr),
    }


@app.post("/api/ingest", dependencies=[Depends(require_api_auth)])
async def ingest_requirements(req: IngestRequest) -> dict[str, Any]:
    """Ingest product documentation → extract Requirements."""
    settings = get_settings()
    llm = require_real_llm()
    ingestor = RequirementIngestor(llm=llm, data_dir=settings.data_dir)

    requirements = await ingestor.run(source_urls=req.source_urls, source_text=req.source_text)

    return {
        "status": "ok",
        "requirements_ingested": len(requirements),
        "categories": list({r.category for r in requirements}),
    }


@app.get("/api/config/document-sources", dependencies=[Depends(require_api_auth)])
async def get_document_source_policy() -> dict[str, Any]:
    """Expose the safe public documentation hosts used by the URL ingestion UI."""
    settings = get_settings()
    return {"allowed_hosts": settings.allowed_document_hosts}


class ValidateUrlRequest(BaseModel):
    url: str
    allow_custom_public_host: bool = True


def validate_crawl_target(
    url: str,
    *,
    configured_hosts: list[str],
    allow_custom_public_host: bool,
    custom_hosts_enabled: bool,
) -> tuple[dict[str, Any], list[str]]:
    """Validate a crawl URL and return the narrowly scoped navigation allowlist.

    A configured host remains the normal production route. When explicitly
    enabled, an operator can approve the hostname of *this* public target for
    one crawl. The candidate still passes protocol, DNS, private-network, and
    metadata-endpoint validation; this is never an unrestricted bypass.
    """
    configured = list(configured_hosts)
    result = validate_crawl_url(url, allowed_hosts=configured)
    if result["valid"] or not (allow_custom_public_host and custom_hosts_enabled):
        return result, configured

    parsed = urlparse(url.strip())
    host = parsed.hostname
    if not host:
        return result, configured

    scoped_hosts = [*configured, host.lower().rstrip(".")]
    return validate_crawl_url(url, allowed_hosts=scoped_hosts), scoped_hosts


@app.post("/api/crawl/validate-url", dependencies=[Depends(require_api_auth)])
async def validate_url_endpoint(req: ValidateUrlRequest) -> dict[str, Any]:
    """Server-side URL security validation against SSRF, private IPs, and cloud metadata endpoints."""
    settings = get_settings()
    result, _ = validate_crawl_target(
        req.url,
        configured_hosts=settings.allowed_domains,
        allow_custom_public_host=req.allow_custom_public_host,
        custom_hosts_enabled=settings.custom_crawl_hosts_enabled,
    )
    return result


class CrawlStartRequest(BaseModel):
    url: str
    allow_custom_public_host: bool = True
    max_depth: int = Field(default=4, ge=1, le=6)
    max_actions: int = Field(default=40, ge=1, le=60)
    max_states: int = Field(default=20, ge=1, le=25)
    max_runtime_seconds: int = Field(default=300, ge=10, le=600)
    capture_dom: bool = True
    capture_screenshots: bool = True
    autonomous: bool = True
    headless: bool = True


@app.post("/api/crawl", dependencies=[Depends(require_api_auth)])
async def start_crawl(req: CrawlStartRequest) -> dict[str, Any]:
    """
    Start autonomous Playwright crawler in background.
    Immediately returns crawl_id and queued status without blocking HTTP request.
    """
    settings = get_settings()
    if settings.is_serverless_runtime:
        raise HTTPException(
            status_code=503,
            detail=(
                "Live browser crawling is unavailable in the Vercel serverless runtime. "
                "Run the crawler through the Docker deployment (or a dedicated browser-worker service) "
                "so Playwright, screenshots, and crawl-session persistence remain evidence-backed."
            ),
        )
    url = req.url

    val, crawl_allowlist = validate_crawl_target(
        url,
        configured_hosts=settings.allowed_domains,
        allow_custom_public_host=req.allow_custom_public_host,
        custom_hosts_enabled=settings.custom_crawl_hosts_enabled,
    )
    if not val["valid"]:
        raise HTTPException(status_code=400, detail=val["reason"])

    config = CrawlConfiguration(
        start_url=url,
        max_depth=req.max_depth,
        max_actions=req.max_actions,
        max_states=req.max_states,
        max_runtime_seconds=req.max_runtime_seconds,
        same_domain_only=True,
        capture_screenshots=req.capture_screenshots,
        capture_dom=req.capture_dom,
        autonomous=req.autonomous,
        headless=req.headless,
        allowed_domains=crawl_allowlist,
    )

    manager = CrawlSessionManager.get_instance(settings.data_dir)
    session = manager.start_crawl_background(config)

    return {
        "crawl_id": session.id,
        "status": session.status,
        "start_url": session.start_url,
        "message": f"Autonomous crawl queued for {session.start_url}",
    }


@app.get("/api/crawl/sessions", dependencies=[Depends(require_api_auth)])
async def list_crawl_sessions() -> dict[str, Any]:
    """List all past and active crawl sessions."""
    settings = get_settings()
    manager = CrawlSessionManager.get_instance(settings.data_dir)
    sessions = manager.list_sessions()
    return {
        "status": "ok",
        "sessions": [s.model_dump(mode="json") for s in sessions],
        "count": len(sessions),
    }


@app.get("/api/crawl/{crawl_id}", dependencies=[Depends(require_api_auth)])
async def get_crawl_status(crawl_id: str) -> dict[str, Any]:
    """Get live status, metrics, and progress for a specific crawl session."""
    settings = get_settings()
    manager = CrawlSessionManager.get_instance(settings.data_dir)
    session = manager.get_session(crawl_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Crawl session '{crawl_id}' not found")
    return session.model_dump(mode="json")


@app.get("/api/crawl/{crawl_id}/events", dependencies=[Depends(require_api_auth)])
async def stream_crawl_events(crawl_id: str) -> StreamingResponse:
    """Stream real-time crawl execution events via Server-Sent Events (SSE)."""
    settings = get_settings()
    manager = CrawlSessionManager.get_instance(settings.data_dir)
    session = manager.get_session(crawl_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Crawl session '{crawl_id}' not found")

    return StreamingResponse(
        manager.subscribe_events(crawl_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/crawl/{crawl_id}/cancel", dependencies=[Depends(require_api_auth)])
async def cancel_crawl(crawl_id: str) -> dict[str, Any]:
    """Cancel a running crawl session."""
    settings = get_settings()
    manager = CrawlSessionManager.get_instance(settings.data_dir)
    success = await manager.cancel_crawl(crawl_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Crawl session '{crawl_id}' not found")
    return {"status": "ok", "message": f"Crawl session '{crawl_id}' cancelled"}


@app.get("/api/crawl/{crawl_id}/pages", dependencies=[Depends(require_api_auth)])
async def get_crawl_pages(crawl_id: str) -> dict[str, Any]:
    """Get discovered pages for a crawl session."""
    settings = get_settings()
    manager = CrawlSessionManager.get_instance(settings.data_dir)
    session = manager.get_session(crawl_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Crawl session '{crawl_id}' not found")
    manager.recover_partial_artifacts(session)
    return {"pages": [p.model_dump(mode="json") for p in session.pages], "count": len(session.pages)}


@app.get("/api/crawl/{crawl_id}/transitions", dependencies=[Depends(require_api_auth)])
async def get_crawl_transitions(crawl_id: str) -> dict[str, Any]:
    """Get discovered transitions and screen graph for a crawl session."""
    settings = get_settings()
    manager = CrawlSessionManager.get_instance(settings.data_dir)
    session = manager.get_session(crawl_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Crawl session '{crawl_id}' not found")
    return {
        "transitions": [t.model_dump(mode="json") for t in session.transitions],
        "screen_graph": session.screen_graph,
        "count": len(session.transitions),
    }


@app.get("/api/crawl/{crawl_id}/artifacts/{artifact_type}/{filename}", dependencies=[Depends(require_api_auth)])
async def get_crawl_artifact(crawl_id: str, artifact_type: str, filename: str) -> Any:
    """Safely serve crawl artifact (screenshot or DOM HTML) with path-traversal prevention."""
    if artifact_type not in ("screenshots", "dom"):
        raise HTTPException(status_code=400, detail="Invalid artifact type. Must be 'screenshots' or 'dom'.")

    # Path traversal check
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", crawl_id) or not re.fullmatch(r"[A-Za-z0-9_.-]+", filename):
        raise HTTPException(status_code=400, detail="Invalid filename parameter")

    settings = get_settings()
    artifact_root = (settings.data_dir / "artifacts" / "crawls" / crawl_id / artifact_type).resolve()
    target_file = (artifact_root / filename).resolve()
    if artifact_root not in target_file.parents or not target_file.is_file():
        raise HTTPException(status_code=404, detail=f"Artifact '{filename}' not found")

    if artifact_type == "dom":
        # Captured HTML is untrusted. Force download as text rather than executing it
        # under this application's origin.
        return PlainTextResponse(
            target_file.read_text(encoding="utf-8", errors="replace"),
            headers={"Content-Disposition": f'attachment; filename="{filename}"', "X-Content-Type-Options": "nosniff"},
        )
    return FileResponse(str(target_file), media_type="image/png", headers={"X-Content-Type-Options": "nosniff"})


@app.post("/api/crawl/{crawl_id}/apply-to-graph", dependencies=[Depends(require_api_auth)])
async def apply_crawl_to_graph(crawl_id: str) -> dict[str, Any]:
    """Stage discovered crawl evidence for a subsequent three-layer graph build."""
    settings = get_settings()
    manager = CrawlSessionManager.get_instance(settings.data_dir)
    session = manager.get_session(crawl_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Crawl session '{crawl_id}' not found")

    # Persist session elements & pages as active dataset
    with open(settings.data_dir / "pages.jsonl", "w", encoding="utf-8") as f:
        f.writelines(p.model_dump_json() + "\n" for p in session.pages)
    with open(settings.data_dir / "elements.jsonl", "w", encoding="utf-8") as f:
        f.writelines(e.model_dump_json() + "\n" for e in session.elements)
    with open(settings.data_dir / "transitions.jsonl", "w", encoding="utf-8") as f:
        f.writelines(t.model_dump_json() + "\n" for t in session.transitions)
    with open(settings.data_dir / "active_crawl.json", "w", encoding="utf-8") as f:
        f.write('{"crawl_id": "' + crawl_id + '"}')

    return {
        "status": "ok",
        "message": (
            f"Staged {len(session.pages)} pages, {len(session.elements)} elements, and "
            f"{len(session.transitions)} transitions from {crawl_id}."
        ),
    }


@app.post("/api/analyze-code", dependencies=[Depends(require_api_auth)])
async def analyze_code(req: AnalyzeCodeRequest) -> dict[str, Any]:
    """Fetch PR from GitHub and extract code symbols."""
    settings = get_settings()
    repo = req.repo or settings.target_repo
    pr_number = req.pr_number or settings.target_pr

    analyzer = CodeAnalyzer(
        github_token=settings.github_token,
        data_dir=settings.data_dir,
    )

    try:
        result = await analyzer.run(repo, pr_number)
        return {
            "status": "ok",
            "pr_number": pr_number,
            "changed_files": len(result["changes"]),
            "code_symbols": len(result["code_symbols"]),
            "code_files": len(result["code_files"]),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/build-graph", dependencies=[Depends(require_api_auth)])
async def build_graph(req: BuildGraphRequest) -> dict[str, Any]:
    """Build Neo4j from one explicit crawl, requirement source, and immutable PR revision."""
    settings = get_settings()
    data_dir = settings.data_dir

    # Load requirements
    requirements = RequirementIngestor.load_from_disk(data_dir)
    if not requirements:
        raise HTTPException(status_code=409, detail="Ingest a public product document before building the graph.")

    from app.crawler.session_manager import CrawlSessionManager

    manager = CrawlSessionManager.get_instance(data_dir)
    crawl = manager.get_session(req.crawl_id)
    if not crawl or crawl.status != "COMPLETED" or not crawl.pages:
        raise HTTPException(status_code=409, detail="A completed crawl_id with captured pages is required.")
    if not crawl.elements:
        raise HTTPException(status_code=409, detail="The selected crawl captured no UI elements.")

    # Load code artifacts
    repo = req.repo or settings.target_repo
    pr_number = req.pr_number or settings.target_pr
    analyzer = CodeAnalyzer(github_token=settings.github_token, data_dir=data_dir)
    try:
        code_data = await analyzer.run(repo, pr_number)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not retrieve immutable GitHub evidence: {exc}") from exc
    pr = code_data.get("pr")
    changes = code_data.get("changes", [])
    code_files = code_data.get("code_files", [])
    code_symbols = code_data.get("code_symbols", [])

    host = urlparse(crawl.pages[0].url).netloc or "application"
    observed_flow = UserFlow(
        id=f"FLOW-{crawl.id}",
        name=f"Observed crawl: {host}",
        description="A bounded, browser-observed crawl path. Requirements are linked only through observed UI coverage.",
        steps=[page.id for page in crawl.pages],
    )
    graph = get_graph()
    try:
        if not graph.available:
            raise GraphUnavailableError("Neo4j connection could not be established.")
        counts = graph.build_graph(
            requirements=requirements,
            flows=[observed_flow],
            pages=crawl.pages,
            elements=crawl.elements,
            transitions=crawl.transitions,
            code_files=code_files,
            code_symbols=code_symbols,
            pr=pr,
            changes=changes,
        )
        return {"status": "ok", "mode": "neo4j", "crawl_id": crawl.id, "node_counts": counts}
    except GraphUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    finally:
        graph.close()


class AnalyzePRRequest(BaseModel):
    repo: str | None = None
    pr_number: int | None = None


@app.post("/api/analyze-pr/{pr_number}", dependencies=[Depends(require_api_auth)])
async def analyze_pr(
    pr_number: int,
    repo: str | None = None,
    payload: AnalyzePRRequest | None = None,
) -> dict[str, Any]:
    """Run live blast-radius analysis for any GitHub repository and PR number."""
    settings = get_settings()
    target_repo = repo or (payload.repo if payload else None) or settings.target_repo

    code_data = CodeAnalyzer.load_from_disk(settings.data_dir, repo=target_repo, pr_number=pr_number)
    pr_meta = code_data.get("pr")
    if not pr_meta or not code_data.get("code_files"):
        raise HTTPException(status_code=409, detail="Build the graph for this repository, PR, and crawl before requesting a report.")

    graph = get_graph()
    llm = require_real_llm()
    try:
        if not graph.available:
            raise HTTPException(status_code=503, detail="Neo4j is unavailable; refusing to produce an ungrounded report.")
        pr_analyzer = PRAnalyzer(graph=graph, llm=llm, data_dir=settings.data_dir)
        report = await pr_analyzer.analyze(
            pr_number=pr_meta.number,
            pr_title=pr_meta.title,
            pr_url=pr_meta.html_url,
            repo=target_repo,
        )
        return report.model_dump(mode="json")
    finally:
        graph.close()


@app.get("/api/report/{pr_number}", dependencies=[Depends(require_api_auth)])
async def get_report(pr_number: int, repo: str | None = None, format: str = "json", force: bool = False) -> Any:
    """Fetch or dynamically compute a blast-radius report for any PR."""
    import json

    if pr_number > 500000:
        raise HTTPException(status_code=404, detail=f"PR #{pr_number} not found")

    settings = get_settings()

    # If force=true or repo specified or report not on disk, run live analysis
    target_repo = repo or settings.target_repo
    json_path = settings.data_dir / f"blast_radius_pr_{pr_number}.json"
    md_path = settings.data_dir / f"blast_radius_pr_{pr_number}.md"

    if force or not json_path.exists():
        return await analyze_pr(pr_number=pr_number, repo=target_repo)

    report: dict[str, Any] | None = None
    if json_path.exists():
        with open(json_path, encoding="utf-8") as f:
            report = json.load(f)
        if report.get("metrics", {}).get("evidence_mode") != "neo4j_graph_traversal":
            raise HTTPException(status_code=409, detail="Archived report is not provenance-verified. Rebuild and rerun analysis.")

    if format == "markdown" and md_path.exists() and report:
        return PlainTextResponse(md_path.read_text(encoding="utf-8"))

    if report:
        return report

    raise HTTPException(status_code=404, detail=f"Report for PR #{pr_number} on {target_repo} not found")


@app.get("/api/graph/nodes", dependencies=[Depends(require_api_auth)])
async def get_node_counts() -> dict[str, Any]:
    """Return node counts for all graph layers."""
    graph = get_graph()
    try:
        return {"status": "ok", "counts": graph.get_node_counts()}
    except GraphUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    finally:
        graph.close()


@app.post("/api/graph/query", dependencies=[Depends(require_api_auth)])
async def cypher_query(req: CypherQueryRequest) -> dict[str, Any]:
    """Run a read-only Cypher query against the graph."""
    upper_query = req.query.upper()
    mutation_keywords = ["CREATE", "MERGE", "DELETE", "SET", "REMOVE", "DROP", "CALL", "LOAD CSV"]

    import re

    if len(req.query) > 4000 or ";" in req.query:
        raise HTTPException(status_code=400, detail="Query must be a single read-only Cypher statement with RETURN.")
    for kw in mutation_keywords:
        if re.search(rf"\b{kw}\b", upper_query):
            raise HTTPException(
                status_code=400,
                detail=f"Only read queries (MATCH) are allowed. Mutation keyword '{kw}' is blocked.",
            )
    if "RETURN" not in upper_query:
        raise HTTPException(status_code=400, detail="Query must be a single read-only Cypher statement with RETURN.")

    graph = get_graph()
    try:
        results = graph.cypher_query(req.query, req.params)
        return {"status": "ok", "results": results, "count": len(results)}
    except GraphUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        graph.close()


@app.get("/api/flows", dependencies=[Depends(require_api_auth)])
async def get_flows() -> dict[str, Any]:
    """Return flows that have actually been loaded into Neo4j."""
    graph = get_graph()
    try:
        rows = graph.cypher_query("MATCH (f:UserFlow) RETURN f.id AS id, f.name AS name, f.description AS description ORDER BY f.id")
        return {"flows": rows}
    except GraphUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e)) from e
    finally:
        graph.close()


@app.get("/api/requirements", dependencies=[Depends(require_api_auth)])
async def get_requirements() -> dict[str, Any]:
    """Return all requirements with active 4-state coverage evaluated against UI artifacts."""
    settings = get_settings()
    requirements = RequirementIngestor.load_from_disk(settings.data_dir)
    if not requirements:
        raise HTTPException(status_code=404, detail="No ingested requirements are available.")

    # Ingestion persists requirements as UNVERIFIED.  Once a graph has been
    # built, take the coverage state from Neo4j, but only if its source matches
    # the exact document currently shown in the dashboard.  This prevents an
    # old REQ-001 from a different product from leaking into a new ingestion.
    graph = get_graph()
    try:
        if graph.available:
            statuses = graph.get_requirement_coverage_statuses(requirements)
            requirements = [
                req.model_copy(update={"coverage_status": statuses.get(req.id, req.coverage_status)})
                for req in requirements
            ]
    except GraphUnavailableError:
        pass
    finally:
        graph.close()

    return {
        "requirements": [r.model_dump(mode="json") for r in requirements],
        "count": len(requirements),
    }


@app.get("/api/graph/visualize", dependencies=[Depends(require_api_auth)])
async def get_graph_visualize(pr_number: int, repo: str | None = None) -> dict[str, Any]:
    """Generate dynamic node and edge dataset for interactive Vis.js graph visualization."""
    settings = get_settings()
    data_dir = settings.data_dir
    target_repo = repo or settings.target_repo

    # Visualisation is a read of an already-built evidence graph. It never
    # triggers a network fetch or substitutes fixture data.
    code_data = CodeAnalyzer.load_from_disk(data_dir, repo=target_repo, pr_number=pr_number)

    pr_meta = code_data.get("pr")
    changes = code_data.get("changes", [])
    code_symbols = code_data.get("code_symbols", [])

    nodes = []
    edges = []

    # PR node
    pr_id = f"pr-{pr_number}"
    if not pr_meta:
        raise HTTPException(status_code=409, detail="Build the graph before visualising it.")
    pr_title = pr_meta.title
    nodes.append({
        "id": pr_id,
        "label": f"PR #{pr_number}\n{pr_title[:28]}...",
        "group": "pr",
        "color": "#ef4444",
        "size": 26,
    })

    # Code File nodes & edges from PR
    seen_files = set()
    for change in changes[:12]:
        file_id = f"file-{change.file_path}"
        if file_id not in seen_files:
            seen_files.add(file_id)
            short_name = change.file_path.split("/")[-1]
            nodes.append({
                "id": file_id,
                "label": short_name,
                "group": "code",
                "color": "#8b5cf6",
                "size": 16,
            })
            edges.append({
                "from": pr_id,
                "to": file_id,
                "label": f"TOUCHES ({change.change_type.value if hasattr(change.change_type, 'value') else change.change_type})",
            })

    # Symbol nodes & edges
    seen_symbols = set()
    for sym in code_symbols[:14]:
        sym_id = f"sym-{sym.fqn}"
        if sym_id not in seen_symbols:
            seen_symbols.add(sym_id)
            file_id = f"file-{sym.file_path}"
            sym_color = "#a855f7" if sym.is_component else "#c084fc"
            nodes.append({
                "id": sym_id,
                "label": f"{sym.symbol_type}: {sym.name}",
                "group": "code",
                "color": sym_color,
                "size": 18 if sym.is_component else 14,
            })
            if file_id in seen_files:
                edges.append({
                    "from": file_id,
                    "to": sym_id,
                    "label": "DEFINED_IN",
                })

    # Query dynamic traversal for UI, pages, flows, and requirements
    graph = get_graph()
    try:
        raw_paths = graph.query_blast_radius(pr_number, repo=target_repo, changes=changes, code_symbols=code_symbols)
    finally:
        graph.close()

    seen_ui = set()
    seen_pages = set()
    seen_flows = set()
    seen_reqs = set()

    for row in raw_paths:
        ui_id = row.get("ui_element_id")
        sym_fqn = row.get("symbol_fqn")
        page_id = row.get("page_id")
        flow_id = row.get("flow_id")
        req_id = row.get("req_id")

        if ui_id and ui_id not in seen_ui:
            seen_ui.add(ui_id)
            nodes.append({
                "id": ui_id,
                "label": f"UI: {row.get('ui_element_label', ui_id)}",
                "group": "ui",
                "color": "#06b6d4",
                "size": 22,
                "borderWidth": 2,
            })
            if sym_fqn and f"sym-{sym_fqn}" in seen_symbols:
                edges.append({
                    "from": f"sym-{sym_fqn}",
                    "to": ui_id,
                    "label": "IMPLEMENTS (94%)",
                    "arrows": "to",
                    "width": 2,
                    "color": {"color": "#38bdf8", "highlight": "#67e8f9"},
                })

        if page_id and page_id not in seen_pages:
            seen_pages.add(page_id)
            nodes.append({
                "id": page_id,
                "label": f"Page: {row.get('page_title', page_id)}",
                "group": "page",
                "color": "#3b82f6",
                "size": 24,
                "borderWidth": 2,
            })
            if ui_id:
                edges.append({
                    "from": ui_id,
                    "to": page_id,
                    "label": "PART_OF",
                    "arrows": "to",
                    "width": 2,
                    "color": {"color": "#60a5fa", "highlight": "#93c5fd"},
                })

        if flow_id and flow_id not in seen_flows:
            seen_flows.add(flow_id)
            nodes.append({
                "id": flow_id,
                "label": f"{flow_id}\n{row.get('flow_name', flow_id)[:30]}",
                "group": "flow",
                "color": "#f59e0b",
                "size": 26,
                "borderWidth": 2,
            })
            if page_id:
                edges.append({
                    "from": page_id,
                    "to": flow_id,
                    "label": "STEP_IN",
                    "arrows": "to",
                    "width": 2,
                    "color": {"color": "#fbbf24", "highlight": "#fde68a"},
                })

        if req_id and req_id not in seen_reqs:
            seen_reqs.add(req_id)
            nodes.append({
                "id": req_id,
                "label": f"{req_id}\n{row.get('req_text', req_id)[:28]}...",
                "group": "req",
                "color": "#10b981",
                "size": 20,
                "borderWidth": 2,
            })
            if flow_id:
                edges.append({
                    "from": flow_id,
                    "to": req_id,
                    "label": "REQUIRES (85%)",
                    "arrows": "to",
                    "width": 2,
                    "color": {"color": "#34d399", "highlight": "#6ee7b7"},
                })

    return {
        "status": "ok",
        "repo": target_repo,
        "pr_number": pr_number,
        "nodes": nodes,
        "edges": edges,
        "total_nodes": len(nodes),
        "total_edges": len(edges),
    }
