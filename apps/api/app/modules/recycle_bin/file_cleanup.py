"""文件清理与内容删除分离；失败后保留队列，可安全重试。"""
import logging
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ...core.ownership import user_id_for_username
from ...infrastructure.storage import delete_file
from ...shared.models import PendingFileDeletion

logger = logging.getLogger(__name__)


def pending_count(db: Session, username: str) -> int:
    owner = user_id_for_username(db, username)
    return db.scalar(select(func.count(PendingFileDeletion.id)).where(PendingFileDeletion.user_id == owner)) or 0


def clean_pending_files(db: Session, username: str) -> dict:
    owner = user_id_for_username(db, username)
    ids = list(db.scalars(select(PendingFileDeletion.id).where(PendingFileDeletion.user_id == owner)
                         .order_by(PendingFileDeletion.created_at).limit(100)))
    cleaned = 0
    for identity in ids:
        pending = db.scalar(select(PendingFileDeletion).where(PendingFileDeletion.id == identity, PendingFileDeletion.user_id == owner)
                            .with_for_update(skip_locked=True))
        if pending is None:
            continue
        try:
            delete_file(pending.object_key)
            db.delete(pending)
            db.commit()
            cleaned += 1
        except Exception:
            # 文件已删、队列提交失败也可重试：存储删除对不存在的文件幂等。
            db.rollback()
            logger.warning("回收站文件清理失败，保留待清理记录", exc_info=True)
    return {"cleaned": cleaned, "pending": pending_count(db, username)}
