"""读取旧版 Excel 课表，保留合并单元格的小节跨度。"""
from fastapi import HTTPException


def xls_grids(data):
    import xlrd
    from .importing import Grid, clean
    book = None
    try:
        book = xlrd.open_workbook(file_contents=data, formatting_info=True, on_demand=True)
        if book.nsheets > 10:
            raise HTTPException(422, "Excel 最多支持 10 张工作表，请只保留课表")
        grids, warnings = [], []
        for sheet in book.sheets():
            if sheet.nrows > 300 or sheet.ncols > 40:
                raise HTTPException(422, "Excel 表格过大，请只保留课表区域")
            rows = [[clean(sheet.cell_value(row, col)) for col in range(sheet.ncols)] for row in range(sheet.nrows)]
            spans = {(row, col): last - row for row, last, col, _ in sheet.merged_cells}
            grids.append(Grid(f"Excel·{sheet.name}", rows, spans))
            from .importing import weekday
            import re
            day_columns = next(({weekday(cell): col for col, cell in enumerate(row) if weekday(cell)} for row in rows if sum(bool(weekday(cell)) for cell in row) >= 2), {})
            extra_rows = []
            for row_index, row in enumerate(rows):
                for col, value in enumerate(row):
                    if col > 0 and (value == "全周" or "全天" in value):
                        title = row[col - 1]
                        weeks = row[col + 1] if col + 1 < len(row) else "周次未注明"
                        teacher = row[col + 2] if col + 2 < len(row) else ""
                        days = list(range(1, 6)) if value == "全周" else [weekday(token) for token in re.findall(r"(?:周|星期)[一二三四五六日天1-7]", value)]
                        activity = [""] * sheet.ncols
                        activity[0] = "全天"
                        for day in days:
                            if day in day_columns:
                                activity[day_columns[day]] = f"{title}\n教师：{teacher}\n{weeks}\n全天"
                        extra_rows.append(activity)
                        warnings.append(f"全天实践：{title} · {weeks}。" + ("全周按周一至周五" if value == "全周" else value) + "、第1—10小节展示，晚上留空；同日的不同实践并列展示。")
                        rows[row_index] = [""] * len(row)
            rows.extend(extra_rows)
        return grids, warnings
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, "Excel 无法读取，请确认是完整、未加密的 .xls 课表") from exc
    finally:
        if book is not None:
            book.release_resources()
