"""
Knowledge store — reads and writes Markdown files with YAML frontmatter.

File format:
  ---
  id: getnote-12345
  source: getnote
  created: 2026-03-15T10:30:00+00:00
  synced: 2026-03-19T15:00:00+00:00
  confidence: high
  category: idea
  tags: [AI, 教育]
  entities:
    people: [李总]
    companies: [某某公司]
    topics: [AI教育]
  ---
  # Title

  ## 摘要
  One-line summary...

  ## 原文
  Original content...

Directory layout:
  data/
  ├── inbox/{source}/{id}.md     # raw imported content
  ├── knowledge/{id}.md          # distilled, high-confidence
  └── staging/{id}.md            # distilled, needs review
"""

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import frontmatter


@dataclass
class Note:
    """A note in the knowledge base."""
    id: str
    source: str  # getnote, wechat, photo
    title: str
    content: str
    created: str = ""
    synced: str = ""
    confidence: str = ""  # high, medium, low
    category: str = ""
    tags: list[str] = field(default_factory=list)
    entities: dict = field(default_factory=dict)
    summary: str = ""
    raw_content: str = ""  # original content before distillation


def save_note(note: Note, directory: str | Path) -> Path:
    """Save a note as a Markdown file with YAML frontmatter.

    Args:
        note: The note to save.
        directory: Target directory (inbox/knowledge/staging).

    Returns:
        Path to the saved file.
    """
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)

    # Build frontmatter metadata
    metadata = {
        "id": note.id,
        "source": note.source,
    }
    if note.created:
        metadata["created"] = note.created
    if note.synced:
        metadata["synced"] = note.synced
    if note.confidence:
        metadata["confidence"] = note.confidence
    if note.category:
        metadata["category"] = note.category
    if note.tags:
        metadata["tags"] = note.tags
    if note.entities:
        metadata["entities"] = note.entities

    # Build body
    body_parts = [f"# {note.title}"]

    if note.summary:
        body_parts.append(f"\n## 摘要\n{note.summary}")

    if note.raw_content:
        body_parts.append(f"\n## 原文\n{note.raw_content}")
    elif note.content:
        body_parts.append(f"\n## 内容\n{note.content}")

    body = "\n".join(body_parts)

    # Write file
    post = frontmatter.Post(body, **metadata)
    filepath = directory / f"{_safe_filename(note.id)}.md"
    filepath.write_text(frontmatter.dumps(post), encoding="utf-8")

    return filepath


def load_note(filepath: str | Path) -> Note:
    """Load a note from a Markdown file with YAML frontmatter.

    Args:
        filepath: Path to the .md file.

    Returns:
        Parsed Note object.

    Raises:
        FileNotFoundError: If the file doesn't exist.
        ValueError: If the file can't be parsed.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Note not found: {filepath}")

    post = frontmatter.load(str(filepath))

    return Note(
        id=post.metadata.get("id", filepath.stem),
        source=post.metadata.get("source", "unknown"),
        title=_extract_title(post.content),
        content=post.content,
        created=str(post.metadata.get("created", "")),
        synced=str(post.metadata.get("synced", "")),
        confidence=post.metadata.get("confidence", ""),
        category=post.metadata.get("category", ""),
        tags=post.metadata.get("tags", []),
        entities=post.metadata.get("entities", {}),
        summary=_extract_section(post.content, "摘要"),
        raw_content=_extract_section(post.content, "原文"),
    )


def list_notes(directory: str | Path) -> list[Note]:
    """List all notes in a directory.

    Args:
        directory: Path to scan for .md files.

    Returns:
        List of parsed Notes, sorted by synced date (newest first).
    """
    directory = Path(directory)
    if not directory.exists():
        return []

    notes = []
    for filepath in sorted(directory.glob("*.md"), reverse=True):
        try:
            notes.append(load_note(filepath))
        except (ValueError, Exception):
            continue  # skip unparseable files

    return notes


def query_notes(directory: str | Path, keyword: str) -> list[Note]:
    """Search notes by keyword in content, title, tags, and entities.

    Args:
        directory: Path to search.
        keyword: Search term (case-insensitive).

    Returns:
        Matching notes.
    """
    keyword_lower = keyword.lower()
    results = []

    for note in list_notes(directory):
        if _note_matches(note, keyword_lower):
            results.append(note)

    return results


def move_note(src_path: str | Path, dest_dir: str | Path) -> Path:
    """Move a note file from one directory to another.

    Args:
        src_path: Source file path.
        dest_dir: Destination directory.

    Returns:
        New file path.
    """
    src_path = Path(src_path)
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_path = dest_dir / src_path.name
    src_path.rename(dest_path)
    return dest_path


def count_notes(directory: str | Path) -> int:
    """Count .md files in a directory."""
    directory = Path(directory)
    if not directory.exists():
        return 0
    return len(list(directory.glob("*.md")))


# --- Helpers ---

def _safe_filename(note_id: str) -> str:
    """Convert a note ID to a safe filename."""
    return note_id.replace("/", "_").replace("\\", "_").replace(" ", "_")


def _extract_title(content: str) -> str:
    """Extract the first H1 heading from Markdown content."""
    for line in content.split("\n"):
        line = line.strip()
        if line.startswith("# ") and not line.startswith("## "):
            return line[2:].strip()
    return "Untitled"


def _extract_section(content: str, heading: str) -> str:
    """Extract content under a specific H2 heading."""
    lines = content.split("\n")
    capturing = False
    section_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped == f"## {heading}":
            capturing = True
            continue
        if capturing:
            if stripped.startswith("## "):
                break
            section_lines.append(line)

    return "\n".join(section_lines).strip()


def _note_matches(note: Note, keyword: str) -> bool:
    """Check if a note matches a keyword (case-insensitive)."""
    # Search in title
    if keyword in note.title.lower():
        return True
    # Search in content
    if keyword in note.content.lower():
        return True
    # Search in tags
    if any(keyword in tag.lower() for tag in note.tags):
        return True
    # Search in entities
    for entity_list in note.entities.values():
        if isinstance(entity_list, list):
            if any(keyword in str(e).lower() for e in entity_list):
                return True
    # Search in category
    if keyword in note.category.lower():
        return True

    return False
