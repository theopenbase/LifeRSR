"""
Photo importer — extracts knowledge from images using Claude Vision.

Processes photos and screenshots to extract:
  - Scene descriptions
  - Text content (OCR for whiteboards, documents, business cards)
  - Location info from EXIF
  - Contextual understanding

  photos/ ──▶ Claude Vision ──▶ inbox/photo/{hash}.md

Supported formats: .jpg, .jpeg, .png, .heic, .webp
"""

import base64
import hashlib
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import anthropic

from .store import Note, save_note


SUPPORTED_FORMATS = {".jpg", ".jpeg", ".png", ".heic", ".webp"}

VISION_PROMPT = """请分析这张图片，提取以下信息：

1. **场景描述**: 简要描述图片中的场景（1-2句话）
2. **文字内容**: 如果图片中有文字（白板、文档、名片、屏幕截图等），请完整转录
3. **关键信息**: 提取任何有价值的结构化信息（人名、公司名、日期、数字、地址等）

请用以下格式输出：

场景: [描述]

文字内容:
[如果有文字，完整转录；如果没有，写"无"]

关键信息:
[提取的结构化信息，每条一行；如果没有，写"无"]
"""


@dataclass
class PhotoResult:
    """Result of processing a photo."""
    description: str
    text_content: str
    key_info: str


class PhotoImporter:
    """Imports and processes photos using Claude Vision."""

    def __init__(
        self,
        inbox_dir: str | Path,
        api_key: Optional[str] = None,
        model: str = "claude-sonnet-4-20250514",
    ):
        self.inbox_dir = Path(inbox_dir)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.model = model
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY not set.")
        self._client = anthropic.Anthropic(api_key=self.api_key)

    def process_photo(self, photo_path: str | Path) -> Note | None:
        """Process a single photo and save as a note.

        Args:
            photo_path: Path to the image file.

        Returns:
            The saved Note, or None if processing fails.
        """
        photo_path = Path(photo_path)

        if not photo_path.exists():
            raise FileNotFoundError(f"Photo not found: {photo_path}")

        if photo_path.suffix.lower() not in SUPPORTED_FORMATS:
            return None  # skip unsupported formats

        # Check file size (Claude limit: ~20MB)
        size_mb = photo_path.stat().st_size / (1024 * 1024)
        if size_mb > 20:
            return None  # skip oversized files

        # Generate stable ID from file hash
        file_hash = _file_hash(photo_path)
        note_id = f"photo-{file_hash}"

        # Read and encode image
        image_data = base64.b64encode(photo_path.read_bytes()).decode("utf-8")
        media_type = _media_type(photo_path.suffix.lower())

        # Call Claude Vision
        try:
            result = self._analyze_image(image_data, media_type)
        except Exception as e:
            # Log but don't crash — save what we can
            result = PhotoResult(
                description=f"图片分析失败: {e}",
                text_content="",
                key_info="",
            )

        # Extract EXIF timestamp if available
        created = _get_exif_time(photo_path) or _now_iso()

        # Build note content
        content_parts = [f"**来源文件**: {photo_path.name}"]
        if result.description:
            content_parts.append(f"\n**场景**: {result.description}")
        if result.text_content and result.text_content != "无":
            content_parts.append(f"\n**文字内容**:\n{result.text_content}")
        if result.key_info and result.key_info != "无":
            content_parts.append(f"\n**关键信息**:\n{result.key_info}")

        note = Note(
            id=note_id,
            source="photo",
            title=f"照片: {result.description[:50]}" if result.description else f"照片: {photo_path.name}",
            content="\n".join(content_parts),
            created=created,
            synced=_now_iso(),
        )

        save_note(note, self.inbox_dir)
        return note

    def process_directory(self, photo_dir: str | Path) -> list[Note]:
        """Process all photos in a directory.

        Args:
            photo_dir: Directory containing photos.

        Returns:
            List of successfully processed notes.
        """
        photo_dir = Path(photo_dir)
        if not photo_dir.exists():
            return []

        notes = []
        for filepath in sorted(photo_dir.iterdir()):
            if filepath.suffix.lower() in SUPPORTED_FORMATS:
                try:
                    note = self.process_photo(filepath)
                    if note:
                        notes.append(note)
                except Exception:
                    continue  # skip failed photos

        return notes

    def _analyze_image(self, image_data: str, media_type: str) -> PhotoResult:
        """Call Claude Vision API to analyze an image."""
        response = self._client.messages.create(
            model=self.model,
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data,
                        },
                    },
                    {
                        "type": "text",
                        "text": VISION_PROMPT,
                    },
                ],
            }],
        )

        text = response.content[0].text
        return self._parse_vision_response(text)

    def _parse_vision_response(self, text: str) -> PhotoResult:
        """Parse the structured response from Claude Vision."""
        description = ""
        text_content = ""
        key_info = ""

        current_section = None
        lines = text.split("\n")

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("场景:") or stripped.startswith("场景："):
                description = stripped.split(":", 1)[-1].split("：", 1)[-1].strip()
                current_section = "description"
            elif stripped.startswith("文字内容:") or stripped.startswith("文字内容："):
                content_after = stripped.split(":", 1)[-1].split("：", 1)[-1].strip()
                text_content = content_after
                current_section = "text"
            elif stripped.startswith("关键信息:") or stripped.startswith("关键信息："):
                content_after = stripped.split(":", 1)[-1].split("：", 1)[-1].strip()
                key_info = content_after
                current_section = "info"
            elif current_section == "text":
                text_content += "\n" + line
            elif current_section == "info":
                key_info += "\n" + line

        return PhotoResult(
            description=description.strip(),
            text_content=text_content.strip(),
            key_info=key_info.strip(),
        )


# --- Helpers ---

def _file_hash(filepath: Path) -> str:
    h = hashlib.sha256()
    h.update(filepath.read_bytes())
    return h.hexdigest()[:12]


def _media_type(suffix: str) -> str:
    return {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".heic": "image/heic",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")


def _get_exif_time(filepath: Path) -> Optional[str]:
    """Try to extract creation time from EXIF data."""
    try:
        # Use file modification time as fallback
        mtime = filepath.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    except Exception:
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
