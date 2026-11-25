import json
from datetime import date, datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from ...core.ownership import user_id_for_username
from ...shared.models import Course, TimetableEntry, TimetableSemester, User
from .schemas import EntryWrite, SemesterWrite, default_periods
from .colors import allocate_colors, normalized_title


def semester_read(semester: TimetableSemester) -> dict:
    return {"id": semester.id, "name": semester.name, "start_date": semester.start_date,
            "week_count": semester.week_count, "periods": json.loads(semester.periods_json),
            "is_active": semester.is_active}


def entry_read(entry: TimetableEntry) -> dict:
    return {"id": entry.id, **{field: getattr(entry, field) for field in EntryWrite.model_fields}}


def owned_semester(db: Session, semester_id: str, username: str, *, lock: bool = False) -> TimetableSemester:
    query = select(TimetableSemester).where(TimetableSemester.id == semester_id,
        TimetableSemester.owner_id == user_id_for_username(db, username))
    if lock:
        query = query.with_for_update()
    semester = db.scalar(query)
    if semester is None:
        raise HTTPException(404, "学期不存在")
    return semester


def list_semesters(db: Session, username: str) -> dict:
    owner = user_id_for_username(db, username)
    rows = db.scalars(select(TimetableSemester).where(TimetableSemester.owner_id == owner)
        .order_by(TimetableSemester.is_active.desc(), TimetableSemester.created_at.desc(), TimetableSemester.id))
    return {"items": [semester_read(row) for row in rows],
            "default_periods": [period.model_dump() for period in default_periods()]}


def save_semester(db: Session, username: str, payload: SemesterWrite, semester_id: str | None = None) -> dict:
    owner = user_id_for_username(db, username)
    # 所有首页学期切换都锁定同一用户行，使并发操作也只有一个当前学期。
    db.scalar(select(User).where(User.id == owner).with_for_update())
    if semester_id:
        semester = owned_semester(db, semester_id, username, lock=True)
        entries = list(db.scalars(select(TimetableEntry).where(TimetableEntry.semester_id == semester.id)))
        if any(entry.end_period > len(payload.periods) or entry.end_week > payload.week_count for entry in entries):
            raise HTTPException(409, "已有排课超出新的节次或学期周数，请先调整排课")
    else:
        db.execute(update(TimetableSemester).where(TimetableSemester.owner_id == owner).values(is_active=False))
        semester = TimetableSemester(owner_id=owner, is_active=True)
        db.add(semester)
    semester.name = payload.name
    semester.start_date = payload.start_date
    semester.week_count = payload.week_count
    semester.periods_json = json.dumps([period.model_dump() for period in payload.periods])
    db.commit()
    db.refresh(semester)
    return semester_read(semester)


def activate_semester(db: Session, semester_id: str, username: str) -> dict:
    owner = user_id_for_username(db, username)
    db.scalar(select(User).where(User.id == owner).with_for_update())
    semester = owned_semester(db, semester_id, username, lock=True)
    db.execute(update(TimetableSemester).where(TimetableSemester.owner_id == owner).values(is_active=False))
    semester.is_active = True
    db.commit()
    return semester_read(semester)


def delete_semester(db: Session, semester_id: str, username: str) -> None:
    owner = user_id_for_username(db, username)
    db.scalar(select(User).where(User.id == owner).with_for_update())
    semester = owned_semester(db, semester_id, username, lock=True)
    was_active = semester.is_active
    db.delete(semester)
    db.flush()
    if was_active:
        replacement = db.scalar(select(TimetableSemester).where(TimetableSemester.owner_id == owner)
            .order_by(TimetableSemester.created_at.desc(), TimetableSemester.id))
        if replacement:
            replacement.is_active = True
    db.commit()


def list_entries(db: Session, semester_id: str, username: str) -> list[dict]:
    owned_semester(db, semester_id, username)
    entries = list(db.scalars(select(TimetableEntry)
        .where(TimetableEntry.semester_id == semester_id)
        .order_by(TimetableEntry.weekday, TimetableEntry.start_period, TimetableEntry.id)))
    colors = allocate_colors(entries)
    return [{**entry_read(entry), "color": colors[entry.id]} for entry in entries]


