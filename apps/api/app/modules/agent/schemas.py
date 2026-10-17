from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator, field_validator
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


class CourseProgressArguments(PageArguments):
    course_id: Identity | None = None


class CreateCourseArguments(ToolArguments):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class CreateLessonArguments(ToolArguments):
    course_id: Identity
    title: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    lesson_date: Annotated[str, StringConstraints(min_length=10, max_length=10)] | None = None

    @field_validator("lesson_date")
    @classmethod
    def valid_date(cls, value):
        if value is not None:
            from datetime import date
            if date.fromisoformat(value).isoformat() != value:
                raise ValueError("日期应为 YYYY-MM-DD")
        return value


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


class QuizAttemptListArguments(PageArguments):
    course_id: Identity | None = None
    quiz_id: Identity | None = None
    query: Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)] = ""


class QuizAttemptArguments(PageArguments):
    attempt_id: Identity
    limit: int = Field(default=5, ge=1, le=15)


class QuizArguments(ToolArguments):
    course_id: Identity
    lesson_ids: list[Identity] | None = Field(default=None, min_length=1, max_length=50)
    count: int = Field(default=5, ge=3, le=15)
    question_type: Literal["mixed", "single_choice", "true_false"] = "mixed"


class PracticeQuizArguments(ToolArguments):
    course_id: Identity
    knowledge_point_ids: list[Identity] = Field(default_factory=list, max_length=20)
    wrong_question_ids: list[Identity] = Field(default_factory=list, max_length=20)
    count: int = Field(default=5, ge=3, le=15)
    question_type: Literal["mixed", "single_choice", "true_false"] = "mixed"

    @model_validator(mode="after")
    def require_targets(self):
        self.knowledge_point_ids = list(dict.fromkeys(self.knowledge_point_ids))
        self.wrong_question_ids = list(dict.fromkeys(self.wrong_question_ids))
        if not self.knowledge_point_ids and not self.wrong_question_ids:
            raise ValueError("需要选择至少一个学习记录")
        return self
