from pydantic import BaseModel, ConfigDict, Field, field_validator


class CourseExport(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    lesson_ids: list[str] | None = Field(default=None, min_length=1, max_length=500)

    @field_validator("lesson_ids")
    @classmethod
    def unique_ids(cls, value):
        if value is not None:
            if any(not identity.strip() or len(identity) > 36 for identity in value):
                raise ValueError("课次编号无效")
            return list(dict.fromkeys(value))
        return value
