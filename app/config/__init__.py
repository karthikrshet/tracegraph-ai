"""
TraceGraph AI — Application Configuration

Loads from .env / environment variables. Uses pydantic-settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_DOCUMENT_HOSTS = ("github.com", "raw.githubusercontent.com")


def _is_serverless_runtime_environment() -> bool:
    """Detect a serverless function without relying on optional Vercel env exposure."""
    return bool(os.environ.get("TRACEGRAPH_SERVERLESS") or os.environ.get("VERCEL"))


def _parse_allowed_hosts(value: str) -> list[str]:
    """Return normalized hostnames from a comma-separated allowlist.

    Operators naturally paste either ``example.com`` or
    ``https://example.com`` into the dashboard configuration.  The security
    boundary operates on hostnames, so normalize both forms here rather than
    silently creating a non-matching allowlist entry.  Invalid entries are
    deliberately ignored; they must not widen the allowlist.
    """
    hosts: list[str] = []
    for raw_entry in value.split(","):
        entry = raw_entry.strip()
        if not entry:
            continue

        parsed = urlparse(entry)
        if parsed.scheme:
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                continue
            host = parsed.hostname
        elif all(character not in entry for character in "/?#@"):
            host = entry
        else:
            continue

        normalized = host.rstrip(".").lower()
        if normalized and normalized not in hosts:
            hosts.append(normalized)
    return hosts


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ──────────────────────────────────
    openai_api_key: str = ""
    xai_api_key: str = ""
    xai_base_url: str = "https://api.x.ai/v1"
    groq_api_key: str = ""
    groq_base_url: str = "https://api.groq.com/openai/v1"
    llm_provider: str = "groq"  # openai | groq | grok | xai | mock
    llm_model: str = "qwen/qwen3.6-27b"
    embedding_model: str = "text-embedding-3-small"

    # ── Neo4j ────────────────────────────────
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # ── GitHub ───────────────────────────────
    github_token: str | None = None
    target_repo: str = ""
    target_pr: int = 0

    # ── Crawler ──────────────────────────────
    crawler_base_url: str = ""
    crawler_timeout: int = 30000
    crawler_max_depth: int = 3
    allowed_crawl_domains: str = ""
    # GitHub is the documented default source in the dashboard. Additional
    # public documentation hosts can be added by an operator, but arbitrary
    # URL fetching remains disallowed.
    allowed_document_domains: str = ",".join(DEFAULT_DOCUMENT_HOSTS)
    # Development supports a user-selected public target after the same SSRF
    # validation as configured targets. Production defaults to opt-out unless
    # an authenticated operator explicitly enables it.
    allow_custom_crawl_hosts: bool | None = None

    # ── Paths ────────────────────────────────
    data_dir: Path = Path(os.environ.get("DATA_DIR", "/tmp/data" if _is_serverless_runtime_environment() else "./data"))
    artifacts_dir: Path = Path(os.environ.get("ARTIFACTS_DIR", "/tmp/data/artifacts" if _is_serverless_runtime_environment() else "./data/artifacts"))

    # ── Logging ──────────────────────────────
    log_level: str = "INFO"
    app_env: str = "development"
    api_bearer_token: str = ""
    allowed_origins: str = "http://localhost:8000"

    @field_validator("target_pr", "crawler_timeout", "crawler_max_depth", mode="before")
    @classmethod
    def blank_integer_environment_values_use_defaults(cls, value: object, info: object) -> object:
        """Treat blank deployment variables as absent rather than crashing startup.

        Vercel preserves an environment variable whose value is left blank. For
        integer settings, Pydantic correctly rejects that value, but doing so
        while the ASGI app is importing makes *every* route return a 500. These
        settings are optional and have safe defaults, so a blank value has the
        same semantics as an unset one. Invalid non-blank values still fail
        fast during deployment/configuration.
        """
        if isinstance(value, str) and not value.strip():
            defaults = {
                "target_pr": 0,
                "crawler_timeout": 30000,
                "crawler_max_depth": 3,
            }
            field_name = getattr(info, "field_name", "")
            return defaults[field_name]
        return value

    @property
    def allowed_domains(self) -> list[str]:
        return _parse_allowed_hosts(self.allowed_crawl_domains)

    @property
    def allowed_document_hosts(self) -> list[str]:
        configured_hosts = _parse_allowed_hosts(self.allowed_document_domains)
        return configured_hosts or list(DEFAULT_DOCUMENT_HOSTS)

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "staging"}

    @property
    def is_serverless_runtime(self) -> bool:
        """Whether the application is running in Vercel's serverless runtime.

        A serverless request handler is not a durable browser-worker process:
        it cannot safely own a long-lived Playwright browser, persist an SSE
        stream, or retain an in-memory crawl session after the response.
        """
        return _is_serverless_runtime_environment()

    @property
    def custom_crawl_hosts_enabled(self) -> bool:
        """Whether an operator may approve one public target host per crawl."""
        if self.allow_custom_crawl_hosts is not None:
            return self.allow_custom_crawl_hosts
        return not self.is_production


# Singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
