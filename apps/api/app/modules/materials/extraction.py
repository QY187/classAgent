"""有界课件文本提取；保留原始页/幻灯片/段落编号，不推测图片内容。"""
from pathlib import Path
import re
from xml.etree import ElementTree
from zipfile import ZipFile, BadZipFile


SUPPORTED_SUFFIXES = {".pdf", ".pptx", ".docx", ".txt", ".md"}
MAX_TEXT_CHARS = 1_000_000
MAX_UNITS = 2000
MAX_XML_BYTES = 32 * 1024 * 1024
CHUNK_CHARS = 1400


class ExtractionError(ValueError):
    pass


def extract_units(path: Path, filename: str) -> list[dict]:
    suffix = Path(filename).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ExtractionError("该格式暂不支持问答解析，可继续预览或下载。请转换为文字型 PDF、PPTX、DOCX 或文本。")
    units = []
    total = 0

    def add(kind, number, text):
        nonlocal total
        text = text.replace("\x00", "").strip()
        total += len(text)
        if total > MAX_TEXT_CHARS or number > MAX_UNITS:
            raise ExtractionError("资料内容超出解析限制，请拆分后重新上传。")
        if text:
            units.append({"locator_type": kind, "locator_number": number, "content": text})

    try:
        if suffix in {".txt", ".md"}:
            data = path.read_bytes()
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                try:
                    text = data.decode("gb18030")
                except UnicodeDecodeError as exc:
                    raise ExtractionError("文本编码无法识别，请保存为 UTF-8 后重试。") from exc
            for number, paragraph in enumerate(re.split(r"\n\s*\n", text), 1):
                add("paragraph", number, paragraph)
        elif suffix == ".pdf":
            from pypdf import PdfReader
            reader = PdfReader(path)
            if reader.is_encrypted:
                raise ExtractionError("加密 PDF 暂不能解析，请解密后重新上传。")
            if len(reader.pages) > MAX_UNITS:
                raise ExtractionError("PDF 页数超出解析限制，请拆分后上传。")
            for number, page in enumerate(reader.pages, 1):
                add("page", number, page.extract_text() or "")
        else:
            with ZipFile(path) as archive:
                if suffix == ".docx":
                    names = ["word/document.xml"]
                    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
                else:
                    names = sorted((name for name in archive.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", name)),
                                   key=lambda name: int(re.search(r"slide(\d+)", name).group(1)))
                    # 以演示文稿的关系顺序为准，文件名编号不一定是展示顺序。
                    if "ppt/presentation.xml" in archive.namelist() and "ppt/_rels/presentation.xml.rels" in archive.namelist():
                        from posixpath import normpath
                        for name in ("ppt/presentation.xml", "ppt/_rels/presentation.xml.rels"):
                            if archive.getinfo(name).file_size > MAX_XML_BYTES:
                                raise ExtractionError("文档结构过大，无法解析。")
                        rels = ElementTree.fromstring(archive.read("ppt/_rels/presentation.xml.rels"))
                        targets = {item.get("Id"): normpath("ppt/" + item.get("Target", ""))
                                   for item in rels if item.get("TargetMode") != "External"}
                        presentation = ElementTree.fromstring(archive.read("ppt/presentation.xml"))
                        ids = presentation.findall(".//{http://schemas.openxmlformats.org/presentationml/2006/main}sldId")
                        if ids:
                            names = [targets.get(item.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"), "") for item in ids]
                    namespace = "http://schemas.openxmlformats.org/drawingml/2006/main"
                if len(names) > MAX_UNITS:
                    raise ExtractionError("文档页数超出解析限制，请拆分后上传。")
                remaining = MAX_XML_BYTES
                for number, name in enumerate(names, 1):
                    info = archive.getinfo(name)
                    remaining -= info.file_size
                    if remaining < 0 or info.flag_bits & 1:
                        raise ExtractionError("文档内容过大或已加密，无法解析。")
                    root = ElementTree.fromstring(archive.read(name))
                    paragraphs = ["".join(node.text or "" for node in paragraph.iter(f"{{{namespace}}}t"))
                                  for paragraph in root.iter(f"{{{namespace}}}p")]
                    if suffix == ".docx":
                        for index, paragraph in enumerate(paragraphs, 1):
                            add("paragraph", index, paragraph)
                    else:
                        add("slide", number, "\n".join(paragraphs))
    except ExtractionError:
        raise
    except (BadZipFile, KeyError, ElementTree.ParseError, OSError, ValueError) as exc:
        raise ExtractionError("文档无法解析，请确认文件完整且格式正确。") from exc
    if not units:
        raise ExtractionError("没有可提取的文字，可能是扫描件或图片课件；首版暂不支持 OCR，请上传文字版本。")
    return units


def make_material_chunks(units: list[dict]) -> list[dict]:
    chunks = []
    for unit in units:
        for start in range(0, len(unit["content"]), CHUNK_CHARS - 150):
            chunks.append({**unit, "content": unit["content"][start:start + CHUNK_CHARS], "position": len(chunks)})
            if start + CHUNK_CHARS >= len(unit["content"]):
                break
    return chunks
