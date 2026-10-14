from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from . import tools
from .schemas import ToolArguments, CourseListArguments, LessonListArguments, TranscriptArguments, SummaryArguments, SearchArguments, QuizArguments


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments: type[ToolArguments]
    handler: Callable
    writes: bool = False

    def model_schema(self) -> dict:
        return {"type": "function", "function": {"name": self.name, "description": self.description,
                "parameters": self.arguments.model_json_schema()}}


_definitions = (
    ToolDefinition("list_courses", "查询当前用户可见课程，支持名称搜索和分页。", CourseListArguments, tools.list_courses),
    ToolDefinition("list_lessons", "查询指定课程课次，按用户设定顺序返回，支持标题搜索和分页。", LessonListArguments, tools.list_lessons),
    ToolDefinition("get_transcript", "分页读取课堂文字记录，包含片段编号和时间点。truncated 表示该片段文本被截短。", TranscriptArguments, tools.get_transcript),
    ToolDefinition("get_summary", "读取已有纪要及状态，按字符分页；available 为 false 时不可作为课堂依据。", SummaryArguments, tools.get_summary),
    ToolDefinition("search_course", "按关键词搜索课堂文字记录，返回原文片段和时间点；不是语义检索，未命中不代表课堂没有相关内容。", SearchArguments, tools.search_course),
    ToolDefinition("generate_quiz", "用户明确要求生成小测时使用。使用对话已绑定的课程或先查询课程，生成前查询课次；范围不明确先询问。未限定课次时使用整门课程。生成后即可答题，不返回答案。同一问题只生成一组。", QuizArguments, tools.generate_quiz, writes=True),
)
TOOLS = MappingProxyType({tool.name: tool for tool in _definitions})


def tool_schemas(include_actions: bool = False) -> list[dict]:
    return [tool.model_schema() for tool in TOOLS.values() if not tool.writes or include_actions]
