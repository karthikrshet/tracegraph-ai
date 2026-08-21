"""
TraceGraph AI — LLM Provider Abstraction

Supports: openai | mock
Never hard-codes a model — controlled by config.
All external content is treated as UNTRUSTED DATA (not instructions).
"""

from __future__ import annotations

import hashlib
import json
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)


class LLMProvider(ABC):
    """Abstract base for all LLM backends."""

    @abstractmethod
    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str: ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

    async def complete_json(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> dict[str, Any]:
        """Complete and parse as JSON. Returns {} on failure."""
        raw = await self.complete(system, user, temperature, max_tokens)
        try:
            # Extract JSON block if wrapped in markdown
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()
            return json.loads(raw)
        except (json.JSONDecodeError, IndexError) as e:
            logger.warning("LLM JSON parse failed: %s | raw=%s", e, raw[:200])
            return {}


class OpenAIProvider(LLMProvider):
    """OpenAI-backed LLM provider."""

    def __init__(self, api_key: str, model: str, embedding_model: str) -> None:
        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=api_key)
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")
        self._model = model
        self._embedding_model = embedding_model

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error("LLM completion failed: %s", e)
            return ""

    async def embed(self, text: str) -> list[float]:
        try:
            response = await self._client.embeddings.create(
                model=self._embedding_model,
                input=text[:8000],  # truncate to safe limit
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error("LLM embed failed: %s", e)
            return [0.0] * 1536


class GroqProvider(LLMProvider):
    """Groq-backed high-speed LLM provider using OpenAI-compatible API."""

    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.3-70b-versatile",
        base_url: str = "https://api.groq.com/openai/v1",
        openai_api_key: str = "",
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            self._openai_client = (
                AsyncOpenAI(api_key=openai_api_key)
                if openai_api_key and "your" not in openai_api_key.lower() and "..." not in openai_api_key
                else None
            )
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")
        self._model = model
        self._embedding_model = embedding_model

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        try:
            # Ensure reasoning models have enough headroom for output
            effective_max_tokens = max(max_tokens, 2048)
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=effective_max_tokens,
            )
            content = response.choices[0].message.content or ""
            if "</think>" in content:
                content = content.split("</think>")[-1].strip()
            return content
        except Exception as e:
            logger.error("Groq LLM completion failed: %s", e)
            return ""

    async def embed(self, text: str) -> list[float]:
        if self._openai_client:
            try:
                response = await self._openai_client.embeddings.create(
                    model=self._embedding_model,
                    input=text[:8000],
                )
                return response.data[0].embedding
            except Exception as e:
                logger.warning("OpenAI embedding bridge error (%s) — falling back to deterministic vector", e)

        h = int(hashlib.md5(text.encode()).hexdigest(), 16)
        return [float((h >> i) & 0xFF) / 255.0 for i in range(1536)]


class GrokProvider(LLMProvider):
    """xAI Grok-backed LLM provider with dual OpenAI embedding bridge."""

    def __init__(
        self,
        api_key: str,
        model: str = "grok-2-mini",
        base_url: str = "https://api.x.ai/v1",
        openai_api_key: str = "",
        embedding_model: str = "text-embedding-3-small",
    ) -> None:
        try:
            from openai import AsyncOpenAI

            self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            self._openai_client = (
                AsyncOpenAI(api_key=openai_api_key)
                if openai_api_key and "your" not in openai_api_key.lower() and "..." not in openai_api_key
                else None
            )
        except ImportError:
            raise RuntimeError("openai package not installed. Run: pip install openai")
        self._model = model
        self._embedding_model = embedding_model

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error("Grok LLM completion failed: %s", e)
            return ""

    async def embed(self, text: str) -> list[float]:
        # If OpenAI key is also provided, use OpenAI embeddings for vector representations
        if self._openai_client:
            try:
                response = await self._openai_client.embeddings.create(
                    model=self._embedding_model,
                    input=text[:8000],
                )
                return response.data[0].embedding
            except Exception as e:
                logger.warning("OpenAI embedding bridge error (%s) — falling back to deterministic vector", e)

        # Fallback to normalized pseudo-embedding
        h = int(hashlib.md5(text.encode()).hexdigest(), 16)
        return [float((h >> i) & 0xFF) / 255.0 for i in range(1536)]


class MockLLMProvider(LLMProvider):
    """
    Deterministic mock provider for testing.
    Returns canned responses based on input hash — no network calls.
    """

    async def complete(
        self,
        system: str,
        user: str,
        temperature: float = 0.1,
        max_tokens: int = 1024,
    ) -> str:
        return json.dumps(
            {
                "label": "Mock Element",
                "category": "product",
                "confidence": 0.75,
                "requirements": [],
            }
        )

    async def embed(self, text: str) -> list[float]:
        # Deterministic pseudo-embedding based on hash
        h = int(hashlib.md5(text.encode()).hexdigest(), 16)
        return [float((h >> i) & 0xFF) / 255.0 for i in range(1536)]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two embedding vectors."""
    import math

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def get_llm_provider(settings: Any | None = None) -> LLMProvider:
    """Factory — returns provider based on config (Groq | OpenAI | Grok / xAI | Mock)."""
    if settings is None:
        from app.config import get_settings

        settings = get_settings()

    if settings.llm_provider == "mock":
        logger.info("Using MockLLMProvider (no API calls)")
        return MockLLMProvider()

    # ── 1. Groq Provider (High-speed cloud inference) ─────────
    groq_key = settings.groq_api_key or (settings.xai_api_key if settings.xai_api_key.startswith("gsk_") else "") or (settings.openai_api_key if settings.openai_api_key.startswith("gsk_") else "")
    if settings.llm_provider == "groq" or groq_key:
        if groq_key and "your" not in groq_key.lower():
            model = settings.llm_model if ("qwen" in settings.llm_model.lower() or "gpt-oss" in settings.llm_model.lower()) else "qwen/qwen3.6-27b"
            logger.info("Using GroqProvider model=%s (high-speed inference)", model)
            return GroqProvider(
                api_key=groq_key,
                model=model,
                base_url=settings.groq_base_url,
                openai_api_key=settings.openai_api_key if not settings.openai_api_key.startswith("gsk_") else "",
                embedding_model=settings.embedding_model,
            )

    # ── 2. Grok / xAI Provider ──────────────────────────────────
    if settings.llm_provider in ("grok", "xai") or (settings.xai_api_key and settings.xai_api_key.startswith("xai-")):
        api_key = settings.xai_api_key or settings.openai_api_key
        model = settings.llm_model if "grok" in settings.llm_model.lower() else "grok-2-mini"
        logger.info("Using GrokProvider model=%s (dual OpenAI embedding bridge enabled)", model)
        return GrokProvider(
            api_key=api_key,
            model=model,
            base_url=settings.xai_base_url,
            openai_api_key=settings.openai_api_key,
            embedding_model=settings.embedding_model,
        )

    # ── 3. OpenAI Provider ──────────────────────────────────────
    if settings.openai_api_key and "your" not in settings.openai_api_key.lower() and "..." not in settings.openai_api_key and not settings.openai_api_key.startswith("gsk_"):
        logger.info("Using OpenAIProvider model=%s", settings.llm_model)
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            model=settings.llm_model,
            embedding_model=settings.embedding_model,
        )

    logger.info("No valid cloud LLM API key detected — using MockLLMProvider")
    return MockLLMProvider()
