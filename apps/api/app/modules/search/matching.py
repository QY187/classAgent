import re

from sqlalchemy import and_, or_


def search_condition(query: str, *columns):
    """空格分词取交集，短中文词允许字间有其他文字，SQL 通配符按字面处理。"""
    tokens = query.split()
    if not tokens:
        return False
    conditions = []
    for token in tokens:
        characters = token if re.fullmatch(r"[\u3400-\u9fff]{2,12}", token) else [token]
        escaped = [part.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") for part in characters]
        pattern = "%" + "%".join(escaped) + "%"
        conditions.append(or_(*(column.ilike(pattern, escape="\\") for column in columns)))
    return and_(*conditions)
