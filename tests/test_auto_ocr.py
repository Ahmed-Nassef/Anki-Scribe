"""Automatic OCR: the worker, persistence and progress status."""

from __future__ import annotations

import time

import pymupdf
import pytest

import app.store as store_module
from app.store import Store


def scanned_pdf(tmp_path, pages=1):
    pdf = pymupdf.open()
    for _ in range(pages):
        pdf.new_page(width=600, height=800)
    path = tmp_path / "scan.pdf"
    path.write_bytes(pdf.tobytes())
    pdf.close()
    return path


def fake_lines(image_path, width):
    return [
        {
            "text": "Scanned beta blocker text.",
            "x0": 40.0,
            "y0": 80.0,
            "x1": 420.0,
            "y1": 100.0,
        }
    ]


def test_scanned_pdf_is_marked_for_ocr(tmp_path):
    store = Store(tmp_path / "documents")
    doc = store.create_pdf(scanned_pdf(tmp_path), "scan.pdf")
    assert doc.pages
    assert all(page.needs_ocr for page in doc.pages)
    status = store.ocr_status(doc)
    assert status["pending"] == 1
    assert status["total"] == 1
    assert status["running"] is False


def test_background_worker_fills_every_scanned_page(tmp_path, monkeypatch):
    store = Store(tmp_path / "documents")
    doc = store.create_pdf(scanned_pdf(tmp_path, pages=2), "scan.pdf")
    monkeypatch.setattr(store_module, "ocr_lines", fake_lines)

    status = store.start_ocr(doc, background=False)
    assert status["pending"] == 0
    assert status["done"] == 2
    assert status["total"] == 2
    assert status["percent"] == 100
    assert status["finished"] is True
    for page in doc.pages:
        assert page.needs_ocr is False
        assert page.ocr_done is True
        assert page.lines[0]["text"] == "Scanned beta blocker text."

    # The lines are written to meta.json, so reopening the app must not OCR
    # the same pages again.
    reloaded = Store(tmp_path / "documents").require(doc.id)
    assert all(page.lines for page in reloaded.pages)
    assert all(not page.needs_ocr for page in reloaded.pages)


def test_threaded_worker_reaches_finished_status(tmp_path, monkeypatch):
    store = Store(tmp_path / "documents")
    doc = store.create_pdf(scanned_pdf(tmp_path), "scan.pdf")
    monkeypatch.setattr(store_module, "ocr_lines", fake_lines)

    store.start_ocr(doc)
    deadline = time.time() + 5
    status = store.ocr_status(doc)
    while status["running"] and time.time() < deadline:
        time.sleep(0.02)
        status = store.ocr_status(doc)
    assert status["running"] is False
    assert status["pending"] == 0
    assert status["done"] == 1


def test_worker_records_an_ocr_engine_error(tmp_path, monkeypatch):
    store = Store(tmp_path / "documents")
    doc = store.create_pdf(scanned_pdf(tmp_path), "scan.pdf")

    def no_engine(image_path, width):
        raise RuntimeError("Windows OCR is not installed")

    monkeypatch.setattr(store_module, "ocr_lines", no_engine)
    status = store.start_ocr(doc, background=False)
    assert status["pending"] == 1
    assert status["running"] is False
    assert "Windows OCR" in status["error"]
    assert doc.pages[0].needs_ocr is True


def test_text_pdf_needs_no_ocr(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 100), "Text already exists.", fontsize=13)
    path = tmp_path / "text.pdf"
    path.write_bytes(pdf.tobytes())
    pdf.close()
    store = Store(tmp_path / "documents")
    doc = store.create_pdf(path, "text.pdf")
    status = store.start_ocr(doc)
    assert status["pending"] == 0
    assert status["total"] == 0
    assert status["finished"] is True


def test_cancel_before_start_is_safe(tmp_path):
    store = Store(tmp_path / "documents")
    doc = store.create_pdf(scanned_pdf(tmp_path), "scan.pdf")
    status = store.cancel_ocr(doc)
    assert status["cancelled"] is False
    assert status["pending"] == 1
