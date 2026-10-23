from dataclasses import dataclass
from types import MappingProxyType
from typing import Callable

from . import tools
from . import learning
from . import quiz_results
from . import progress, workflow_queries, processing_actions
from .schemas import RetryTranscriptionArguments, UpdateCourseArguments, UpdateLessonArguments
from .schemas import PendingLessonsArguments, UnansweredQuizArguments, ProcessingDetailArguments
from .schemas import CourseProgressArguments, CreateCourseArguments, CreateLessonArguments
from . import course_actions
from . import knowledge_actions
from .schemas import KnowledgeStatusArguments
from .schemas import QuizAttemptArguments, QuizAttemptListArguments
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
    ToolDefinition("update_course", "仅用户本条明确指定课程名称或学期修改时调用。先查询定位唯一课程，使用后端识别的字段，未指定字段省略；同名歧义先澄清。", UpdateCourseArguments, course_actions.update_course, writes=True),
    ToolDefinition("update_lesson", "仅用户本条明确指定课次标题或日期修改时调用。先查询定位唯一课次，只按后端字段修改；日期必须完整 YYYY-MM-DD，不猜年份，不改变未指定字段。", UpdateLessonArguments, course_actions.update_lesson, writes=True),
    ToolDefinition("retry_transcription", "仅明确要求重试转写时调用。先查询并确认课程、课次和当前任务失败，必须使用本条指令指定的唯一课次标题；排队或已完成不重复提交，已有文字不覆盖，仅登记任务而非已经完成转写。", RetryTranscriptionArguments, processing_actions.retry_transcription, writes=True),
    ToolDefinition("get_processing_detail", "查询一节课当前处理阶段、最近转写任务进度、纪要状态和当前失败原因。先定位唯一课次，不推断预计完成时间；任务进度仅属于转写，不等于纪要进度。", ProcessingDetailArguments, workflow_queries.processing_detail),
    ToolDefinition("list_unanswered_quizzes", "查询可答且本人尚未提交作答的小测，返回标题、题量和答题入口，不返回答案。支持课程、课次、标题搜索与分页；草稿不计入。主对话省略课程查询本人全部课程。", UnansweredQuizArguments, workflow_queries.unanswered_quizzes),
    ToolDefinition("list_pending_lessons", "查询待处理课次及当前阶段、失败原因，支持分页。主对话省略课程查所有课程，课程对话仅查当前课程；包括等待上传和缺少纪要，不等同于失败课次。", PendingLessonsArguments, workflow_queries.pending_lessons),
    ToolDefinition("list_courses", "查询当前用户可见课程，支持名称搜索和分页。", CourseListArguments, tools.list_courses),
    ToolDefinition("list_lessons", "查询指定课程课次，按用户设定顺序返回，支持标题搜索和分页。", LessonListArguments, tools.list_lessons),
    ToolDefinition("get_course_progress", "查询一门课程的真实进度：课次、文字记录、可用纪要、手动标记的知识点状态，并分页列出缺少可用纪要的课次及其状态。省略 course_id 使用当前课程，主对话先定位一门课程。纪要排队、失败或过期不算完成；知识点状态不代表考试能力。", CourseProgressArguments, progress.get_course_progress),
    ToolDefinition("create_course", "仅用户明确要求创建课程时可用，仅在主对话执行。name 必须是用户明确指定的新课程名称，不猜名称或学期。每条问题最多创建一门；同名已有课程先澄清，失败重试不会重复创建。", CreateCourseArguments, course_actions.create_course, writes=True),
    ToolDefinition("create_lesson", "仅明确要求添加课次时可用。先查询课程和课次以核对归属及同名；title 必须是用户指定的标题，未指定日期则 lesson_date 留空，不猜日期。主对话先定位唯一课程，或使用本条问题刚创建课程的 ID。每条问题最多添加一节，同名课次先澄清。", CreateLessonArguments, course_actions.create_lesson, writes=True),
    ToolDefinition("update_knowledge_status", "仅用户明确要求将某个知识点标记为指定状态时可用。必须先用 list_knowledge_points 查找并确认唯一目标，再使用本次查到的 knowledge_point_id。new 未学习、review 需要复习、mastered 已掌握。不依据成绩推断或批量修改，同名或范围有歧义先澄清；每条问题最多修改一个知识点。", KnowledgeStatusArguments, knowledge_actions.update_knowledge_status, writes=True),
    ToolDefinition("get_transcript", "分页读取课堂文字记录，包含片段编号和时间点。truncated 表示该片段文本被截短。", TranscriptArguments, tools.get_transcript),
    ToolDefinition("get_summary", "读取已有纪要及状态，按字符分页；available 为 false 时不可作为课堂依据。", SummaryArguments, tools.get_summary),
    ToolDefinition("search_course", "按关键词搜索课堂文字记录，返回原文片段和时间点；不是语义检索，未命中不代表课堂没有相关内容。", SearchArguments, tools.search_course),
    ToolDefinition("list_knowledge_points", "查询知识点与用户手动标记的状态：new 未学习、review 需要复习、mastered 已掌握；all 全部。支持课程、课次、关键词和分页，省略课程时使用当前对话范围，主对话可查全部课程。状态不是考试评估。", KnowledgeListArguments, learning.list_knowledge_points),
    ToolDefinition("list_wrong_questions", "查询错题本，pending 待巩固、mastered 最近作答正确、all 全部。支持课程、来源课次、题干关键词和分页；wrong_count 是小测答错次数，retry_count 是错题重练次数；不返回答案。省略课程时使用当前对话范围，主对话可查全部课程。", WrongQuestionListArguments, learning.list_wrong_questions),
    ToolDefinition("list_quiz_attempts", "查询自己的已提交小测成绩，最新作答在前，可按课程、quiz_id、小测标题关键词筛选及分页。省略课程使用当前课程，主对话查询全部课程；未提交小测不计入。page_summary 只统计本页，不是全部历史。返回真实 attempt id，可继续 get_quiz_attempt 查看某次作答。", QuizAttemptListArguments, quiz_results.list_quiz_attempts),
    ToolDefinition("get_quiz_attempt", "按 list_quiz_attempts 查到的 attempt_id 分页读取已提交作答，包含实际选择、正确选项、历史解析和课堂来源状态。不能读取未提交小测答案。source_status=changed/unavailable 时不能把旧来源当作当前课堂依据；解释新的课堂结论仍需读取原文。", QuizAttemptArguments, quiz_results.get_quiz_attempt),
    ToolDefinition("generate_quiz", "用户明确要求生成小测时使用。使用对话已绑定的课程或先查询课程，生成前查询课次；范围不明确先询问。未限定课次时使用整门课程。生成后即可答题，不返回答案。同一问题只生成一组。", QuizArguments, tools.generate_quiz, writes=True),
    ToolDefinition("generate_practice_quiz", "用户明确要求根据错题或薄弱知识点出题时使用。先查询学习记录，只选择本次查到的 review（需要复习）知识点或 pending（待巩固）错题。选择一门课程，不能跨课程混合；没有记录或课堂来源时先说明，不能改为普通小测。生成新题，不返回答案。", PracticeQuizArguments, tools.generate_practice_quiz, writes=True),
)
TOOLS = MappingProxyType({tool.name: tool for tool in _definitions})


def tool_schemas(include_actions: bool = False, practice_only: bool = False, allowed_actions=()) -> list[dict]:
    action = "generate_practice_quiz" if practice_only else "generate_quiz"
    return [tool.model_schema() for tool in TOOLS.values() if not tool.writes or
            (include_actions and tool.name == action) or tool.name in allowed_actions]
