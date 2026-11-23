"""学期内同课程同色，不同课程避开已用色；保存时固化分配结果。"""
from collections import Counter, defaultdict
import colorsys
import re
import unicodedata


PALETTE = ["#14B8A6", "#8B5CF6", "#3B82F6", "#F59E0B", "#EC4899", "#F97316",
           "#84CC16", "#06B6D4", "#6366F1", "#D946EF", "#22C55E", "#F43F5E"]
LEGACY = dict(zip(("teal", "purple", "blue", "amber", "rose"), PALETTE[:5]))


def normalized_title(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def _color(value: str) -> str | None:
    value = LEGACY.get(value, value)
    return value.upper() if re.fullmatch(r"#[0-9a-fA-F]{6}", value) else None


def allocate_colors(entries: list) -> dict[str, str]:
    # 同一个关联课程即使改了显示名称，也使用相同颜色。未关联的同名记录合并到唯一关联课程。
    linked = defaultdict(set)
    for entry in entries:
        if entry.course_id:
            linked[normalized_title(entry.title)].add(entry.course_id)
    groups = defaultdict(list)
    for entry in entries:
        name = normalized_title(entry.title)
        aliases = linked[name]
        course_id = entry.course_id or (next(iter(aliases)) if len(aliases) == 1 else None)
        key = f"course:{course_id}" if course_id else f"title:{name}"
        groups[key].append(entry)
    assigned, used = {}, set()
    # 先保留已有颜色。新课程的空色值不会抢走原课程颜色。
    for key in sorted(groups):
        choices = Counter(color for entry in groups[key] if (color := _color(entry.color)))
        for color, _count in sorted(choices.items(), key=lambda item: (-item[1], item[0])):
            if color not in used:
                assigned[key] = color
                used.add(color)
                break
    extra = 0
    for key in sorted(groups):
        if key in assigned:
            continue
        color = next((value for value in PALETTE if value not in used), None)
        while color is None:
            # 常用色用完后继续生成独立色值，避免课程多于色板时直接循环复用。
            hue = ((extra + 1) * 0.61803398875) % 1
            lightness = 0.48 + (extra % 4) * 0.04
            red, green, blue = colorsys.hls_to_rgb(hue, lightness, 0.64 + (extra % 3) * 0.07)
            candidate = "#{:02X}{:02X}{:02X}".format(round(red * 255), round(green * 255), round(blue * 255))
            extra += 1
            if candidate not in used:
                color = candidate
        assigned[key] = color
        used.add(color)
    return {entry.id: assigned[key] for key, rows in groups.items() for entry in rows}
