import io

import pytest
from fastapi import HTTPException
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Table, TableStyle

from app.core.deps import get_current_user
from app.modules.timetable.importing import Grid, MAX_FILE_BYTES, parse_candidates, read_grids
from app.modules.timetable.schemas import SemesterWrite
from test_timetable import create_semester, entry_payload, timetable_api


def make_pdf(matrix=True):
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    style = ParagraphStyle("cell", fontName="STSong-Light", fontSize=9, leading=12)
    if matrix:
        rows = [["节次", "星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]]
        rows += [[f"第{i}小节", "", "", "", "", "", "", ""] for i in range(1, 14)]
        rows[1][1] = "软件工程<br/>第1-16周<br/>教师:张三<br/>教室:IV-A504"
        rows[4][3] = "单片机原理<br/>第1-8,10-16周(双)<br/>第4-5节<br/>教室:IV-A304"
        spans = [("SPAN", (1, 1), (1, 3)), ("SPAN", (3, 4), (3, 5))]
        widths = [62] + [95] * 7
    else:
        rows = [["课程名称", "星期", "节次", "周次", "教师", "教室"],
                ["导入验证课程（示例）", "周四", "6-7", "1-20周", "示例教师", "示例教室"]]
        spans = []
        widths = [180, 65, 65, 90, 100, 100]
    content = [[Paragraph(text, style) for text in row] for row in rows]
    table = Table(content, colWidths=widths, rowHeights=[32] * len(rows))
    table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), .5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), *spans]))
    stream = io.BytesIO()
    SimpleDocTemplate(stream, pagesize=landscape(A4), leftMargin=25, rightMargin=25, topMargin=20, bottomMargin=20).build([table])
    return stream.getvalue()


def preview(client, semester, data, name="课表.pdf"):
    return client.post(f"/timetable/semesters/{semester['id']}/import/preview", files={"file": (name, data)})


def test_pdf_week_grid_merged_periods_disjoint_weeks_and_parity(timetable_api):
    client, _, _ = timetable_api
    semester = create_semester(client)
    response = preview(client, semester, make_pdf())
    assert response.status_code == 200, response.text
    entries = [row["entry"] for row in response.json()["candidates"]]
    first = next(item for item in entries if item["title"] == "软件工程")
    assert (first["weekday"], first["start_period"], first["end_period"]) == (1, 1, 3)
    assert (first["room"], first["teacher"]) == ("IV-A504", "张三")
    second = [item for item in entries if item["title"] == "单片机原理"]
    assert [(item["start_week"], item["end_week"]) for item in second] == [(1, 8), (10, 16)]
    assert all(item["weekday"] == 3 and item["week_pattern"] == "even" for item in second)
    assert client.get(f"/timetable/semesters/{semester['id']}/entries").json() == []


def test_pdf_list_preview_then_confirm_and_repeat_is_idempotent(timetable_api):
    client, _, _ = timetable_api
    semester = create_semester(client)
    response = preview(client, semester, make_pdf(matrix=False))
    assert response.status_code == 200, response.text
    entries = [row["entry"] for row in response.json()["candidates"]]
    assert len(entries) == 1 and entries[0]["title"] == "导入验证课程(示例)"
    path = f"/timetable/semesters/{semester['id']}/import"
    assert client.post(path, json={"entries": entries}).json() == {"added": 1, "skipped": 0}
    assert client.post(path, json={"entries": entries}).json() == {"added": 0, "skipped": 1}
    again = preview(client, semester, make_pdf(matrix=False)).json()["candidates"]
    assert [row["status"] for row in again] == ["duplicate"]


def test_batch_failure_rolls_back_earlier_entries_and_preserves_existing(timetable_api):
    client, _, _ = timetable_api
    semester = create_semester(client)
    base = f"/timetable/semesters/{semester['id']}"
    assert client.post(base + "/entries", json=entry_payload()).status_code == 201
    result = client.post(base + "/import", json={"entries": [entry_payload(title="先处理的一条", weekday=2), entry_payload(title="冲突的一条")]})
    assert result.status_code == 409 and "本次未导入任何课程" in result.text
    assert [entry["title"] for entry in client.get(base + "/entries").json()] == ["软件测试"]


