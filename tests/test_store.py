"""Tests for the store module — Markdown + YAML frontmatter I/O."""

import pytest
from pathlib import Path

from src.store import (
    Note, save_note, load_note, list_notes, query_notes,
    move_note, count_notes, _safe_filename, _extract_title,
    _extract_section, _note_matches,
)


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory for test notes."""
    return tmp_path


@pytest.fixture
def sample_note():
    """A fully populated note for testing."""
    return Note(
        id="test-001",
        source="getnote",
        title="AI教育笔记",
        content="这是一篇关于AI在教育领域应用的笔记。",
        created="2026-03-15T10:30:00+00:00",
        synced="2026-03-19T15:00:00+00:00",
        confidence="high",
        category="idea",
        tags=["AI", "教育", "技术"],
        entities={"people": ["李总"], "companies": ["某某公司"], "topics": ["AI教育"], "places": []},
        summary="AI在教育领域的应用前景",
        raw_content="原始内容：AI教育笔记",
    )


@pytest.fixture
def minimal_note():
    """A minimal note with only required fields."""
    return Note(
        id="test-002",
        source="wechat",
        title="简单笔记",
        content="一些内容",
    )


# --- save_note / load_note round-trip ---

class TestSaveLoad:
    def test_save_creates_file(self, tmp_dir, sample_note):
        path = save_note(sample_note, tmp_dir)
        assert path.exists()
        assert path.suffix == ".md"

    def test_save_load_roundtrip_full(self, tmp_dir, sample_note):
        save_note(sample_note, tmp_dir)
        loaded = load_note(tmp_dir / "test-001.md")
        assert loaded.id == "test-001"
        assert loaded.source == "getnote"
        assert loaded.confidence == "high"
        assert loaded.category == "idea"
        assert loaded.tags == ["AI", "教育", "技术"]
        assert loaded.entities["people"] == ["李总"]
        assert "AI在教育领域" in loaded.summary

    def test_save_load_roundtrip_minimal(self, tmp_dir, minimal_note):
        save_note(minimal_note, tmp_dir)
        loaded = load_note(tmp_dir / "test-002.md")
        assert loaded.id == "test-002"
        assert loaded.source == "wechat"
        assert loaded.tags == []
        assert loaded.entities == {}

    def test_save_creates_parent_dirs(self, tmp_path, sample_note):
        nested = tmp_path / "a" / "b" / "c"
        path = save_note(sample_note, nested)
        assert path.exists()

    def test_load_nonexistent_raises(self, tmp_dir):
        with pytest.raises(FileNotFoundError):
            load_note(tmp_dir / "nonexistent.md")

    def test_save_overwrites_existing(self, tmp_dir, sample_note):
        save_note(sample_note, tmp_dir)
        sample_note.summary = "更新后的摘要"
        save_note(sample_note, tmp_dir)
        loaded = load_note(tmp_dir / "test-001.md")
        assert "更新后" in loaded.summary


# --- list_notes / count_notes ---

class TestListCount:
    def test_list_notes_empty_dir(self, tmp_dir):
        assert list_notes(tmp_dir) == []

    def test_list_notes_nonexistent_dir(self, tmp_path):
        assert list_notes(tmp_path / "nope") == []

    def test_list_notes_returns_all(self, tmp_dir, sample_note, minimal_note):
        save_note(sample_note, tmp_dir)
        save_note(minimal_note, tmp_dir)
        notes = list_notes(tmp_dir)
        assert len(notes) == 2

    def test_count_notes(self, tmp_dir, sample_note, minimal_note):
        assert count_notes(tmp_dir) == 0
        save_note(sample_note, tmp_dir)
        assert count_notes(tmp_dir) == 1
        save_note(minimal_note, tmp_dir)
        assert count_notes(tmp_dir) == 2

    def test_count_nonexistent_dir(self, tmp_path):
        assert count_notes(tmp_path / "nope") == 0


# --- query_notes ---

class TestQuery:
    def test_query_by_title(self, tmp_dir, sample_note):
        save_note(sample_note, tmp_dir)
        results = query_notes(tmp_dir, "AI教育")
        assert len(results) == 1

    def test_query_by_tag(self, tmp_dir, sample_note):
        save_note(sample_note, tmp_dir)
        results = query_notes(tmp_dir, "教育")
        assert len(results) == 1

    def test_query_by_content(self, tmp_dir, sample_note):
        save_note(sample_note, tmp_dir)
        results = query_notes(tmp_dir, "教育领域")
        assert len(results) == 1

    def test_query_no_match(self, tmp_dir, sample_note):
        save_note(sample_note, tmp_dir)
        results = query_notes(tmp_dir, "量子计算")
        assert len(results) == 0

    def test_query_case_insensitive(self, tmp_dir):
        note = Note(id="en-001", source="test", title="Machine Learning", content="Deep learning notes")
        save_note(note, tmp_dir)
        results = query_notes(tmp_dir, "machine")
        assert len(results) == 1

    def test_query_by_category(self, tmp_dir, sample_note):
        save_note(sample_note, tmp_dir)
        results = query_notes(tmp_dir, "idea")
        assert len(results) == 1

    def test_query_by_entity(self, tmp_dir, sample_note):
        save_note(sample_note, tmp_dir)
        results = query_notes(tmp_dir, "李总")
        assert len(results) == 1


# --- move_note ---

class TestMoveNote:
    def test_move_note(self, tmp_path, sample_note):
        src_dir = tmp_path / "src"
        dest_dir = tmp_path / "dest"
        src_dir.mkdir()

        src_path = save_note(sample_note, src_dir)
        assert src_path.exists()

        new_path = move_note(src_path, dest_dir)
        assert new_path.exists()
        assert not src_path.exists()
        assert new_path.parent == dest_dir


# --- Helpers ---

class TestHelpers:
    def test_safe_filename(self):
        assert _safe_filename("getnote/123") == "getnote_123"
        assert _safe_filename("note with spaces") == "note_with_spaces"
        assert _safe_filename("simple") == "simple"

    def test_extract_title(self):
        assert _extract_title("# My Title\n\nContent") == "My Title"
        assert _extract_title("No heading here") == "Untitled"
        assert _extract_title("## Not H1\n# Real Title") == "Real Title"

    def test_extract_section(self):
        content = "# Title\n\n## 摘要\n这是摘要\n\n## 原文\n这是原文"
        assert _extract_section(content, "摘要") == "这是摘要"
        assert _extract_section(content, "原文") == "这是原文"
        assert _extract_section(content, "不存在") == ""

    def test_note_matches(self):
        note = Note(
            id="t", source="test", title="AI教育", content="内容",
            tags=["机器学习"], category="idea",
            entities={"people": ["张三"]},
        )
        assert _note_matches(note, "ai教育")
        assert _note_matches(note, "机器学习")
        assert _note_matches(note, "idea")
        assert _note_matches(note, "张三")
        assert not _note_matches(note, "量子")
