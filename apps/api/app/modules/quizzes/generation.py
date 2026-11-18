"""有界分窗、跨课次均衡选材和跨批题干去重。"""
import re
import unicodedata
from contextvars import ContextVar
from time import monotonic
from types import SimpleNamespace


def stem_key(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text)).casefold()


def source_batches(segments, source_windows=None):
    groups = {}
    for source in segments:
        text = source_windows[source.id] if source_windows else source.text
        windows = groups.setdefault(getattr(source, "material_id", None) or source.lesson_id, [])
        for start in range(0, len(text), 900):
            content = text[start:start + 1000]
            if content.strip():
                windows.append(SimpleNamespace(id=source.id, lesson_id=source.lesson_id,
                                               text=content, original=source))
    # 最多90个窗口；各课次或文件内均匀选取，同时保留短来源。
    allocations = dict.fromkeys(groups, 0)
    for _ in range(90):
        available = [key for key in groups if allocations[key] < len(groups[key])]
        if not available:
            break
        key = min(available, key=lambda key: allocations[key])
        allocations[key] += 1
    chosen = []
    for key, windows in groups.items():
        group = []
        size = allocations[key]
        for i in range(size):
            index = round(i * (len(windows) - 1) / (size - 1)) if size > 1 else len(windows) // 2
            group.append(windows[index])
        chosen.append(group)
    # 批次内交错不同来源，避免短来源仅出现在最后一批。
    selected = [group[i] for i in range(max(allocations.values(), default=0)) for group in chosen if i < len(group)]
    if not selected:
        from fastapi import HTTPException
        raise HTTPException(400, "没有可用于出题的原文")
    return [selected[i:i + 15] for i in range(0, len(selected), 15)]


# 同步生成沿用现有180秒代理窗口，所有生成和审核共享150秒预算。
generation_deadline = ContextVar("quiz_generation_deadline", default=None)


def model_timeout():
    deadline = generation_deadline.get()
    remaining = deadline - monotonic() if deadline is not None else 120
    if remaining <= 0:
        from fastapi import HTTPException
        raise HTTPException(504, "小测生成超时，请缩小范围或减少题量后重试")
    return min(120, remaining)