def test_import_ownership_and_related_course_checks(timetable_api):
    client, app, _ = timetable_api
    semester = create_semester(client)
    path = f"/timetable/semesters/{semester['id']}/import"
    assert client.post(path, json={"entries": [entry_payload(course_id="other-course")]}).status_code == 404
    app.dependency_overrides[get_current_user] = lambda: "other"
    assert preview(client, semester, b"bad").status_code == 404
    assert client.post(path, json={"entries": [entry_payload(course_id=None)]}).status_code == 404
    app.dependency_overrides.clear()
    assert preview(client, semester, b"bad").status_code == 401


def test_csv_preserves_title_words_and_warns_missing_weeks(timetable_api):
    client, _, _ = timetable_api
    semester = create_semester(client)
    data = "课程名称,星期,节次,周次,教师,教室\n单片机原理,周五,8-10,,李老师,A101\n".encode("utf-8-sig")
    response = preview(client, semester, data, "课程.csv")
    assert response.status_code == 200, response.text
    row = response.json()["candidates"][0]
    assert row["entry"]["week_pattern"] == "all"
    assert row["entry"]["start_week"] == 1 and row["entry"]["end_week"] == 20
    assert any("全学期" in warning for warning in row["warnings"])


def test_incomplete_rows_are_returned_for_manual_correction():
    semester = SemesterWrite(name="秋季", start_date="2026-08-24").model_dump(mode="json")
    candidates, _ = parse_candidates([Grid("清单", [["课程名称", "星期", "节次"], ["待核对课程", "未知", "未知"]])], semester)
    assert candidates[0]["entry"]["weekday"] == 0
    assert candidates[0]["errors"]


@pytest.mark.parametrize("name,data,status", [
    ("image.png", b"data", 422), ("fake.pdf", b"not a PDF", 422),
    ("empty.pdf", b"", 422), ("huge.pdf", b"x" * (MAX_FILE_BYTES + 1), 413),
])
def test_invalid_uploads_are_rejected(name, data, status):
    with pytest.raises(HTTPException) as error:
        read_grids(name, data)
    assert error.value.status_code == status


def test_image_only_pdf_has_actionable_error(timetable_api):
    from reportlab.pdfgen.canvas import Canvas
    stream = io.BytesIO()
    canvas = Canvas(stream); canvas.rect(10, 10, 100, 100); canvas.showPage(); canvas.save()
    client, _, _ = timetable_api
    response = preview(client, create_semester(client), stream.getvalue())
    assert response.status_code == 422 and "扫描" in response.text


def test_import_rejects_out_of_bounds_and_empty_batches(timetable_api):
    client, _, _ = timetable_api
    semester = create_semester(client)
    path = f"/timetable/semesters/{semester['id']}/import"
    assert client.post(path, json={"entries": []}).status_code == 422
    assert client.post(path, json={"entries": [entry_payload(end_period=14)]}).status_code == 422
    assert client.get(f"/timetable/semesters/{semester['id']}/entries").json() == []


def make_scanned_pdf(matrix=True):
    import pypdfium2 as pdfium
    from reportlab.pdfgen.canvas import Canvas
    from reportlab.lib.utils import ImageReader

    stream = io.BytesIO()
    with pdfium.PdfDocument(make_pdf(matrix)) as source:
        page = source[0]
        bitmap = page.render(scale=3)
        try:
            image = bitmap.to_pil()
            canvas = Canvas(stream, pagesize=page.get_size())
            canvas.drawImage(ImageReader(image), 0, 0, width=page.get_width(), height=page.get_height())
            canvas.showPage(); canvas.save()
        finally:
            bitmap.close(); page.close()
    return stream.getvalue()


