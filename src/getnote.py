"""
Get笔记 (biji.com) API client.

Uses the recall endpoint to retrieve raw notes from knowledge bases.
API base: https://open-api.biji.com/getnote/openapi

Architecture note:
  biji.com API is search-based, NOT export-based. There is no "list all notes"
  endpoint. We use /knowledge/search/recall with broad queries to pull relevant
  content, then cache results locally. The more you query, the more you accumulate.

  ┌──────────┐     recall(query)     ┌──────────────┐
  │ biji.com │ ──────────────────▶  │ local inbox  │
  │ API      │  ◀── top_k results   │ getnote/     │
  └──────────┘                       └──────────────┘
"""

import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx


API_BASE = "https://open-api.biji.com/getnote/openapi"
DEFAULT_TOP_K = 10
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds


@dataclass
class RecalledNote:
    """A note returned from the recall API."""
    id: str
    title: str
    content: str
    score: float
    type: str  # FILE, NOTE, or BLOGGER
    recall_source: str  # embedding or keyword


@dataclass
class GetNoteConfig:
    """Configuration for the Get笔记 API client."""
    api_key: str
    topic_id: str
    api_base: str = API_BASE
    top_k: int = DEFAULT_TOP_K


class GetNoteClient:
    """Client for the Get笔记 recall API.

    Rate limits: QPS < 2, daily < 5000 calls.
    """

    def __init__(self, config: GetNoteConfig):
        self.config = config
        self._client = httpx.Client(
            base_url=config.api_base,
            headers={
                "Authorization": f"Bearer {config.api_key}",
                "X-OAuth-Version": "1",
                "Content-Type": "application/json",
            },
            timeout=30.0,
        )

    def recall(
        self,
        query: str,
        top_k: Optional[int] = None,
        intent_rewrite: bool = False,
    ) -> list[RecalledNote]:
        """Recall raw notes matching a query.

        Args:
            query: Search query text.
            top_k: Max results to return (default from config).
            intent_rewrite: Whether to rewrite query intent.

        Returns:
            List of recalled notes.

        Raises:
            GetNoteAuthError: API key is invalid or expired.
            GetNoteRateLimitError: Rate limit exceeded.
            GetNoteAPIError: Other API errors.
        """
        payload = {
            "question": query,
            "topic_ids": [self.config.topic_id],
            "top_k": top_k or self.config.top_k,
            "intent_rewrite": intent_rewrite,
        }

        response = self._request_with_retry(payload)
        return self._parse_recall_response(response)

    def _request_with_retry(self, payload: dict) -> dict:
        """Make API request with exponential backoff retry."""
        last_error = None

        for attempt in range(MAX_RETRIES):
            try:
                resp = self._client.post("/knowledge/search/recall", json=payload)

                if resp.status_code == 401:
                    raise GetNoteAuthError(
                        "API key is invalid or expired. "
                        "Update GET_BIJI_API_KEY in .env and reconfigure at "
                        "https://www.biji.com/subject"
                    )
                if resp.status_code == 429:
                    if attempt < MAX_RETRIES - 1:
                        wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                        time.sleep(wait)
                        continue
                    raise GetNoteRateLimitError(
                        "Rate limit exceeded (QPS < 2, daily < 5000). "
                        "Try again later."
                    )
                if resp.status_code >= 500:
                    if attempt < MAX_RETRIES - 1:
                        wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                        time.sleep(wait)
                        continue
                    raise GetNoteAPIError(f"Server error: {resp.status_code}")

                resp.raise_for_status()
                return resp.json()

            except httpx.TimeoutException:
                last_error = GetNoteAPIError("Request timed out")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF_BASE ** (attempt + 1))
                    continue

            except (httpx.ConnectError, httpx.ReadError) as e:
                last_error = GetNoteAPIError(f"Network error: {e}")
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_BACKOFF_BASE ** (attempt + 1))
                    continue

        raise last_error or GetNoteAPIError("Max retries exceeded")

    def _parse_recall_response(self, data: dict) -> list[RecalledNote]:
        """Parse the recall API response into RecalledNote objects."""
        notes = []
        # The recall API returns a list of results directly or nested in 'data'
        results = data if isinstance(data, list) else data.get("data", data.get("results", []))

        if not isinstance(results, list):
            results = [results] if results else []

        for item in results:
            if not isinstance(item, dict):
                continue
            try:
                notes.append(RecalledNote(
                    id=str(item.get("id", "")),
                    title=item.get("title", "Untitled"),
                    content=item.get("content", ""),
                    score=float(item.get("score", 0.0)),
                    type=item.get("type", "NOTE"),
                    recall_source=item.get("recall_source", "unknown"),
                ))
            except (ValueError, TypeError):
                continue  # skip malformed items

        return notes

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


