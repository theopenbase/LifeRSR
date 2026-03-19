"""
AI distillation pipeline — transforms raw notes into structured knowledge.

Uses Claude API to:
  1. Classify the note (idea, event, opportunity, todo, reference, etc.)
  2. Extract tags
  3. Generate a one-line summary
  4. Extract entities (people, companies, topics, places)
  5. Self-assess confidence (high/medium/low)

  inbox/{id}.md ──▶ Claude API ──▶ knowledge/{id}.md (high confidence)
                                 ▶ staging/{id}.md   (medium/low confidence)
"""

import json
import os
from dataclasses import dataclass
from typing import Optional

import anthropic

from .store import Note


DISTILL_SYSTEM_PROMPT = """你是一个知识蒸馏助手。你的任务是分析一段笔记内容，提取结构化信息。

请严格按照以下 JSON 格式返回结果，不要包含任何其他文字：

{
  "category": "idea|event|opportunity|todo|reference|insight|conversation|other",
  "tags": ["标签1", "标签2", "标签3"],
  "summary": "一句话摘要（不超过50字）",
  "entities": {
    "people": ["人名1", "人名2"],
    "companies": ["公司名"],
    "topics": ["主题1"],
    "places": ["地点"]
  },
  "confidence": "high|medium|low"
}

置信度判断标准：
- high: 内容清晰明确，分类和实体提取无歧义
- medium: 内容有些模糊，但大部分信息可以确定
- low: 内容非常模糊、碎片化，或含有大量不确定信息

注意事项：
- 如果某个 entities 类别没有相关内容，返回空列表
- tags 最多 5 个，选择最相关的
- summary 必须是中文
- 如果内容为空或无法理解，confidence 设为 low
"""


@dataclass
class DistillResult:
    """Result of distilling a note."""
    category: str
    tags: list[str]
    summary: str
    entities: dict
    confidence: str  # high, medium, low


class DistillError(Exception):
    """Error during distillation."""
    pass


class Distiller:
    """AI-powered note distillation using Claude API."""

    def __init__(self, api_key: Optional[str] = None, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key:
            raise DistillError(
                "ANTHROPIC_API_KEY not set. Copy .env.example to .env and configure."
            )
        self.model = model
        self._client = anthropic.Anthropic(api_key=self.api_key)

    def distill(self, note: Note) -> DistillResult:
        """Distill a single note into structured knowledge.

        Args:
            note: Raw note to distill.

        Returns:
            DistillResult with category, tags, summary, entities, confidence.

        Raises:
            DistillError: If distillation fails after retries.
        """
        if not note.content.strip():
            return DistillResult(
                category="other",
                tags=[],
                summary="空内容",
                entities={"people": [], "companies": [], "topics": [], "places": []},
                confidence="low",
            )

        user_prompt = f"标题: {note.title}\n\n内容:\n{note.content[:4000]}"

        # Try up to 2 times
        for attempt in range(2):
            try:
                response = self._client.messages.create(
                    model=self.model,
                    max_tokens=1024,
                    system=DISTILL_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": user_prompt}],
                )

                text = response.content[0].text.strip()
                return self._parse_response(text)

            except anthropic.APIStatusError as e:
                if e.status_code == 429:
                    # Rate limit — wait and retry
                    import time
                    time.sleep(5)
                    if attempt == 0:
                        continue
                raise DistillError(f"Claude API error: {e}")

            except anthropic.APIConnectionError as e:
                raise DistillError(f"Claude API connection error: {e}")

            except json.JSONDecodeError:
                if attempt == 0:
                    continue  # retry with the same prompt
                raise DistillError("Claude returned invalid JSON after 2 attempts")

        raise DistillError("Distillation failed after max retries")

    def distill_note(self, note: Note) -> Note:
        """Distill a note and return a new Note with metadata filled in.

        This is the main method for the pipeline — takes a raw note,
        distills it, and returns an enriched copy.
        """
        result = self.distill(note)

        return Note(
            id=note.id,
            source=note.source,
            title=note.title,
            content=note.content,
            created=note.created,
            synced=note.synced,
            confidence=result.confidence,
            category=result.category,
            tags=result.tags,
            entities=result.entities,
            summary=result.summary,
            raw_content=note.content if note.content != note.raw_content else note.raw_content,
        )

    def _parse_response(self, text: str) -> DistillResult:
        """Parse Claude's JSON response into a DistillResult.

        Handles cases where Claude wraps JSON in markdown code blocks.
        """
        # Strip markdown code block markers if present
        if text.startswith("```"):
            lines = text.split("\n")
            # Remove first and last lines (``` markers)
            lines = [l for l in lines if not l.strip().startswith("```")]
            text = "\n".join(lines)

        data = json.loads(text)

        # Validate and normalize
        valid_categories = {
            "idea", "event", "opportunity", "todo",
            "reference", "insight", "conversation", "other"
        }
        category = data.get("category", "other")
        if category not in valid_categories:
            category = "other"

        valid_confidence = {"high", "medium", "low"}
        confidence = data.get("confidence", "medium")
        if confidence not in valid_confidence:
            confidence = "medium"

        entities = data.get("entities", {})
        # Ensure all entity keys exist
        for key in ("people", "companies", "topics", "places"):
            if key not in entities:
                entities[key] = []
            if not isinstance(entities[key], list):
                entities[key] = [entities[key]] if entities[key] else []

        return DistillResult(
            category=category,
            tags=data.get("tags", [])[:5],
            summary=data.get("summary", ""),
            entities=entities,
            confidence=confidence,
        )

    def close(self):
        """Clean up resources."""
        pass  # anthropic client doesn't need explicit cleanup

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