@pytest.mark.parametrize("matrix", [True, False])
def test_real_ocr_scanned_pdf_preview_requires_confirmation(timetable_api, matrix):
    client, _, _ = timetable_api
    semester = create_semester(client)
    response = preview(client, semester, make_scanned_pdf(matrix))
    assert response.status_code == 200, response.text
    result = response.json()
    assert any("OCR" in warning for warning in result["warnings"])
    entries = [row["entry"] for row in result["candidates"]]
    if matrix:
        first = next(item for item in entries if item["title"] == "软件工程")
        assert (first["weekday"], first["start_period"], first["end_period"]) == (1, 1, 3)
    else:
        assert entries[0]["title"].startswith("导入验证课程")
        assert (entries[0]["weekday"], entries[0]["start_period"], entries[0]["end_period"]) == (4, 6, 7)
    assert client.get(f"/timetable/semesters/{semester['id']}/entries").json() == []
    assert client.post(f"/timetable/semesters/{semester['id']}/import", json={"entries": entries}).status_code == 200


def test_ocr_limits_and_concurrent_request_have_actionable_errors():
    from app.modules.timetable import ocr
    with pytest.raises(HTTPException) as error:
        ocr.scanned_grids(b"", list(range(6)))
    assert error.value.status_code == 422
    with ocr._lock:
        with pytest.raises(HTTPException) as error:
            ocr.scanned_grids(b"", [0])
    assert error.value.status_code == 429


def test_text_pdf_does_not_call_ocr(monkeypatch):
    from app.modules.timetable import ocr
    def unexpected(*_args):
        raise AssertionError("文字 PDF 不应走 OCR")
    monkeypatch.setattr(ocr, "scanned_grids", unexpected)
    assert read_grids("文字课表.pdf", make_pdf())[0]


def test_ocr_process_timeout_and_crash_are_isolated(monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from app.modules.timetable import ocr
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 120)
    monkeypatch.setattr(ocr.subprocess, "run", timeout)
    with pytest.raises(HTTPException) as error:
        ocr.scanned_grids(b"test", [0])
    assert "120" in error.value.detail and not ocr._lock.locked()
    monkeypatch.setattr(ocr.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1, stdout=b""))
    with pytest.raises(HTTPException) as error:
        ocr.scanned_grids(b"test", [0])
    assert "进程异常" in error.value.detail and not ocr._lock.locked()


def test_mixed_pdf_extracts_text_and_dispatches_only_scanned_page(monkeypatch):
    from pypdf import PdfReader, PdfWriter
    from app.modules.timetable import ocr
    writer = PdfWriter()
    writer.add_page(PdfReader(io.BytesIO(make_pdf())).pages[0])
    writer.add_page(PdfReader(io.BytesIO(make_scanned_pdf(False))).pages[0])
    stream = io.BytesIO(); writer.write(stream)
    called = []
    def recognize(data, indexes):
        called.extend(indexes)
        return [Grid("第2页·OCR", [["软件测试 周二 第4-5节 第1-16周"]])]
    monkeypatch.setattr(ocr, "scanned_grids", recognize)
    grids, warnings = read_grids("混合课表.pdf", stream.getvalue())
    assert called == [1] and len(grids) >= 2
    assert any("OCR" in warning for warning in warnings)


@pytest.mark.parametrize("text,expected", [
    ("5,7-20(周)", [(5, 5), (7, 20)]),
    ("10-13（周）", [(10, 13)]),
    ("第1-8,10-16周(双)", [(1, 8), (10, 16)]),
])
def test_parenthesized_teaching_weeks(text, expected):
    from app.modules.timetable.importing import week_ranges
    weeks, _pattern, warnings = week_ranges(text, 20)
    assert weeks == expected and warnings == []


