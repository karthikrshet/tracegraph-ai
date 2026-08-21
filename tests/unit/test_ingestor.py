"""
Tests for the Requirement Ingestor subsystem.
Run: pytest tests/unit/test_ingestor.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.ingestor import SEED_REQUIREMENTS, RequirementIngestor
from app.llm import MockLLMProvider
from app.models import CoverageStatus, Requirement


@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path


@pytest.fixture
def mock_ingestor(tmp_data_dir):
    return RequirementIngestor(llm=MockLLMProvider(), data_dir=tmp_data_dir)


@pytest.mark.asyncio
async def test_seed_requirements_loaded(mock_ingestor):
    """Seed requirements should always load — no network needed."""
    requirements = await mock_ingestor.run(use_seeds=True)
    assert len(requirements) >= len(SEED_REQUIREMENTS), (
        f"Expected at least {len(SEED_REQUIREMENTS)} requirements, got {len(requirements)}"
    )


@pytest.mark.asyncio
async def test_requirement_ids_unique(mock_ingestor):
    """All requirement IDs must be unique."""
    requirements = await mock_ingestor.run(use_seeds=True)
    ids = [r.id for r in requirements]
    assert len(ids) == len(set(ids)), "Duplicate requirement IDs found"


@pytest.mark.asyncio
async def test_requirement_fields_non_empty(mock_ingestor):
    """All requirements must have non-empty text and category."""
    requirements = await mock_ingestor.run(use_seeds=True)
    for req in requirements:
        assert req.text.strip(), f"Empty text for {req.id}"
        assert req.category.strip(), f"Empty category for {req.id}"


@pytest.mark.asyncio
async def test_testability_scores_in_range(mock_ingestor):
    """Testability scores must be between 0 and 1."""
    requirements = await mock_ingestor.run(use_seeds=True)
    for req in requirements:
        assert 0.0 <= req.testability_score <= 1.0, (
            f"Testability score out of range for {req.id}: {req.testability_score}"
        )


@pytest.mark.asyncio
async def test_requirements_persisted_to_disk(mock_ingestor, tmp_data_dir):
    """Ingested requirements should be saved to JSONL."""
    await mock_ingestor.run(use_seeds=True)
    output_file = tmp_data_dir / "requirements.jsonl"
    assert output_file.exists(), "requirements.jsonl not created"
    lines = output_file.read_text().strip().split("\n")
    assert len(lines) >= len(SEED_REQUIREMENTS)


@pytest.mark.asyncio
async def test_load_from_disk_excludes_seed_fixtures(mock_ingestor, tmp_data_dir):
    """Legacy seed artifacts must never reappear as user-ingested requirements."""
    await mock_ingestor.run(use_seeds=True)
    loaded = RequirementIngestor.load_from_disk(tmp_data_dir)
    assert loaded == []


def test_coverage_status_default():
    """New requirements should default to UNVERIFIED."""
    req = Requirement(id="REQ-TEST", text="test", category="test")
    assert req.coverage_status == CoverageStatus.UNVERIFIED


def test_product_attribute_requirements_exist():
    """Critical: product_attributes category requirements must be present (needed for PR #6857 analysis)."""
    ids_and_categories = [(r["id"], r["category"]) for r in SEED_REQUIREMENTS]
    attr_reqs = [r for r in ids_and_categories if r[1] == "product_attributes"]
    assert len(attr_reqs) >= 3, (
        "Need at least 3 product_attributes requirements for PR #6857 blast radius"
    )
