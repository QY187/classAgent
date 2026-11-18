from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ExportContents(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summaries: bool = True
    transcripts: bool = True
    knowledge: bool = False
    quizzes: bool = False
    answers: bool = False
    audio: bool = False
    materials: bool = False

    @model_validator(mode="after")
    def valid_selection(self):
        if not any((self.summaries, self.transcripts, self.knowledge, self.quizzes, self.audio, self.materials)):
            raise ValueError("请至少选择一种导出内容")
        if self.answers and not self.quizzes:
            raise ValueError("附带答案需要同时选择小测")
        return self


class CourseExport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    contents: ExportContents = Field(default_factory=ExportContents)
    lesson_ids: list[str] | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("lesson_ids")
    @classmethod
    def unique_ids(cls, value):
        if value is not None:
            if any(not identity.strip() or len(identity) > 36 for identity in value):
                raise ValueError("课次编号无效")
            return list(dict.fromkeys(value))
        return value
