from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from . import tools
from . import learning
from .schemas import KnowledgeListArguments, WrongQuestionListArguments, PracticeQuizArguments
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
    ToolDefinition("list_knowledge_points", "查询知识点与用户手动标记的状态：new 未学习、review 需要复习、mastered 已掌握；all 全部。支持课程、课次、关键词和分页，省略课程时使用当前对话范围，主对话可查全部课程。状态不是考试评估。", KnowledgeListArguments, learning.list_knowledge_points),
    ToolDefinition("list_wrong_questions", "查询错题本，pending 待巩固、mastered 最近作答正确、all 全部。支持课程、来源课次、题干关键词和分页；wrong_count 是小测答错次数，retry_count 是错题重练次数；不返回答案。省略课程时使用当前对话范围，主对话可查全部课程。", WrongQuestionListArguments, learning.list_wrong_questions),
    ToolDefinition("generate_quiz", "用户明确要求生成小测时使用。使用对话已绑定的课程或先查询课程，生成前查询课次；范围不明确先询问。未限定课次时使用整门课程。生成后即可答题，不返回答案。同一问题只生成一组。", QuizArguments, tools.generate_quiz, writes=True),
    ToolDefinition("generate_practice_quiz", "用户明确要求根据错题或薄弱知识点出题时使用。先查询学习记录，只选择本次查到的 review（需要复习）知识点或 pending（待巩固）错题。选择一门课程，不能跨课程混合；没有记录或课堂来源时先说明，不能改为普通小测。生成新题，不返回答案。", PracticeQuizArguments, tools.generate_practice_quiz, writes=True),
)
TOOLS = MappingProxyType({tool.name: tool for tool in _definitions})


def tool_schemas(include_actions: bool = False, practice_only: bool = False) -> list[dict]:
    action = "generate_practice_quiz" if practice_only else "generate_quiz"
    return [tool.model_schema() for tool in TOOLS.values() if not tool.writes or (include_actions and tool.name == action)]
