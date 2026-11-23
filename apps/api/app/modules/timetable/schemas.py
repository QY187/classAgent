from datetime import date, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Period(BaseModel):
    start: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    end: str = Field(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")

    @model_validator(mode="after")
    def chronological(self):
        if self.start >= self.end:
            raise ValueError("每节课的结束时间必须晚于开始时间")
        return self


def default_periods() -> list[Period]:
    # 学校作息：五个大节，分别含 3、2、2、3、3 小节，每小节 45 分钟，课间 5 分钟。
    blocks = [("08:00", 3), ("10:40", 2), ("14:00", 2), ("15:50", 3), ("19:00", 3)]
    periods = []
    for value, count in blocks:
        start = datetime.strptime(value, "%H:%M")
        for index in range(count):
            lesson_start = start + timedelta(minutes=50 * index)
            periods.append(Period(start=lesson_start.strftime("%H:%M"),
                end=(lesson_start + timedelta(minutes=45)).strftime("%H:%M")))
    return periods


class SemesterWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    start_date: date = Field(ge=date(1900, 1, 1), le=date(2199, 12, 31))
    week_count: int = Field(default=20, ge=1, le=52)
    periods: list[Period] = Field(default_factory=default_periods, min_length=1, max_length=20)

    @model_validator(mode="after")
    def chronological(self):
        for previous, current in zip(self.periods, self.periods[1:]):
            if current.start < previous.end:
                raise ValueError("节次时间必须依次排列，且不能重叠")
        return self


class EntryWrite(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    course_id: str | None = Field(default=None, max_length=36)
    title: str = Field(min_length=1, max_length=100)
    room: str = Field(default="", max_length=100)
    teacher: str = Field(default="", max_length=100)
    weekday: int = Field(ge=1, le=7)
    start_period: int = Field(ge=1, le=20)
    end_period: int = Field(ge=1, le=20)
    start_week: int = Field(default=1, ge=1, le=52)
    end_week: int = Field(default=20, ge=1, le=52)
    week_pattern: Literal["all", "odd", "even"] = "all"
    color: str = Field(default="teal", pattern=r"^(?:teal|purple|blue|amber|rose|#[0-9a-fA-F]{6})$")

    @model_validator(mode="after")
    def ordered_ranges(self):
        if self.end_period < self.start_period or self.end_week < self.start_week:
            raise ValueError("结束节次和结束周次不能早于开始值")
        if not self.weeks():
            raise ValueError("所选范围中没有对应的单周或双周")
        return self

    def weeks(self) -> set[int]:
        return {week for week in range(self.start_week, self.end_week + 1)
                if self.week_pattern == "all" or week % 2 == (1 if self.week_pattern == "odd" else 0)}


class ImportEntries(BaseModel):
    entries: list[EntryWrite] = Field(min_length=1, max_length=300)
