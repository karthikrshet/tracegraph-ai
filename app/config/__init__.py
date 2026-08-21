"""
TraceGraph AI — Application Configuration

Loads from .env / environment variables. Uses pydantic-settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


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
    allowed_document_domains: str = ""

    # ── Paths ────────────────────────────────
    data_dir: Path = Path(os.environ.get("DATA_DIR", "/tmp/data" if os.environ.get("VERCEL") else "./data"))
    artifacts_dir: Path = Path(os.environ.get("ARTIFACTS_DIR", "/tmp/data/artifacts" if os.environ.get("VERCEL") else "./data/artifacts"))

    # ── Logging ──────────────────────────────
    log_level: str = "INFO"
    app_env: str = "development"
    api_bearer_token: str = ""
    allowed_origins: str = "http://localhost:8000"

    @property
    def allowed_domains(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_crawl_domains.split(",") if d.strip()]

    @property
    def allowed_document_hosts(self) -> list[str]:
        return [d.strip().lower() for d in self.allowed_document_domains.split(",") if d.strip()]

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.allowed_origins.split(",") if origin.strip()]

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() in {"production", "staging"}


# Singleton
_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