class SyncState:
    """Tracks which notes have been synced to avoid duplicates.

    Uses SQLite for robust state management.
    """

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._init_db()

    def _init_db(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS synced_notes (
                note_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                content_hash TEXT NOT NULL
            )
        """)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS recall_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                results_count INTEGER NOT NULL
            )
        """)
        self._conn.commit()

    def is_synced(self, note_id: str) -> bool:
        """Check if a note has already been synced."""
        row = self._conn.execute(
            "SELECT 1 FROM synced_notes WHERE note_id = ?", (note_id,)
        ).fetchone()
        return row is not None

    def has_changed(self, note_id: str, content: str) -> bool:
        """Check if a previously synced note's content has changed."""
        row = self._conn.execute(
            "SELECT content_hash FROM synced_notes WHERE note_id = ?", (note_id,)
        ).fetchone()
        if row is None:
            return True
        return row[0] != _content_hash(content)

    def mark_synced(self, note_id: str, source: str, content: str):
        """Mark a note as synced."""
        now = _now_iso()
        content_h = _content_hash(content)
        self._conn.execute("""
            INSERT INTO synced_notes (note_id, source, first_seen, last_seen, content_hash)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(note_id) DO UPDATE SET
                last_seen = excluded.last_seen,
                content_hash = excluded.content_hash
        """, (note_id, source, now, now, content_h))
        self._conn.commit()

    def log_recall(self, query: str, results_count: int):
        """Log a recall query for tracking."""
        self._conn.execute(
            "INSERT INTO recall_log (query, timestamp, results_count) VALUES (?, ?, ?)",
            (query, _now_iso(), results_count),
        )
        self._conn.commit()

    def stats(self) -> dict:
        """Get sync statistics."""
        total = self._conn.execute("SELECT COUNT(*) FROM synced_notes").fetchone()[0]
        recalls = self._conn.execute("SELECT COUNT(*) FROM recall_log").fetchone()[0]
        return {"synced_notes": total, "recall_queries": recalls}

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# --- Exceptions ---

class GetNoteError(Exception):
    """Base exception for Get笔记 API errors."""
    pass

class GetNoteAuthError(GetNoteError):
    """API key is invalid or expired."""
    pass

class GetNoteRateLimitError(GetNoteError):
    """Rate limit exceeded."""
    pass

class GetNoteAPIError(GetNoteError):
    """General API error."""
    pass


# --- Helpers ---

def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def load_config() -> GetNoteConfig:
    """Load config from environment variables."""
    api_key = os.environ.get("GET_BIJI_API_KEY", "")
    topic_id = os.environ.get("GET_BIJI_TOPIC_ID", "")

    if not api_key:
        raise GetNoteAuthError(
            "GET_BIJI_API_KEY not set. Copy .env.example to .env and configure."
        )
    if not topic_id:
        raise GetNoteError(
            "GET_BIJI_TOPIC_ID not set. Get your topic ID from "
            "https://www.biji.com/subject → API 设置"
        )

    return GetNoteConfig(api_key=api_key, topic_id=topic_id)
