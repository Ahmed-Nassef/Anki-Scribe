import json
from pathlib import Path

import pymupdf
import pytest

from app import chapters, split
from app.config import data_dir
from app.store import Store


def make_book(path: Path, pages: int = 6) -> Path:
    """A six-page PDF with three chapters and bookmarks for them."""
    pdf = pymupdf.open()
    for index in range(pages):
        page = pdf.new_page(width=600, height=800)
        page.insert_text((60, 60), f"Content page {index + 1}", fontsize=12)
        page.insert_text((60, 120), f"Body text for page {index + 1}.", fontsize=12)
    pdf.set_toc([[1, "Chapter One", 1], [1, "Chapter Two", 3], [1, "Chapter Three", 5]])
    pdf.save(path)
    pdf.close()
    return path


@pytest.fixture
def book(tmp_path):
    store = Store(tmp_path / "documents")
    doc = store.create_pdf_path(make_book(tmp_path / "book.pdf"), "Gray's Anatomy.pdf")
    return store, doc, chapters.build_plan(doc)


def test_split_writes_one_markdown_file_per_chapter(book, tmp_path):
    store, doc, plan = book
    folder = tmp_path / "chapters"
    result = split.split_document(store, doc, plan, folder)

    assert result["chapterCount"] == 3
    assert result["strategy"] == "toc"
    assert result["folder"] == str(folder)
    assert sorted(result["files"]) == [
        "01 - Chapter One.md",
        "02 - Chapter Two.md",
        "03 - Chapter Three.md",
    ]
    assert result["characters"] > 0

    first = (folder / "01 - Chapter One.md").read_text(encoding="utf-8")
    assert first.startswith('---\nbook: "Gray\'s Anatomy"\nchapter: 1\n')
    assert 'title: "Chapter One"' in first
    assert 'pages: "1-2"' in first
    assert "Content page 1" in first
    assert "Content page 3" not in first

    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["source"] == "Gray's Anatomy.pdf"
    assert manifest["chapterCount"] == 3
    assert manifest["chapters"][1]["file"] == "02 - Chapter Two.md"
    assert manifest["chapters"][1]["startPage"] == 3
    assert manifest["chapters"][1]["characters"] > 0


def test_split_defaults_to_a_folder_under_the_data_directory(book):
    store, doc, plan = book
    result = split.split_document(store, doc, plan)
    folder = Path(result["folder"])
    assert folder.is_dir()
    assert folder.parent == data_dir() / "splits"
    assert (folder / "manifest.json").is_file()


def test_split_sanitizes_chapter_titles(book, tmp_path):
    store, doc, plan = book
    plan = json.loads(json.dumps(plan))
    plan["chapters"][0]["title"] = 'Part 1/2: <Intro>?'
    folder = tmp_path / "odd"
    result = split.split_document(store, doc, plan, folder)
    name = result["files"][0]
    assert name == "01 - Part 1 2 Intro.md"
    assert not any(character in name for character in '<>:"/\\|?*')
    assert '# Part 1/2: <Intro>?' in (folder / name).read_text(encoding="utf-8")


def test_resplit_removes_files_from_the_previous_run(book, tmp_path):
    store, doc, plan = book
    folder = tmp_path / "chapters"
    split.split_document(store, doc, plan, folder)
    assert len(list(folder.glob("*.md"))) == 3

    fewer = json.loads(json.dumps(plan))
    fewer["chapters"] = fewer["chapters"][:2]
    fewer["chapters"][1]["endPage"] = len(doc.pages)
    result = split.split_document(store, doc, fewer, folder)
    assert result["chapterCount"] == 2
    assert sorted(path.name for path in folder.glob("*.md")) == [
        "01 - Chapter One.md",
        "02 - Chapter Two.md",
    ]


def test_split_rejects_a_relative_output_folder(book):
    store, doc, plan = book
    with pytest.raises(ValueError, match="full folder path"):
        split.split_document(store, doc, plan, "chapters")


def test_split_rejects_a_plan_without_chapters(book, tmp_path):
    store, doc, _ = book
    with pytest.raises(ValueError, match="no chapters"):
        split.split_document(store, doc, {"chapters": []}, tmp_path / "none")


def test_slug_truncates_at_a_word_boundary():
    long_title = "101 Essays That Will Change The Way You Think (Brianna Wiest) (Z-Library)"
    assert split.slug(long_title) == "101 Essays That Will Change The Way You Think (Brianna Wiest)"
    assert split.slug("  A/B:  test  ") == "A B test"
    assert split.slug("") == "untitled"


def test_split_writes_a_transcript_by_timestamp(tmp_path):
    source = tmp_path / "lecture.srt"
    source.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\nChapter 1\n\n"
        "2\n00:00:04,000 --> 00:00:06,000\nBeta blockers reduce heart rate.\n\n"
        "3\n00:00:20,000 --> 00:00:22,000\nChapter 2\n\n"
        "4\n00:00:24,000 --> 00:00:26,000\nACE inhibitors reduce afterload.\n",
        encoding="utf-8",
    )
    store = Store(tmp_path / "documents")
    doc = store.create_transcript(source, "lecture.srt")
    plan = chapters.build_plan(doc)

    folder = tmp_path / "talk"
    result = split.split_document(store, doc, plan, folder)
    assert result["chapterCount"] == 2
    first = (folder / result["files"][0]).read_text(encoding="utf-8")
    assert "Beta blockers reduce heart rate." in first
    assert "ACE inhibitors" not in first
    assert "segments:" in first
