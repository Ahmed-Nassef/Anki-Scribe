"""Images attached to a card: a crop of a page, or a picture from disk.

The figure tool makes a masked/revealed pair for image-occlusion cards. This is
the plainer case: one picture that belongs on the front or the back of a card
that already exists — a diagram to label, an ECG to read, a table to explain.

Images live beside the figures in the document's cache and travel to Anki as
media, so the card works on the desktop and on a phone with no add-on.
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path

import pymupdf
from PIL import Image, ImageOps

from .store import Document

# AnkiConnect media names must stay simple; the same pattern guards the path.
NAME_PATTERN = re.compile(r"^img-[0-9a-f]{12}\.png$")

DPI = 200
MAX_SIDE = 1600
MIN_SIDE_PX = 12
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def valid_name(name: str) -> bool:
    return bool(NAME_PATTERN.match(name or ""))


def image_path(doc: Document, name: str) -> Path:
    if not valid_name(name):
        raise ValueError("That isn't a card image name.")
    target = doc.directory / name
    if not target.is_file():
        raise ValueError("That image isn't on disk any more.")
    return target


def _write(doc: Document, image: "Image.Image", digest: str) -> dict:
    name = f"img-{digest}.png"
    doc.directory.mkdir(parents=True, exist_ok=True)
    image.save(doc.directory / name, "PNG", optimize=True)
    return {"name": name, "width": image.width, "height": image.height}


def crop(doc: Document, page_index: int, rect: dict) -> dict:
    """Cut the selected region of a page, at a resolution that stays readable."""
    if doc.kind != "pdf":
        raise ValueError("Cropping a picture needs a PDF page.")
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
        scale = pdf_page.rect.width / page.width if page.width else 1.0
        clip = pymupdf.Rect(x0 * scale, y0 * scale, x1 * scale, y1 * scale) & pdf_page.rect
        if clip.is_empty:
            raise ValueError("That selection falls outside the page.")
        zoom = min(DPI / 72.0, MAX_SIDE / max(clip.width, clip.height, 1.0))
        pix = pdf_page.get_pixmap(
            clip=clip, matrix=pymupdf.Matrix(zoom, zoom), alpha=False
        )

    image = Image.open(io.BytesIO(pix.tobytes("png"))).convert("RGB")
    digest = hashlib.sha1(
        f"{doc.id}:{page_index}:{x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}".encode("utf-8")
    ).hexdigest()[:12]
    result = _write(doc, image, digest)
    result.update({"page": page_index, "label": f"Page {page_index + 1}"})
    return result


def store_upload(doc: Document, data: bytes) -> dict:
    """Keep a picture the user already has, as a PNG in the document cache."""
    if not data:
        raise ValueError("That image file is empty.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"That image is larger than {MAX_UPLOAD_BYTES // (1024 * 1024)} MB."
        )
    try:
        with Image.open(io.BytesIO(data)) as opened:
            image = ImageOps.exif_transpose(opened)
            if image.mode == "RGBA":
                canvas = Image.new("RGB", image.size, "white")
                canvas.paste(image, mask=image.split()[-1])
                image = canvas
            else:
                image = image.convert("RGB")
            image.thumbnail((MAX_SIDE, MAX_SIDE), Image.LANCZOS)
    except Exception as exc:  # PIL raises a different type per bad format
        raise ValueError(
            "Couldn't read that image. Use a PNG, JPG or WEBP file."
        ) from exc
    digest = hashlib.sha1(data).hexdigest()[:12]
    return _write(doc, image, digest)
