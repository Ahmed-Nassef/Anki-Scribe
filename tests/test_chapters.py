from pathlib import Path

import pymupdf
import pytest

from app import chapters
from app.store import Store


def make_book(path: Path, pages: int = 4, toc: bool = True) -> None:
    pdf = pymupdf.open()
    for index in range(pages):
        page = pdf.new_page(width=600, height=800)
        if index == 0:
            page.insert_text((60, 60), "Chapter One", fontsize=20)
        if index == 2:
            page.insert_text((60, 60), "Chapter Two", fontsize=20)
        page.insert_text((60, 120), f"Content for page {index + 1}.", fontsize=12)
    if toc and pages >= 4:
        pdf.set_toc([[1, "Chapter One", 1], [1, "Chapter Two", 3]])
    pdf.save(path)
    pdf.close()


def test_toc_plan_uses_chapters_and_page_ranges(tmp_path):
    source = tmp_path / "book.pdf"
    make_book(source)
    store = Store(tmp_path / "docs")
    doc = store.create_pdf_path(source, "book.pdf")

    plan = chapters.build_plan(doc)
    assert plan["strategy"] == "toc"
    assert plan["sourceTitle"] == "book"
    assert plan["chapterCount"] == 2
    assert [chapter["title"] for chapter in plan["chapters"]] == [
        "Chapter One",
        "Chapter Two",
    ]
    assert plan["chapters"][0]["startPage"] == 1
    assert plan["chapters"][0]["endPage"] == 2
    assert plan["chapters"][1]["startPage"] == 3


def test_toc_subtitles_become_deck_paths(tmp_path):
    source = tmp_path / "sub.pdf"
    pdf = pymupdf.open()
    for index in range(6):
        page = pdf.new_page(width=600, height=800)
        page.insert_text((60, 60), f"Page {index + 1}", fontsize=14)
        page.insert_text((60, 120), f"Content {index + 1}", fontsize=12)
    pdf.set_toc(
        [
            [1, "Cardiology", 1],
            [2, "Beta Blockers", 2],
            [2, "ACE Inhibitors", 4],
        ]
    )
    pdf.save(source)
    pdf.close()

    store = Store(tmp_path / "docs")
    doc = store.create_pdf_path(source, "sub.pdf")
    plan = chapters.build_plan(doc)
    assert plan["strategy"] == "toc"
    assert len(plan["chapters"]) == 2
    assert plan["chapters"][0]["path"] == ["Cardiology", "Beta Blockers"]
    assert plan["chapters"][1]["path"] == ["Cardiology", "ACE Inhibitors"]


def test_heading_plan_when_no_toc(tmp_path):
    source = tmp_path / "headings.pdf"
    make_book(source, pages=6, toc=False)
    store = Store(tmp_path / "docs")
    doc = store.create_pdf_path(source, "headings.pdf")
    plan = chapters.build_plan(doc)
    assert plan["strategy"] == "headings"
    assert len(plan["chapters"]) >= 2
    assert plan["chapters"][0]["title"].startswith("Chapter One")


def test_fallback_plan_splits_large_file(tmp_path):
    source = tmp_path / "large.pdf"
    pdf = pymupdf.open()
    for index in range(24):
        page = pdf.new_page(width=600, height=800)
        page.insert_text((60, 120), f"Content for page {index + 1}.", fontsize=12)
    pdf.save(source)
    pdf.close()
    store = Store(tmp_path / "docs")
    doc = store.create_pdf_path(source, "large.pdf")
    plan = chapters.build_plan(doc)
    assert plan["strategy"] == "fallback"
    assert plan["chapterCount"] >= 2


def test_plan_from_proposals(tmp_path):
    source = tmp_path / "book.pdf"
    make_book(source)
    store = Store(tmp_path / "docs")
    doc = store.create_pdf_path(source, "book.pdf")
    fallback = chapters.build_plan(doc)
    proposed = [
        {"title": "Foundations", "subtitle": "Cells", "start": 1, "end": 2},
        {"title": "Cardiology", "subtitle": "", "start": 3, "end": 4},
    ]
    plan = chapters.plan_from_proposals(doc, proposed, fallback)
    assert plan is not None
    assert plan["strategy"] == "llm"
    assert plan["chapters"][0]["path"] == ["Foundations", "Cells"]
    assert plan["chapters"][1]["path"] == ["Cardiology"]


def test_plan_from_proposals_fills_gaps_and_edges(tmp_path):
    source = tmp_path / "book.pdf"
    make_book(source)
    store = Store(tmp_path / "docs")
    doc = store.create_pdf_path(source, "book.pdf")
    fallback = chapters.build_plan(doc)
    proposed = [
        {"title": "First", "start": 1, "end": 1},
        {"title": "Second", "start": 3, "end": 3},
    ]
    plan = chapters.plan_from_proposals(doc, proposed, fallback)
    assert plan is not None
    ranges = [(chapter["startPage"], chapter["endPage"]) for chapter in plan["chapters"]]
    cursor = 1
    for start, end in ranges:
        assert start == cursor
        assert end >= start
        cursor = end + 1
    assert cursor == len(doc.pages) + 1


def test_extract_chunks_respects_page_range(tmp_path):
    source = tmp_path / "book.pdf"
    make_book(source)
    store = Store(tmp_path / "docs")
    doc = store.create_pdf_path(source, "book.pdf")
    extract = store.extract_chunks(doc, start_page=3, end_page=4)
    assert extract["selectedPageCount"] == 2
    assert extract["chunks"]
    assert all(chunk["pages"][0] >= 3 for chunk in extract["chunks"])


def test_transcript_heading_plan_and_range(tmp_path):
    source = tmp_path / "lecture.srt"
    source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nChapter 1\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nBeta blockers reduce heart rate.\n\n"
        "3\n00:00:20,000 --> 00:00:22,000\nChapter 2\n\n"
        "4\n00:00:24,000 --> 00:00:26,000\nACE inhibitors reduce afterload.\n",
        encoding="utf-8",
    )
    store = Store(tmp_path / "docs")
    doc = store.create_transcript(source, "lecture.srt")
    plan = chapters.build_plan(doc)
    assert plan["kind"] == "transcript"
    assert plan["strategy"] == "headings"
    assert plan["chapterCount"] == 2
    assert plan["chapters"][0]["startSegment"] == 1

    extract = store.extract_chunks(doc, start_segment=3, end_segment=4)
    assert extract["selectedSegmentCount"] == 2
    assert extract["chunks"][0]["segments"][0] >= 3