def test_combined_week_grid_and_detail_list_preserve_names_weeks_and_partial_periods():
    semester = SemesterWrite(name="测试学期", start_date="2026-08-24").model_dump(mode="json")
    rows = [
        ["", "星期一", "星期二", "星期三"],
        ["第一大节", "课程甲\n测试教师甲\n10-13(周)\nA101\n--------\n----\n课程乙\n测试教师乙\n5,7-8(周)\nA102", "", "数理\n基础(I)\nB\n测试教师丙\n5,7-20(周)\nB201"],
        ["课程名称", "教师", "时间", "地点"],
        ["课程甲", "测试教师甲", "星期一(02-03小\n节)", "A101"],
        ["课程乙", "测试教师乙", "星期一(01-03小节)", "A102"],
        ["数理基础(I)", "测试教师丙", "星期三(01-02小节)", "B201"],
    ]
    candidates, warnings = parse_candidates([Grid("网页打印型课表", rows)], semester)
    assert len(candidates) == 5
    assert all(not row["warnings"] and not row["errors"] for row in candidates)
    first = next(row["entry"] for row in candidates if row["entry"]["title"] == "课程甲")
    assert (first["start_period"], first["end_period"], first["start_week"], first["end_week"]) == (2, 3, 10, 13)
    math = [row["entry"] for row in candidates if row["entry"]["title"] == "数理基础(I)"]
    assert all((row["weekday"], row["start_period"], row["end_period"], row["teacher"]) == (3, 1, 2, "测试教师丙") for row in math)
    assert [(row["start_week"], row["end_week"]) for row in math] == [(5, 5), (7, 20)]
    assert any("交叉核对" in warning for warning in warnings)


def test_excel_week_grid_keeps_titles_teachers_and_square_bracket_weeks():
    semester = SemesterWrite(name="测试学期", start_date="2026-08-24").model_dump(mode="json")
    rows = [["", "星期一", "星期二"],
            ["第二大节", "课程甲\n测试教师(副教授)\n4-6,8-10[周]\nA101\n\n课程乙\n另一教师(讲师)\n13-16[周]\nA102", ""]]
    candidates, _ = parse_candidates([Grid("Excel", rows)], semester)
    assert len(candidates) == 3
    first = candidates[0]["entry"]
    assert (first["start_period"], first["end_period"], first["start_week"], first["end_week"], first["teacher"]) == (4, 5, 4, 6, "测试教师(副教授)")
    assert all(not row["errors"] and not row["warnings"] for row in candidates)


def test_excel_whole_week_activities_are_displayed_without_fake_daily_entries(monkeypatch):
    import xlrd
    from types import SimpleNamespace
    from app.modules.timetable.excel import xls_grids
    rows = [["", "星期一", "星期二", "", ""],
            ["第一大节", "课程甲\n测试教师(讲师)\n1-16[周]\nA101", "", "", ""],
            ["", "毕业实习", "全周", "1-3周(50学时)", "测试教师"]]
    sheet = SimpleNamespace(name="课表", nrows=3, ncols=5, merged_cells=[], cell_value=lambda r,c: rows[r][c])
    book = SimpleNamespace(nsheets=1, sheets=lambda: [sheet], release_resources=lambda: None)
    monkeypatch.setattr(xlrd, "open_workbook", lambda **kwargs: book)
    grids, warnings = xls_grids(b"test")
    candidates, _ = parse_candidates(grids, SemesterWrite(name="学期", start_date="2026-08-24").model_dump(mode="json"))
    assert len(candidates) == 3 and candidates[0]["entry"]["title"] == "课程甲"
    activities = [row["entry"] for row in candidates if row["entry"]["is_all_day"]]
    assert {row["weekday"] for row in activities} == {1, 2}
    assert all(row["start_period"] == 1 and row["end_period"] == 10 for row in activities)
    assert len(warnings) == 1 and "毕业实习" in warnings[0] and "1-3周" in warnings[0]


def test_fake_excel_has_actionable_error():
    with pytest.raises(HTTPException) as error:
        read_grids("课表.xls", b"not an Excel")
    assert error.value.status_code == 422 and "xls" in error.value.detail
