"""OCR for phone photos and scanned PDF pages.

Windows' built-in OCR engine produces clean line segmentation and correct
spacing for printed English, so it is tried first. RapidOCR (ONNX) is the
offline fallback for machines where the Windows OCR language pack is missing.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path

_engine = None
_engine_lock = threading.Lock()
_windows_lock = threading.Lock()


def _get_rapidocr():
    global _engine
    with _engine_lock:
        if _engine is None:
            from rapidocr_onnxruntime import RapidOCR

            _engine = RapidOCR()
    return _engine


def _sort_yx(lines: list[dict]) -> list[dict]:
    return sorted(lines, key=lambda line: (line["y0"], line["x0"]))


def order_lines(lines: list[dict], page_width: int) -> list[dict]:
    """Put OCR lines in reading order, splitting two-column textbook pages.

    Detectors often order boxes by y across the whole page, which interleaves
    the columns of a textbook. If a wide vertical gutter exists, read the left
    column first, then the right.
    """
    if len(lines) < 8 or page_width <= 0:
        return _sort_yx(lines)
    centers = sorted((line["x0"] + line["x1"]) / 2 for line in lines)
    widest_gap = 0.0
    split_at = None
    for left, right in zip(centers, centers[1:]):
        gap = right - left
        if gap > widest_gap:
            widest_gap = gap
            split_at = (left + right) / 2
    if split_at is None or widest_gap < page_width * 0.10:
        return _sort_yx(lines)
    left_column = [line for line in lines if (line["x0"] + line["x1"]) / 2 < split_at]
    right_column = [line for line in lines if (line["x0"] + line["x1"]) / 2 >= split_at]
    if min(len(left_column), len(right_column)) < max(3, len(lines) * 0.15):
        return _sort_yx(lines)
    return _sort_yx(left_column) + _sort_yx(right_column)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def lines_from_winocr(result: dict, page_width: int) -> list[dict]:
    """Convert a winocr result dict into the app's line format."""
    lines: list[dict] = []
    for entry in result.get("lines", []) if isinstance(result, dict) else []:
        if not isinstance(entry, dict):
            continue
        words = entry.get("words") or []
        rects = []
        for word in words:
            rect = word.get("bounding_rect") if isinstance(word, dict) else None
            if not isinstance(rect, dict):
                continue
            try:
                x = float(rect["x"])
                y = float(rect["y"])
                width = float(rect["width"])
                height = float(rect["height"])
            except (KeyError, TypeError, ValueError):
                continue
            rects.append((x, y, x + width, y + height))
        if not rects:
            continue
        text = entry.get("text")
        if not isinstance(text, str):
            text = " ".join(
                str(word.get("text", "")) for word in words if isinstance(word, dict)
            )
        text = _clean(text)
        if not text:
            continue
        x0 = min(rect[0] for rect in rects)
        y0 = min(rect[1] for rect in rects)
        x1 = max(rect[2] for rect in rects)
        y1 = max(rect[3] for rect in rects)
        if x1 - x0 < 2 or y1 - y0 < 3:
            continue
        lines.append(
            {
                "text": text,
                "x0": round(x0, 2),
                "y0": round(y0, 2),
                "x1": round(x1, 2),
                "y1": round(y1, 2),
            }
        )
    return order_lines(lines, page_width)


def _windows_ocr(image_path: Path, page_width: int) -> list[dict] | None:
    try:
        from PIL import Image
        from winocr import recognize_pil_sync
    except ImportError:
        return None
    try:
        with Image.open(image_path) as image:
            with _windows_lock:
                result = recognize_pil_sync(image, "en")
    except Exception:
        # No Windows OCR language pack, unsupported image, or WinRT failure:
        # let the caller fall back to RapidOCR.
        return None
    return lines_from_winocr(result, page_width)


def _coerce_entry(entry) -> tuple[object, str, float] | None:
    if isinstance(entry, dict):
        return entry.get("box"), str(entry.get("text", "")), float(entry.get("score", 1.0))
    if len(entry) >= 3:
        return entry[0], str(entry[1]), float(entry[2])
    return None


def _rapidocr_lines(image_path: Path, page_width: int) -> list[dict]:
    engine = _get_rapidocr()
    result, _elapsed = engine(str(image_path))
    lines: list[dict] = []
    for entry in result or []:
        coerced = _coerce_entry(entry)
        if coerced is None:
            continue
        box, text, score = coerced
        text = _clean(text)
        if not text or score < 0.30 or box is None:
            continue
        try:
            xs = [float(point[0]) for point in box]
            ys = [float(point[1]) for point in box]
        except (TypeError, ValueError, IndexError):
            continue
        x0, x1 = min(xs), max(xs)
        y0, y1 = min(ys), max(ys)
        if x1 - x0 < 2 or y1 - y0 < 3:
            continue
        lines.append(
            {
                "text": text,
                "x0": round(x0, 2),
                "y0": round(y0, 2),
                "x1": round(x1, 2),
                "y1": round(y1, 2),
            }
        )
    return order_lines(lines, page_width)


def ocr_lines(image_path: Path, page_width: int) -> list[dict]:
    """OCR one image. Coordinates are pixels in the image's own space."""
    lines = _windows_ocr(image_path, page_width)
    if lines is not None:
        return lines
    return _rapidocr_lines(image_path, page_width)
