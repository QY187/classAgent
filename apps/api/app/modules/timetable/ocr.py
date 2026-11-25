"""本地扫描课表识别，不上传文件；文字框按表格单元格还原。"""
import threading
import json
import os
import subprocess
import sys
from functools import lru_cache

from fastapi import HTTPException

_lock = threading.Lock()
MAX_OCR_PAGES = 5


@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR
    return RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1)


def _boundaries(values):
    groups = []
    for value in sorted(values):
        if groups and value - groups[-1][-1] <= 6:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [sum(group) / len(group) for group in groups]


def image_grids(image, page_number):
    import cv2
    import numpy as np
    from .importing import Grid, clean

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
    height, width = gray.shape
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (max(35, width // 35), 1)))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, max(35, height // 35))))
    lines = cv2.bitwise_or(horizontal, vertical)
    contours, hierarchy = cv2.findContours(lines, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    if hierarchy is not None:
        for index, contour in enumerate(contours):
            x, y, w, h = cv2.boundingRect(contour)
            # 取表格线围出的空腔，外框及字符的小轮廓不作为单元格。
            if hierarchy[0][index][3] >= 0 and w >= 28 and h >= 20:
                boxes.append((x, y, x + w, y + h))
    if len(boxes) > 1200:
        raise HTTPException(422, "扫描课表结构过于复杂，请裁剪到课表区域")
    cleaned = image.copy()
    cleaned[cv2.dilate(lines, np.ones((2, 2), np.uint8)) > 0] = 255
    result, _ = _engine()(cleaned)
    words = []
    for points, text, score in result or []:
        if score < .45 or not text.strip():
            continue
        points = np.asarray(points)
        words.append((float(points[:, 0].mean()), float(points[:, 1].mean()), clean(text)))
    source = f"第{page_number}页·OCR"
    grids = []
    if boxes:
        xs = _boundaries([value for box in boxes for value in (box[0], box[2])])
        ys = _boundaries([value for box in boxes for value in (box[1], box[3])])
        if 2 <= len(xs) <= 41 and 2 <= len(ys) <= 301:
            rows = [["" for _ in xs[:-1]] for _ in ys[:-1]]
            spans = {}
            for x0, y0, x1, y1 in boxes:
                col = min(range(len(xs)), key=lambda i: abs(xs[i] - x0))
                row = min(range(len(ys)), key=lambda i: abs(ys[i] - y0))
                end = min(range(len(ys)), key=lambda i: abs(ys[i] - y1))
                if row >= len(rows) or col >= len(rows[row]):
                    continue
                values = sorted((word for word in words if x0 <= word[0] <= x1 and y0 <= word[1] <= y1), key=lambda word: (round(word[1] / 10), word[0]))
                rows[row][col] = "\n".join(word[2] for word in values)
                spans[(row, col)] = max(1, end - row)
            grids.append(Grid(source + "·表格", rows, spans))
    # 无边框清单或表格外的显式排课文字，保留按位置排列的文字行供同一解析器处理。
    text_rows = []
    for word in sorted(words, key=lambda value: (value[1], value[0])):
        if text_rows and abs(word[1] - text_rows[-1][0]) < 12:
            text_rows[-1][1].append(word)
        else:
            text_rows.append((word[1], [word]))
    if not grids:
        grids.append(Grid(source + "·文字", [[" ".join(word[2] for word in sorted(row, key=lambda value: value[0]))] for _, row in text_rows]))
    return grids


def scanned_grids(data, page_indexes):
    if len(page_indexes) > MAX_OCR_PAGES:
        raise HTTPException(422, "每次最多识别 5 页扫描课表，请拆分文件后导入")
    if not _lock.acquire(blocking=False):
        raise HTTPException(429, "另一个扫描课表正在识别，请稍后重试")
    try:
        # 原生推理库放在独立进程中，超时或原生崩溃不能带走 API 服务。
        result = subprocess.run([sys.executable, "-m", "app.modules.timetable.ocr_worker", ",".join(map(str, page_indexes))],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if result.returncode != 0 or len(result.stdout) > 8 * 1024 * 1024:
            raise HTTPException(422, "OCR 识别进程异常，请检查后端 OCR 依赖，或改用文字版 PDF")
        value = json.loads(result.stdout)
        if "error" in value:
            raise HTTPException(value["status"], value["error"])
        from .importing import Grid
        return [Grid(row["name"], row["rows"], {(item[0], item[1]): item[2] for item in row["spans"]}) for row in value["grids"]]
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(422, "扫描课表识别超过 120 秒，请减少页数或裁剪课表区域后重试") from exc
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(422, "OCR 未返回有效识别结果，请重试或改用文字版 PDF") from exc
    except OSError as exc:
        raise HTTPException(503, "OCR 识别进程无法启动，请检查后端运行环境") from exc
    finally:
        _lock.release()


def scan_document(data, page_indexes):
    try:
        import pypdfium2 as pdfium
        grids = []
        with pdfium.PdfDocument(data) as document:
            for index in page_indexes:
                page = document[index]
                try:
                    width, height = page.get_size()
                    if width <= 0 or height <= 0:
                        raise HTTPException(422, "扫描课表页面尺寸无效")
                    scale = min(2.8, 2400 / max(width, height))
                    bitmap = page.render(scale=scale)
                    try:
                        image = bitmap.to_numpy()
                        import cv2
                        if image.shape[2] == 4:
                            image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
                        grids.extend(image_grids(image, index + 1))
                    finally:
                        bitmap.close()
                finally:
                    page.close()
        return grids
    except HTTPException:
        raise
    except ImportError as exc:
        raise HTTPException(503, "OCR 组件未安装，请安装后端 requirements.txt 依赖并重启服务") from exc
    except Exception as exc:
        raise HTTPException(422, "扫描课表识别失败，请使用清晰、方向端正的 PDF，或改用文字版导出") from exc
