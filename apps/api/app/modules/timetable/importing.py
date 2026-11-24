"""课表文件仅在内存中解析；预览不写库，确认后通过排课服务原子导入。"""
import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

from fastapi import HTTPException
from pydantic import ValidationError

from .schemas import EntryWrite

MAX_FILE_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 300


@dataclass
class Grid:
    name: str
    rows: list[list[str]]
    spans: dict[tuple[int, int], int] = field(default_factory=dict)


def clean(value) -> str:
    return unicodedata.normalize("NFKC", str(value or "")).replace("⻢", "马").replace("\r", "\n").strip()


def weekday(value: str) -> int:
    value = re.sub(r"\s+", "", clean(value))
    match = re.search(r"(?:星期|周|礼拜)([一二三四五六日天1-7])", value)
    token = match[1] if match else value
    return int(token) if token in list("1234567") else {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "日": 7, "天": 7}.get(token, 0)


def ranges(value: str) -> list[tuple[int, int]]:
    value = re.sub(r"\s+", "", clean(value)).replace("至", "-")
    value = re.sub(r"[~～—–－]", "-", value).strip("第[]()节小周")
    if not re.fullmatch(r"\d{1,2}(?:-\d{1,2})?(?:[,、;]\d{1,2}(?:-\d{1,2})?)*", value):
        return []
    numbers = set()
    for part in re.split(r"[,、;]", value):
        values = [int(n) for n in part.split("-")]
        start, end = values[0], values[-1]
        if start < 1 or end < start or end > 52:
            return []
        numbers.update(range(start, end + 1))
    result = []
    for number in sorted(numbers):
        if result and result[-1][1] == number - 1:
            result[-1] = (result[-1][0], number)
        else:
            result.append((number, number))
    return result


def period_ranges(text: str) -> list[tuple[int, int]]:
    match = re.search(r"(?:第|\[)?(\d{1,2}(?:\s*[-~～—–至,、]\s*\d{1,2})*)\s*\]?\s*(?:小节|节)", clean(text))
    return ranges(match[1]) if match else ranges(text)


def week_ranges(text: str, week_count: int) -> tuple[list[tuple[int, int]], str, list[str]]:
    text = clean(text)
    text = re.sub(r"[\[(]\s*周\s*[\])]", "周", text)
    odd = bool(re.search(r"单周|周\s*\(?\s*单|\(单\)", text)) or text.strip() == "单"
    even = bool(re.search(r"双周|周\s*\(?\s*双|\(双\)", text)) or text.strip() == "双"
    pattern = "odd" if odd else "even" if even else "all"
    if odd and even:
        return [], "all", ["同时出现单周和双周，请拆分并核对"]
    matches = re.findall(r"(\d{1,2}(?:\s*[-~～—–至,、]\s*\d{1,2})*)\s*周", text)
    result = [pair for value in matches for pair in ranges(value)]
    if not result:
        stripped = re.sub(r"周次\s*[:：]?|[()单双周第]", "", text).strip()
        result = ranges(stripped)
    if result:
        return sorted(set(result)), pattern, []
    return [(1, week_count)], pattern, ["未识别到明确周次，暂按全学期填写，请核对"]


def _header(value: str) -> str:
    return re.sub(r"[\s:：()（）]", "", clean(value))


ALIASES = {
    "title": {"课程名称", "课程名", "课程", "教学科目"},
    "weekday": {"星期", "上课星期", "周几"},
    "period": {"节次", "小节", "上课节次", "上课时间"},
    "start_period": {"开始小节", "开始节次", "起始节次"},
    "end_period": {"结束小节", "结束节次"},
    "weeks": {"周次", "上课周次", "教学周", "上课周"},
    "start_week": {"开始周次", "起始周次"}, "end_week": {"结束周次"},
    "teacher": {"教师", "任课教师", "授课教师"},
    "room": {"教室", "上课地点", "地点", "上课教室"},
    "pattern": {"单双周", "上课频率"},
}


