"""
TraceGraph AI — Code Analyzer

Pipeline:
1. Fetch PR file list from GitHub API
2. For each changed TypeScript/React file, fetch content
3. Use regex + heuristic AST to extract CodeSymbol entities
4. Map observed UI labels to changed symbols with deterministic heuristics
5. Output structured CodeFile + CodeSymbol lists

Stage determinism:
- GitHub API fetch: DETERMINISTIC
- Symbol extraction (regex/AST): DETERMINISTIC
- Symbol→UI mapping hints: DETERMINISTIC heuristic
"""

from __future__ import annotations

import logging
import re
from base64 import b64decode
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from app.models import ChangeType, CodeFile, CodeSymbol, PRChange, PullRequest

logger = logging.getLogger(__name__)


class GitHubEvidenceError(RuntimeError):
    """Raised when a PR cannot be retrieved as verifiable GitHub evidence."""

# React component / hook name pattern
_COMPONENT_RE = re.compile(
    r"(?:export\s+(?:const|function|default\s+function)\s+)([A-Z][a-zA-Z0-9_]*)"
)
_CLASS_RE = re.compile(r"(?:export\s+)?(?:abstract\s+)?class\s+([A-Z][a-zA-Z0-9_]*)")
_HOOK_RE = re.compile(r"(?:export\s+(?:const|function)\s+)(use[A-Z][a-zA-Z0-9_]*)")
_FUNCTION_RE = re.compile(r"(?:export\s+(?:async\s+)?function\s+)([a-z][a-zA-Z0-9_]*)")
_ARROW_FN_RE = re.compile(
    r"^\s*export\s+const\s+([a-z][a-zA-Z0-9_]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)
_LOCAL_ARROW_FN_RE = re.compile(
    r"^\s*(?:const|let)\s+([a-zA-Z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
)


def _validate_repository(repo: str) -> str:
    """Accept only GitHub owner/repository identifiers, never arbitrary URL fragments."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("Repository must be in GitHub owner/repository form.")
    return repo


def _symbols_declared_in_patch(patch: str) -> set[str]:
    """Return symbols declared on added diff lines; never infer from a filename."""
    names: set[str] = set()
    for line in patch.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        source = line[1:]
        for pattern in (_COMPONENT_RE, _HOOK_RE, _FUNCTION_RE, _ARROW_FN_RE, _LOCAL_ARROW_FN_RE):
            names.update(match.group(1) for match in pattern.finditer(source))
    return names


def _infer_language(path: str) -> str:
    ext = Path(path).suffix.lower()
    return {
        ".ts": "typescript",
        ".tsx": "typescript-react",
        ".js": "javascript",
        ".jsx": "javascript-react",
        ".py": "python",
    }.get(ext, "unknown")


def _is_react_component(name: str) -> bool:
    return bool(name) and name[0].isupper()


def _is_hook(name: str) -> bool:
    return name.startswith("use") and len(name) > 3


def extract_symbols_from_content(file_path: str, content: str) -> list[CodeSymbol]:
    """
    Extract exported symbols from TypeScript/React file content.
    Uses regex heuristics — deterministic, no LLM.
    """
    symbols: list[CodeSymbol] = []
    lines = content.split("\n")

    seen_names: set[str] = set()

    def add_symbol(name: str, sym_type: str, line_idx: int, exported: bool = True) -> None:
        if name in seen_names:
            return
        seen_names.add(name)
        symbols.append(
            CodeSymbol(
                fqn=f"{Path(file_path).stem}.{name}",
                name=name,
                symbol_type=sym_type,
                file_path=file_path,
                start_line=line_idx + 1,
                end_line=min(line_idx + 50, len(lines)),  # estimate
                exported=exported,
                is_component=_is_react_component(name),
                is_hook=_is_hook(name),
            )
        )

    for i, line in enumerate(lines):
        for m in _CLASS_RE.finditer(line):
            add_symbol(m.group(1), "class", i)
        for m in _COMPONENT_RE.finditer(line):
            name = m.group(1)
            add_symbol(name, "component" if _is_react_component(name) else "function", i)

        for m in _HOOK_RE.finditer(line):
            add_symbol(m.group(1), "hook", i)

        for m in _FUNCTION_RE.finditer(line):
            add_symbol(m.group(1), "function", i)

        for m in _ARROW_FN_RE.finditer(line):
            name = m.group(1)
            if not _is_react_component(name) and not _is_hook(name):
                add_symbol(name, "arrow_function", i)

        for m in _LOCAL_ARROW_FN_RE.finditer(line):
            name = m.group(1)
            if name not in seen_names:
                add_symbol(name, "arrow_function", i, exported=False)

    return symbols


class CodeAnalyzer:
    """
    Fetches changed files from ANY GitHub PR and extracts code symbols.
    Uses GitHub REST API — works for any public repository and PR.
    """

    def __init__(
        self,
        github_token: str | None = None,
        data_dir: Path = Path("./data"),
    ) -> None:
        self._token = github_token
        self._data_dir = data_dir
        self._headers: dict[str, str] = {
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "TraceGraph-AI-Agent",
        }
        if github_token:
            self._headers["Authorization"] = f"token {github_token}"

    def _get_pr_file_prefix(self, repo: str, pr_number: int) -> str:
        clean_repo = repo.replace("/", "_").replace("-", "_").lower()
        return f"pr_{clean_repo}_{pr_number}"

    async def fetch_pr(self, repo: str, pr_number: int) -> PullRequest:
        """Fetch immutable PR metadata from GitHub, failing closed on any error."""
        repo = _validate_repository(repo)
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}"
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
                resp = await client.get(url, headers=self._headers)
                resp.raise_for_status()
                data = resp.json()
                from datetime import datetime

                merged_at = None
                if data.get("merged_at"):
                    merged_at = datetime.fromisoformat(data["merged_at"].rstrip("Z"))
                return PullRequest(
                    number=data["number"],
                    title=data["title"],
                    author=data.get("user", {}).get("login", "contributor"),
                    body=data.get("body") or "",
                    base_branch=data.get("base", {}).get("ref", "main"),
                    head_sha=data.get("head", {}).get("sha", ""),
                    merged_at=merged_at,
                    html_url=data.get("html_url", f"https://github.com/{repo}/pull/{pr_number}"),
                )
        except Exception as e:
            raise GitHubEvidenceError(f"Unable to fetch {repo} PR #{pr_number} from GitHub: {e}") from e

    async def fetch_pr_files(self, repo: str, pr_number: int) -> list[PRChange]:
        """Fetch changed source files for a PR; do not synthesize changes."""
        repo = _validate_repository(repo)
        url = f"https://api.github.com/repos/{repo}/pulls/{pr_number}/files"
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
                resp = await client.get(url, headers=self._headers)
                resp.raise_for_status()
                files = resp.json()
                changes: list[PRChange] = []
                for f in files:
                    file_path = f["filename"]
                    if not any(file_path.endswith(ext) for ext in [".ts", ".tsx", ".js", ".jsx", ".py"]):
                        continue
                    patch = f.get("patch", "")
                    changes.append(
                        PRChange(
                            id=f"change-{pr_number}-{file_path.replace('/', '_')}",
                            pr_number=pr_number,
                            file_path=file_path,
                            change_type=ChangeType(f.get("status", "modified")),
                            additions=f.get("additions", 0),
                            deletions=f.get("deletions", 0),
                            patch=patch,
                            changed_symbols=sorted(_symbols_declared_in_patch(patch)),
                        )
                    )
                return changes
        except Exception as e:
            raise GitHubEvidenceError(f"Unable to fetch changed files for {repo} PR #{pr_number}: {e}") from e

    async def fetch_file_content(self, repo: str, file_path: str, ref: str) -> str:
        """Fetch a source file at the PR head SHA via GitHub's contents API."""
        repo = _validate_repository(repo)
        if not ref or not re.fullmatch(r"[0-9a-fA-F]{7,64}", ref):
            raise GitHubEvidenceError("GitHub PR does not provide a valid immutable head SHA.")
        safe_path = quote(file_path, safe="/")
        url = f"https://api.github.com/repos/{repo}/contents/{safe_path}?ref={ref}"
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
                response = await client.get(url, headers=self._headers)
                response.raise_for_status()
                payload = response.json()
                if payload.get("encoding") != "base64" or not isinstance(payload.get("content"), str):
                    raise GitHubEvidenceError(f"GitHub returned no base64 source for {file_path}.")
                return b64decode(payload["content"]).decode("utf-8", errors="replace")
        except GitHubEvidenceError:
            raise
        except Exception as e:
            raise GitHubEvidenceError(f"Unable to fetch {file_path} at {ref[:12]}: {e}") from e

    async def extract_symbols_from_pr(
        self, repo: str, head_sha: str, changes: list[PRChange]
    ) -> tuple[list[CodeFile], list[CodeSymbol]]:
        """Extract CodeFile and CodeSymbol objects for the changed files."""
        code_files: list[CodeFile] = []
        code_symbols: list[CodeSymbol] = []

        for change in changes:
            file_path = change.file_path
            lang = _infer_language(file_path)
            content = await self.fetch_file_content(repo, file_path, head_sha)
            comp_name = Path(file_path).stem
            parsed_symbols = extract_symbols_from_content(file_path, content)
            changed_names = set(change.changed_symbols)
            # A patch can omit source because GitHub truncates large diffs. In that case
            # retain the file as an unmapped review item rather than claiming symbols changed.
            changed_symbols = [symbol for symbol in parsed_symbols if symbol.name in changed_names]
            if not changed_symbols:
                # Existing Angular/TypeScript components commonly change methods
                # without redeclaring the class in the diff. Keep the real source
                # symbol, but label the coarser file-scope association explicitly.
                changed_symbols = [symbol for symbol in parsed_symbols if symbol.is_component][:1]
                if changed_symbols:
                    change.changed_symbols = [symbol.name for symbol in changed_symbols]
                    change.symbol_mapping_method = "file_scope_fallback"
            code_files.append(
                CodeFile(
                    path=file_path,
                    language=lang,
                    component_name=comp_name,
                    size_bytes=len(content.encode("utf-8")),
                )
            )
            code_symbols.extend(changed_symbols)

        return code_files, code_symbols

    async def run(self, repo: str, pr_number: int) -> dict[str, Any]:
        """Full pipeline: fetch PR → extract files → extract symbols → save."""
        import json

        pr = await self.fetch_pr(repo, pr_number)
        changes = await self.fetch_pr_files(repo, pr_number)
        code_files, code_symbols = await self.extract_symbols_from_pr(repo, pr.head_sha, changes)

        # Persist per-PR
        out_dir = self._data_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = self._get_pr_file_prefix(repo, pr_number)

        with open(out_dir / f"{prefix}_metadata.json", "w") as f:
            json.dump(pr.model_dump(mode="json"), f, indent=2, default=str)

        with open(out_dir / f"{prefix}_changes.jsonl", "w") as f:
            f.writelines(c.model_dump_json() + "\n" for c in changes)

        with open(out_dir / f"{prefix}_code_symbols.jsonl", "w") as f:
            f.writelines(s.model_dump_json() + "\n" for s in code_symbols)
        with open(out_dir / f"{prefix}_code_files.jsonl", "w") as f:
            f.writelines(item.model_dump_json() + "\n" for item in code_files)

        # Also update active generic pointers
        with open(out_dir / "pr_metadata.json", "w") as f:
            json.dump(pr.model_dump(mode="json"), f, indent=2, default=str)
        with open(out_dir / "pr_changes.jsonl", "w") as f:
            f.writelines(c.model_dump_json() + "\n" for c in changes)
        with open(out_dir / "code_symbols.jsonl", "w") as f:
            f.writelines(s.model_dump_json() + "\n" for s in code_symbols)
        with open(out_dir / "code_files.jsonl", "w") as f:
            f.writelines(item.model_dump_json() + "\n" for item in code_files)

        return {
            "pr": pr,
            "changes": changes,
            "code_files": code_files,
            "code_symbols": code_symbols,
        }

    @classmethod
    def load_from_disk(cls, data_dir: Path = Path("./data"), repo: str | None = None, pr_number: int | None = None) -> dict[str, Any]:
        """Load analyzed code data from disk."""
        import json
        result: dict[str, Any] = {}

        if repo and pr_number:
            clean_repo = repo.replace("/", "_").replace("-", "_").lower()
            pr_path = data_dir / f"pr_{clean_repo}_{pr_number}_metadata.json"
            changes_path = data_dir / f"pr_{clean_repo}_{pr_number}_changes.jsonl"
            symbols_path = data_dir / f"pr_{clean_repo}_{pr_number}_code_symbols.jsonl"
            files_path = data_dir / f"pr_{clean_repo}_{pr_number}_code_files.jsonl"
        else:
            pr_path = data_dir / "pr_metadata.json"
            changes_path = data_dir / "pr_changes.jsonl"
            symbols_path = data_dir / "code_symbols.jsonl"
            files_path = data_dir / "code_files.jsonl"

        if pr_path.exists():
            with open(pr_path) as f:
                result["pr"] = PullRequest.model_validate(json.load(f))
        if changes_path.exists():
            result["changes"] = []
            with open(changes_path) as f:
                for line in f:
                    if line.strip():
                        result["changes"].append(PRChange.model_validate_json(line))
        if symbols_path.exists():
            result["code_symbols"] = []
            with open(symbols_path) as f:
                for line in f:
                    if line.strip():
                        result["code_symbols"].append(CodeSymbol.model_validate_json(line))
        if files_path.exists():
            result["code_files"] = []
            with open(files_path) as f:
                for line in f:
                    if line.strip():
                        result["code_files"].append(CodeFile.model_validate_json(line))

        return result
