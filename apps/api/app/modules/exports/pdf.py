"""离线PDF排版：嵌入中文TrueType字体，只有文本和受限链接，无外部资源读取。"""
from html import escape
from io import BytesIO
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit
import os
import re

from fastapi import HTTPException

FONT_PATH = Path("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc")
FONT_NAME = "ClassAgentCJK"
_FONT_LOCK = Lock()
MAX_PAGES = 200


def font_name():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    with _FONT_LOCK:
        if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
            path = Path(os.environ.get("PDF_CJK_FONT", str(FONT_PATH)))
            if not path.is_file():
                raise HTTPException(503, "PDF中文字体未就绪，请联系管理员后重试")
            pdfmetrics.registerFont(TTFont(FONT_NAME, str(path), subfontIndex=0))
            pdfmetrics.registerFontFamily(FONT_NAME, normal=FONT_NAME, bold=FONT_NAME, italic=FONT_NAME, boldItalic=FONT_NAME)
    return FONT_NAME


def render_pdf(content, *, plain=False, check=lambda: None):
    try:
        from markdown_it import MarkdownIt
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.platypus import HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer
    except ImportError as exc:
        raise HTTPException(503, "PDF生成服务尚未就绪，请稍后重试") from exc
    check()
    font = font_name()
    navy = colors.HexColor("#263f64")
    muted = colors.HexColor("#748197")
    base = ParagraphStyle("Body", fontName=font, fontSize=10.5, leading=18, textColor=colors.HexColor("#243247"),
                          alignment=TA_LEFT, wordWrap="CJK", spaceAfter=7, allowWidows=0, allowOrphans=0)
    title = ParagraphStyle("Title", parent=base, fontSize=22, leading=31, spaceBefore=8, spaceAfter=20, textColor=navy, keepWithNext=True)
    headings = {"h1": title, "h2": ParagraphStyle("H2", parent=base, fontSize=14, leading=22, spaceBefore=18, spaceAfter=10, textColor=navy, keepWithNext=True),
                "h3": ParagraphStyle("H3", parent=base, fontSize=11.5, leading=19, spaceBefore=12, spaceAfter=7, textColor=navy, keepWithNext=True)}
    meta = ParagraphStyle("Meta", parent=base, fontSize=9, leading=15, textColor=muted, spaceAfter=10)
    segment_meta = ParagraphStyle("SegmentMeta", parent=meta, textColor=navy, keepWithNext=True, spaceBefore=10, spaceAfter=5)
    quote = ParagraphStyle("Quote", parent=base, leftIndent=12, rightIndent=8, textColor=muted, backColor=colors.HexColor("#f3f6fa"), borderPadding=7, spaceBefore=5, spaceAfter=10)

    def text(value):
        return escape(re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value))

    def inline(tokens):
        result, links = [], []
        for token in tokens or []:
            kind = token.type
            if kind in {"text", "code_inline"}:
                result.append(text(token.content))
            elif kind in {"softbreak", "hardbreak"}:
                result.append("<br/>")
            elif kind == "strong_open":
                result.append('<font color="#263f64"><b>')
            elif kind == "strong_close":
                result.append("</b></font>")
            elif kind == "em_open":
                result.append("<i>")
            elif kind == "em_close":
                result.append("</i>")
            elif kind == "link_open":
                href = token.attrGet("href") or ""
                allowed = urlsplit(href).scheme in {"", "https", "http", "mailto"} and not href.startswith(("/", "\\"))
                links.append(allowed)
                if allowed:
                    result.append(f'<link href="{escape(href, quote=True)}" color="#426496">')
            elif kind == "link_close":
                if links and links.pop():
                    result.append("</link>")
            elif kind == "image":
                result.append(text(token.content))
        return "".join(result) or " "

    story = []
    if plain:
        blocks = content.replace("\r\n", "\n").strip().split("\n\n")
        for index, block in enumerate(blocks):
            check()
            lines = block.splitlines()
            if not lines:
                continue
            if index == 0:
                story.append(Paragraph(text(lines[0]), title))
                if len(lines) > 1:
                    story.append(Paragraph("<br/>".join(text(line) for line in lines[1:]), meta))
            elif re.match(r"^\d+\s+\d+:\d+", lines[0]):
                story.append(Paragraph(text(lines[0]), segment_meta))
                if len(lines) > 1:
                    story.append(Paragraph("<br/>".join(text(line) for line in lines[1:]), base))
            else:
                story.append(Paragraph("<br/>".join(text(line) for line in lines), base))
    else:
        tokens = MarkdownIt("commonmark", {"html": False}).parse(content)
        position = 0
        def blocks(end=None, quoted=False):
            nonlocal position
            output = []
            while position < len(tokens):
                check()
                token = tokens[position]
                position += 1
                if token.type == end:
                    break
                if token.type == "heading_open":
                    body = tokens[position]; position += 1
                    output.append(Paragraph(inline(body.children), headings.get(token.tag, headings["h3"])))
                    if position < len(tokens) and tokens[position].type == "heading_close": position += 1
                elif token.type == "paragraph_open":
                    body = tokens[position]; position += 1
                    output.append(Paragraph(inline(body.children), quote if quoted else base))
                    if position < len(tokens) and tokens[position].type == "paragraph_close": position += 1
                elif token.type in {"bullet_list_open", "ordered_list_open"}:
                    items = []
                    closing = token.type.replace("_open", "_close")
                    while position < len(tokens) and tokens[position].type != closing:
                        if tokens[position].type == "list_item_open":
                            position += 1
                            items.append(ListItem(blocks("list_item_close", quoted) or [Spacer(1, 1)]))
                        else: position += 1
                    if position < len(tokens): position += 1
                    ordered = token.type == "ordered_list_open"
                    output.append(ListFlowable(items, bulletType="1" if ordered else "bullet", start=token.attrGet("start") or 1 if ordered else None,
                        leftIndent=18, bulletFontName=font, bulletFontSize=9, spaceAfter=9))
                elif token.type == "blockquote_open":
                    output.extend(blocks("blockquote_close", True))
                elif token.type in {"fence", "code_block"}:
                    output.append(Paragraph(text(token.content).replace("\n", "<br/>"), quote))
                elif token.type == "hr":
                    output.append(HRFlowable(width="100%", thickness=.6, color=colors.HexColor("#dce3ec"), spaceBefore=10, spaceAfter=12))
            return output
        story = blocks()
    if not story:
        story = [Paragraph("暂无已保存的内容。", base)]

    class NumberedCanvas(Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.page_states = []
        def showPage(self):
            self.page_states.append(dict(self.__dict__))
            self._startPage()
        def save(self):
            total = len(self.page_states)
            for state in self.page_states:
                self.__dict__.update(state)
                self.setFont(font, 8)
                self.setFillColor(muted)
                self.drawString(17 * mm, 13 * mm, "ClassAgent · 课程学习资料")
                self.drawRightString(A4[0] - 17 * mm, 13 * mm, f"{self._pageNumber} / {total}")
                super().showPage()
            super().save()

    failure = None
    def check_layout(page=None):
        # ReportLab会用字符串重建回调异常，保留原有HTTP状态后终止排版。
        nonlocal failure
        try:
            check()
            if page is not None and page > MAX_PAGES:
                raise HTTPException(413, "单份PDF超过200页，请减少资料内容后重试")
        except HTTPException as exc:
            failure = exc
            raise RuntimeError("PDF export limit reached") from exc

    class CheckedDocument(SimpleDocTemplate):
        def afterFlowable(self, flowable):
            check_layout()
    def page_header(canvas, doc):
        check_layout(doc.page)
        canvas.saveState()
        canvas.setFont(font, 9)
        canvas.setFillColor(muted)
        canvas.drawString(17 * mm, A4[1] - 15 * mm, "ClassAgent  /  课堂资料")
        canvas.setStrokeColor(colors.HexColor("#dce3ec"))
        canvas.line(17 * mm, A4[1] - 19 * mm, A4[0] - 17 * mm, A4[1] - 19 * mm)
        canvas.restoreState()
    buffer = BytesIO()
    doc = CheckedDocument(buffer, pagesize=A4, leftMargin=17 * mm, rightMargin=17 * mm, topMargin=25 * mm, bottomMargin=23 * mm,
                          title="ClassAgent 课程资料", author="ClassAgent", pageCompression=1)
    try:
        doc.build(story, onFirstPage=page_header, onLaterPages=page_header, canvasmaker=NumberedCanvas)
    except HTTPException:
        raise
    except Exception as exc:
        if failure is not None:
            raise failure from exc
        raise HTTPException(503, "PDF排版生成失败，请减少资料范围后重试") from exc
    check()
    return buffer.getvalue()
