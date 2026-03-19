"""Tests for the distillation pipeline — mock Claude API calls."""

import json
import pytest
from unittest.mock import MagicMock, patch

from src.store import Note
from src.distill import Distiller, DistillResult, DistillError


MOCK_RESPONSE_JSON = json.dumps({
    "category": "idea",
    "tags": ["AI", "教育"],
    "summary": "AI在教育领域的应用",
    "entities": {
        "people": ["李总"],
        "companies": ["某某公司"],
        "topics": ["AI教育"],
        "places": [],
    },
    "confidence": "high",
})


def _mock_response(text: str):
    """Create a mock Anthropic API response."""
    mock = MagicMock()
    mock.content = [MagicMock(text=text)]
    return mock


@pytest.fixture
def distiller():
    """Create a Distiller with mocked API key."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-123"}):
        d = Distiller()
        d._client = MagicMock()
        return d


@pytest.fixture
def sample_note():
    return Note(
        id="test-distill-001",
        source="getnote",
        title="AI教育笔记",
        content="这是一篇关于AI在教育领域应用的详细笔记。",
    )


class TestDistill:
    def test_distill_success(self, distiller, sample_note):
        distiller._client.messages.create.return_value = _mock_response(MOCK_RESPONSE_JSON)

        result = distiller.distill(sample_note)
        assert isinstance(result, DistillResult)
        assert result.category == "idea"
        assert result.confidence == "high"
        assert "AI" in result.tags
        assert result.entities["people"] == ["李总"]

    def test_distill_empty_content(self, distiller):
        note = Note(id="empty", source="test", title="Empty", content="   ")
        result = distiller.distill(note)
        assert result.confidence == "low"
        assert result.category == "other"

    def test_distill_code_block_wrapped(self, distiller, sample_note):
        """Claude sometimes wraps JSON in markdown code blocks."""
        wrapped = f"```json\n{MOCK_RESPONSE_JSON}\n```"
        distiller._client.messages.create.return_value = _mock_response(wrapped)

        result = distiller.distill(sample_note)
        assert result.category == "idea"

    def test_distill_invalid_category_normalized(self, distiller, sample_note):
        bad_json = json.dumps({
            "category": "invalid_category",
            "tags": [],
            "summary": "test",
            "entities": {},
            "confidence": "high",
        })
        distiller._client.messages.create.return_value = _mock_response(bad_json)

        result = distiller.distill(sample_note)
        assert result.category == "other"  # normalized

    def test_distill_invalid_confidence_normalized(self, distiller, sample_note):
        bad_json = json.dumps({
            "category": "idea",
            "tags": [],
            "summary": "test",
            "entities": {},
            "confidence": "very_high",
        })
        distiller._client.messages.create.return_value = _mock_response(bad_json)

        result = distiller.distill(sample_note)
        assert result.confidence == "medium"  # normalized

    def test_distill_missing_entity_keys(self, distiller, sample_note):
        """Missing entity keys should be filled with empty lists."""
        partial_json = json.dumps({
            "category": "idea",
            "tags": [],
            "summary": "test",
            "entities": {"people": ["张三"]},
            "confidence": "high",
        })
        distiller._client.messages.create.return_value = _mock_response(partial_json)

        result = distiller.distill(sample_note)
        assert result.entities["companies"] == []
        assert result.entities["topics"] == []
        assert result.entities["places"] == []

    def test_distill_tags_max_5(self, distiller, sample_note):
        many_tags = json.dumps({
            "category": "idea",
            "tags": ["1", "2", "3", "4", "5", "6", "7"],
            "summary": "test",
            "entities": {},
            "confidence": "high",
        })
        distiller._client.messages.create.return_value = _mock_response(many_tags)

        result = distiller.distill(sample_note)
        assert len(result.tags) == 5


class TestDistillNote:
    def test_distill_note_enriches(self, distiller, sample_note):
        distiller._client.messages.create.return_value = _mock_response(MOCK_RESPONSE_JSON)

        enriched = distiller.distill_note(sample_note)
        assert enriched.id == sample_note.id
        assert enriched.source == sample_note.source
        assert enriched.confidence == "high"
        assert enriched.category == "idea"
        assert enriched.summary == "AI在教育领域的应用"


class TestDistillerInit:
    def test_no_api_key_raises(self):
        with patch.dict("os.environ", {}, clear=True):
            # Remove ANTHROPIC_API_KEY if set
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(DistillError, match="ANTHROPIC_API_KEY"):
                Distiller()
