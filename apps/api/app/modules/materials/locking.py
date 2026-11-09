"""文件与索引发布同回收站保持课程→资料的锁顺序。"""
from fastapi import HTTPException
from sqlalchemy import select

from ...core.ownership import user_id_for_username
from ...shared.models import Course, CourseMaterial


def lock_material(db, course_id, material_id, username=None):
    query = select(Course).where(Course.id == course_id)
    if username is not None:
        query = query.where(Course.owner_id == user_id_for_username(db, username))
    course = db.scalar(query.with_for_update().execution_options(populate_existing=True))
    if course is None:
        raise HTTPException(404, "资料不存在")
    material = db.scalar(select(CourseMaterial).where(CourseMaterial.id == material_id,
        CourseMaterial.course_id == course_id).with_for_update().execution_options(populate_existing=True))
    if material is None:
        raise HTTPException(404, "资料不存在")
    return material, course
