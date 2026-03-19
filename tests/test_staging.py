"""Tests for the staging review workflow."""

import pytest
from pathlib import Path

from src.store import Note, save_note
from src.staging import StagingManager


@pytest.fixture
def dirs(tmp_path):
    staging = tmp_path / "staging"
    knowledge = tmp_path / "knowledge"
    return staging, knowledge


@pytest.fixture
def manager(dirs):
    return StagingManager(*dirs)


@pytest.fixture
def staged_note(dirs):
    """Create a note in staging and return it."""
    staging, _ = dirs
    note = Note(
        id="test-staged-001",
        source="getnote",
        title="待审核笔记",
        content="这是一篇待审核的笔记。",
        confidence="medium",
        category="idea",
        tags=["测试"],
    )
    save_note(note, staging)
    return note


class TestPending:
    def test_pending_empty(self, manager):
        assert manager.pending() == []
        assert manager.pending_count() == 0

    def test_pending_lists_notes(self, manager, staged_note):
        pending = manager.pending()
        assert len(pending) == 1
        assert pending[0].id == "test-staged-001"

    def test_pending_count(self, manager, staged_note):
        assert manager.pending_count() == 1


class TestApprove:
    def test_approve_moves_to_knowledge(self, manager, staged_note, dirs):
        staging, knowledge = dirs
        new_path = manager.approve("test-staged-001")
        assert new_path.exists()
        assert new_path.parent == knowledge
        # Should be gone from staging
        assert manager.pending_count() == 0

    def test_approve_nonexistent_raises(self, manager):
        with pytest.raises(FileNotFoundError):
            manager.approve("nonexistent-id")


class TestReject:
    def test_reject_deletes_from_staging(self, manager, staged_note):
        manager.reject("test-staged-001")
        assert manager.pending_count() == 0

    def test_reject_nonexistent_raises(self, manager):
        with pytest.raises(FileNotFoundError):
            manager.reject("nonexistent-id")


class TestApproveAll:
    def test_approve_all(self, manager, dirs):
        staging, knowledge = dirs
        # Create multiple staged notes
        for i in range(3):
            note = Note(
                id=f"batch-{i}",
                source="test",
                title=f"批量笔记 {i}",
                content=f"内容 {i}",
                confidence="low",
            )
            save_note(note, staging)

        count = manager.approve_all()
        assert count == 3
        assert manager.pending_count() == 0
        # All should be in knowledge
        from src.store import count_notes
        assert count_notes(knowledge) == 3

    def test_approve_all_empty(self, manager):
        assert manager.approve_all() == 0
