"""有界分窗、跨课次均衡选材和跨批题干去重。"""
import re
import unicodedata
from types import SimpleNamespace


def stem_key(text):
    return re.sub(r"[\W_]+", "", unicodedata.normalize("NFKC", text)).casefold()


def source_batches(segments, source_windows=None):
    groups = {}
    for source in segments:
        text = source_windows[source.id] if source_windows else source.text
        windows = groups.setdefault(source.lesson_id, [])
        for start in range(0, len(text), 900):
            content = text[start:start + 1000]
            if content.strip():
                windows.append(SimpleNamespace(id=source.id, lesson_id=source.lesson_id,
                                               text=content, original=source))
    # 最多90个窗口；每门课内均匀选取，同时保留短课次。
    allocations = dict.fromkeys(groups, 0)
    for _ in range(90):
        available = [key for key in groups if allocations[key] < len(groups[key])]
        if not available:
            break
        key = min(available, key=lambda key: allocations[key])
        allocations[key] += 1
    selected = []
    for key, windows in groups.items():
        size = allocations[key]
        for i in range(size):
            index = round(i * (len(windows) - 1) / (size - 1)) if size > 1 else len(windows) // 2
            selected.append(windows[index])
    if not selected:
        from fastapi import HTTPException
        raise HTTPException(400, "没有可用于出题的原文")
    return [selected[i:i + 15] for i in range(0, len(selected), 15)]
