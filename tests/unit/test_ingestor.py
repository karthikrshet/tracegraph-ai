"""
Tests for the Requirement Ingestor subsystem.
Run: pytest tests/unit/test_ingestor.py -v
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.ingestor import RequirementIngestor
from app.llm import MockLLMProvider
from app.models import CoverageStatus, Requirement


@pytest.fixture
def tmp_data_dir(tmp_path):
    return tmp_path


TEST_SPEC_TEXT = (
    "People can open a public article detail screen, read its title and body, "
    "and use its observed navigation controls to return to the article list."
)


@pytest.fixture
def mock_ingestor(tmp_data_dir, monkeypatch):
    ingestor = RequirementIngestor(llm=MockLLMProvider(), data_dir=tmp_data_dir)

    async def extract_from_test_source(*_args, **_kwargs):
        return [
            Requirement(
                id="REQ-001",
                text="People can open an article detail screen and return to the article list.",
                category="articles",
                source_url="inline://operator-submitted",
                testability_score=0.9,
            )
        ]

    monkeypatch.setattr(ingestor, "_extract_requirements_llm", extract_from_test_source)
    return ingestor


@pytest.mark.asyncio
async def test_requirements_are_extracted_from_an_explicit_source(mock_ingestor):
    """A test extractor stands in for the real LLM; production has no seed fallback."""
    requirements = await mock_ingestor.run(source_text=TEST_SPEC_TEXT)
    assert [requirement.id for requirement in requirements] == ["REQ-001"]


@pytest.mark.asyncio
async def test_requirement_ids_unique(mock_ingestor):
    """All requirement IDs must be unique."""
    requirements = await mock_ingestor.run(source_text=TEST_SPEC_TEXT)
    ids = [r.id for r in requirements]
    assert len(ids) == len(set(ids)), "Duplicate requirement IDs found"


@pytest.mark.asyncio
async def test_requirement_fields_non_empty(mock_ingestor):
    """All requirements must have non-empty text and category."""
    requirements = await mock_ingestor.run(source_text=TEST_SPEC_TEXT)
    for req in requirements:
        assert req.text.strip(), f"Empty text for {req.id}"
        assert req.category.strip(), f"Empty category for {req.id}"


@pytest.mark.asyncio
async def test_testability_scores_in_range(mock_ingestor):
    """Testability scores must be between 0 and 1."""
    requirements = await mock_ingestor.run(source_text=TEST_SPEC_TEXT)
    for req in requirements:
        assert 0.0 <= req.testability_score <= 1.0, (
            f"Testability score out of range for {req.id}: {req.testability_score}"
        )


@pytest.mark.asyncio
async def test_requirements_persisted_to_disk(mock_ingestor, tmp_data_dir):
    """Ingested requirements should be saved to JSONL."""
    await mock_ingestor.run(source_text=TEST_SPEC_TEXT)
    output_file = tmp_data_dir / "requirements.jsonl"
    assert output_file.exists(), "requirements.jsonl not created"
    lines = output_file.read_text().strip().split("\n")
    assert len(lines) == 1


@pytest.mark.asyncio
async def test_load_from_disk_excludes_legacy_seed_artifacts(tmp_data_dir):
    """Legacy seed artifacts must never reappear as user-ingested requirements."""
    (tmp_data_dir / "requirements.jsonl").write_text(
        Requirement(
            id="REQ-OLD",
            text="Legacy data must not be used.",
            category="legacy",
            source_url="seed://tracegraph-ai/requirements",
        ).model_dump_json()
        + "\n",
        encoding="utf-8",
    )
    loaded = RequirementIngestor.load_from_disk(tmp_data_dir)
    assert loaded == []


def test_coverage_status_default():
    """New requirements should default to UNVERIFIED."""
    req = Requirement(id="REQ-TEST", text="test", category="test")
    assert req.coverage_status == CoverageStatus.UNVERIFIED


@pytest.mark.asyncio
async def test_ingestion_rejects_missing_sources(mock_ingestor):
    """The pipeline must not invent requirements when no source was supplied."""
    with pytest.raises(ValueError, match="no requirements were invented"):
        await mock_ingestor.run()
