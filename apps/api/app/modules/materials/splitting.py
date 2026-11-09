"""递归字符切分：逐级降低分隔符优先级，保留原文和自然边界。"""
from collections import deque
import re


CHUNK_CHARS = 1400
CHUNK_OVERLAP = 150
# 分隔符保留在前一段末尾；英文句点只在空白/文本末尾前作为句界，避免拆开小数。
SEPARATORS = tuple(re.compile(pattern) for pattern in (
    r"\r?\n[ \t]*\r?\n(?:[ \t]*\r?\n)*",
    r"\r?\n",
    r'''[。！？!?]+[”’」』"']*|\.+(?=\s|$)''',
    r"[；;]",
    r"[，,、]",
    r"[ \t\u3000]+",
))


def recursive_character_chunks(text: str, *, chunk_size: int = CHUNK_CHARS,
                               chunk_overlap: int = CHUNK_OVERLAP) -> list[str]:
    """在结构单元内递归切分；重叠至多 chunk_overlap 字符，优先保留完整分段。"""
    if chunk_size <= 0 or not 0 <= chunk_overlap < chunk_size:
        raise ValueError("切片长度须为正数，重叠须非负且小于切片长度")
    if not text.strip():
        return []

    def merge(spans):
        current = deque()
        size = 0
        for start, end in spans:
            length = end - start
            if current and size + length > chunk_size:
                yield current[0][0], current[-1][1]
                # 只保留完整分段作重叠；不为了凑足重叠长度再次截断句子。
                while current and (size > chunk_overlap or size + length > chunk_size):
                    old_start, old_end = current.popleft()
                    size -= old_end - old_start
            current.append((start, end))
            size += length
        if current:
            yield current[0][0], current[-1][1]

    def split(start, end, separators):
        if end - start <= chunk_size:
            yield start, end
            return
        for index, separator in enumerate(separators):
            if separator.search(text, start, end):
                remaining = separators[index + 1:]
                break
        else:
            # 没有更细的自然分隔符，才退到单字符；流式合并避免创建百万个切片对象。
            yield from merge((position, position + 1) for position in range(start, end))
            return

        pending = []
        cursor = start
        for match in separator.finditer(text, start, end):
            boundary = match.end()
            if boundary > cursor:
                if boundary - cursor > chunk_size:
                    yield from merge(pending)
                    pending.clear()
                    yield from split(cursor, boundary, remaining)
                else:
                    pending.append((cursor, boundary))
                cursor = boundary
        if cursor < end:
            if end - cursor > chunk_size:
                yield from merge(pending)
                pending.clear()
                yield from split(cursor, end, remaining)
            else:
                pending.append((cursor, end))
        yield from merge(pending)

    return [text[start:end] for start, end in split(0, len(text), SEPARATORS)
            if text[start:end].strip()]
