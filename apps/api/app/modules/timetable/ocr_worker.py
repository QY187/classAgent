"""OCR 子进程入口：标准输入为 PDF，标准输出为结构化 JSON。"""
import json
import sys

from fastapi import HTTPException

from .ocr import scan_document


def main():
    try:
        indexes = [int(value) for value in sys.argv[1].split(",") if value]
        grids = scan_document(sys.stdin.buffer.read(8 * 1024 * 1024 + 1), indexes)
        result = {"grids": [{"name": grid.name, "rows": grid.rows,
            "spans": [[row, col, count] for (row, col), count in grid.spans.items()]} for grid in grids]}
    except HTTPException as exc:
        result = {"status": exc.status_code, "error": exc.detail}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))


if __name__ == "__main__":
    main()
