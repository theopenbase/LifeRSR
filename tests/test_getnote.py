"""Tests for the Get笔记 API client — mock HTTP calls."""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.getnote import (
    GetNoteClient, GetNoteConfig, SyncState, RecalledNote,
    GetNoteAuthError, GetNoteRateLimitError, GetNoteAPIError,
    load_config, _content_hash,
)


@pytest.fixture
def config():
    return GetNoteConfig(
        api_key="test-key-123",
        topic_id="topic-456",
        top_k=5,
    )


@pytest.fixture
def sync_state(tmp_path):
    db_path = tmp_path / ".state.db"
    with SyncState(db_path) as state:
        yield state


MOCK_RECALL_RESPONSE = {
    "data": [
        {
            "id": "note-001",
            "title": "AI教育笔记",
            "content": "这是一篇关于AI教育的笔记。",
            "score": 0.95,
            "type": "NOTE",
            "recall_source": "embedding",
        },
        {
            "id": "note-002",
            "title": "机器学习入门",
            "content": "机器学习基础知识。",
            "score": 0.88,
            "type": "FILE",
            "recall_source": "keyword",
        },
    ]
}


class TestGetNoteClient:
    def test_recall_parses_response(self, config):
        client = GetNoteClient(config)
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = MOCK_RECALL_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        client._client = MagicMock()
        client._client.post.return_value = mock_resp

        notes = client.recall("AI教育")
        assert len(notes) == 2
        assert notes[0].id == "note-001"
        assert notes[0].title == "AI教育笔记"
        assert notes[0].score == 0.95
        assert notes[1].recall_source == "keyword"

    def test_recall_auth_error(self, config):
        client = GetNoteClient(config)
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        client._client = MagicMock()
        client._client.post.return_value = mock_resp

        with pytest.raises(GetNoteAuthError):
            client.recall("test")

    def test_parse_empty_response(self, config):
        client = GetNoteClient(config)
        assert client._parse_recall_response({"data": []}) == []
        assert client._parse_recall_response({}) == []

    def test_parse_flat_list_response(self, config):
        """Some API responses return a flat list instead of nested 'data'."""
        client = GetNoteClient(config)
        flat = [
            {"id": "1", "title": "T", "content": "C", "score": 0.9, "type": "NOTE", "recall_source": "embedding"},
        ]
        notes = client._parse_recall_response(flat)
        assert len(notes) == 1

    def test_parse_malformed_item_skipped(self, config):
        client = GetNoteClient(config)
        data = {"data": [{"id": "1", "title": "T", "content": "C", "score": "not_a_number", "type": "NOTE", "recall_source": "x"}, "not_a_dict"]}
        notes = client._parse_recall_response(data)
        # "not_a_number" can be cast to float? No, it will raise ValueError
        # Actually float("not_a_number") raises ValueError, so it gets skipped
        # "not_a_dict" is not a dict, gets skipped
        assert len(notes) == 0


class TestSyncState:
    def test_is_synced_false_initially(self, sync_state):
        assert not sync_state.is_synced("note-001")

    def test_mark_synced_then_is_synced(self, sync_state):
        sync_state.mark_synced("note-001", "getnote", "some content")
        assert sync_state.is_synced("note-001")

    def test_has_changed_new_note(self, sync_state):
        assert sync_state.has_changed("note-001", "content")

    def test_has_changed_same_content(self, sync_state):
        sync_state.mark_synced("note-001", "getnote", "content")
        assert not sync_state.has_changed("note-001", "content")

    def test_has_changed_different_content(self, sync_state):
        sync_state.mark_synced("note-001", "getnote", "old content")
        assert sync_state.has_changed("note-001", "new content")

    def test_log_recall(self, sync_state):
        sync_state.log_recall("AI教育", 5)
        stats = sync_state.stats()
        assert stats["recall_queries"] == 1

    def test_stats(self, sync_state):
        sync_state.mark_synced("n1", "getnote", "c1")
        sync_state.mark_synced("n2", "getnote", "c2")
        sync_state.log_recall("q1", 3)
        stats = sync_state.stats()
        assert stats["synced_notes"] == 2
        assert stats["recall_queries"] == 1

    def test_mark_synced_updates_on_conflict(self, sync_state):
        """Re-syncing the same note should update, not fail."""
        sync_state.mark_synced("note-001", "getnote", "v1")
        sync_state.mark_synced("note-001", "getnote", "v2")
        assert not sync_state.has_changed("note-001", "v2")
        stats = sync_state.stats()
        assert stats["synced_notes"] == 1  # still 1, not 2


class TestLoadConfig:
    def test_load_config_success(self):
        with patch.dict("os.environ", {
            "GET_BIJI_API_KEY": "my-key",
            "GET_BIJI_TOPIC_ID": "my-topic",
        }):
            config = load_config()
            assert config.api_key == "my-key"
            assert config.topic_id == "my-topic"

    def test_load_config_missing_key(self):
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("GET_BIJI_API_KEY", None)
            os.environ.pop("GET_BIJI_TOPIC_ID", None)
            with pytest.raises(GetNoteAuthError):
                load_config()

    def test_load_config_missing_topic(self):
        with patch.dict("os.environ", {"GET_BIJI_API_KEY": "key"}, clear=True):
            import os
            os.environ.pop("GET_BIJI_TOPIC_ID", None)
            with pytest.raises(Exception):
                load_config()


class TestHelpers:
    def test_content_hash_deterministic(self):
        assert _content_hash("hello") == _content_hash("hello")
        assert _content_hash("hello") != _content_hash("world")
