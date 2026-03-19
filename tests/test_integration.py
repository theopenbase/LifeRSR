"""Integration tests — end-to-end workflows across modules."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.store import Note, save_note, load_note, list_notes, count_notes
from src.staging import StagingManager
from src.wechat import WeChatImporter


@pytest.fixture
def data_dir(tmp_path):
    """Set up the full data directory structure."""
    dirs = {
        "inbox_getnote": tmp_path / "inbox" / "getnote",
        "inbox_wechat": tmp_path / "inbox" / "wechat",
        "inbox_photo": tmp_path / "inbox" / "photo",
        "knowledge": tmp_path / "knowledge",
        "staging": tmp_path / "staging",
    }
    for d in dirs.values():
        d.mkdir(parents=True)
    dirs["root"] = tmp_path
    return dirs


class TestIngestDistillFlow:
    """Test the full ingest → distill → route flow."""

    def test_getnote_to_knowledge(self, data_dir):
        """Simulate: recall note → save to inbox → distill → route to knowledge."""
        # Step 1: Save a raw note to inbox (simulating recall)
        raw_note = Note(
            id="getnote-abc123",
            source="getnote",
            title="AI创业笔记",
            content="今天和李总聊了AI在教育领域的机会，觉得有很大潜力。",
        )
        save_note(raw_note, data_dir["inbox_getnote"])
        assert count_notes(data_dir["inbox_getnote"]) == 1

        # Step 2: Simulate distillation result (mock)
        enriched = Note(
            id=raw_note.id,
            source=raw_note.source,
            title=raw_note.title,
            content=raw_note.content,
            confidence="high",
            category="opportunity",
            tags=["AI", "教育", "创业"],
            entities={"people": ["李总"], "companies": [], "topics": ["AI教育"], "places": []},
            summary="与李总讨论AI教育领域的创业机会",
            raw_content=raw_note.content,
        )

        # Step 3: Route by confidence
        save_note(enriched, data_dir["knowledge"])
        assert count_notes(data_dir["knowledge"]) == 1

        # Verify the saved note
        loaded = load_note(data_dir["knowledge"] / "getnote-abc123.md")
        assert loaded.confidence == "high"
        assert loaded.category == "opportunity"
        assert "李总" in loaded.entities.get("people", [])

    def test_wechat_to_staging(self, data_dir):
        """Simulate: WeChat ingest → distill → route to staging (low confidence)."""
        # Step 1: Ingest WeChat text
        importer = WeChatImporter(data_dir["inbox_wechat"])
        note = importer.ingest_text(
            "张三: 下周二开会\n李四: 好的",
            context="工作群",
        )
        assert note is not None

        # Step 2: Simulate low-confidence distillation
        enriched = Note(
            id=note.id,
            source=note.source,
            title=note.title,
            content=note.content,
            confidence="low",
            category="event",
            tags=["会议"],
            summary="工作群讨论开会安排",
            raw_content=note.content,
        )

        # Step 3: Route to staging
        save_note(enriched, data_dir["staging"])
        assert count_notes(data_dir["staging"]) == 1


class TestStagingReviewFlow:
    """Test the staging review workflow end-to-end."""

    def test_approve_flow(self, data_dir):
        staging = StagingManager(data_dir["staging"], data_dir["knowledge"])

        # Create staged notes
        for i, conf in enumerate(["medium", "low", "medium"]):
            note = Note(
                id=f"review-{i}",
                source="getnote",
                title=f"待审核 {i}",
                content=f"内容 {i}",
                confidence=conf,
                category="idea",
            )
            save_note(note, data_dir["staging"])

        assert staging.pending_count() == 3

        # Approve one
        staging.approve("review-0")
        assert staging.pending_count() == 2
        assert count_notes(data_dir["knowledge"]) == 1

        # Reject one
        staging.reject("review-1")
        assert staging.pending_count() == 1

        # Approve remaining
        staging.approve_all()
        assert staging.pending_count() == 0
        assert count_notes(data_dir["knowledge"]) == 2  # 1 + 1 from approve_all


class TestCrossSourceQuery:
    """Test querying across multiple sources."""

    def test_query_finds_across_sources(self, data_dir):
        # Add notes from different sources
        notes = [
            Note(id="gn-1", source="getnote", title="AI笔记", content="机器学习相关",
                 tags=["AI"], category="reference"),
            Note(id="wc-1", source="wechat", title="微信: AI讨论", content="聊了聊AI的未来",
                 tags=["AI"], category="conversation"),
        ]
        save_note(notes[0], data_dir["knowledge"])
        save_note(notes[1], data_dir["knowledge"])

        from src.store import query_notes
        results = query_notes(data_dir["knowledge"], "AI")
        assert len(results) == 2

    def test_query_empty_knowledge_base(self, data_dir):
        from src.store import query_notes
        results = query_notes(data_dir["knowledge"], "anything")
        assert results == []


class TestNoteIdempotency:
    """Test that the same content produces stable IDs."""

    def test_wechat_same_text_same_id(self, data_dir):
        importer = WeChatImporter(data_dir["inbox_wechat"])
        text = "张三: 你好\n李四: 你好呀"
        note1 = importer.ingest_text(text)
        note2 = importer.ingest_text(text)
        assert note1.id == note2.id

    def test_overwrite_preserves_latest(self, data_dir):
        """Saving the same note ID twice should keep the latest version."""
        note_v1 = Note(id="stable-001", source="test", title="V1", content="版本1")
        note_v2 = Note(id="stable-001", source="test", title="V2", content="版本2")

        save_note(note_v1, data_dir["knowledge"])
        save_note(note_v2, data_dir["knowledge"])

        loaded = load_note(data_dir["knowledge"] / "stable-001.md")
        assert "V2" in loaded.title
        assert count_notes(data_dir["knowledge"]) == 1
