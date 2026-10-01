from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


CardType = Literal["concept", "question", "rule", "pitfall"]
CardStatus = Literal["new", "review", "mastered"]


class CardCreate(BaseModel):
    card_type: CardType = "concept"
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10000)
    source_segment_id: str | None = None

    @field_validator("title", "body")
    @classmethod
    def non_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("卡片内容不能为空")
        return value.strip()


class CardUpdate(BaseModel):
    card_type: CardType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=10000)

    @field_validator("title", "body")
    @classmethod
    def non_blank(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("卡片内容不能为空")
        return value.strip() if value is not None else None


class CardReview(BaseModel):
    status: CardStatus


class CardRead(BaseModel):
    id: str
    course_id: str
    course_name: str
    lesson_id: str
    lesson_title: str
    card_type: CardType
    title: str
    body: str
    status: CardStatus
    source_segment_id: str | None
    source_start_ms: int | None
    source_excerpt: str | None
    created_at: datetime
