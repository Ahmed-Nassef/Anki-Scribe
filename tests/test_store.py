import threading

import pymupdf
import pytest
from PIL import Image

from app.ocr import order_lines
from app.store import Store


def make_pdf(path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 80), "Cardiology Lecture 3", fontsize=20)
    page.insert_text((60, 130), "Beta blockers reduce heart rate.", fontsize=13)
    page.insert_text((60, 160), "Metoprolol is cardioselective.", fontsize=13)
    pdf.save(path)
    pdf.close()


def make_table_pdf(path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 70), "Beta blocker comparison", fontsize=16)
    rows = [
        ["Drug", "Mechanism", "Adverse effect"],
        ["Metoprolol", "Beta-1 blockade", "Bradycardia"],
        ["Atenolol", "Beta-1 blockade", "Fatigue"],
        ["Propranolol", "Non-selective", "Bronchospasm"],
    ]
    x0, y0, row_height = 60, 100, 34
    col_widths = [120, 180, 160]
    lines_x = [x0]
    for width in col_widths:
        lines_x.append(lines_x[-1] + width)
    for xline in lines_x:
        page.draw_line((xline, y0), (xline, y0 + row_height * len(rows)), width=0.8)
    for row in range(len(rows) + 1):
        page.draw_line(
            (x0, y0 + row * row_height),
            (lines_x[-1], y0 + row * row_height),
            width=0.8,
        )
    for row_index, row in enumerate(rows):
        for col_index, cell in enumerate(row):
            page.insert_text(
                (lines_x[col_index] + 5, y0 + row_index * row_height + 22),
                cell,
                fontsize=10,
            )
    page.insert_text((60, 300), "Beta blockers lower myocardial oxygen demand.", fontsize=12)
    pdf.save(path)
    pdf.close()


def test_pdf_text_and_render(tmp_path):
    source = tmp_path / "lecture.pdf"
    make_pdf(source)

    store = Store(tmp_path / "documents")
    doc = store.create_pdf(source, "lecture.pdf")
    assert doc.kind == "pdf"
    assert len(doc.pages) == 1
    texts = [line["text"] for line in doc.pages[0].lines]
    assert "Cardiology Lecture 3" in texts
    assert any("Beta blockers" in text for text in texts)

    image_path = store.render_page(doc, 0)
    assert image_path.exists()
    with Image.open(image_path) as image:
        assert image.size == (doc.pages[0].width, doc.pages[0].height)

    lines, used_ocr = store.page_lines(doc, 0)
    assert lines and used_ocr is False


def test_coverage_reports_text_and_image_pages(tmp_path):
    source = tmp_path / "lecture.pdf"
    make_pdf(source)
    store = Store(tmp_path / "documents")
    doc = store.create_pdf(source, "lecture.pdf")

    coverage = store.coverage(doc)
    assert coverage["pageCount"] == 1
    assert coverage["contentPages"] == 1
    assert coverage["textPages"] == 1
    assert coverage["imagePages"] == 0
    assert coverage["textCharacters"] > 0
    assert coverage["pages"][0]["needsOcr"] is False
    assert coverage["pages"][0]["imageArea"] == 0.0

    image_pdf = tmp_path / "scan.pdf"
    png = tmp_path / "scan.png"
    Image.new("RGB", (300, 400), "white").save(png)
    pdf = pymupdf.open()
    page = pdf.new_page(width=300, height=400)
    page.insert_image(pymupdf.Rect(0, 0, 300, 400), filename=str(png))
    pdf.save(image_pdf)
    pdf.close()

    scanned = store.create_pdf(image_pdf, "scan.pdf")
    scan_coverage = store.coverage(scanned)
    assert scan_coverage["contentPages"] == 1
    assert scan_coverage["textPages"] == 0
    assert scan_coverage["imagePages"] == 1
    assert scan_coverage["pages"][0]["needsOcr"] is True
    assert scan_coverage["pages"][0]["imageArea"] > 0.5