def _pdf_grids(data: bytes) -> tuple[list[Grid], list[str]]:
    import pdfplumber
    grids, warnings, scan_pages = [], [], []
    try:
        with pdfplumber.open(io.BytesIO(data)) as document:
            if len(document.pages) > 15:
                raise HTTPException(422, "课表 PDF 最多支持 15 页，请只保留课表页")
            total_chars = 0
            for page_number, page in enumerate(document.pages, 1):
                total_chars += len(page.chars)
                if total_chars > 80000 or len(page.edges) > 12000:
                    raise HTTPException(422, "PDF 内容过于复杂，请只保留课表页后重试")
                text = page.extract_text(layout=False) or ""
                if not page.chars or (page.images and (len(page.chars) < 20 or not re.search(r"(?:周|星期)[一二三四五六日天1-7]", text))):
                    scan_pages.append(page_number - 1)
                    page.close()
                    continue
                tables = page.find_tables()
                if not tables:
                    tables = page.find_tables({"vertical_strategy": "text", "horizontal_strategy": "text",
                        "min_words_vertical": 2, "min_words_horizontal": 1})
                for number, table in enumerate(tables, 1):
                    rows = [[clean(cell) for cell in row] for row in table.extract()]
                    if len(rows) > 300 or any(len(row) > 40 for row in rows):
                        raise HTTPException(422, "PDF 表格过大，请只保留课表区域")
                    spans = {}
                    tops = [row.bbox[1] for row in table.rows]
                    for row_index, row in enumerate(table.rows):
                        for col, cell in enumerate(row.cells):
                            if cell:
                                spans[(row_index, col)] = sum(top >= cell[1] - 1 and top < cell[3] - 1 for top in tops)
                    grids.append(Grid(f"第{page_number}页·表{number}", rows, spans))
                # 无边框 PDF 的逐行课程列表：课程名称 周一 第1-3节 第1-16周。
                free_rows = [[line] for line in text.splitlines() if re.search(r"(?:周|星期)[一二三四五六日天1-7]", line) and period_ranges(line)]
                if not tables and free_rows:
                    grids.append(Grid(f"第{page_number}页·文字列表", free_rows))
                page.close()
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "PDF 无法读取，请确认文件完整、未加密，并从教务系统重新导出") from exc
    if scan_pages:
        from .ocr import scanned_grids
        grids.extend(scanned_grids(data, scan_pages))
        warnings.append(f"第 {', '.join(str(index + 1) for index in scan_pages)} 页已使用本地 OCR 识别。扫描识别可能有误，请逐项核对课程名、星期、节次和周次后确认导入。")
    if not grids:
        raise HTTPException(422, "未找到可识别的课表，请使用清晰扫描件或教务系统直接导出的 PDF")
    return grids, warnings


def read_grids(filename: str, data: bytes) -> tuple[list[Grid], list[str]]:
    if not data:
        raise HTTPException(422, "文件为空")
    if len(data) > MAX_FILE_BYTES:
        raise HTTPException(413, "课表文件不能超过 8 MB")
    if filename.lower().endswith(".xls"):
        if not data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
            raise HTTPException(422, "文件内容不是有效的 .xls Excel，请从教务系统重新导出")
        from .excel import xls_grids
        return xls_grids(data)
    if filename.lower().endswith(".pdf"):
        if not data.startswith(b"%PDF-"):
            raise HTTPException(422, "文件内容不是有效的 PDF")
        return _pdf_grids(data)
    if not filename.lower().endswith(".csv"):
        raise HTTPException(422, "请选择 PDF、XLS 课表或 CSV 课程清单")
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(422, "无法读取 CSV 编码，请另存为 UTF-8 后上传")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        rows = []
        for row in csv.reader(io.StringIO(text), dialect):
            if len(rows) >= 1000 or len(row) > 40:
                raise HTTPException(422, "CSV 内容过多，请只保留课表数据")
            rows.append([clean(value) for value in row])
        return [Grid("课程清单", rows)], []
    except (csv.Error, ValueError) as exc:
        raise HTTPException(422, "CSV 格式无法识别，请使用标准课程清单") from exc


def _name_and_details(raw: str) -> tuple[str, str, str]:
    lines = [line.strip() for line in clean(raw).splitlines() if line.strip()]
    title = re.sub(r"^(?:课程名称|课程名|课程)\s*[:：]\s*", "", lines[0]) if lines else ""
    teacher = re.search(r"(?:任课教师|授课教师|教师)\s*[:：]\s*([^\n;；]+)", raw)
    if not teacher and len(lines) > 1 and re.search(r"\((?:讲师|副教授|教授|助教|教师|研究员|副研究员)\)", lines[1]):
        teacher_value = lines[1]
    else:
        teacher_value = teacher[1].strip() if teacher else ""
    room = re.search(r"(?:上课地点|教室|地点)\s*[:：]\s*([^\n;；]+)", raw)
    if not room:
        room = next((re.match(r"^((?:[A-Za-zⅠ-Ⅻ]+[-－]?[A-Za-z]?\d{2,5})|(?:[^\n]*[楼馆室]\s*\d{2,5}))$", line) for line in lines if re.match(r"^(?:[A-Za-zⅠ-Ⅻ]+[-－]?[A-Za-z]?\d{2,5}|[^\n]*[楼馆室]\s*\d{2,5})$", line)), None)
    # 连续文字列表的标题只取星期之前的部分。
    title = re.split(r"(?:星期|周|礼拜)[一二三四五六日天1-7]", title)[0].strip(" ;；")
    return title, teacher_value, room[1].strip() if room else ""


def _block_range(text: str, periods: list[dict]) -> list[tuple[int, int]]:
    if clean(text) == "全天":
        return [(1, min(10, len(periods))) ]
    match = re.search(r"第?([一二三四五六七八九]|\d{1,2})大节", text)
    if not match:
        return period_ranges(text)
    index = int(match[1]) if match[1].isdigit() else "一二三四五六七八九".index(match[1]) + 1
    groups = []
    minute = lambda value: int(value[:2]) * 60 + int(value[3:])
    for i, period in enumerate(periods):
        if i and minute(period["start"]) - minute(periods[i - 1]["end"]) == 5:
            groups[-1] = (groups[-1][0], i + 1)
        else:
            groups.append((i + 1, i + 1))
    return [groups[index - 1]] if 1 <= index <= len(groups) else []


