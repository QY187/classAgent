"""结合周网格的周次与课程明细的准确小节，处理网页打印型课表。"""
import re


def reconcile_grids(grids, semester):
    from .importing import Grid, clean, weekday, _header, _block_range, week_ranges
    compact = lambda value: re.sub(r"\s+", "", clean(value))
    details = []
    for grid in grids:
        for index, row in enumerate(grid.rows):
            header = {_header(cell): col for col, cell in enumerate(row) if cell}
            if not {"课程名称", "教师", "时间", "地点"} <= header.keys():
                continue
            for values in grid.rows[index + 1:]:
                get = lambda key: compact(values[header[key]]) if header[key] < len(values) else ""
                title, time = get("课程名称"), get("时间")
                slots = [(weekday(day), int(start), int(end or start)) for day, start, end in
                    re.findall(r"((?:星期|周)[一二三四五六日天1-7])\(?第?(\d{1,2})(?:[-~～—–至](\d{1,2}))?(?:小节|节)\)?", time)]
                if title and slots:
                    rooms = re.split(r"[,、;；]", get("地点"))
                    detail = {"title": title, "teacher": get("教师"), "slots": slots, "rooms": rooms}
                    if detail not in details:
                        details.append(detail)
    if not details:
        return None
    header = ["课程名称", "星期", "节次", "周次", "教师", "教室"]
    output, seen, matched, notes = [], set(), set(), []
    for grid in grids:
        for header_index, row in enumerate(grid.rows):
            day_columns = {col: weekday(cell) for col, cell in enumerate(row) if weekday(cell)}
            if len(day_columns) < 2:
                continue
            first_day = min(day_columns)
            for values in grid.rows[header_index + 1:]:
                labels = values[:first_day]
                block = next((_block_range(cell, semester["periods"]) for cell in reversed(labels) if _block_range(cell, semester["periods"])), [])
                if not block:
                    continue
                for col, day in day_columns.items():
                    raw = clean(values[col]) if col < len(values) else ""
                    if not raw:
                        continue
                    # 同一单元格中用一行或多行横线分隔的不同课程。
                    parts = re.split(r"\n\s*[-—–_]{3,}[^\S\n]*(?:\n\s*[-—–_]{3,}[^\S\n]*)*\n", raw)
                    for part in parts:
                        text = compact(part)
                        candidates = sorted((item for item in details if text.startswith(item["title"])), key=lambda item: -len(item["title"]))
                        if not candidates:
                            continue
                        detail = candidates[0]
                        slots = [(i, start, end) for i, (slot_day, start, end) in enumerate(detail["slots"])
                                 if slot_day == day and any(start <= last and end >= first for first, last in block)]
                        if not slots:
                            continue
                        weeks, pattern, warnings = week_ranges(part, semester["week_count"])
                        if warnings:
                            # 周次缺失不能悄悄转成全学期，留空交给原解析器显示核对警告。
                            weeks_text = ""
                        else:
                            weeks_text = ",".join(str(first) if first == last else f"{first}-{last}" for first, last in weeks) + "周"
                            if pattern != "all":
                                weeks_text += "单周" if pattern == "odd" else "双周"
                        for slot_index, start, end in slots:
                            room = detail["rooms"][slot_index] if slot_index < len(detail["rooms"]) else detail["rooms"][0]
                            key = (detail["title"], day, start, end, weeks_text, room)
                            if key in seen:
                                continue
                            seen.add(key)
                            matched.add((detail["title"], day, start, end))
                            output.append([detail["title"], str(day), f"{start}-{end}", weeks_text, detail["teacher"], room])
            break
    if not output:
        return None
    # 有明细却没有匹配到周网格时，保留为待核对记录，避免课程静默丢失。
    for detail in details:
        for index, (day, start, end) in enumerate(detail["slots"]):
            if (detail["title"], day, start, end) not in matched:
                room = detail["rooms"][index] if index < len(detail["rooms"]) else detail["rooms"][0]
                output.append([detail["title"], str(day), f"{start}-{end}", "", detail["teacher"], room])
                notes.append(f"「{detail['title']}」周{day}的周次未能与周课表匹配，请人工核对")
    notes.insert(0, "已交叉核对周课表与课程明细：周次取自周课表，教师、教室及精确小节取自课程明细。文件中的学年学期不会自动修改当前学期设置。")
    return [Grid("周课表与课程明细交叉识别", [header, *output])], notes
