from pydantic import BaseModel, ConfigDict, Field, StringConstraints
from typing import Annotated, Literal


Identity = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]


class ToolArguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class PageArguments(ToolArguments):
    offset: int = Field(default=0, ge=0, le=100000)
    limit: int = Field(default=20, ge=1, le=50)


class CourseListArguments(PageArguments):
    query: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""


class LessonListArguments(PageArguments):
    course_id: Identity
    query: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""


class TranscriptArguments(PageArguments):
    lesson_id: Identity


class SummaryArguments(ToolArguments):
    lesson_id: Identity
    offset: int = Field(default=0, ge=0, le=1000000)
    limit: int = Field(default=8000, ge=1, le=12000)


class SearchArguments(ToolArguments):
    course_id: Identity
    query: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
    lesson_id: Identity | None = None
    limit: int = Field(default=10, ge=1, le=30)


class LearningListArguments(PageArguments):
    course_id: Identity | None = None
    lesson_id: Identity | None = None
    query: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""


class KnowledgeListArguments(LearningListArguments):
    status: Literal["all", "new", "review", "mastered"] = "all"


class WrongQuestionListArguments(LearningListArguments):
    status: Literal["all", "pending", "mastered"] = "all"


class QuizArguments(ToolArguments):
    course_id: Identity
    lesson_ids: list[Identity] | None = Field(default=None, min_length=1, max_length=50)
    count: int = Field(default=5, ge=3, le=15)
    question_type: Literal["mixed", "single_choice", "true_false"] = "mixed"
