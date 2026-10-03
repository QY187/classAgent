"""独立的到期清理服务，不依赖用户打开回收站页面。"""
import logging
from datetime import timedelta
from sqlalchemy import select
from sqlalchemy.orm import Session
from ...shared.models import Course, CourseMaterial, Lesson, PendingFileDeletion, User, now_utc
from .file_cleanup import clean_pending_files
from .mapper import owned_item
from .purge import purge_locked_item
from .retention import RETENTION_DAYS, is_expired

logger = logging.getLogger(__name__)


def remove_expired_items(db: Session, now=None) -> dict:
    cutoff_time = now or now_utc()
    removed = 0
    failed = 0
    # 父级先处理；独立删除的子项即使隐藏在父级中，也按自己的期限清理。
    for kind, model in (("course", Course), ("lesson", Lesson), ("material", CourseMaterial)):
        table = model.__table__
        course = Course.__table__
        users = User.__table__
        source = table.join(users, table.c.owner_id == users.c.id) if kind == "course" else table.join(course, table.c.course_id == course.c.id).join(users, course.c.owner_id == users.c.id)
        candidates = list(db.execute(select(table.c.id, users.c.username).select_from(source).where(
            table.c.deleted_at <= cutoff_time - timedelta(days=RETENTION_DAYS))))
        db.rollback()
        for identity, username in candidates:
            try:
                item, parent, _ = owned_item(db, kind, identity, username)
                # 获取锁后重新核对，避免已恢复或再次删除的对象被旧任务删除。
                if item.deleted_at is None or not is_expired(item.deleted_at, cutoff_time):
                    db.rollback()
                    continue
                purge_locked_item(db, kind, item, parent)
                removed += 1
            except Exception:
                db.rollback()
                failed += 1
                logger.warning("回收站到期项目清理失败，将在下一轮重试", exc_info=True)
    # 即使本轮没有新到期对象，也重试之前失败的文件清理。
    usernames = list(db.scalars(select(User.username).join(PendingFileDeletion, PendingFileDeletion.user_id == User.id).distinct()))
    cleaned = 0
    for username in usernames:
        cleaned += clean_pending_files(db, username)["cleaned"]
    return {"removed": removed, "failed": failed, "cleaned": cleaned}
