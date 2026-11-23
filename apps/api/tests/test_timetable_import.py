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
