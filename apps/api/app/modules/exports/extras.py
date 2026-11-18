"""知识点、小测及原文件按已核对的导出范围分组。"""
from collections import defaultdict
from pathlib import Path
from urllib.parse import quote
from zipfile import ZIP_STORED, ZipInfo
import json

from fastapi import HTTPException
from minio.error import S3Error
from sqlalchemy import or_, select
from urllib3.exceptions import HTTPError

from ...core.config import get_settings
from ...infrastructure.storage import get_client
from ...shared.models import AudioFile, CourseMaterial, Quiz, ReviewCard
from ..quizzes.material_sources import material_evidence
from .render import clock, md

CARD_STATUS = {"new": "未学习", "review": "需要复习", "mastered": "已掌握"}
CARD_TYPE = {"concept": "知识点", "question": "问答", "rule": "公式或规则", "pitfall": "易错点"}


def quoted(text):
    return "\n".join("> " + md(line) for line in (text or "").splitlines())


def knowledge_markdown(lesson, cards):
    lines = [f"# {md(lesson.title)} · 知识点", "", f"共 {len(cards)} 张卡片；掌握状态为导出时记录。", ""]
    for index, card in enumerate(cards, 1):
        lines += [f"## {index}. {md(card.title)}", "", f"类型：{CARD_TYPE.get(card.card_type, '知识点')} · 状态：{CARD_STATUS.get(card.status, '未学习')}", "", md(card.body), ""]
        if card.source_excerpt:
            lines += [f"课堂来源（保存时摘录） · {clock(card.source_start_ms)}", "", quoted(card.source_excerpt), ""]
    if not cards:
        lines += ["本课次暂无已保存的知识点。", ""]
    return "\n".join(lines)


def quiz_scope(quiz):
    try:
        ids = json.loads(quiz.lesson_ids_json) if quiz.lesson_ids_json else ([quiz.lesson_id] if quiz.lesson_id else [])
    except (ValueError, TypeError):
        return None
    return ids if isinstance(ids, list) and all(isinstance(value, str) for value in ids) else None


def quiz_markdown(db, quiz, answers, username, titles):
    questions = list(quiz.questions)
    scope = quiz_scope(quiz)
    label = "整门课程" if scope == [] else "、".join(titles.get(identity, "课次已不可用") for identity in scope) if scope else "范围记录无法读取"
    lines = ["# " + md(quiz.title), "", f"范围：{md(label)}", f"题量：{len(questions)} · {'含参考答案与解析' if answers else '练习版，不含答案与解析'}", "",
             "题目与答案为生成时保存的版本，复习时请结合来源核对。" if answers else "请先独立作答。", ""]
    valid_options = {}
    for index, question in enumerate(questions, 1):
        try:
            options = json.loads(question.options_json)
            assert isinstance(options, list) and all(isinstance(option, str) for option in options)
        except (ValueError, TypeError, AssertionError):
            options = []
        valid_options[question.id] = options
        lines += [f"## 第 {index} 题 · {'判断' if question.kind == 'true_false' else '单选'}", "", md(question.stem), ""]
        lines += [f"- {chr(65 + position)}. {md(option)}" for position, option in enumerate(options)]
        if not options:
            lines += ["选项格式无法读取，请在应用中核对。"]
        lines += [""]
    if answers:
        lines += ["---", "", "## 参考答案与解析", ""]
        for index, question in enumerate(questions, 1):
            options = valid_options[question.id]
            correct = question.correct_option
            answer = f"{chr(65 + correct)}. {md(options[correct])}" if type(correct) is int and 0 <= correct < len(options) else "标准答案无法读取，请在应用中核对"
            lines += [f"### 第 {index} 题", "", f"**正确答案**：{answer}", "", "**解析**：" + md(question.explanation), ""]
            if question.source_material_json:
                try:
                    citation = material_evidence(db, question, username)["source_material"]
                    state = "当前可核对" if citation["source_status"] == "current" else "原文件已变更或不可用"
                    lines += [f"课件来源：{md(citation.get('filename', '课件'))} · {md(citation.get('locator_label', '原文位置'))} · {state}", ""]
                except (ValueError, KeyError, TypeError):
                    lines += ["课件引用记录无法读取，请在应用中核对。", ""]
            else:
                lines += [f"课堂来源：{md(titles.get(question.source_lesson_id, '来源课次已不可用'))} · {clock(question.source_start_ms)}", ""]
            if question.source_excerpt:
                lines += ["出题时保存的原文摘录：", "", quoted(question.source_excerpt), ""]
    return "\n".join(lines)


def add_binary(archive, record, name):
    """原文件直接分块写ZIP；S3连接和本地文件均在成功/异常时释放。"""
    archive.check(files=1)
    settings = get_settings()
    response = None
    stream = None
    started = False
    try:
        if settings.storage_backend == "local":
            root = Path(settings.local_storage_path).resolve()
            target = (root / record.object_key).resolve()
            if not target.is_relative_to(root):
                raise HTTPException(503, "原文件路径异常，请联系管理员核对资料")
            stream = target.open("rb")
            chunks = iter(lambda: stream.read(1024 * 1024), b"")
        else:
            response = get_client().get_object(settings.s3_bucket, record.object_key)
            chunks = response.stream(1024 * 1024)
        entry = ZipInfo(name)
        entry.compress_type = ZIP_STORED
        started = True
        with archive.zip.open(entry, "w", force_zip64=True) as destination:
            for chunk in chunks:
                archive.check(len(chunk))
                destination.write(chunk)
                archive.bytes += len(chunk)
        archive.files += 1
        return True
    except FileNotFoundError as exc:
        if started:
            raise HTTPException(503, "原文件读取中断，请重新导出") from exc
        return False
    except S3Error as exc:
        if not started and exc.code in {"NoSuchKey", "NoSuchObject"}:
            return False
        raise HTTPException(503, "原文件暂时无法读取，请稍后重试或取消附件选项") from exc
    except (OSError, HTTPError) as exc:
        raise HTTPException(503, "原文件暂时无法读取，请稍后重试或取消附件选项") from exc
    finally:
        try:
            if stream is not None:
                stream.close()
        finally:
            if response is not None:
                try:
                    response.close()
                finally:
                    response.release_conn()