def parse_candidates(grids: list[Grid], semester: dict) -> tuple[list[dict], list[str]]:
    from .reconciliation import reconcile_grids
    reconciled = reconcile_grids(grids, semester)
    if reconciled is not None:
        rows, notes = reconciled
        candidates, warnings = parse_candidates(rows, semester)
        return candidates, notes + warnings
    candidates, warnings = [], []

    def add(raw, source, day, period_pairs, weeks_text="", title=None, room="", teacher=""):
        parsed_title, parsed_teacher, parsed_room = _name_and_details(raw)
        week_pairs, pattern, notes = week_ranges(weeks_text or raw, semester["week_count"])
        if not period_pairs:
            period_pairs = [(0, 0)]
            notes.append("未识别到小节，请填写开始与结束小节")
        for start, end in period_pairs:
            for first, last in week_pairs or [(0, 0)]:
                entry = {"title": (title if title is not None else parsed_title), "teacher": teacher or parsed_teacher,
                    "room": room or parsed_room, "course_id": None, "weekday": day,
                    "start_period": start, "end_period": end, "start_week": first, "end_week": last,
                    "week_pattern": pattern, "color": "teal", "is_all_day": bool(re.search(r"(?:^|\n)全天(?:$|\n)", raw))}
                errors = []
                try:
                    payload = EntryWrite.model_validate(entry)
                    if payload.end_period > len(semester["periods"]) or payload.end_week > semester["week_count"]:
                        errors.append("节次或周次超出当前学期设置")
                except ValidationError:
                    errors.append("课程名称、星期、节次或周次不完整，请核对")
                candidates.append({"source": source, "raw": raw[:3000], "entry": entry, "warnings": list(notes), "errors": errors})
                if len(candidates) > MAX_ENTRIES:
                    raise HTTPException(422, "识别结果超过 300 条，请拆分文件后导入")

    for grid in grids:
        recognized = False
        for header_row, row in enumerate(grid.rows[:40]):
            mapping = {field: col for col, cell in enumerate(row) for field, aliases in ALIASES.items() if _header(cell) in aliases}
            if "title" in mapping and ("weekday" in mapping or "period" in mapping) and ("period" in mapping or "start_period" in mapping):
                for index in range(header_row + 1, len(grid.rows)):
                    values = grid.rows[index]
                    get = lambda key: values[mapping[key]] if key in mapping and mapping[key] < len(values) else ""
                    if not get("title") or _header(get("title")) in ALIASES["title"]:
                        continue
                    period = get("period") or f"{get('start_period')}-{get('end_period') or get('start_period')}"
                    weeks = get("weeks") or (f"{get('start_week')}-{get('end_week')}周" if get("start_week") else "")
                    add("\n".join(values), f"{grid.name}·第{index + 1}行", weekday(get("weekday") or period),
                        period_ranges(period), weeks + get("pattern"), get("title"), get("room"), get("teacher"))
                recognized = True
                break
            day_columns = {col: weekday(cell) for col, cell in enumerate(row) if weekday(cell)}
            if len(day_columns) < 2:
                continue
            first_day = min(day_columns)
            row_periods = {}
            for index in range(header_row + 1, len(grid.rows)):
                labels = grid.rows[index][:first_day]
                # 优先使用最靠近星期列的节次，避免“上午”等合并列。
                pair = next((_block_range(cell, semester["periods"]) for cell in reversed(labels) if _block_range(cell, semester["periods"])), [])
                if pair:
                    row_periods[index] = pair
            for index in range(header_row + 1, len(grid.rows)):
                for col, day in day_columns.items():
                    raw = grid.rows[index][col] if col < len(grid.rows[index]) else ""
                    if not raw or raw in {"无", "—", "-"} or re.fullmatch(r"(?:星期|周)[一二三四五六日天1-7]", raw):
                        continue
                    span = grid.spans.get((index, col), 1)
                    merged = [p for r in range(index, min(index + span, len(grid.rows))) for p in row_periods.get(r, [])]
                    inferred = [(min(p[0] for p in merged), max(p[1] for p in merged))] if merged else []
                    for part in re.split(r"\n\s*\n", raw):
                        if part.strip():
                            add(part, f"{grid.name}·第{index + 1}行第{col + 1}列", day, period_ranges(part) or inferred)
            recognized = True
            break
        if not recognized:
            for index, row in enumerate(grid.rows):
                text = " ".join(row)
                if weekday(text) and period_ranges(text):
                    add(text, f"{grid.name}·第{index + 1}行", weekday(text), period_ranges(text))
                    recognized = True
        if not recognized:
            warnings.append(f"{grid.name}未识别到课程结构，已跳过")
    if not candidates:
        raise HTTPException(422, "未识别到课程。扫描件请确保文字清晰、方向端正且包含星期、节次和课程名称；也可上传文字版 PDF 或课程清单 CSV")
    return candidates, warnings
