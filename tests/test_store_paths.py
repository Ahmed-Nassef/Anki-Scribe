import os

import pymupdf

from app.store import Store


def make_pdf(path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 80), "Path-based lecture", fontsize=18)
    page.insert_text((60, 120), "The original file should stay in place.", fontsize=12)
    pdf.save(path)
    pdf.close()


def test_create_pdf_path_does_not_copy_source(tmp_path):
    source = tmp_path / "lecture.pdf"
    make_pdf(source)
    original = source.read_bytes()

    store = Store(tmp_path / "documents")
    doc = store.create_pdf_path(source, "lecture.pdf")

    assert source.exists()
    assert source.read_bytes() == original
    assert doc.source_path == str(source)
    assert not (doc.directory / "source.pdf").exists()
    assert doc.pages[0].lines
    assert store.render_page(doc, 0).exists()


def test_path_document_reloads_with_source(tmp_path):
    source = tmp_path / "lecture.pdf"
    make_pdf(source)
    store = Store(tmp_path / "documents")
    doc = store.create_pdf_path(source)
    reopened = Store(tmp_path / "documents")
    loaded = reopened.get(doc.id)
    assert loaded is not None
    assert loaded.source_path == str(source)
    assert loaded.pages


def test_find_by_source_reuses_the_imported_document(tmp_path):
    source = tmp_path / "lecture.pdf"
    make_pdf(source)
    store = Store(tmp_path / "documents")
    doc = store.create_pdf_path(source)

    assert store.find_by_source(source).id == doc.id
    # The path survives a restart, so a library click does not re-extract it.
    assert Store(tmp_path / "documents").find_by_source(source).id == doc.id
    assert store.find_by_source(tmp_path / "other.pdf") is None


def test_a_changed_source_is_imported_again(tmp_path):
    source = tmp_path / "lecture.pdf"
    make_pdf(source)
    store = Store(tmp_path / "documents")
    doc = store.create_pdf_path(source)

    make_pdf(source)  # rewritten on disk
    os.utime(source, (doc.origin_mtime + 60, doc.origin_mtime + 60))
    assert store.find_by_source(source) is None
