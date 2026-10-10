"""流式传输与数据库事务分离；离开页面后后台仍完成历史保存。"""
import asyncio
import json
from queue import Queue, Empty
from threading import Thread
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from ...core.db import SessionLocal
from .sending import send_message


def encode_event(event, data):
    return f"event: {event}\ndata: {json.dumps(jsonable_encoder(data), ensure_ascii=False)}\n\n"


async def message_events(conversation_id, username, content, request_id):
    queue = Queue()

    def generate():
        try:
            with SessionLocal() as db:
                result = send_message(db, conversation_id, username, content, request_id,
                                      on_progress=lambda data: queue.put(("answer", data)),
                                      on_started=lambda: queue.put(("status", {"ready": True})))
            queue.put(("done", result))
        except Exception as exc:
            detail = exc.detail if isinstance(exc, HTTPException) and isinstance(exc.detail, str) else "回答失败，请稍后重试"
            queue.put(("error", {"detail": detail}))

    Thread(target=generate, daemon=True).start()
    yield encode_event("status", {"message": "正在查找课堂依据并整理回答…"})
    while True:
        try:
            event, data = await asyncio.to_thread(queue.get, True, 10)
        except Empty:
            yield ": keepalive\n\n"
            continue
        yield encode_event(event, data)
        if event in ("done", "error"):
            break