def save_entry(db: Session, semester_id: str, username: str, payload: EntryWrite, entry_id: str | None = None, *, commit: bool = True) -> dict:
    semester = owned_semester(db, semester_id, username, lock=True)
    if payload.end_period > len(json.loads(semester.periods_json)) or payload.end_week > semester.week_count:
        raise HTTPException(422, "排课超出已设置的节次或学期周数")
    if payload.course_id:
        course = db.scalar(select(Course).where(Course.id == payload.course_id, Course.owner_id == semester.owner_id))
        if course is None:
            raise HTTPException(404, "关联课程不存在")
    entry = None
    if entry_id:
        entry = db.scalar(select(TimetableEntry).where(TimetableEntry.id == entry_id, TimetableEntry.semester_id == semester.id))
        if entry is None:
            raise HTTPException(404, "排课不存在")
    overlapping = db.scalars(select(TimetableEntry).where(TimetableEntry.semester_id == semester.id,
        TimetableEntry.weekday == payload.weekday, TimetableEntry.start_period <= payload.end_period,
        TimetableEntry.end_period >= payload.start_period))
    for other in overlapping:
        if other.id != entry_id and not (payload.is_all_day and other.is_all_day) and payload.weeks() & EntryWrite.model_validate(entry_read(other)).weeks():
            raise HTTPException(409, f"与「{other.title}」的上课时间冲突，请调整节次或周次")
    # 先固化旧课表的兼容配色，新增课程不能抢走原来已展示的颜色。
    existing_entries = list(db.scalars(select(TimetableEntry).where(TimetableEntry.semester_id == semester.id)))
    existing_colors = allocate_colors(existing_entries)
    for item in existing_entries:
        item.color = existing_colors[item.id]
    identity_changed = entry is None or entry.course_id != payload.course_id or (
        not payload.course_id and normalized_title(entry.title) != normalized_title(payload.title))
    if entry is None:
        entry = TimetableEntry(semester_id=semester.id)
        db.add(entry)
    for key, value in payload.model_dump().items():
        if key != "color":
            setattr(entry, key, value)
    if identity_changed:
        entry.color = ""
    db.flush()
    all_entries = list(db.scalars(select(TimetableEntry).where(TimetableEntry.semester_id == semester.id)))
    colors = allocate_colors(all_entries)
    for item in all_entries:
        item.color = colors[item.id]
    if commit:
        db.commit()
        db.refresh(entry)
    else:
        db.flush()
    return entry_read(entry)


def _entry_identity(entry: dict) -> tuple:
    return tuple(entry[field] for field in ("title", "room", "teacher", "weekday", "start_period", "end_period", "start_week", "end_week", "week_pattern")) + (bool(entry.get("is_all_day", False)),)


def preview_import(db: Session, semester_id: str, username: str, filename: str, content: bytes) -> dict:
    from .importing import parse_candidates, read_grids
    semester = owned_semester(db, semester_id, username)
    grids, file_warnings = read_grids(filename, content)
    candidates, warnings = parse_candidates(grids, semester_read(semester))
    existing = list_entries(db, semester_id, username)
    for candidate in candidates:
        value = candidate["entry"]
        candidate["status"] = "incomplete" if candidate["errors"] else "ready"
        if candidate["errors"]:
            continue
        payload = EntryWrite.model_validate(value)
        for other in existing:
            if _entry_identity(value) == _entry_identity(other):
                candidate["status"] = "duplicate"
                candidate["warnings"].append("该排课已存在，再次导入会自动跳过")
                break
            if not (payload.is_all_day and other.get("is_all_day")) and other["weekday"] == payload.weekday and other["start_period"] <= payload.end_period and other["end_period"] >= payload.start_period and payload.weeks() & EntryWrite.model_validate(other).weeks():
                candidate["status"] = "conflict"
                candidate["errors"].append(f"与已有排课「{other['title']}」时间冲突")
                break
    return {"filename": filename, "candidates": candidates, "warnings": file_warnings + warnings,
            "message": "请核对识别结果；预览不会保存课程，确认导入后才写入课表。"}


def import_entries(db: Session, semester_id: str, username: str, entries: list[EntryWrite]) -> dict:
    owned_semester(db, semester_id, username, lock=True)
    identities = {_entry_identity(item) for item in list_entries(db, semester_id, username)}
    added, skipped = 0, 0
    try:
        for index, payload in enumerate(entries, 1):
            identity = _entry_identity(payload.model_dump())
            if identity in identities:
                skipped += 1
                continue
            try:
                save_entry(db, semester_id, username, payload, commit=False)
            except HTTPException as exc:
                raise HTTPException(exc.status_code, f"第 {index} 条「{payload.title}」：{exc.detail}；本次未导入任何课程") from exc
            identities.add(identity)
            added += 1
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"added": added, "skipped": skipped}


def delete_entry(db: Session, semester_id: str, entry_id: str, username: str) -> None:
    owned_semester(db, semester_id, username, lock=True)
    entry = db.scalar(select(TimetableEntry).where(TimetableEntry.semester_id == semester_id, TimetableEntry.id == entry_id))
    if entry is None:
        raise HTTPException(404, "排课不存在")
    db.delete(entry)
    db.commit()


def week_view(db: Session, username: str, semester_id: str | None = None, week: int | None = None, *, today: date | None = None) -> dict:
    today = today or datetime.now(timezone(timedelta(hours=8))).date()
    if semester_id:
        semester = owned_semester(db, semester_id, username)
    else:
        semester = db.scalar(select(TimetableSemester).where(
            TimetableSemester.owner_id == user_id_for_username(db, username), TimetableSemester.is_active.is_(True)))
    if semester is None:
        return {"semester": None, "today": today, "days": [], "entries": [], "week": None,
                "current_week": None, "status": "unset"}
    current_week = (today - semester.start_date).days // 7 + 1
    displayed_week = week if week is not None else max(1, min(current_week, semester.week_count))
    if not 1 <= displayed_week <= semester.week_count:
        raise HTTPException(422, "周次超出学期范围")
    start = semester.start_date + timedelta(weeks=displayed_week - 1)
    days = [start + timedelta(days=index) for index in range(7)]
    entries = list_entries(db, semester.id, username)
    entries = [entry for entry in entries if displayed_week in EntryWrite.model_validate(entry).weeks()]
    status = "before" if current_week < 1 else "after" if current_week > semester.week_count else "current"
    return {"semester": semester_read(semester), "today": today, "days": days, "entries": entries,
            "week": displayed_week, "current_week": current_week, "status": status}
