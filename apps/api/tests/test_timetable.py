from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base, get_db
from app.core.deps import get_current_user
from app.modules.timetable.controller import router
from app.modules.timetable.service import week_view
from app.shared.models import Course, TimetableEntry, User


@pytest.fixture
def timetable_api():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    with Session(engine) as db:
        db.add_all([User(id="owner", username="owner", password_hash="x"), User(id="other", username="other", password_hash="x")])
        db.flush()
        db.add_all([Course(id="course", owner_id="owner", name="软件测试"), Course(id="other-course", owner_id="other", name="其他课程")])
        db.commit()

    def database():
        with Session(engine) as db:
            yield db

    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides.update({get_db: database, get_current_user: lambda: "owner"})
    with TestClient(app) as client:
        yield client, app, engine
    engine.dispose()


def create_semester(client, **changes):
    payload = {"name": "2026年秋季", "start_date": "2026-08-24", "week_count": 20, **changes}
    response = client.post("/timetable/semesters", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def entry_payload(**changes):
    return {"title": "软件测试", "course_id": "course", "weekday": 3,
            "start_period": 4, "end_period": 5, "start_week": 1, "end_week": 20, **changes}


def test_week_numbers_follow_start_date_and_boundaries(timetable_api):
    client, _, engine = timetable_api
    assert client.get("/timetable/week").json()["semester"] is None
    semester = create_semester(client)
    with Session(engine) as db:
        first = week_view(db, "owner", today=date(2026, 8, 24))
        seventh_day = week_view(db, "owner", today=date(2026, 8, 30))
        second = week_view(db, "owner", today=date(2026, 8, 31))
        fourteenth = week_view(db, "owner", today=date(2026, 11, 23))
        before = week_view(db, "owner", today=date(2026, 8, 23))
        after = week_view(db, "owner", today=date(2027, 2, 1))
    assert (first["week"], seventh_day["week"], second["week"], fourteenth["week"]) == (1, 1, 2, 14)
    assert fourteenth["days"] == [date(2026, 11, day) for day in range(23, 30)]
    assert before["status"] == "before" and before["week"] == 1
    assert after["status"] == "after" and after["week"] == 20
    assert client.get("/timetable/week", params={"semester_id": semester["id"], "week": 21}).status_code == 422


def test_entry_crud_patterns_and_conflicts(timetable_api):
    client, _, _ = timetable_api
    semester = create_semester(client)
    path = f"/timetable/semesters/{semester['id']}/entries"
    response = client.post(path, json=entry_payload(week_pattern="odd"))
    assert response.status_code == 201, response.text
    odd = response.json()
    even = client.post(path, json=entry_payload(title="另一门课", week_pattern="even"))
    assert even.status_code == 201
    assert client.post(path, json=entry_payload()).status_code == 409
    assert len(client.get("/timetable/week", params={"week": 1}).json()["entries"]) == 1
    assert client.get("/timetable/week", params={"week": 2}).json()["entries"][0]["title"] == "另一门课"
    updated = client.put(f"{path}/{odd['id']}", json=entry_payload(week_pattern="odd", room="IV-A304"))
    assert updated.status_code == 200 and updated.json()["room"] == "IV-A304"
    assert client.delete(f"{path}/{odd['id']}").status_code == 204
    assert len(client.get(path).json()) == 1


def test_ownership_applies_to_every_route_and_related_course(timetable_api):
    client, app, _ = timetable_api
    semester = create_semester(client)
    path = f"/timetable/semesters/{semester['id']}"
    entry = client.post(path + "/entries", json=entry_payload()).json()
    assert client.post(path + "/entries", json=entry_payload(course_id="other-course")).status_code == 404
    app.dependency_overrides[get_current_user] = lambda: "other"
    assert client.get("/timetable/semesters").json()["items"] == []
    assert client.get("/timetable/week").json()["semester"] is None
    assert client.get(path + "/entries").status_code == 404
    assert client.get("/timetable/week", params={"semester_id": semester["id"]}).status_code == 404
    assert client.put(path, json={"name": "x", "start_date": "2026-08-24"}).status_code == 404
    assert client.post(path + "/activate").status_code == 404
    assert client.delete(path).status_code == 404
    assert client.post(path + "/entries", json=entry_payload(course_id=None)).status_code == 404
    assert client.put(path + f"/entries/{entry['id']}", json=entry_payload(course_id=None)).status_code == 404
    assert client.delete(path + f"/entries/{entry['id']}").status_code == 404


def test_active_semester_switch_delete_and_existing_schedule_safety(timetable_api):
    client, _, engine = timetable_api
    first = create_semester(client)
    path = f"/timetable/semesters/{first['id']}"
    assert client.post(path + "/entries", json=entry_payload()).status_code == 201
    shorter = client.put(path, json={"name": "短学期", "start_date": "2026-08-24", "week_count": 10})
    assert shorter.status_code == 409
    second = create_semester(client, name="2027年春季", start_date="2027-02-22")
    assert client.get("/timetable/week").json()["semester"]["id"] == second["id"]
    assert client.post(path + "/activate").status_code == 200
    active = [semester for semester in client.get("/timetable/semesters").json()["items"] if semester["is_active"]]
    assert [semester["id"] for semester in active] == [first["id"]]
    assert client.delete(path).status_code == 204
    assert client.get("/timetable/week").json()["semester"]["id"] == second["id"]
    with Session(engine) as db:
        assert list(db.scalars(select(TimetableEntry))) == []


@pytest.mark.parametrize("changes", [
    {"weekday": 0}, {"end_period": 14}, {"end_period": 1}, {"end_week": 21},
    {"start_week": 2, "end_week": 2, "week_pattern": "odd"}, {"title": "   "},
])
def test_invalid_entries_are_rejected(timetable_api, changes):
    client, _, _ = timetable_api
    semester = create_semester(client)
    response = client.post(f"/timetable/semesters/{semester['id']}/entries", json=entry_payload(**changes))
    assert response.status_code == 422


def test_invalid_periods_are_rejected_and_non_monday_anchor_is_supported(timetable_api):
    client, _, engine = timetable_api
    bad = client.post("/timetable/semesters", json={
        "name": "错误时间", "start_date": "2026-08-24",
        "periods": [{"start": "08:50", "end": "08:00"}],
    })
    assert bad.status_code == 422
    create_semester(client, start_date="2026-08-26")
    with Session(engine) as db:
        view = week_view(db, "owner", today=date(2026, 9, 1))
    assert view["week"] == 1
    assert view["days"][0] == date(2026, 8, 26)


def test_course_colors_are_shared_persisted_and_stable_across_weeks(timetable_api):
    client, _, engine = timetable_api
    semester = create_semester(client)
    path = f"/timetable/semesters/{semester['id']}/entries"
    first = client.post(path, json=entry_payload()).json()
    same = client.post(path, json=entry_payload(title="软件测试实验", weekday=4, color="rose")).json()
    alias = client.post(path, json=entry_payload(title=" 软件 测试 ", course_id=None, weekday=5)).json()
    different = client.post(path, json=entry_payload(title="高等数学", course_id=None, weekday=1, week_pattern="even")).json()
    assert first["color"].startswith("#")
    assert first["color"] == same["color"] == alias["color"] != different["color"]
    # 新课程不能改变已有课程的颜色，旧客户端传入的颜色也不能拆散同课程配色。
    updated = client.put(f"{path}/{first['id']}", json=entry_payload(color="amber", room="A101"))
    assert updated.status_code == 200 and updated.json()["color"] == first["color"]
    renamed = client.put(f"{path}/{same['id']}", json=entry_payload(title="软件测试实践", weekday=4))
    assert renamed.status_code == 200 and renamed.json()["color"] == first["color"]
    for week in (1, 2, 14, 15):
        rows = client.get("/timetable/week", params={"week": week}).json()["entries"]
        assert next(row for row in rows if row["id"] == first["id"])["color"] == first["color"]
    with Session(engine) as db:
        stored = {row.id: row.color for row in db.scalars(select(TimetableEntry))}
    assert stored == {row["id"]: row["color"] for row in client.get(path).json()}


def test_legacy_color_collisions_are_resolved_before_week_filtering(timetable_api):
    client, _, engine = timetable_api
    semester = create_semester(client)
    with Session(engine) as db:
        db.add_all([TimetableEntry(semester_id=semester["id"], title=title, weekday=day,
                                  start_period=1, end_period=3, start_week=1, end_week=20,
                                  week_pattern=pattern, color="teal")
                    for title, day, pattern in [("软件工程", 1, "all"), ("软件测试", 2, "even"), ("软件工程", 3, "all")]])
        db.commit()
    weeks = [client.get("/timetable/week", params={"week": week}).json()["entries"] for week in (1, 2)]
    same_color = weeks[0][0]["color"]
    assert all(row["color"] == same_color for rows in weeks for row in rows if row["title"] == "软件工程")
    assert next(row for row in weeks[1] if row["title"] == "软件测试")["color"] != same_color
    original = {row["id"]: row["color"] for row in weeks[1]}
    path = f"/timetable/semesters/{semester['id']}/entries"
    added = client.post(path, json=entry_payload(title="新课程", course_id=None, weekday=4))
    assert added.status_code == 201
    assert all(row["color"] == original[row["id"]] for row in client.get(path).json() if row["id"] in original)


def test_color_palette_extends_without_reusing_colors():
    from types import SimpleNamespace
    from app.modules.timetable.colors import allocate_colors

    entries = [SimpleNamespace(id=str(index), title=f"课程{index}", course_id=None, color="") for index in range(40)]
    colors = allocate_colors(entries)
    assert len(set(colors.values())) == 40
    assert allocate_colors(list(reversed(entries))) == colors
