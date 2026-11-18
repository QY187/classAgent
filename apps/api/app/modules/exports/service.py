"""课程导出只读业务：磁盘ZIP、有界输出、权限和回收站范围。"""
from datetime import datetime
from pathlib import Path
from tempfile import mkstemp
from time import monotonic
from urllib.parse import quote
from zoneinfo import ZoneInfo
from zipfile import ZipFile, ZIP_DEFLATED
import os
import re

from fastapi import HTTPException
from sqlalchemy import select

from ...core.ownership import user_id_for_username
from ...core.visibility import visible_get
from ...shared.models import Course, Lesson, LessonSummary, SpeakerAlias, TranscriptSegment
from ..courses.mapper import find_lessons
from .render import md, summary_markdown, transcript_text
from .extras import Extras

MAX_BYTES = 512 * 1024 * 1024
MAX_FILES = 2000
MAX_SECONDS = 150


def safe_name(value, fallback="未命名"):
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", str(value or "")).strip(" .")[:80].rstrip(" .")
    if not value:
        return fallback
    if value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(1, 10)], *[f"LPT{i}" for i in range(1, 10)]}:
        value = "_" + value
    return value


class Archive:
    def __init__(self, path):
        self.zip = ZipFile(path, "w", compression=ZIP_DEFLATED, compresslevel=3, allowZip64=True)
        self.bytes = 0
        self.files = 0
        self.deadline = monotonic() + MAX_SECONDS

    def check(self, size=0, files=0):
        if monotonic() > self.deadline:
            raise HTTPException(408, "打包耗时过长，请减少课次或导出内容后重试")
        if self.bytes + size > MAX_BYTES or self.files + files > MAX_FILES:
            raise HTTPException(413, "单次导出最多512MB原始内容、2000个文件，请分批导出")

    def text(self, name, content, plain=False):
        data = (("\ufeff" + content.replace("\r\n", "\n").replace("\n", "\r\n")) if plain else content).encode("utf-8")
        self.check(len(data), 1)
        self.zip.writestr(name, data)
        self.bytes += len(data)
        self.files += 1

    def close(self):
        self.zip.close()


def selected_scope(db, course_id, payload, username):
    course = db.scalar(select(Course).where(Course.id == course_id).execution_options(populate_existing=True))
    if course is None or course.owner_id != user_id_for_username(db, username):
        raise HTTPException(404, "课程不存在")
    lessons = find_lessons(db, course_id)
    if payload.lesson_ids is not None:
        selected = set(payload.lesson_ids)
        if selected - {lesson.id for lesson in lessons}:
            raise HTTPException(400, "所选课次不存在、已删除或不属于当前课程，请刷新后重试")
        lessons = [lesson for lesson in lessons if lesson.id in selected]
    return course, lessons


def build_course_archive(db, course_id, payload, username):
    course, lessons = selected_scope(db, course_id, payload, username)
    descriptor, filename = mkstemp(prefix="classagent-export-", suffix=".zip")
    os.close(descriptor)
    path = Path(filename)
    archive = None
    try:
        archive = Archive(path)
        extras = Extras(db, course, lessons, payload, username)
        extras.check_size(archive)
        contents = payload.contents
        labels = [label for key, label in [("summaries", "智能纪要"), ("transcripts", "文字记录"), ("knowledge", "知识点"), ("quizzes", "小测与答案" if contents.answers else "小测题目"), ("audio", "原音频"), ("materials", "上传课件（含课程公共资料）")] if getattr(contents, key)]
        exported_at = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M")
        index = [f"# {md(course.name)} · 课程目录", "", "> ClassAgent · 课程资料归档", "", f"学期：{md(course.semester or '未设置')}",
                 f"导出时间：{exported_at}（北京时间）", f"导出范围：{'整门课程' if payload.lesson_ids is None else '指定课次'} · {len(lessons)} 节", "",
                 "导出内容：" + "、".join(labels), "", "资料保留已保存的版本；导出不会重新转写或调用AI生成内容。", "", "## 课次目录", ""]
        if not lessons:
            index += ["本课程暂无可导出的课次。", ""]
        for position, lesson in enumerate(lessons, 1):
            folder = f"{position:03}_{safe_name(lesson.title)}"
            before_files = archive.files
            links = []
            details = [f"日期：{md(lesson.lesson_date or '未设置')}"]
            if contents.summaries:
                prefix = f"# {md(lesson.title)} · 智能纪要\n\n课程：{md(course.name)}\n\n上课日期：{md(lesson.lesson_date or '未设置')}\n\n"
                summary = db.scalar(select(LessonSummary).where(LessonSummary.lesson_id == lesson.id))
                state = {"completed": "已生成", "edited": "已手动编辑", "stale": "文字记录更新后，纪要尚未同步", "queued": "等待生成", "generating": "生成中", "failed": "生成失败"}.get(summary.status, "未生成") if summary else "未生成"
                body = summary_markdown(summary.content, summary.status) if summary else "暂无已保存的智能纪要。\n"
                archive.text(f"{folder}/智能纪要.md", prefix + f"纪要状态：{state}\n\n" + body)
                links.append(f"- [智能纪要]({quote(folder + '/智能纪要.md')})")
                details.append("纪要：" + state)
            if contents.transcripts:
                segments = list(db.scalars(select(TranscriptSegment).where(TranscriptSegment.lesson_id == lesson.id).order_by(TranscriptSegment.start_ms, TranscriptSegment.id)))
                aliases = {alias.raw_label: alias.display_name for alias in db.scalars(select(SpeakerAlias).where(SpeakerAlias.lesson_id == lesson.id))}
                archive.text(f"{folder}/文字记录.txt", transcript_text(lesson, segments, aliases), plain=True)
                links.append(f"- [文字记录]({quote(folder + '/文字记录.txt')})")
                details.append(f"文字记录：{len(segments)} 段")
            links += extras.lesson(archive, lesson, folder)
            if archive.files == before_files:
                archive.text(f"{folder}/课次说明.md", f"# {md(lesson.title)}\n\n本课次在当前勾选的内容中没有可导出的文件；请查看课程目录中的公共资料和缺失提醒。\n")
                links.append(f"- [课次说明]({quote(folder + '/课次说明.md')})")
            index += [f"### {position:03} · {md(lesson.title)}", "", " · ".join(details), "", *links, ""]
        index += extras.shared(archive)
        index += ["## 阅读说明", "", "- Markdown文件可用支持Markdown的阅读器打开；TXT为UTF-8文本。", "- 原音频和课件按原始字节保存，ZIP不会转码或修改它们。", "- 指定课次仅包含范围完全落在所选课次内的小测；整门课程小测仅在全课程模式中包含。", "- 手动修改、掌握状态和答案为导出时保存的记录，来源变化时请回到应用核对。", ""]
        # 构建期间被回收或权限发生变化时，不返回旧范围的文件。
        current, visible = selected_scope(db, course_id, payload, username)
        if {lesson.id for lesson in lessons} - {lesson.id for lesson in visible}:
            raise HTTPException(409, "导出期间课次范围已变化，请刷新后重试")
        archive.text("课程目录.md", "\n".join(index).rstrip() + "\n")
        archive.close()
        return path, safe_name(current.name) + "-课程资料.zip"
    except BaseException:
        try:
            if archive is not None:
                archive.close()
        finally:
            path.unlink(missing_ok=True)
        raise
