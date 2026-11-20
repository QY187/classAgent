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


DOCUMENTS = {
    "summary": ("智能纪要", "CLASS NOTES", "#355C98"),
    "knowledge": ("知识点", "KNOWLEDGE", "#247B78"),
    "quiz": ("小测题目", "PRACTICE", "#946521"),
    "transcript": ("文字记录", "TRANSCRIPT", "#506582"),
    "index": ("课程目录", "COURSE ARCHIVE", "#355C98"),
}


def render_pdf(content, *, plain=False, document_type="summary", check=lambda: None):
    try:
        from markdown_it import MarkdownIt
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.pdfgen.canvas import Canvas
        from reportlab.platypus import HRFlowable, ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer, KeepTogether
    except ImportError as exc:
        raise HTTPException(503, "PDF生成服务尚未就绪，请稍后重试") from exc
    check()
    font = font_name()
    label, english, accent_hex = DOCUMENTS.get(document_type, DOCUMENTS["summary"])
    accent = colors.HexColor(accent_hex)
    navy = colors.HexColor("#20334D")
    muted = colors.HexColor("#6A788B")
    pale = colors.HexColor("#F1F5FA")
    base = ParagraphStyle("Body", fontName=font, fontSize=10.5, leading=18.5,
                          textColor=colors.HexColor("#29384B"), alignment=TA_LEFT,
                          wordWrap="CJK", spaceAfter=9, allowWidows=0, allowOrphans=0)
    title = ParagraphStyle("Title", parent=base, fontSize=23, leading=33,
                           spaceBefore=7, spaceAfter=15, textColor=navy, keepWithNext=True)
    eyebrow = ParagraphStyle("Eyebrow", parent=base, fontSize=9, leading=14,
                             textColor=accent, spaceAfter=0, keepWithNext=True)
    headings = {
        "h1": title,
        "h2": ParagraphStyle("H2", parent=base, fontSize=13, leading=21,
                             leftIndent=12, rightIndent=10, spaceBefore=21,
                             spaceAfter=13, textColor=accent, keepWithNext=True),
        "h3": ParagraphStyle("H3", parent=base, fontSize=11.5, leading=19,
                             spaceBefore=13, spaceAfter=8, textColor=navy, keepWithNext=True),
    }
    meta = ParagraphStyle("Meta", parent=base, fontSize=9, leading=16, textColor=muted,
                          spaceAfter=10)
    info = ParagraphStyle("Info", parent=meta, leftIndent=10, rightIndent=10,
                          backColor=colors.HexColor("#F6F8FB"), borderPadding=8,
                          spaceBefore=4, spaceAfter=15)
    segment_meta = ParagraphStyle("SegmentMeta", parent=meta, textColor=accent,
                                  keepWithNext=True, spaceBefore=17, spaceAfter=13,
                                  borderColor=colors.HexColor("#E1E7EF"), borderWidth=.5, borderPadding=6)
    quote = ParagraphStyle("Quote", parent=base, fontSize=9.5, leading=17,
                           leftIndent=12, rightIndent=12, textColor=muted,
                           backColor=pale, borderPadding=8, spaceBefore=3, spaceAfter=12)
    option_style = ParagraphStyle("Option", parent=base, leftIndent=15, spaceAfter=5)

    class ReadingParagraph(Paragraph):
        def breakLinesCJK(self, widths):
            result = super().breakLinesCJK(widths)
            # ReportLab默认禁则缺少中文全角逗号等字符，允许其悬挂在上一行末尾。
            if result.kind == 0:
                from reportlab.pdfbase.pdfmetrics import stringWidth
                for index in range(1, len(result.lines)):
                    space, words = result.lines[index]
                    previous_space, previous_words = result.lines[index - 1]
                    while words and words[0] and words[0][0] in "，；：！？、。）》】”’":
                        char = words[0][0]
                        width = stringWidth(char, self.style.fontName, self.style.fontSize)
                        previous_words[-1] += char
                        words[0] = words[0][1:]
                        previous_space -= width
                        space += width
                    result.lines[index - 1] = (previous_space, previous_words)
                    result.lines[index] = (space, words)
                result.lines = [(space, words) for space, words in result.lines if any(words)]
            return result

    # 段落、列表和分页后的拆分段落都沿用中文阅读规则。
    Paragraph = ReadingParagraph

    class SectionHeading(Paragraph):
        def draw(self):
            self.canv.saveState()
            self.canv.setFillColor(pale)
            self.canv.roundRect(0, -5, self.width, self.height + 10, 4, fill=1, stroke=0)
            self.canv.setFillColor(accent)
            self.canv.roundRect(0, -5, 3, self.height + 10, 1, fill=1, stroke=0)
            self.canv.restoreState()
            super().draw()

    def hero(value):
        suffix = " · " + label
        if value.endswith(suffix):
            value = value[:-len(suffix)]
        length = len(re.sub(r"<[^>]+>", "", value))
        hero_style = title if length <= 64 else ParagraphStyle("LongTitle", parent=title,
                            fontSize=18 if length <= 120 else 16, leading=27 if length <= 120 else 24)
        return [Paragraph(f"{label}  /  {english}", eyebrow), Paragraph(value, hero_style),
                HRFlowable(width=42, thickness=2, color=accent, hAlign="LEFT", spaceAfter=16)]

    def metadata(value):
        return bool(re.match(r"^(课程：|上课日期：|纪要状态：|学期：|导出时间：|导出范围：|导出内容：|范围：|题量：|共 \d+ 张卡片)", value))

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
                story.extend(hero(text(lines[0])))
                if len(lines) > 1:
                    story.append(Paragraph("<br/>".join(text(line) for line in lines[1:] if not line.startswith("ClassAgent")), info))
            elif re.match(r"^\d+\s+\d+:\d+", lines[0]):
                story.append(Paragraph(text(lines[0]), segment_meta))
                if len(lines) > 1:
                    story.append(Paragraph("<br/>".join(text(line) for line in lines[1:]), base))
            else:
                story.append(Paragraph("<br/>".join(text(line) for line in lines), base))
    else:
        tokens = MarkdownIt("commonmark", {"html": False}).parse(content)
        position = 0
        first_title = True
        def blocks(end=None, quoted=False):
            nonlocal position, first_title
            output = []
            while position < len(tokens):
                check()
                token = tokens[position]
                position += 1
                if token.type == end:
                    break
                if token.type == "heading_open":
                    body = tokens[position]; position += 1
                    heading_text = inline(body.children)
                    if token.tag == "h1" and first_title:
                        output.extend(hero(heading_text))
                        first_title = False
                    elif token.tag == "h2":
                        output.append(SectionHeading(heading_text, headings["h2"]))
                    else:
                        output.append(Paragraph(heading_text, headings["h3"] if token.tag == "h1" else headings.get(token.tag, headings["h3"])))
                    if position < len(tokens) and tokens[position].type == "heading_close": position += 1
                elif token.type == "paragraph_open":
                    body = tokens[position]; position += 1
                    output.append(Paragraph(inline(body.children), quote if quoted else meta if metadata(body.content) else base))
                    if position < len(tokens) and tokens[position].type == "paragraph_close": position += 1
                elif token.type in {"bullet_list_open", "ordered_list_open"}:
                    items = []
                    closing = token.type.replace("_open", "_close")
                    while position < len(tokens) and tokens[position].type != closing:
                        if tokens[position].type == "list_item_open":
                            position += 1
                            item = blocks("list_item_close", quoted) or [Spacer(1, 1)]
                            if document_type == "quiz" and item and isinstance(item[0], Paragraph) and re.match(r"^[A-Z]\.", item[0].getPlainText()):
                                item[0] = Paragraph(item[0].text, option_style)
                                items.append(item)
                            else:
                                items.append(ListItem(item))
                        else: position += 1
                    if position < len(tokens): position += 1
                    ordered = token.type == "ordered_list_open"
                    if items and all(isinstance(item, list) for item in items):
                        output.extend(flowable for item in items for flowable in item)
                        output.append(Spacer(1, 10))
                        continue
                    # 混合列表仍使用统一的列表容器。
                    items = [ListItem(item) if isinstance(item, list) else item for item in items]
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
        # 汇总相邻的信息行，形成紧凑的信息区，避免与正文争夺视觉层级。
        combined = []
        for flowable in story:
            if isinstance(flowable, Paragraph) and flowable.style.name == "Meta":
                if combined and isinstance(combined[-1], Paragraph) and combined[-1].style.name == "Info":
                    combined[-1] = Paragraph(combined[-1].text + "<br/>" + flowable.text, info)
                else:
                    combined.append(Paragraph(flowable.text, info))
            else:
                combined.append(flowable)
        story = combined
        if document_type == "quiz":
            # 常规短题与选项一起分页；长题交给正常段落拆分，避免溢出。
            grouped, question = [], []
            def flush_question():
                if not question:
                    return
                length = sum(len(item.getPlainText()) for item in question if isinstance(item, Paragraph))
                if length < 1400:
                    grouped.append(KeepTogether(question[:]))
                else:
                    grouped.extend(question)
                question.clear()
            for flowable in story:
                if isinstance(flowable, SectionHeading) and re.match(r"第 \d+ 题", flowable.getPlainText()):
                    flush_question()
                    question.append(flowable)
                elif isinstance(flowable, Paragraph) and flowable.style.name == "H3":
                    flush_question()
                    grouped.append(flowable)
                elif question:
                    question.append(flowable)
                else:
                    grouped.append(flowable)
            flush_question()
            story = grouped
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
                # 页眉页脚在内容排版完成后统一绘制，首页和续页保持一致。
                self.saveState()
                left, right = 20 * mm, A4[0] - 20 * mm
                self.setFont(font, 8)
                self.setFillColor(accent)
                self.drawString(left, A4[1] - 15 * mm, "ClassAgent  /  学习资料")
                self.setFillColor(muted)
                self.drawRightString(right, A4[1] - 15 * mm, label)
                self.setStrokeColor(colors.HexColor("#DEE5EE"))
                self.setLineWidth(.5)
                self.line(left, A4[1] - 19 * mm, right, A4[1] - 19 * mm)
                self.line(left, 20 * mm, right, 20 * mm)
                self.setFont(font, 8)
                self.drawString(left, 14 * mm, "CLASSAGENT  /  " + english)
                self.drawRightString(right, 14 * mm, f"{self._pageNumber} / {total}")
                self.restoreState()
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
    buffer = BytesIO()
    doc = CheckedDocument(buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=28 * mm, bottomMargin=27 * mm,
                          title=f"ClassAgent {label}", author="ClassAgent", pageCompression=1)
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
