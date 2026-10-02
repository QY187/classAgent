from pydantic import BaseModel, Field


class QuizGenerate(BaseModel):
    lesson_id: str | None = None
    count: int = Field(default=5, ge=3, le=10)


class QuizQuestionUpdate(BaseModel):
    stem: str = Field(min_length=1, max_length=500)
    options: list[str] = Field(min_length=2, max_length=4)
    correct_option: int = Field(ge=0, le=3)
    explanation: str = Field(min_length=1, max_length=2000)


class QuizSubmit(BaseModel):
    answers: dict[str, int]


class WrongQuestionRetry(BaseModel):
    selected_option: int = Field(strict=True, ge=0, le=3)
