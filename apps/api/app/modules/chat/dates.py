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
    week = re.fullmatch(r"(本|这|下|下下|上)(?:周|星期|礼拜)([一二三四五六日天])", text)
    if week:
        shift = {"本": 0, "这": 0, "下": 1, "下下": 2, "上": -1}[week[1]]
        weekday = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}[week[2]]
        return (reference_day - timedelta(days=reference_day.weekday()) + timedelta(weeks=shift, days=weekday)).isoformat()
    days = re.fullmatch(r"(\d{1,3})天([后前])", text)
    if days:
        return (reference_day + timedelta(days=int(days[1]) * (1 if days[2] == "后" else -1))).isoformat()
    match = re.fullmatch(r"(\d{4})年\s*(\d{1,2})月\s*(\d{1,2})(?:日|号)?", text)
    if not match:
        match = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", text)
    if match:
        try:
            return date(*(int(part) for part in match.groups())).isoformat()
        except ValueError:
            pass
    return value  # 不完整或无效日期继续交由业务校验澄清。


def supplement_year(value, previous_source):
    """只把明确补充的年份和有效待办月日组合，不能用系统年份补缺失输入。"""
    year = re.fullmatch(r"(\d{4})年?", value or "")
    month_day = re.fullmatch(r"(\d{1,2})月(\d{1,2})(?:日|号)?", previous_source or "")
    if year and month_day:
        try:
            return date(int(year[1]), int(month_day[1]), int(month_day[2])).isoformat()
        except ValueError:
            pass
    return value
