"""Read a .pptx without a dependency.

A slide deck is a zip of XML. The app already knows how to work with a page of
text at known positions, so a deck is converted into a synthetic PDF at import
and everything downstream — selection, chapters, objectives, figure cards,
extraction — works unchanged.

Only what a lecture actually carries is read: shape text, tables and pictures.
"""

from __future__ import annotations

import posixpath
import re
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import pymupdf

A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
P = "{http://schemas.openxmlformats.org/presentationml/2006/main}"
R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
PR = "{http://schemas.openxmlformats.org/package/2006/relationships}"
# Office Math Markup: equations a slide carries as real math.
M = "{http://schemas.openxmlformats.org/officeDocument/2006/math}"

EMU_PER_POINT = 12700
MAX_SLIDES = 300
MAX_TEXT_POINTS = 28
MIN_TEXT_POINTS = 6.5
LINE_FACTOR = 1.35

_SLIDE = re.compile(r"slides/slide(\d+)\.xml$")


def _frame(element) -> tuple[float, float, float, float] | None:
    """Shape geometry in points: x, y, width, height.

    Looks for ``a:off``/``a:ext`` anywhere below the shape, because a normal
    shape nests them under ``a:xfrm`` while a table nests them under ``p:xfrm``.
    """
    off = element.find(f".//{A}off")
    ext = element.find(f".//{A}ext")
    if off is None or ext is None:
        return None
    try:
        return (
            int(off.get("x", 0)) / EMU_PER_POINT,
            int(off.get("y", 0)) / EMU_PER_POINT,
            int(ext.get("cx", 0)) / EMU_PER_POINT,
            int(ext.get("cy", 0)) / EMU_PER_POINT,
        )
    except (TypeError, ValueError):
        return None


def _runs(element, separator: str = "") -> str:
    """Text runs in document order, including a slide's OMML equations."""
    values = [
        node.text or ""
        for node in element.iter()
        if node.tag in (f"{A}t", f"{M}t") and node.text
    ]
    return separator.join(values)


def _shape_text(element) -> str:
    lines = []
    for paragraph in element.iter(f"{A}p"):
        line = _runs(paragraph).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _table_text(element) -> str:
    """A table as a Markdown grid, so the model sees cells and not a run-on."""
    rows = []
    for row in element.iter(f"{A}tr"):
        cells = [
            re.sub(r"\s+", " ", _runs(cell, " ")).strip()
            for cell in row.iter(f"{A}tc")
        ]
        if any(cells):
            rows.append("| " + " | ".join(cells) + " |")
    if rows:
        width = max(1, rows[0].count("|") - 1)
        rows.insert(1, "| " + " | ".join(["---"] * width) + " |")
    return "\n".join(rows)


def _relationships(archive: zipfile.ZipFile, part: str) -> dict[str, str]:
    folder, name = posixpath.split(part)
    rels_path = posixpath.join(folder, "_rels", f"{name}.rels")
    try:
        data = archive.read(rels_path)
    except KeyError:
        return {}
    try:
        root = ET.fromstring(data)
    except ET.ParseError:
        return {}
    mapping = {}
    for rel in root.iter(f"{PR}Relationship"):
        rid = rel.get("Id")
        target = rel.get("Target")
        if rid and target:
            mapping[rid] = posixpath.normpath(posixpath.join(folder, target))
    return mapping


def _slide_parts(archive: zipfile.ZipFile) -> list[str]:
    """Slides in the order the deck plays them, not alphabetical order."""
    try:
        presentation = ET.fromstring(archive.read("ppt/presentation.xml"))
        rels = _relationships(archive, "ppt/presentation.xml")
    except (KeyError, ET.ParseError):
        # Fall back to file order when the manifest is unreadable.
        names = [name for name in archive.namelist() if _SLIDE.match(name)]
        return sorted(names, key=lambda name: int(_SLIDE.match(name).group(1)))

    parts = []
    for slide_id in presentation.iter(f"{P}sldId"):
        rid = slide_id.get(f"{R}id")
        target = rels.get(rid or "")
        if target:
            parts.append(target)
    if parts:
        return parts
    names = [name for name in archive.namelist() if _SLIDE.match(name)]
    return sorted(names, key=lambda name: int(_SLIDE.match(name).group(1)))


