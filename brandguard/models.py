"""The one finding model every feature reuses.

Trust is built into the data model: a Finding cannot exist without a source
(guideline rule or approved fact), a source quote, a severity and a confidence.
Malformed records (for example from an LLM) are rejected by validation.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

Category = Literal["tone", "terminology", "fact", "claim", "visual", "accessibility"]
Level = Literal["high", "medium", "low"]


class Finding(BaseModel):
    category: Category
    issue: str = Field(min_length=3)
    # Where the problem is. For body text these are character offsets into the
    # version's body. For image checks span_text is the image name and
    # span_start is -1.
    span_text: str = ""
    span_start: int = -1
    span_end: int = -1
    # What a fix would change: "body", "image.alt:<name>" or "image.text_color:<name>".
    target: str = "body"
    source_type: Literal["guideline", "fact"]
    source_id: str = Field(min_length=1)  # rule code (G-04) or fact code (F-01)
    source_quote: str = Field(min_length=3)
    severity: Level
    confidence: Level
    suggested_fix: Optional[str] = None  # replacement for the span, never auto-applied
    fix_note: str = ""
    ai_generated: bool = False

    @property
    def needs_reviewer(self) -> bool:
        """Low-confidence findings are routed to a person with review rights."""
        return self.confidence == "low"