class Extras:
    def __init__(self, db, course, lessons, payload, username):
        self.db, self.course, self.payload, self.username = db, course, payload, username
        self.titles = {lesson.id: lesson.title for lesson in lessons}
        self.cards, self.quizzes, self.audio, self.materials = (defaultdict(list) for _ in range(4))
        self.warnings = []
        ids = list(self.titles)
        contents = payload.contents
        if contents.knowledge:
            for card in db.scalars(select(ReviewCard).where(ReviewCard.course_id == course.id, ReviewCard.lesson_id.in_(ids)).order_by(ReviewCard.created_at, ReviewCard.id)):
                self.cards[card.lesson_id].append(card)
        if contents.quizzes:
            for quiz in db.scalars(select(Quiz).where(Quiz.course_id == course.id).order_by(Quiz.created_at, Quiz.id)):
                scope = quiz_scope(quiz)
                # 多课次题组也不能带入未选中或回收站课次的题目。
                if scope is None or (scope and not set(scope).issubset(ids)) or any(q.source_lesson_id and q.source_lesson_id not in ids for q in quiz.questions):
                    continue
                if payload.lesson_ids is not None and not scope:
                    continue
                key = scope[0] if scope and len(scope) == 1 and scope[0] in self.titles else "shared"
                self.quizzes[key].append(quiz)
        if contents.audio:
            for audio in db.scalars(select(AudioFile).where(AudioFile.lesson_id.in_(ids)).order_by(AudioFile.created_at, AudioFile.id)):
                self.audio[audio.lesson_id].append(audio)
        if contents.materials:
            for material in db.scalars(select(CourseMaterial).where(CourseMaterial.course_id == course.id,
                    or_(CourseMaterial.lesson_id.is_(None), CourseMaterial.lesson_id.in_(ids))).order_by(CourseMaterial.created_at, CourseMaterial.id)):
                self.materials[material.lesson_id or "shared"].append(material)

    def check_size(self, archive):
        records = [record for groups in [self.audio, self.materials] for values in groups.values() for record in values]
        archive.check(sum(max(0, record.size_bytes) for record in records), len(records))

    def files(self, archive, records, folder, kind):
        from .service import safe_name
        lines = []
        for index, record in enumerate(records, 1):
            suffix = Path(record.filename.replace("\\", "/")).suffix
            suffix = suffix if len(suffix) <= 12 and all(char.isalnum() or char == "." for char in suffix) else ""
            stem = safe_name(record.filename[:-len(suffix)] if suffix else record.filename)
            filename = f"{folder}/{index:03}_{stem[:80-len(suffix)]}{suffix}"
            if add_binary(archive, record, filename):
                lines.append(f"- [{md(record.filename)}]({quote(filename)})")
            else:
                self.warnings.append(f"{kind}「{record.filename}」原文件不存在，未收进资料包。")
        return lines

    def quiz_files(self, archive, quizzes, folder):
        from .service import safe_name
        lines = []
        for index, quiz in enumerate(quizzes, 1):
            name = f"{folder}/{index:03}_{safe_name(quiz.title)}.md"
            archive.text(name, quiz_markdown(self.db, quiz, self.payload.contents.answers, self.username, self.titles))
            lines.append(f"- [{md(quiz.title)}]({quote(name)})")
        return lines

    def lesson(self, archive, lesson, folder):
        lines = []
        contents = self.payload.contents
        if contents.knowledge:
            name = f"{folder}/知识点.md"
            archive.text(name, knowledge_markdown(lesson, self.cards[lesson.id]))
            lines.append(f"- [知识点（{len(self.cards[lesson.id])}张）]({quote(name)})")
        if contents.quizzes:
            quizzes = self.quizzes[lesson.id]
            lines += self.quiz_files(archive, quizzes, folder + "/小测")
            if not quizzes:
                lines.append("- 本课次暂无单课次小测；跨课次或整门课程小测见下方公共区。")
        if contents.audio:
            records = self.audio[lesson.id]
            lines += self.files(archive, records, folder + "/原音频", "原音频")
            if not records:
                lines.append("- 本课次暂无原音频。")
        if contents.materials:
            records = self.materials[lesson.id]
            lines += self.files(archive, records, folder + "/上传课件", "课件")
            if not records:
                lines.append("- 本课次暂无上传课件。")
        return lines

    def shared(self, archive):
        lines = []
        if self.quizzes["shared"]:
            lines += ["## 跨课次与课程小测", "", *self.quiz_files(archive, self.quizzes["shared"], "课程公共资料/小测"), ""]
        if self.materials["shared"]:
            lines += ["## 课程公共课件", "", *self.files(archive, self.materials["shared"], "课程公共资料/上传课件", "课程公共课件"), ""]
        if self.warnings:
            lines += ["## 原文件缺失提醒", "", *["- " + md(warning) for warning in self.warnings], ""]
        return lines