def _slide_size(archive: zipfile.ZipFile) -> tuple[float, float]:
    try:
        root = ET.fromstring(archive.read("ppt/presentation.xml"))
    except (KeyError, ET.ParseError):
        return 960.0, 540.0
    size = root.find(f"{P}sldSz")
    if size is None:
        return 960.0, 540.0
    try:
        width = int(size.get("cx", 0)) / EMU_PER_POINT
        height = int(size.get("cy", 0)) / EMU_PER_POINT
    except (TypeError, ValueError):
        return 960.0, 540.0
    if width < 10 or height < 10:
        return 960.0, 540.0
    return width, height


def _draw_text(page, rect, text: str) -> None:
    lines = max(1, text.count("\n") + 1)
    size = min(MAX_TEXT_POINTS, max(MIN_TEXT_POINTS, rect.height / (lines * LINE_FACTOR)))
    while size >= MIN_TEXT_POINTS:
        remaining = page.insert_textbox(
            rect, text, fontsize=size, fontname="helv", lineheight=LINE_FACTOR, align=0
        )
        if remaining >= 0:
            return
        size -= 1.0
    # Nothing fits: write it at the minimum size and let it clip rather than
    # losing the words entirely.
    page.insert_textbox(rect, text, fontsize=MIN_TEXT_POINTS, fontname="helv", align=0)


def convert(source: Path, target: Path) -> int:
    """Write a PDF version of the deck to ``target`` and return the slide count."""
    source = Path(source)
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("That file isn't a PowerPoint presentation.") from exc

    with archive:
        parts = _slide_parts(archive)
        if not parts:
            raise ValueError("That presentation has no slides.")
        if len(parts) > MAX_SLIDES:
            raise ValueError(f"That presentation has {len(parts)} slides (max {MAX_SLIDES}).")
        width, height = _slide_size(archive)

        pdf = pymupdf.open()
        try:
            for part in parts:
                page = pdf.new_page(width=width, height=height)
                try:
                    slide = ET.fromstring(archive.read(part))
                except (KeyError, ET.ParseError):
                    continue
                rels = _relationships(archive, part)
                # Shapes that inherit their position from the slide layout have
                # no geometry of their own; keep their text in document order
                # instead of dropping it.
                fallback_y = 36.0

                for node in slide.iter():
                    if node.tag == f"{P}sp":
                        text = _shape_text(node)
                        if not text:
                            continue
                        frame = _frame(node)
                        if frame:
                            rect = pymupdf.Rect(*_rect(frame, width, height))
                        else:
                            rect = pymupdf.Rect(36.0, fallback_y, width - 36.0, fallback_y + 58.0)
                            fallback_y += 66.0
                        _draw_text(page, rect, text)
                    elif node.tag == f"{P}graphicFrame":
                        text = _table_text(node)
                        if not text:
                            continue
                        frame = _frame(node)
                        rect = (
                            pymupdf.Rect(*_rect(frame, width, height))
                            if frame
                            else pymupdf.Rect(36.0, fallback_y, width - 36.0, fallback_y + 58.0)
                        )
                        if not frame:
                            fallback_y += 66.0
                        _draw_text(page, rect, text)
                    elif node.tag == f"{P}pic":
                        frame = _frame(node)
                        blip = node.find(f".//{A}blip")
                        if not frame or blip is None:
                            continue
                        media = rels.get(blip.get(f"{R}embed") or "")
                        if not media:
                            continue
                        try:
                            blob = archive.read(media)
                        except KeyError:
                            continue
                        try:
                            page.insert_image(
                                pymupdf.Rect(*_rect(frame, width, height)),
                                stream=blob,
                                keep_proportion=True,
                            )
                        except Exception:
                            continue
            pdf.save(target)
        finally:
            pdf.close()
    return len(parts)


def _rect(frame: tuple[float, float, float, float], width: float, height: float) -> tuple:
    x, y, w, h = frame
    x = max(0.0, min(x, width))
    y = max(0.0, min(y, height))
    w = max(4.0, min(w, width - x))
    h = max(4.0, min(h, height - y))
    return (x, y, x + w, y + h)
