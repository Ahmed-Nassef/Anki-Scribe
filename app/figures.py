"""Figure cards: crop the figure around a region and mask it.

A student drags a box over a label or a structure. The card should show the
*figure*, not a fragment, so the crop is widened to the picture that contains
the selection when the page has one. Two images come out of it: one with the
selection covered, and one with it outlined.
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw

from .store import Document, normalize_text

ACCENT = (15, 118, 110)
PAPER = (255, 253, 248)
DPI = 200
MAX_SIDE = 1600
PAD_RATIO = 0.12
MIN_SIDE_PX = 12
MAX_LINES_FOR_LABEL = 2

NAME_PATTERN = re.compile(r"^fig-[0-9a-f]{12}-[mr]\.png$")


def valid_name(name: str) -> bool:
    return bool(NAME_PATTERN.match(name or ""))


def _scale(doc: Document, page, pdf_page) -> float:
    """Page-image pixels to PDF points."""
    if not page.width:
        return 1.0
    return pdf_page.rect.width / page.width


def _context_box(pdf_page, clip: pymupdf.Rect) -> pymupdf.Rect:
    """The picture that contains the selection, or the selection plus padding."""
    page_rect = pdf_page.rect
    best = None
    try:
        infos = pdf_page.get_image_info()
    except Exception:
        infos = []
    center = pymupdf.Point((clip.x0 + clip.x1) / 2, (clip.y0 + clip.y1) / 2)
    for info in infos:
        try:
            box = pymupdf.Rect(info["bbox"])
        except (KeyError, TypeError, ValueError):
            continue
        if box.is_empty or not box.contains(center):
            continue
        if best is None or box.get_area() < best.get_area():
            best = box
    if best is not None:
        return best & page_rect

    pad_x = clip.width * PAD_RATIO
    pad_y = clip.height * PAD_RATIO
    padded = pymupdf.Rect(
        clip.x0 - pad_x, clip.y0 - pad_y, clip.x1 + pad_x, clip.y1 + pad_y
    )
    return padded & page_rect


def _suggested_label(doc: Document, page, clip: pymupdf.Rect, scale: float) -> str:
    """Text lines whose centre sits inside the selection: usually the label."""
    if scale <= 0:
        return ""
    rect = pymupdf.Rect(clip.x0 / scale, clip.y0 / scale, clip.x1 / scale, clip.y1 / scale)
    picked = []
    for line in page.lines:
        cx = (line["x0"] + line["x1"]) / 2
        cy = (line["y0"] + line["y1"]) / 2
        if rect.x0 <= cx <= rect.x1 and rect.y0 <= cy <= rect.y1:
            picked.append(line)
    if not picked:
        return ""
    picked.sort(key=lambda line: (line["y0"], line["x0"]))
    text = " ".join(line["text"] for line in picked[:MAX_LINES_FOR_LABEL])
    return normalize_text(text)[:120]


def build(doc: Document, page_index: int, rect: dict) -> dict:
    """Render the masked and revealed crops for a selection on one page."""
    if doc.kind != "pdf":
        raise ValueError("Figure cards need a PDF page.")
    if page_index < 0 or page_index >= len(doc.pages):
        raise ValueError("That page doesn't exist.")

    try:
        x0 = float(rect["x0"])
        y0 = float(rect["y0"])
        x1 = float(rect["x1"])
        y1 = float(rect["y1"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("That selection isn't a rectangle.") from exc
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if x1 - x0 < MIN_SIDE_PX or y1 - y0 < MIN_SIDE_PX:
        raise ValueError("Draw a bigger box \u2014 that one is too small to read.")

    page = doc.pages[page_index]
    with pymupdf.open(doc.source) as pdf:
        pdf_page = pdf[page_index]
        scale = _scale(doc, page, pdf_page)
        clip = pymupdf.Rect(x0 * scale, y0 * scale, x1 * scale, y1 * scale) & pdf_page.rect
        if clip.is_empty:
            raise ValueError("That selection falls outside the page.")
        box = _context_box(pdf_page, clip)
        zoom = min(DPI / 72.0, MAX_SIDE / max(box.width, box.height, 1.0))
        pix = pdf_page.get_pixmap(clip=box, matrix=pymupdf.Matrix(zoom, zoom), alpha=False)
        suggested = _suggested_label(doc, page, clip, scale)

    image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    mx0 = max(0.0, (clip.x0 - box.x0) * zoom)
    my0 = max(0.0, (clip.y0 - box.y0) * zoom)
    mx1 = min(float(image.width - 1), (clip.x1 - box.x0) * zoom)
    my1 = min(float(image.height - 1), (clip.y1 - box.y0) * zoom)
    box_px = [round(mx0), round(my0), round(mx1), round(my1)]
    stroke = max(2, round(image.width / 320))

    masked = image.copy()
    ImageDraw.Draw(masked).rectangle(box_px, fill=PAPER, outline=ACCENT, width=stroke)

    revealed = image.copy()
    ImageDraw.Draw(revealed).rectangle(box_px, outline=ACCENT, width=stroke)

    digest = hashlib.sha1(
        f"{doc.id}:{page_index}:{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}".encode("utf-8")
    ).hexdigest()[:12]
    masked_name = f"fig-{digest}-m.png"
    revealed_name = f"fig-{digest}-r.png"
    doc.directory.mkdir(parents=True, exist_ok=True)
    masked.save(doc.directory / masked_name, "PNG", optimize=True)
    revealed.save(doc.directory / revealed_name, "PNG", optimize=True)

    return {
        "masked": masked_name,
        "revealed": revealed_name,
        "suggested": suggested,
        "page": page_index,
        "label": f"Page {page_index + 1}",
    }


def figure_path(doc: Document, name: str) -> Path:
    if not valid_name(name):
        raise ValueError("That isn't a figure name.")
    target = doc.directory / name
    if not target.is_file():
        raise ValueError("That figure isn't on disk any more.")
    return target
