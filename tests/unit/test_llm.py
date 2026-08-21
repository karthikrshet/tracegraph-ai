"""
Tests for the LLM provider abstraction.
Run: pytest tests/unit/test_llm.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.llm import MockLLMProvider, cosine_similarity, get_llm_provider
from app.models import ConfidenceTier as ModelConfidenceTier


@pytest.mark.asyncio
async def test_mock_llm_complete():
    """MockLLMProvider.complete should return valid JSON string."""
    import json

    llm = MockLLMProvider()
    result = await llm.complete("system", "user")
    assert isinstance(result, str)
    assert len(result) > 0
    # Should be parseable as JSON
    parsed = json.loads(result)
    assert isinstance(parsed, dict)


@pytest.mark.asyncio
async def test_mock_llm_embed():
    """MockLLMProvider.embed should return 1536-dimensional vector."""
    llm = MockLLMProvider()
    vector = await llm.embed("Product attribute dropdown")
    assert len(vector) == 1536
    assert all(0.0 <= v <= 1.0 for v in vector)


@pytest.mark.asyncio
async def test_mock_llm_embed_deterministic():
    """Same input should always produce the same embedding."""
    llm = MockLLMProvider()
    v1 = await llm.embed("test text")
    v2 = await llm.embed("test text")
    assert v1 == v2


@pytest.mark.asyncio
async def test_mock_llm_embed_different():
    """Different inputs should produce different embeddings."""
    llm = MockLLMProvider()
    v1 = await llm.embed("product listing page")
    v2 = await llm.embed("payment checkout form")
    assert v1 != v2


@pytest.mark.asyncio
async def test_mock_llm_complete_json():
    """complete_json should parse the returned JSON."""
    llm = MockLLMProvider()
    result = await llm.complete_json("system", "user")
    assert isinstance(result, dict)


def test_cosine_similarity_identical():
    """Identical vectors should have similarity = 1.0."""
    v = [1.0, 0.0, 0.0]
    assert abs(cosine_similarity(v, v) - 1.0) < 1e-6


def test_cosine_similarity_orthogonal():
    """Orthogonal vectors should have similarity = 0.0."""
    v1 = [1.0, 0.0]
    v2 = [0.0, 1.0]
    assert abs(cosine_similarity(v1, v2)) < 1e-6


def test_cosine_similarity_zero_vector():
    """Zero vector edge case should not crash."""
    v1 = [0.0, 0.0]
    v2 = [1.0, 0.0]
    result = cosine_similarity(v1, v2)
    assert result == 0.0


def test_confidence_tier_thresholds():
    """ConfidenceTier thresholds must match spec."""
    assert ModelConfidenceTier.from_score(0.95) == ModelConfidenceTier.HIGH
    assert ModelConfidenceTier.from_score(0.80) == ModelConfidenceTier.MEDIUM
    assert ModelConfidenceTier.from_score(0.55) == ModelConfidenceTier.LOW
    assert ModelConfidenceTier.from_score(0.20) == ModelConfidenceTier.UNVERIFIED


def test_get_llm_provider_mock_when_no_key():
    """Should return MockLLMProvider when no API key is configured."""
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"OPENAI_API_KEY": "", "GROQ_API_KEY": "", "XAI_API_KEY": "", "LLM_PROVIDER": "openai"}):
        # Reset settings singleton
        import app.config as config_module

        config_module._settings = None

        provider = get_llm_provider()
        assert isinstance(provider, MockLLMProvider)

        config_module._settings = None  # cleanup


def test_get_llm_provider_mock_explicit():
    """Should return MockLLMProvider when LLM_PROVIDER=mock."""
    import os
    from unittest.mock import patch

    with patch.dict(os.environ, {"LLM_PROVIDER": "mock"}):
        import app.config as config_module

        config_module._settings = None

        provider = get_llm_provider()
        assert isinstance(provider, MockLLMProvider)

        config_module._settings = None
