"""
WeChat importer — parses manually pasted chat text and screenshots.

Input methods:
  1. Paste chat text into a file in data/inbox/wechat/
  2. Drop screenshots into data/inbox/wechat/ (multimodal processing via photo.py)

Chat text format detection:
  WeChat exported text typically looks like:
    张三 2026-03-15 10:30
    这是一条消息

    李四 2026-03-15 10:31
    这是回复

  Or simpler format:
    张三: 这是一条消息
    李四: 这是回复

  ┌───────────────┐     parse      ┌──────────────┐
  │ pasted text   │ ─────────────▶ │ inbox/wechat/ │
  │ or screenshot │                │ {hash}.md     │
  └───────────────┘                └──────────────┘
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .store import Note, save_note


@dataclass
class ChatMessage:
    """A single message from a WeChat conversation."""
    sender: str
    content: str
    timestamp: Optional[str] = None


class WeChatImporter:
    """Parses WeChat chat text into structured notes."""

    def __init__(self, inbox_dir: str | Path):
        self.inbox_dir = Path(inbox_dir)
        self.inbox_dir.mkdir(parents=True, exist_ok=True)

    def ingest_text(self, text: str, context: str = "") -> Note | None:
        """Parse pasted WeChat text and save as a note.

        Args:
            text: Raw pasted chat text.
            context: Optional context about the conversation (e.g., group name).

        Returns:
            The saved Note, or None if text is empty/unparseable.
        """
        text = text.strip()
        if not text:
            return None

        messages = self._parse_messages(text)

        # Generate a stable ID from content hash
        note_id = f"wechat-{_text_hash(text)}"

        # Build title from context or first message
        if context:
            title = f"微信: {context}"
        elif messages:
            first = messages[0]
            preview = first.content[:30] + ("..." if len(first.content) > 30 else "")
            title = f"微信: {first.sender} - {preview}"
        else:
            title = "微信对话"

        # Build structured content
        content_parts = []
        if context:
            content_parts.append(f"**对话: {context}**\n")

        senders = set()
        for msg in messages:
            senders.add(msg.sender)
            ts = f" ({msg.timestamp})" if msg.timestamp else ""
            content_parts.append(f"**{msg.sender}**{ts}: {msg.content}")

        content = "\n\n".join(content_parts) if content_parts else text

        note = Note(
            id=note_id,
            source="wechat",
            title=title,
            content=content,
            created=_now_iso(),
            synced=_now_iso(),
            raw_content=text,
        )

        save_note(note, self.inbox_dir)
        return note

    def ingest_file(self, filepath: str | Path, context: str = "") -> Note | None:
        """Read a text file and ingest its content.

        Args:
            filepath: Path to a .txt file containing pasted chat.
            context: Optional conversation context.

        Returns:
            The saved Note, or None if file is empty.
        """
        filepath = Path(filepath)
        if not filepath.exists():
            raise FileNotFoundError(f"File not found: {filepath}")

        text = filepath.read_text(encoding="utf-8")
        return self.ingest_text(text, context)

    def _parse_messages(self, text: str) -> list[ChatMessage]:
        """Attempt to parse chat text into structured messages.

        Supports multiple formats:
          1. "Name timestamp\\ncontent" (WeChat export)
          2. "Name: content" (simple format)
          3. Falls back to treating entire text as one message
        """
        messages = []

        # Try format 1: "Name YYYY-MM-DD HH:MM\ncontent"
        pattern1 = re.compile(
            r'^(.+?)\s+(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}(?::\d{2})?)\s*$',
            re.MULTILINE,
        )
        matches = list(pattern1.finditer(text))
        if matches:
            for i, match in enumerate(matches):
                sender = match.group(1).strip()
                timestamp = match.group(2).strip()
                # Content is between this match end and next match start
                start = match.end()
                end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
                content = text[start:end].strip()
                if content:
                    messages.append(ChatMessage(
                        sender=sender,
                        content=content,
                        timestamp=timestamp,
                    ))
            if messages:
                return messages

        # Try format 2: "Name: content"
        pattern2 = re.compile(r'^(.{1,20})[:：]\s*(.+)$', re.MULTILINE)
        matches2 = list(pattern2.finditer(text))
        if len(matches2) >= 2:  # at least 2 messages to consider it a conversation
            for match in matches2:
                sender = match.group(1).strip()
                content = match.group(2).strip()
                if content:
                    messages.append(ChatMessage(sender=sender, content=content))
            if messages:
                return messages

        # Fallback: treat as single message from unknown sender
        messages.append(ChatMessage(sender="未知", content=text))
        return messages


# --- Helpers ---

def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