def test_documents_reload_from_disk(tmp_path):
    source = tmp_path / "lecture.pdf"
    make_pdf(source)
    store = Store(tmp_path / "documents")
    doc = store.create_pdf(source, "lecture.pdf")

    reopened = Store(tmp_path / "documents")
    loaded = reopened.get(doc.id)
    assert loaded is not None
    assert loaded.filename == "lecture.pdf"
    assert [line["text"] for line in loaded.pages[0].lines][0] == "Cardiology Lecture 3"


def test_order_lines_two_columns():
    left = [
        {"text": f"left {i}", "x0": 40, "y0": 100 + i * 20, "x1": 420, "y1": 112 + i * 20}
        for i in range(5)
    ]
    right = [
        {"text": f"right {i}", "x0": 520, "y0": 100 + i * 20, "x1": 900, "y1": 112 + i * 20}
        for i in range(5)
    ]
    mixed = [right[0], left[0], right[1], left[1], right[2], left[2], right[3], left[3], right[4], left[4]]
    ordered = order_lines(mixed, 1000)
    assert [line["text"] for line in ordered] == [
        "left 0", "left 1", "left 2", "left 3", "left 4",
        "right 0", "right 1", "right 2", "right 3", "right 4",
    ]


def test_scanned_pdf_uses_ocr_without_deadlock(tmp_path, monkeypatch):
    source = tmp_path / "scan.pdf"
    pdf = pymupdf.open()
    pdf.new_page(width=600, height=800)  # deliberately no text layer
    pdf.save(source)
    pdf.close()

    store = Store(tmp_path / "documents")
    doc = store.create_pdf(source, "scan.pdf")
    assert doc.pages[0].needs_ocr is True

    monkeypatch.setattr(
        "app.store.ocr_lines",
        lambda path, width: [
            {"text": "Scanned line", "x0": 10, "y0": 10, "x1": 200, "y1": 24}
        ],
    )

    result = {}

    def read():
        result["lines"], result["ocr"] = store.page_lines(doc, 0)

    worker = threading.Thread(target=read)
    worker.start()
    worker.join(timeout=10)
    assert not worker.is_alive(), "page_lines deadlocked on the OCR path"
    assert result["ocr"] is True
    assert result["lines"][0]["text"] == "Scanned line"

    lines, used_ocr = store.page_lines(doc, 0)
    assert used_ocr is False
    assert lines[0]["text"] == "Scanned line"


def test_extract_chunks_includes_text_and_tables(tmp_path):
    source = tmp_path / "table.pdf"
    make_table_pdf(source)
    store = Store(tmp_path / "documents")
    doc = store.create_pdf(source, "table.pdf")

    result = store.extract_chunks(doc)
    assert result["tableCount"] == 1
    assert result["pageCount"] == 1
    assert len(result["chunks"]) == 1
    assert result["chunks"][0]["label"] == "Page 1"

    text = "\n".join(chunk["text"] for chunk in result["chunks"])
    assert "--- Page 1 ---" in text
    assert "| Drug | Mechanism | Adverse effect |" in text
    assert "| Metoprolol | Beta-1 blockade | Bradycardia |" in text
    assert "Beta blockers lower myocardial oxygen demand." in text
    # Cell text should appear once: the table replaces the lines inside its box.
    assert text.count("Metoprolol") == 1
    assert text.count("Bradycardia") == 1


def test_unwritable_data_folder_explains_itself(tmp_path):
    store = Store(tmp_path / "documents")
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    store.root = blocker

    with pytest.raises(ValueError) as info:
        store.create_pdf_path(tmp_path / "lecture.pdf")

    message = str(info.value)
    assert "couldn't write to its data folder" in message
    assert "Troubleshooting" in message


def test_split_text_respects_limit():
    from app.store import _split_text

    text = "\n".join(f"line {index} " + "x" * 80 for index in range(200))
    parts = _split_text(text, 2000)
    assert len(parts) > 1
    assert all(len(part) <= 2000 for part in parts)
    assert "line 0" in parts[0]
    assert "line 199" in parts[-1]
