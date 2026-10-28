"""日期格式归一化；有明确参照日的相对日期不等同于猜测年份。"""
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


def current_day():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def normalize_lesson_date(value, reference_day):
    if value is None:
        return None
    text = value.strip()
    offsets = {"今天": 0, "今日": 0, "明天": 1, "明日": 1, "后天": 2,
               "昨天": -1, "昨日": -1, "前天": -2, "大后天": 3, "大前天": -3}
    if text in offsets:
        return (reference_day + timedelta(days=offsets[text])).isoformat()
    match = re.fullmatch(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})(?:日|号)?", text)
    if not match:
        match = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        try:
            return date(*(int(part) for part in match.groups())).isoformat()
        except ValueError:
            pass
    return value  # 不完整或无效日期继续交由业务校验澄清。
