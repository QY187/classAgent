"""语义计划契约；只描述用户委托，数据库权限仍由业务工具校验。"""
from typing import Annotated, Literal
from datetime import date

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Target = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
Question = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)]


class IntentModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class CreateCourseIntent(IntentModel):
    name: Name | None = None
    semester: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)] | None = Field(
        default=None, description="可选字段，用户未指定则保持为空，不询问、不猜测")


class CreateLessonIntent(IntentModel):
    course: Name | None = None
    title: Name | None = None
    lesson_date: Name | None = None


class EditIntent(IntentModel):
    kind: Literal["course", "lesson"] | None = None
    target: Target | None = None
    fields: dict[str, Name] = Field(default_factory=dict, max_length=2)

    @model_validator(mode="after")
    def supported_fields(self):
        allowed = {"name", "semester"} if self.kind == "course" else {"title", "lesson_date"}
        if set(self.fields) - allowed or (self.kind is None and self.fields):
            raise ValueError("修改字段与目标类型不匹配")
        if len(self.fields.get("semester", "")) > 100:
            raise ValueError("学期过长")
        return self


class KnowledgeIntent(IntentModel):
    course: Name | None = None
    lesson: Name | None = None
    title: Target | None = None
    status: Literal["new", "review", "mastered"] | None = None


class RetryIntent(IntentModel):
    course: Name | None = None
    title: Name | None = None


class VerifyIntent(IntentModel):
    target: Target | None = None


class QuizIntent(IntentModel):
    mode: Literal["quiz", "practice"]
    course: Name | None = None
    lessons: list[Name] | None = Field(default=None, min_length=1, max_length=50)
    count: int | None = Field(default=None, ge=1, le=1000)
    question_type: Literal["mixed", "single_choice", "true_false"] | None = None


class IntentPayload(IntentModel):
    answer_mode: Literal["standard", "source_location"] = Field(default="standard",
        description="source_location仅用于用户只问课堂主题在哪门课程、哪个课次或时间点；不含学习状态或内容解释要求。混合请求用standard。")
    create_course: CreateCourseIntent | None = None
    create_lesson: CreateLessonIntent | None = None
    edit: EditIntent | None = None
    knowledge: KnowledgeIntent | None = None
    retry: RetryIntent | None = None
    quiz: QuizIntent | None = None
    verify: VerifyIntent | None = None
    queries: list[Literal["catalog", "progress", "learning", "quiz_results", "workflow"]] = Field(default_factory=list, max_length=5)
    catalog: list[Literal["list_courses", "list_lessons"]] = Field(default_factory=list, max_length=2)
    issue: Question | None = None

    @model_validator(mode="after")
    def coherent_actions(self):
        if self.answer_mode == "source_location" and (self.write_keys() or self.queries or self.catalog or self.verify):
            raise ValueError("仅定位课堂内容不能同时要求业务清单或写操作；混合请求使用standard")
        families = sum(item is not None for item in (self.edit, self.knowledge, self.retry))
        families += bool(self.create_course is not None or self.create_lesson is not None)
        if families > 1:
            raise ValueError("本轮只支持一类管理操作，可组合创建课程和课次")
        if self.issue and self.write_keys():
            raise ValueError("不支持或冲突的请求不能同时授权写入")
        if len(set(self.queries)) != len(self.queries) or len(set(self.catalog)) != len(self.catalog):
            raise ValueError("查询类别不能重复")
        if self.catalog and "catalog" not in self.queries:
            self.queries.append("catalog")
        if "catalog" in self.queries and not self.catalog:
            raise ValueError("目录查询必须指定课程或课次")
        if self.create_course and self.create_lesson:
            if self.create_course.name != self.create_lesson.course:
                raise ValueError("组合创建时课次必须属于新课程；名称未给出时均为 null")
        return self

    def write_keys(self) -> set[str]:
        return {key for key in ("create_course", "create_lesson", "edit", "knowledge", "retry", "quiz")
                if getattr(self, key) is not None}

    def legacy(self) -> dict:
        """连接既有业务处理器；主入口始终传 dict，不再回落到关键词授权。"""
        value = {key: item for key, item in self.model_dump().items()
                 if item is not None and (item or key not in {"queries", "catalog"})}
        if self.answer_mode == "standard":
            value.pop("answer_mode", None)
        if self.quiz:
            value["quiz"] = self.quiz.mode
            value["quiz_spec"] = self.quiz.model_dump(exclude={"mode"})
        return value


class TurnDecision(IntentModel):
    relation: Literal["new", "continue", "cancel"]
    task_id: Name | None = None
    intent: IntentPayload
    clarification: Question | None = None
    date_source: Name | None = Field(default=None,
        description="涉及日期时，逐字提取当前用户或待办请求中的日期表达，如明天、11月2日、2026年；不能补入原文没有的年份")

    @model_validator(mode="after")
    def coherent_relation(self):
        if (self.relation == "continue") != bool(self.task_id):
            raise ValueError("只有续接必须填写待澄清 task_id")
        if self.relation == "cancel" and self.intent.write_keys():
            raise ValueError("取消不能授权写入，可同时保留只读查询")
        return self


def operation_tools(intent: IntentPayload) -> dict[str, str]:
    """统一的意图到实际回执映射，用于扣除已成功操作，防止续接重复执行。"""
    tools = {"create_course": "create_course", "create_lesson": "create_lesson",
             "knowledge": "update_knowledge_status", "retry": "retry_transcription"}
    if intent.edit and intent.edit.kind:
        tools["edit"] = "update_" + intent.edit.kind
    if intent.quiz:
        tools["quiz"] = "generate_practice_quiz" if intent.quiz.mode == "practice" else "generate_quiz"
    return {key: tool for key, tool in tools.items() if key in intent.write_keys()}


def missing_information(intent: IntentPayload, bound_course=None) -> str | None:
    """参数完整性校验，不根据用户措辞判断意图。"""
    if intent.create_course and not intent.create_course.name:
        return "请提供要创建的课程名称？"
    if intent.create_lesson:
        if not intent.create_lesson.title:
            return "请提供要添加的课次标题？"
        if not bound_course and not intent.create_lesson.course:
            return "请明确要在哪门课程添加课次？"
    if intent.edit and (not intent.edit.kind or not intent.edit.target or not intent.edit.fields):
        return "请补充要修改的课程或课次，以及具体字段和新值？"
    if intent.knowledge and (not intent.knowledge.title or not intent.knowledge.status):
        return "请补充要修改的知识点及状态（未学习、需要复习或已掌握）？"
    if intent.retry and not intent.retry.title:
        return "请明确需要重试转写的课次？"
    if intent.retry and not bound_course and not intent.retry.course:
        return "请明确需要重试的课次属于哪门课程？"
    if intent.quiz and intent.quiz.count is not None and not 3 <= intent.quiz.count <= 15:
        return "每组小测支持 3 到 15 道题，请指定范围内的题量？"
    if intent.quiz and not bound_course and not intent.quiz.course:
        return "请告诉我要为哪门课程出题？也可以指定课次。"
    dates = [intent.create_lesson.lesson_date if intent.create_lesson else None,
             intent.edit.fields.get("lesson_date") if intent.edit else None]
    for value in dates:
        if value:
            try:
                if date.fromisoformat(value).isoformat() != value:
                    raise ValueError()
            except ValueError:
                return f"请补充“{value}”的有效完整日期及年份？"
    return None
