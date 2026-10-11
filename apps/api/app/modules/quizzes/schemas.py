from typing import Literal

from pydantic import BaseModel, Field, model_validator


class QuizGenerate(BaseModel):
    lesson_id: str | None = None
    lesson_ids: list[str] | None = Field(default=None, min_length=1, max_length=50)
    count: int = Field(default=5, ge=3, le=15)
    question_type: Literal["mixed", "single_choice", "true_false"] = "mixed"

    @model_validator(mode="after")
    def validate_scope(self):
        if self.lesson_id and self.lesson_ids is not None:
            raise ValueError("单课次与多课次范围不能同时指定")
        if self.lesson_ids is not None:
            if any(not value.strip() for value in self.lesson_ids):
                raise ValueError("课次编号不能为空")
            self.lesson_ids = list(dict.fromkeys(self.lesson_ids))
        return self


class QuizSubmit(BaseModel):
    answers: dict[str, int]


class WrongQuestionRetry(BaseModel):
    selected_option: int = Field(strict=True, ge=0, le=3)
