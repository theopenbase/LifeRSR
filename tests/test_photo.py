"""Tests for the photo importer — mock Claude Vision API."""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.photo import (
    PhotoImporter, PhotoResult, SUPPORTED_FORMATS,
    _file_hash, _media_type,
)


@pytest.fixture
def inbox_dir(tmp_path):
    return tmp_path / "inbox" / "photo"


@pytest.fixture
def importer(inbox_dir):
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-123"}):
        imp = PhotoImporter(inbox_dir)
        imp._client = MagicMock()
        return imp


@pytest.fixture
def sample_jpg(tmp_path):
    """Create a minimal JPEG-like file for testing."""
    f = tmp_path / "test.jpg"
    # Write some bytes (not a real JPEG, but enough for testing)
    f.write_bytes(b"\xff\xd8\xff\xe0" + b"x" * 100)
    return f


@pytest.fixture
def sample_png(tmp_path):
    f = tmp_path / "test.png"
    f.write_bytes(b"\x89PNG" + b"x" * 100)
    return f


MOCK_VISION_RESPONSE = """场景: 一张白板上写满了关于AI教育的思维导图

文字内容:
AI教育
- 个性化学习
- 自适应测试
- 智能辅导

关键信息:
- 主题: AI教育
- 类型: 思维导图"""


class TestProcessPhoto:
    def test_process_photo_success(self, importer, sample_jpg):
        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text=MOCK_VISION_RESPONSE)]
        importer._client.messages.create.return_value = mock_resp

        note = importer.process_photo(sample_jpg)
        assert note is not None
        assert note.source == "photo"
        assert note.id.startswith("photo-")
        assert "白板" in note.title or "AI教育" in note.title

    def test_process_nonexistent_raises(self, importer, tmp_path):
        with pytest.raises(FileNotFoundError):
            importer.process_photo(tmp_path / "nope.jpg")

    def test_process_unsupported_format(self, importer, tmp_path):
        txt = tmp_path / "file.txt"
        txt.write_text("not an image")
        assert importer.process_photo(txt) is None

    def test_process_oversized_file(self, importer, tmp_path):
        big = tmp_path / "huge.jpg"
        # Create a file > 20MB
        big.write_bytes(b"x" * (21 * 1024 * 1024))
        assert importer.process_photo(big) is None

    def test_process_photo_api_failure_graceful(self, importer, sample_jpg):
        """API failure should not crash — saves error description."""
        importer._client.messages.create.side_effect = Exception("API down")

        note = importer.process_photo(sample_jpg)
        assert note is not None
        assert "失败" in note.content or "失败" in note.title


class TestProcessDirectory:
    def test_process_directory(self, importer, tmp_path):
        photo_dir = tmp_path / "photos"
        photo_dir.mkdir()

        # Create test files
        (photo_dir / "a.jpg").write_bytes(b"\xff\xd8" + b"a" * 50)
        (photo_dir / "b.png").write_bytes(b"\x89PNG" + b"b" * 50)
        (photo_dir / "c.txt").write_text("not a photo")

        mock_resp = MagicMock()
        mock_resp.content = [MagicMock(text=MOCK_VISION_RESPONSE)]
        importer._client.messages.create.return_value = mock_resp

        notes = importer.process_directory(photo_dir)
        assert len(notes) == 2  # only .jpg and .png

    def test_process_empty_directory(self, importer, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        assert importer.process_directory(empty) == []

    def test_process_nonexistent_directory(self, importer, tmp_path):
        assert importer.process_directory(tmp_path / "nope") == []


class TestParseVisionResponse:
    def test_parse_full_response(self, importer):
        result = importer._parse_vision_response(MOCK_VISION_RESPONSE)
        assert result.description == "一张白板上写满了关于AI教育的思维导图"
        assert "个性化学习" in result.text_content
        assert "AI教育" in result.key_info

    def test_parse_empty_sections(self, importer):
        text = "场景: 一张风景照\n\n文字内容:\n无\n\n关键信息:\n无"
        result = importer._parse_vision_response(text)
        assert result.description == "一张风景照"
        assert result.text_content == "无"
        assert result.key_info == "无"

    def test_parse_chinese_colons(self, importer):
        text = "场景：办公室照片\n\n文字内容：\n无\n\n关键信息：\n无"
        result = importer._parse_vision_response(text)
        assert result.description == "办公室照片"


class TestHelpers:
    def test_file_hash_deterministic(self, tmp_path):
        f = tmp_path / "test.bin"
        f.write_bytes(b"hello world")
        h1 = _file_hash(f)
        h2 = _file_hash(f)
        assert h1 == h2
        assert len(h1) == 12

    def test_media_type(self):
        assert _media_type(".jpg") == "image/jpeg"
        assert _media_type(".jpeg") == "image/jpeg"
        assert _media_type(".png") == "image/png"
        assert _media_type(".heic") == "image/heic"
        assert _media_type(".webp") == "image/webp"
        assert _media_type(".xyz") == "image/jpeg"  # fallback

    def test_supported_formats(self):
        assert ".jpg" in SUPPORTED_FORMATS
        assert ".jpeg" in SUPPORTED_FORMATS
        assert ".png" in SUPPORTED_FORMATS
        assert ".heic" in SUPPORTED_FORMATS
        assert ".webp" in SUPPORTED_FORMATS
        assert ".gif" not in SUPPORTED_FORMATS


class TestImporterInit:
    def test_no_api_key_raises(self, inbox_dir):
        with patch.dict("os.environ", {}, clear=True):
            import os
            os.environ.pop("ANTHROPIC_API_KEY", None)
            with pytest.raises(ValueError, match="ANTHROPIC_API_KEY"):
                PhotoImporter(inbox_dir)
