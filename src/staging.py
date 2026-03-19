"""
Staging — review workflow for low-confidence distillation results.

Distilled notes with confidence: medium or low go to staging/.
The user reviews them via `kb review` and approves or rejects.

  staging/{id}.md ──▶ approve ──▶ knowledge/{id}.md
                  ──▶ reject  ──▶ (deleted)
"""

from pathlib import Path

from .store import Note, load_note, list_notes, move_note, count_notes


class StagingManager:
    """Manages the staging review workflow."""

    def __init__(self, staging_dir: str | Path, knowledge_dir: str | Path):
        self.staging_dir = Path(staging_dir)
        self.knowledge_dir = Path(knowledge_dir)
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        self.knowledge_dir.mkdir(parents=True, exist_ok=True)

    def pending(self) -> list[Note]:
        """List all notes pending review."""
        return list_notes(self.staging_dir)

    def pending_count(self) -> int:
        """Count notes pending review."""
        return count_notes(self.staging_dir)

    def approve(self, note_id: str) -> Path:
        """Approve a staged note, moving it to knowledge/.

        Args:
            note_id: ID of the note to approve.

        Returns:
            New path in knowledge/.

        Raises:
            FileNotFoundError: If the note is not in staging.
        """
        src = self._find_note_file(note_id)
        return move_note(src, self.knowledge_dir)

    def reject(self, note_id: str):
        """Reject a staged note, deleting it.

        Args:
            note_id: ID of the note to reject.

        Raises:
            FileNotFoundError: If the note is not in staging.
        """
        src = self._find_note_file(note_id)
        src.unlink()

    def approve_all(self) -> int:
        """Approve all pending notes. Returns count approved."""
        count = 0
        for filepath in self.staging_dir.glob("*.md"):
            move_note(filepath, self.knowledge_dir)
            count += 1
        return count

    def _find_note_file(self, note_id: str) -> Path:
        """Find a note file in staging by ID."""
        # Try direct filename match
        safe_id = note_id.replace("/", "_").replace("\\", "_").replace(" ", "_")
        filepath = self.staging_dir / f"{safe_id}.md"
        if filepath.exists():
            return filepath

        # Search by ID in frontmatter
        for fp in self.staging_dir.glob("*.md"):
            try:
                note = load_note(fp)
                if note.id == note_id:
                    return fp
            except Exception:
                continue

        raise FileNotFoundError(
            f"Note '{note_id}' not found in staging. "
            f"Run `kb review` to see pending notes."
        )
