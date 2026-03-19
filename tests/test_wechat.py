"""Tests for the WeChat importer — chat text parsing."""

import pytest
from pathlib import Path

from src.wechat import WeChatImporter, ChatMessage


@pytest.fixture
def importer(tmp_path):
    return WeChatImporter(tmp_path / "inbox" / "wechat")


# --- Format 1: "Name YYYY-MM-DD HH:MM\ncontent" ---

class TestFormat1:
    def test_parse_timestamped_messages(self, importer):
        text = """张三 2026-03-15 10:30
这是一条消息

李四 2026-03-15 10:31
这是回复"""
        messages = importer._parse_messages(text)
        assert len(messages) == 2
        assert messages[0].sender == "张三"
        assert messages[0].timestamp == "2026-03-15 10:30"
        assert messages[0].content == "这是一条消息"
        assert messages[1].sender == "李四"
        assert messages[1].content == "这是回复"

    def test_parse_with_seconds(self, importer):
        text = """张三 2026-03-15 10:30:45
消息内容"""
        messages = importer._parse_messages(text)
        assert len(messages) == 1
        assert messages[0].timestamp == "2026-03-15 10:30:45"


# --- Format 2: "Name: content" ---

class TestFormat2:
    def test_parse_simple_messages(self, importer):
        text = """张三: 你好
李四: 你好呀
张三: 吃了吗"""
        messages = importer._parse_messages(text)
        assert len(messages) == 3
        assert messages[0].sender == "张三"
        assert messages[0].content == "你好"
        assert messages[1].sender == "李四"
        assert messages[2].content == "吃了吗"

    def test_parse_chinese_colon(self, importer):
        text = """张三：你好
李四：你好呀"""
        messages = importer._parse_messages(text)
        assert len(messages) == 2

    def test_single_message_falls_to_fallback(self, importer):
        """Format 2 requires at least 2 messages."""
        text = "张三: 你好"
        messages = importer._parse_messages(text)
        assert len(messages) == 1
        assert messages[0].sender == "未知"  # fallback


# --- Fallback ---

class TestFallback:
    def test_plain_text_fallback(self, importer):
        text = "这只是一段普通文字，没有聊天格式"
        messages = importer._parse_messages(text)
        assert len(messages) == 1
        assert messages[0].sender == "未知"
        assert messages[0].content == text


# --- ingest_text ---

class TestIngestText:
    def test_ingest_empty_returns_none(self, importer):
        assert importer.ingest_text("") is None
        assert importer.ingest_text("   ") is None

    def test_ingest_saves_note(self, importer):
        text = "张三: 你好\n李四: 你好呀"
        note = importer.ingest_text(text)
        assert note is not None
        assert note.source == "wechat"
        assert note.id.startswith("wechat-")
        assert "张三" in note.content

    def test_ingest_with_context(self, importer):
        text = "张三: 你好\n李四: 你好呀"
        note = importer.ingest_text(text, context="工作群")
        assert note is not None
        assert "工作群" in note.title

    def test_ingest_same_text_same_id(self, importer):
        """Same text should produce same ID (idempotent)."""
        text = "张三: 你好\n李四: 你好呀"
        note1 = importer.ingest_text(text)
        note2 = importer.ingest_text(text)
        assert note1.id == note2.id


# --- ingest_file ---

class TestIngestFile:
    def test_ingest_file(self, importer, tmp_path):
        chat_file = tmp_path / "chat.txt"
        chat_file.write_text("张三: 你好\n李四: 你好呀", encoding="utf-8")
        note = importer.ingest_file(chat_file)
        assert note is not None
        assert note.source == "wechat"

    def test_ingest_nonexistent_file_raises(self, importer, tmp_path):
        with pytest.raises(FileNotFoundError):
            importer.ingest_file(tmp_path / "nonexistent.txt")
