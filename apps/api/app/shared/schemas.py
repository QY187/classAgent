from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    semester: str | None = None


class CourseRead(CourseCreate):
    id: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class LessonCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    lesson_date: str | None = None


class LessonRead(LessonCreate):
    id: str
    course_id: str
    status: str
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class JobRead(BaseModel):
    id: str
    lesson_id: str
    stage: str
    progress: int
    error_message: str | None
    model_config = ConfigDict(from_attributes=True)


class TranscriptSegmentRead(BaseModel):
    id: str
    speaker: str
    start_ms: int
    end_ms: int
    text: str
    source: str
    model_config = ConfigDict(from_attributes=True)


class TranscriptSegmentUpdate(BaseModel):
    text: str = Field(min_length=1, max_length=10000)


class TranscriptMerge(BaseModel):
    first_id: str
    second_id: str


class SpeakerAliasRead(BaseModel):
    raw_label: str
    display_name: str


class AudioMeta(BaseModel):
    id: str
    filename: str
    content_type: str
    size_bytes: int
    model_config = ConfigDict(from_attributes=True)


class SummaryRead(BaseModel):
    id: str
    lesson_id: str
    status: str
    content: str | None
    provider: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class SummaryUpdate(BaseModel):
    content: str = Field(min_length=1, max_length=50000)
