"""Immutable, content-addressed evidence manifests for TraceGraph runs."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one evidence file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_run_manifest(
    *,
    data_dir: Path,
    crawl_id: str,
    app_url: str,
    spec_url: str,
    repo: str,
    pr_number: int,
    pr_head_sha: str,
    report_path: Path,
    node_counts: dict[str, int],
) -> Path:
    """Persist hashes for every run artifact referenced by the final report."""
    crawl_dir = data_dir / "artifacts" / "crawls" / crawl_id
    evidence_files = [
        crawl_dir / "session.json",
        crawl_dir / "pages.jsonl",
        crawl_dir / "elements.jsonl",
        crawl_dir / "transitions.jsonl",
        crawl_dir / "screen_graph.json",
        data_dir / "requirements.jsonl",
        data_dir / f"pr_{repo.replace('/', '_').replace('-', '_').lower()}_{pr_number}_metadata.json",
        data_dir / f"pr_{repo.replace('/', '_').replace('-', '_').lower()}_{pr_number}_changes.jsonl",
        data_dir / f"pr_{repo.replace('/', '_').replace('-', '_').lower()}_{pr_number}_code_files.jsonl",
        data_dir / f"pr_{repo.replace('/', '_').replace('-', '_').lower()}_{pr_number}_code_symbols.jsonl",
        report_path,
    ]
    missing = [str(path) for path in evidence_files if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Cannot certify incomplete run evidence: {', '.join(missing)}")

    manifest: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "application": {"url": app_url, "crawl_id": crawl_id},
        "requirements": {"source_url": spec_url},
        "pull_request": {"repository": repo, "number": pr_number, "head_sha": pr_head_sha},
        "neo4j_node_counts": node_counts,
        "artifacts": {str(path.relative_to(data_dir)).replace("\\", "/"): sha256_file(path) for path in evidence_files},
    }
    manifests_dir = data_dir / "run_manifests"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifests_dir / f"{crawl_id}_pr_{pr_number}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path
