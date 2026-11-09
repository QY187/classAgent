"""真实存储/数据库/HTTP 替换与回收流程，仅模拟向量服务边界。"""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.db import Base, get_db
from app.core.deps import get_current_user
from app.modules.materials.controller import router
from app.modules.materials.content import refresh_material_citation
from app.modules.materials.processing import process_material_content
from app.modules.recycle_bin.file_cleanup import clean_pending_files
from app.modules.recycle_bin.purge import purge_item
from app.modules.recycle_bin.restore import restore_item
from app.modules.recycle_bin.service import move_to_bin
from app.modules.search.mapper import search_all
from app.shared.models import (Course, CourseMaterial, Lesson, MaterialChunk, MaterialProcessing,
                               MaterialReplacement, PendingFileDeletion, User)


@pytest.fixture
def files(tmp_path, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "storage_backend", "local")
    monkeypatch.setattr(settings, "local_storage_path", str(tmp_path / "uploads"))
    engine = create_engine("sqlite:///" + str(tmp_path / "files.db"), connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    root = Path(settings.local_storage_path)
    old = root / "materials/c/old.txt"
    old.parent.mkdir(parents=True)
    old.write_text("旧版二叉树说明。", encoding="utf-8")
    with sessions() as db:
        db.add_all([User(id="u", username="owner", password_hash="x"), User(id="v", username="other", password_hash="x")]); db.flush()
        db.add(Course(id="c", owner_id="u", name="数据结构")); db.flush()
        db.add(Lesson(id="l", course_id="c", title="二叉树", status="completed")); db.flush()
        db.add(CourseMaterial(id="m", course_id="c", lesson_id="l", filename="old.txt", object_key="materials/c/old.txt", content_type="text/plain", size_bytes=old.stat().st_size)); db.flush()
        db.add(MaterialProcessing(material_id="m", generation="old", active_version="old", status="ready")); db.flush()
        db.add(MaterialChunk(id="old-chunk", material_id="m", version="old", position=0, locator_type="paragraph", locator_number=1, content="旧版二叉树说明。", embedding=[0.1] * 1536)); db.commit()
    app = FastAPI(); app.include_router(router)
    def database():
        with sessions() as db:
            yield db
    app.dependency_overrides[get_db] = database
    app.dependency_overrides[get_current_user] = lambda: "owner"
    with TestClient(app) as client:
        with patch("app.modules.materials.processing.dispatch_one", return_value=False), \
             patch("app.modules.materials.replacement.dispatch_one", return_value=False):
            yield SimpleNamespace(client=client, sessions=sessions, root=root, old=old, app=app)
    engine.dispose()


def replace(files, text="新版叶子结点说明。", filename="new.txt"):
    return files.client.put("/courses/c/materials/m/file", files={"file": (filename, text.encode("utf-8"), "text/plain")})


def run(files, generation=None, effect=None):
    with files.sessions() as db:
        generation = generation or db.get(MaterialProcessing, "m").generation
        db.rollback()
        with patch("app.modules.materials.processing.embed_texts", side_effect=effect or (lambda texts: [[0.2] * 1536 for _ in texts])):
            return process_material_content(db, "m", generation)


def original(files):
    return files.client.get("/courses/c/materials/m/file").content.decode("utf-8")


def old_citation():
    return {"source_type": "material", "course_id": "c", "material_id": "m", "chunk_id": "old-chunk", "version": "old", "snippet": "旧版二叉树"}


def test_replacement_stages_then_atomically_switches_file_vectors_and_citations(files):
    response = replace(files)
    assert response.status_code == 202, response.text
    data = response.json()
    assert data["id"] == "m" and data["lesson_id"] == "l" and data["filename"] == "old.txt"
    assert data["replacement_filename"] == "new.txt" and data["indexed"] and data["processing_status"] == "queued"
    assert original(files) == "旧版二叉树说明。"
    with files.sessions() as db:
        assert search_all(db, "新版", "owner")["materials"] == []
        assert refresh_material_citation(db, old_citation(), "owner")["source_status"] == "current"
    assert run(files) == 1
    assert original(files) == "新版叶子结点说明。"
    with files.sessions() as db:
        material = db.get(CourseMaterial, "m")
        assert material.filename == "new.txt" and material.lesson_id == "l"
        assert db.get(MaterialReplacement, "m") is None
        assert len(list(db.scalars(select(CourseMaterial)))) == 1
        chunks = list(db.scalars(select(MaterialChunk)))
        assert len(chunks) == 1 and chunks[0].version != "old" and chunks[0].embedding[0] == pytest.approx(0.2)
        assert search_all(db, "旧版", "owner")["materials"] == []
        assert len(search_all(db, "新版", "owner")["materials"]) == 1
        assert refresh_material_citation(db, old_citation(), "owner")["source_status"] == "changed"
        assert clean_pending_files(db, "owner") == {"cleaned": 1, "pending": 0}
        assert not files.old.exists() and (files.root / material.object_key).exists()


def test_failed_replacement_preserves_original_and_retry_uses_pending_file(files):
    with files.sessions() as db:
        db.get(CourseMaterial, "m").filename = "old.pdf"; db.commit()
    assert replace(files).status_code == 202
    def fail(_):
        raise RuntimeError("private-provider-error")
    assert run(files, effect=fail) == 0
    assert original(files) == "旧版二叉树说明。"
    state = files.client.get("/courses/c/materials").json()[0]
    assert state["filename"] == "old.pdf" and state["processing_status"] == "failed" and state["indexed"]
    assert "private" not in state["processing_error"] and state["replacement_filename"] == "new.txt"
    with files.sessions() as db:
        assert db.scalar(select(PendingFileDeletion)) is None
        assert refresh_material_citation(db, old_citation(), "owner")["source_status"] == "current"
    assert files.client.post("/courses/c/materials/m/index").status_code == 202
    assert run(files) == 1
    assert original(files) == "新版叶子结点说明。"


def test_superseded_worker_cannot_publish_an_older_replacement(files):
    assert replace(files, "第二版内容。").status_code == 202
    with files.sessions() as db:
        abandoned = db.get(MaterialReplacement, "m").object_key
    def newer(texts):
        assert replace(files, "第三版内容。", "latest.md").status_code == 202
        return [[0.2] * 1536 for _ in texts]
    assert run(files, effect=newer) == 0
    assert original(files) == "旧版二叉树说明。"
    with files.sessions() as db:
        assert db.get(MaterialReplacement, "m").filename == "latest.md"
        assert db.get(MaterialProcessing, "m").status == "queued"
        assert db.scalar(select(PendingFileDeletion.object_key)) == abandoned
    assert run(files) == 1
    assert original(files) == "第三版内容。"
    with files.sessions() as db:
        assert clean_pending_files(db, "owner")["cleaned"] == 2
        assert (files.root / db.get(CourseMaterial, "m").object_key).exists()


def test_delete_during_embedding_prevents_publish_and_hides_vectors(files):
    assert replace(files).status_code == 202
    def remove(texts):
        assert files.client.delete("/courses/c/materials/m").status_code == 204
        return [[0.2] * 1536 for _ in texts]
    assert run(files, effect=remove) == 0
    assert files.client.get("/courses/c/materials/m/content").status_code == 404
    with files.sessions() as db:
        assert search_all(db, "二叉树", "owner")["materials"] == []
        assert refresh_material_citation(db, old_citation(), "owner")["source_status"] == "unavailable"
        chunks = db.execute(select(MaterialChunk.__table__.c.version)).scalars().all()
        assert chunks == ["old"]
        restore_item(db, "material", "m", "owner")
    assert original(files) == "旧版二叉树说明。"
    assert files.client.post("/courses/c/materials/m/index").status_code == 202
    assert run(files) == 1


@pytest.mark.parametrize("kind,identity", [("material", "m"), ("lesson", "l"), ("course", "c")])
def test_purge_cascades_vectors_and_cleans_current_and_pending_files(files, kind, identity):
    assert replace(files).status_code == 202
    with files.sessions() as db:
        pending_key = db.get(MaterialReplacement, "m").object_key
        move_to_bin(db, kind, identity, "owner")
        assert db.scalar(select(MaterialChunk)) is None
        assert db.scalar(select(MaterialReplacement)) is None
        assert purge_item(db, kind, identity, "owner") == {"cleaned": 2, "pending": 0}
        for model in (CourseMaterial, MaterialChunk, MaterialProcessing, MaterialReplacement):
            assert db.execute(select(model.__table__)).first() is None
    assert not files.old.exists() and not (files.root / pending_key).exists()


@pytest.mark.parametrize("filename,body,code", [("bad.exe", "内容", 400), ("image.png", "内容", 415), ("empty.txt", "", 400)])
def test_invalid_replacement_does_not_change_files_or_vectors(files, filename, body, code):
    assert replace(files, body, filename).status_code == code
    assert original(files) == "旧版二叉树说明。"
    with files.sessions() as db:
        assert db.get(MaterialReplacement, "m") is None
        assert db.get(MaterialProcessing, "m").active_version == "old"
    assert list(files.root.rglob("*.*")) == [files.old]


def test_foreign_user_cannot_replace_or_upload_storage(files):
    files.app.dependency_overrides[get_current_user] = lambda: "other"
    with patch("app.modules.materials.replacement.upload_file") as storage:
        assert replace(files).status_code == 404
        storage.assert_not_called()


def test_replacement_can_index_a_previously_unsupported_file(files):
    with files.sessions() as db:
        db.delete(db.get(MaterialChunk, "old-chunk"))
        db.get(MaterialProcessing, "m").active_version = None
        db.get(MaterialProcessing, "m").status = "unsupported"
        db.get(CourseMaterial, "m").filename = "old.png"
        db.commit()
    response = replace(files)
    assert response.status_code == 202 and not response.json()["indexed"]
    assert run(files) == 1
    assert original(files) == "新版叶子结点说明。"
    assert files.client.get("/courses/c/materials").json()[0]["indexed"]


def test_ready_replacement_metadata_survives_a_fresh_request(files):
    assert replace(files, filename="new.md").status_code == 202
    assert run(files) == 1
    item = files.client.get("/courses/c/materials").json()[0]
    assert item["filename"] == "new.md" and item["replacement_filename"] is None
    assert item["content_type"] == "text/markdown" and item["processing_status"] == "ready"
    source = files.client.get("/courses/c/materials/m/content?version=old").json()
    assert source["source_status"] == "changed"
    assert source["material"]["filename"] == "new.md"
    assert source["items"][0]["filename"] == "new.md"


def test_partial_storage_failure_is_sanitized_and_scheduled_for_cleanup(files):
    def fail(key, *_):
        target = files.root / key
        target.write_text("部分内容", encoding="utf-8")
        raise RuntimeError("private-storage-details")
    with patch("app.modules.materials.replacement.upload_file", side_effect=fail):
        response = replace(files)
    assert response.status_code == 503 and "private" not in response.text
    with files.sessions() as db:
        assert db.get(MaterialReplacement, "m") is None
        assert clean_pending_files(db, "owner")["cleaned"] == 1
    assert original(files) == "旧版二叉树说明。"


def test_deletion_during_upload_rechecks_visibility_and_cleans_new_file(files):
    from app.infrastructure.storage import upload_file
    def upload_then_delete(*args):
        upload_file(*args)
        assert files.client.delete("/courses/c/materials/m").status_code == 204
    with patch("app.modules.materials.replacement.upload_file", side_effect=upload_then_delete):
        assert replace(files).status_code == 404
    with files.sessions() as db:
        assert clean_pending_files(db, "owner")["cleaned"] == 1
    assert files.old.exists()


def test_same_name_upload_requires_explicit_replacement_and_reserves_pending_name(files):
    def upload(name, lesson_id="l"):
        return files.client.post("/courses/c/materials", data={"lesson_id": lesson_id}, files={"file": (name, b"new text")})
    assert upload("old.txt").status_code == 409
    assert replace(files, filename="reserved.txt").status_code == 202
    assert upload("reserved.txt").status_code == 409
    assert upload("old.txt", lesson_id="").status_code == 201
    with files.sessions() as db:
        assert len(list(db.scalars(select(CourseMaterial)))) == 2


def test_replacement_name_cannot_collide_with_another_file(files):
    response = files.client.post("/courses/c/materials", data={"lesson_id": "l"}, files={"file": ("other.txt", b"other text")})
    assert response.status_code == 201
    assert replace(files, filename="other.txt").status_code == 409
    assert original(files) == "旧版二叉树说明。"
    with files.sessions() as db:
        assert db.get(MaterialReplacement, "m") is None
        assert clean_pending_files(db, "owner")["cleaned"] == 1


def test_transaction_failure_cannot_publish_new_file_with_old_vectors(files):
    assert replace(files).status_code == 202
    def fail_publish(db, *_):
        if any(isinstance(item, CourseMaterial) and item.object_key != "materials/c/old.txt" for item in db.dirty):
            raise RuntimeError("database publish failed")
    event.listen(Session, "before_flush", fail_publish)
    try:
        assert run(files) == 0
    finally:
        event.remove(Session, "before_flush", fail_publish)
    with files.sessions() as db:
        assert db.get(MaterialProcessing, "m").active_version == "old"
        assert db.get(MaterialReplacement, "m") is not None
        assert db.scalar(select(MaterialChunk.version)) == "old"
        assert db.scalar(select(PendingFileDeletion)) is None
    assert original(files) == "旧版二叉树说明。"
