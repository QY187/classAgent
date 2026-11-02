"""流式传输与数据库事务分离；离开页面后后台仍完成历史保存。"""
import asyncio
import json
from queue import Queue, Empty
from threading import Thread
from fastapi.encoders import jsonable_encoder
from ...core.db import SessionLocal
from ...core.chat_failures import public_failure
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
                                      on_step=lambda data: queue.put(("step", data)),
                                      on_started=lambda: queue.put(("status", {"ready": True})))
            queue.put(("done", result))
        except Exception as exc:
            failure = public_failure(exc)
            queue.put(("error", {"detail": failure.message, "error_code": failure.code,
                                 "stage": failure.stage, "request_id": request_id}))

    Thread(target=generate, daemon=True).start()
    yield encode_event("status", {"message": "正在查找课堂依据并整理回答…", "request_id": request_id})
    while True:
        try:
            event, data = await asyncio.to_thread(queue.get, True, 10)
        except Empty:
            yield ": keepalive\n\n"
            continue
        yield encode_event(event, data)
        if event in ("done", "error"):
            break
