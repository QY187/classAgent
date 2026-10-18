"""最终响应协议；只验证结构，课堂依据仍由对应结果存储核验。"""
import json
from typing import Annotated, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


class InvalidFinalResponse(HTTPException):
    def __init__(self):
        super().__init__(502, "Agent 未返回可核对的回答，请重试")


class ResponseModel(BaseModel):
    # 模型附带的 answer/score 等自由字段不进入展示，业务结果仍重新查询。
    model_config = ConfigDict(extra="ignore", strict=True)


Reference = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=36)]


class Claim(ResponseModel):
    text: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
    source_ids: list[Reference]


class QuerySelection(ResponseModel):
    query_ids: list[Reference] = Field(min_length=1, max_length=8)


class CatalogSelection(ResponseModel):
    course_ids: list[Reference] = Field(default_factory=list, max_length=50)
    lesson_ids: list[Reference] = Field(default_factory=list, max_length=50)


class FinalResponse(ResponseModel):
    claims: list[Claim]
    outcome: Literal["answered", "insufficient_evidence", "needs_input", "actions_completed"] | None = None
    question: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=300)] | None = None
    progress: QuerySelection | None = None
    quiz_results: QuerySelection | None = None
    learning: QuerySelection | None = None
    catalog: CatalogSelection | None = None

    @model_validator(mode="after")
    def coherent_result(self):
        has_results = bool(self.claims) or any(item is not None for item in (
            self.progress, self.quiz_results, self.learning, self.catalog))
        if self.outcome == "needs_input":
            if not self.question or has_results:
                raise ValueError("澄清不能混入未核验的回答")
        elif self.question is not None:
            raise ValueError("补充问题必须使用澄清结果")
        if self.outcome in {"insufficient_evidence", "actions_completed"} and has_results:
            raise ValueError("结果类型与内容不一致")
        return self


def parse_response(content):
    return FinalResponse.model_validate(json.loads(content or "")).model_dump(exclude_none=True)


FINAL_RESPONSE_INSTRUCTION = """最终响应必须是一个完整 JSON 对象，不能有 Markdown 代码围栏、解释性前缀或普通文字。
历史中的助手消息是已经渲染的页面文字，不是本次输出格式示例。
普通追问可承接近期用户明确讨论的课程和课次，先重新调用工具核实；当前课程绑定仍优先，不使用历史引用作为事实依据。
课程对话遇到明确指定的其他课程时，先核实当前课程名称，提示进入主对话或对应课程对话；不要把范围受限说成课程资料缺失。
需要补充信息或提示进入正确对话时，输出 {"claims":[],"outcome":"needs_input","question":"简短的澄清或范围提示"}。
没有资料依据时输出 {"claims":[],"outcome":"insufficient_evidence"}。
有课堂事实时输出 {"claims":[{"text":"结论","source_ids":["本次原文 evidence_id"]}]}。
目录和业务统计使用前述 catalog、progress、quiz_results、learning 对象，里面只能填写本次实际查询的 ID。
同一问题包含多项要求时，可以在一个最终 JSON 中同时包含 claims、catalog、progress、quiz_results、learning；分别填入每项已查询的结果，不能只保留第一项。未取得课堂依据时不得填入事实结论。
不能用澄清字段承载课堂结论、成绩、状态或声称操作成功。操作成功必须有本次真实执行回执。"""

REPAIR_INSTRUCTION = """刚才的最终响应未通过协议或结果引用校验，请修复一次。
重新检查当前用户问题和本次工具结果；需要依据时继续调用工具，再输出正确 JSON。
不要复述刚才的普通文字，不要编造引用或查询 ID，不要根据历史声称操作完成。
""" + FINAL_RESPONSE_INSTRUCTION
