#!/usr/bin/env python3
"""Run one provenance-backed TraceGraph pipeline execution.

This command deliberately has no offline, static-artifact, or mocked-report
mode. If required evidence cannot be collected, it exits without a report.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

sys.path.insert(0, str(Path(__file__).parent.parent))

app = typer.Typer(add_completion=False)
console = Console()


@app.command()
def main(
    repo: str = typer.Option(..., help="GitHub owner/repository containing the selected PR"),
    pr: int = typer.Option(..., min=1, help="Pull request number"),
    crawl_url: str = typer.Option(..., help="Allowed public application URL to crawl"),
    spec_url: str = typer.Option(..., help="Allowed public PRD or feature-document URL"),
) -> None:
    """Ingest a real specification, crawl a real UI, and analyze a real PR."""
    asyncio.run(_run(repo, pr, crawl_url, spec_url))


async def _run(repo: str, pr_number: int, crawl_url: str, spec_url: str) -> None:
    from app.code_analyzer import CodeAnalyzer
    from app.config import get_settings
    from app.crawler import AutonomousCrawlerAgent
    from app.crawler.security import validate_crawl_url
    from app.graph import GraphBuilder
    from app.ingestor import RequirementIngestor
    from app.llm import get_llm_provider
    from app.models import UserFlow
    from app.pr_analyzer import PRAnalyzer

    settings = get_settings()
    crawl_validation = validate_crawl_url(crawl_url, allowed_hosts=settings.allowed_domains)
    if not crawl_validation["valid"]:
        raise typer.BadParameter(f"crawl_url rejected: {crawl_validation['reason']}")

    data_dir = settings.data_dir
    data_dir.mkdir(parents=True, exist_ok=True)
    llm = get_llm_provider(settings)
    console.print(Panel.fit(f"[bold cyan]TraceGraph AI[/bold cyan]\n{repo} PR #{pr_number}"))

    console.print("[bold]1/5 Ingesting the selected public specification[/bold]")
    requirements = await RequirementIngestor(llm=llm, data_dir=data_dir).run(source_urls=[spec_url])

    console.print("[bold]2/5 Crawling the selected live application[/bold]")
    crawler = AutonomousCrawlerAgent(
        base_url=crawl_url,
        data_dir=data_dir,
        session_id=f"cli_pr_{pr_number}",
        allowed_domains=settings.allowed_domains,
    )
    pages, elements, transitions, _ = await crawler.explore(max_pages=10, max_actions=25)
    if not pages or not elements:
        raise RuntimeError("Crawl returned no observable pages or UI elements; graph build aborted.")

    host = urlparse(crawl_url).hostname or "application"
    flow = UserFlow(
        id=f"observed-crawl-{pr_number}",
        name=f"Observed crawl: {host}",
        description="A browser-observed path. Requirement links are created only after UI coverage is found.",
        steps=[page.id for page in pages],
    )

    console.print("[bold]3/5 Fetching the real pull request and changed source files[/bold]")
    code_data = await CodeAnalyzer(github_token=settings.github_token, data_dir=data_dir).run(repo, pr_number)
    if not code_data["code_files"]:
        raise RuntimeError("No source files could be extracted from the PR; report generation aborted.")

    console.print("[bold]4/5 Building the Neo4j evidence graph[/bold]")
    graph = GraphBuilder(uri=settings.neo4j_uri, user=settings.neo4j_user, password=settings.neo4j_password)
    try:
        counts = graph.build_graph(
            requirements=requirements,
            flows=[flow],
            pages=pages,
            elements=elements,
            transitions=transitions,
            code_files=code_data["code_files"],
            code_symbols=code_data["code_symbols"],
            pr=code_data["pr"],
            changes=code_data["changes"],
        )
        table = Table(title="Neo4j node counts")
        table.add_column("Node type")
        table.add_column("Count", justify="right")
        for label, count in sorted(counts.items()):
            table.add_row(label, str(count))
        console.print(table)

        console.print("[bold]5/5 Computing the deterministic blast-radius traversal[/bold]")
        pr_meta = code_data["pr"]
        report = await PRAnalyzer(graph=graph, llm=llm, data_dir=data_dir).analyze(
            pr_number=pr_meta.number, pr_title=pr_meta.title, pr_url=pr_meta.html_url
        )
    finally:
        graph.close()

    console.print(Panel.fit(
        f"PR #{report.pr_number}: [bold]{report.pr_title}[/bold]\n"
        f"Risk: [yellow]{report.overall_risk}[/yellow]\n"
        f"Impacted UI: {len(report.impacted_ui_elements)} | "
        f"Flows: {len(report.impacted_flows)} | Requirements: {len(report.impacted_requirements)}",
        title="Provenance-verified report",
    ))
    console.print(f"Report: [cyan]{data_dir / f'blast_radius_pr_{pr_number}.md'}[/cyan]")


if __name__ == "__main__":
    app()
