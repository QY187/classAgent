from pathlib import PureWindowsPath
from pathlib import Path
import shutil
import subprocess
from tempfile import mkdtemp
from uuid import uuid4
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.orm import Session

from ...core.ownership import user_id_for_username
from ...infrastructure.storage import materialize_file, upload_file
from ...shared.models import Course, CourseMaterial, Lesson


MAX_MATERIAL_BYTES = 25 * 1024 * 1024
MAX_PREVIEW_CHARS = 100_000
MAX_PREVIEW_XML_BYTES = 8 * 1024 * 1024
MAX_CONVERTED_PDF_BYTES = 80 * 1024 * 1024
OFFICE_SUFFIXES = {".doc", ".docx", ".ppt", ".pptx"}
ALLOWED_TYPES = {
    ".pdf": "application/pdf",
    ".ppt": "application/vnd.ms-powerpoint",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".txt": "text/plain",
    ".md": "text/markdown",
}


def _owned_course(db: Session, course_id: str, username: str) -> Course:
    course = db.get(Course, course_id)
    if course is None or course.owner_id != user_id_for_username(db, username):
        raise HTTPException(status_code=404, detail="课程不存在")
    return course


def list_materials(db: Session, course_id: str, username: str) -> list[CourseMaterial]:
    _owned_course(db, course_id, username)
    return list(db.scalars(select(CourseMaterial).where(CourseMaterial.course_id == course_id).order_by(CourseMaterial.created_at.desc(), CourseMaterial.id.desc())))


def upload_material(db: Session, course_id: str, lesson_id: str | None, file: UploadFile, username: str) -> CourseMaterial:
    _owned_course(db, course_id, username)
    if lesson_id and db.scalar(select(Lesson.id).where(Lesson.id == lesson_id, Lesson.course_id == course_id)) is None:
        raise HTTPException(status_code=400, detail="所选课次不属于当前课程")

    filename = PureWindowsPath(file.filename or "").name
    suffix = PureWindowsPath(filename).suffix.lower()
    if not filename or len(filename) > 255 or suffix not in ALLOWED_TYPES:
        raise HTTPException(status_code=400, detail="仅支持 PDF、PPT、Word、图片和文本资料，文件名不超过 255 个字符")
    file.file.seek(0, 2)
    size = file.file.tell()
    file.file.seek(0)
    if size == 0 or size > MAX_MATERIAL_BYTES:
        raise HTTPException(status_code=400, detail="资料大小须在 1 字节至 25 MB 之间")

    object_key = f"materials/{course_id}/{uuid4()}{suffix}"
    content_type = ALLOWED_TYPES[suffix]
    upload_file(object_key, file.file, size, content_type)
    material = CourseMaterial(course_id=course_id, lesson_id=lesson_id, filename=filename,
                              content_type=content_type, object_key=object_key, size_bytes=size)
    db.add(material)
    db.commit()
    db.refresh(material)
    return material


def get_material_file(db: Session, course_id: str, material_id: str, username: str) -> tuple[CourseMaterial, Path, bool]:
    _owned_course(db, course_id, username)
    material = db.scalar(select(CourseMaterial).where(CourseMaterial.id == material_id, CourseMaterial.course_id == course_id))
    if material is None:
        raise HTTPException(status_code=404, detail="资料不存在")
    try:
        path, must_remove = materialize_file(material.object_key)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="资料文件不存在") from None
    return material, path, must_remove


def convert_office_to_pdf(path: Path, filename: str) -> tuple[Path, Path]:
    if PureWindowsPath(filename).suffix.lower() not in OFFICE_SUFFIXES:
        raise HTTPException(status_code=415, detail="该格式无需转换为 PDF")
    executable = shutil.which("soffice")
    if executable is None:
        raise HTTPException(status_code=503, detail="文档预览服务暂不可用，请下载原文件查看")

    directory = Path(mkdtemp(prefix="classagent-preview-"))
    output_dir = directory / "output"
    output_dir.mkdir()
    try:
        result = subprocess.run(
            [executable, f"-env:UserInstallation={(directory / 'profile').as_uri()}", "--headless", "--norestore",
             "--convert-to", "pdf", "--outdir", str(output_dir), str(path)],
            capture_output=True, timeout=90, check=False,
        )
        converted = output_dir / f"{path.stem}.pdf"
        if result.returncode != 0 or not converted.is_file():
            raise HTTPException(status_code=422, detail="文档无法转换为预览，请下载原文件查看")
        if converted.stat().st_size > MAX_CONVERTED_PDF_BYTES:
            raise HTTPException(status_code=413, detail="预览文件过大，请下载原文件查看")
        return converted, directory
    except subprocess.TimeoutExpired:
        shutil.rmtree(directory, ignore_errors=True)
        raise HTTPException(status_code=504, detail="生成预览超时，请下载原文件查看") from None
    except Exception:
        shutil.rmtree(directory, ignore_errors=True)
        raise


def cleanup_converted_preview(directory: Path, source: Path | None) -> None:
    shutil.rmtree(directory, ignore_errors=True)
    if source is not None:
        source.unlink(missing_ok=True)


def preview_text(path: Path, filename: str) -> tuple[str, bool]:
    suffix = PureWindowsPath(filename).suffix.lower()
    if suffix in {".txt", ".md"}:
        with path.open("rb") as stream:
            content = stream.read(MAX_PREVIEW_CHARS * 4 + 1)
        text = content.decode("utf-8", errors="replace")
        return text[:MAX_PREVIEW_CHARS], len(text) > MAX_PREVIEW_CHARS
    if suffix not in {".docx", ".pptx"}:
        raise HTTPException(status_code=415, detail="该格式暂不支持文字预览，请下载原文件查看")

    try:
        with ZipFile(path) as archive:
            if suffix == ".docx":
                names = ["word/document.xml"]
                paragraph_tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
                text_tag = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"
            else:
                names = sorted((name for name in archive.namelist() if name.startswith("ppt/slides/slide") and name.endswith(".xml")),
                               key=lambda name: int(name.removeprefix("ppt/slides/slide").removesuffix(".xml")))
                paragraph_tag = "{http://schemas.openxmlformats.org/drawingml/2006/main}p"
                text_tag = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
            lines: list[str] = []
            remaining = MAX_PREVIEW_XML_BYTES
            for name in names:
                info = archive.getinfo(name)
                if info.file_size > remaining:
                    raise HTTPException(status_code=413, detail="文字预览内容过大，请下载原文件查看")
                remaining -= info.file_size
                root = ElementTree.fromstring(archive.read(name))
                for paragraph in root.iter(paragraph_tag):
                    line = "".join(node.text or "" for node in paragraph.iter(text_tag)).strip()
                    if line:
                        lines.append(line)
                if suffix == ".pptx":
                    lines.append("")
            text = "\n".join(lines).strip()
            return text[:MAX_PREVIEW_CHARS], len(text) > MAX_PREVIEW_CHARS
    except (BadZipFile, KeyError, ValueError, ElementTree.ParseError):
        raise HTTPException(status_code=422, detail="文件内容无法解析，请下载原文件查看") from None
