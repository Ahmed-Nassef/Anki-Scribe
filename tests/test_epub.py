import zipfile
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient

from app import chapters, epub
from app.config import Settings
from app.drafts import DraftStore
from app.library import Library
from app.main import create_app
from app.sent import SentStore
from app.store import Store

BOOK = [
    ("Chapter 1: The Heart", "The heart pumps blood through the body. " * 30),
    ("Chapter 2: The Lungs", "The lungs exchange oxygen and carbon dioxide. " * 30),
    ("Chapter 3: The Kidneys", "The kidneys filter blood and make urine. " * 30),
]

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>"""

NAV = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
<head><title>Contents</title></head>
<body><nav epub:type="toc"><ol>
{items}
</ol></nav></body>
</html>"""


def build_epub(
    path: Path,
    book: list[tuple[str, str]] = BOOK,
    *,
    nav: bool = True,
    ncx: bool = False,
    nav_items: str | None = None,
) -> Path:
    """A small but valid EPUB 3 (and optionally an EPUB 2 NCX)."""
    manifest = []
    spine = []
    documents = []
    for number, (title, body) in enumerate(book, start=1):
        name = f"ch{number}.xhtml"
        documents.append(
            (
                f"OEBPS/{name}",
                f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head>
<body><h1 id="ch{number}">{title}</h1><p>{body}</p></body></html>""",
            )
        )
        manifest.append(f'<item id="c{number}" href="{name}" media-type="application/xhtml+xml"/>')
        spine.append(f'<itemref idref="c{number}"/>')

    if nav:
        manifest.append(
            '<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>'
        )
        spine.append('<itemref idref="nav" linear="no"/>')
        items = nav_items or "\n".join(
            f'    <li><a href="ch{number}.xhtml">{title}</a></li>'
            for number, (title, _) in enumerate(book, start=1)
        )
        documents.append(("OEBPS/nav.xhtml", NAV.format(items=items)))

    if ncx:
        manifest.append(
            '<item id="ncx" href="toc.ncx" media-type="application/x-dtbncx+xml"/>'
        )
        points = "\n".join(
            f"""    <navPoint id="n{number}" playOrder="{number}">
      <navLabel><text>{title}</text></navLabel>
      <content src="ch{number}.xhtml"/>
    </navPoint>"""
            for number, (title, _) in enumerate(book, start=1)
        )
        documents.append(
            (
                "OEBPS/toc.ncx",
                f"""<?xml version="1.0" encoding="utf-8"?>
<ncx xmlns="http://www.daisy.org/z3986/2005/ncx/" version="2005-1">
  <navMap>
{points}
  </navMap>
</ncx>""",
            )
        )

    toc_attribute = ' toc="ncx"' if ncx else ""
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:test</dc:identifier>
    <dc:title>A Book of Organs</dc:title>
    <dc:creator>Dr Test</dc:creator>
  </metadata>
  <manifest>
{chr(10).join(manifest)}
  </manifest>
  <spine{toc_attribute}>
{chr(10).join(spine)}
  </spine>
</package>"""
    documents.append(("OEBPS/content.opf", opf))

    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_STORED)
        archive.writestr("META-INF/container.xml", CONTAINER)
        for name, content in documents:
            archive.writestr(name, content)
    return path


@pytest.fixture
def client(tmp_path):
    store = Store(tmp_path / "documents")
    app = create_app(
        store=store,
        settings=Settings(api_key="", anki_url="http://127.0.0.1:9"),
        library=Library(tmp_path / "library.json"),
        drafts=DraftStore(tmp_path / "drafts.json"),
        sent=SentStore(tmp_path / "sent.json"),
    )
    return TestClient(app, base_url="http://127.0.0.1")


def test_convert_lays_out_chapters_on_their_own_pages(tmp_path):
    source = build_epub(tmp_path / "book.epub")
    target = tmp_path / "book.pdf"
    info = epub.convert(source, target)

    assert info["title"] == "A Book of Organs"
    assert info["author"] == "Dr Test"
    assert info["pageCount"] == 3
    assert [entry[1] for entry in info["toc"]] == [
        "Chapter 1: The Heart",
        "Chapter 2: The Lungs",
        "Chapter 3: The Kidneys",
    ]
    assert [entry[2] for entry in info["toc"]] == [1, 2, 3]

    # The stored text is the book's own words, with no page markers added.
    first = info["pages"][0]["lines"]
    assert first[0]["text"] == "Chapter 1: The Heart"
    assert any("pumps blood" in line["text"] for line in first)
    assert all(line["x1"] > line["x0"] for line in first)

    with pymupdf.open(target) as pdf:
        assert pdf.page_count == 3
        assert "The heart pumps blood" in pdf[0].get_text()


def test_epub_document_plans_real_chapters(tmp_path):
    source = build_epub(tmp_path / "book.epub")
    store = Store(tmp_path / "documents")
    doc = store.create_epub_path(source, "book.epub")

    assert doc.kind == "pdf"
    assert doc.format == "epub"
    assert len(doc.pages) == 3
    # Drafts are keyed by the file the user opened, not by the cache it becomes.
    assert doc.summary()["originPath"] == str(source)

    plan = chapters.build_plan(doc)
    assert plan["strategy"] == "toc"
    assert [chapter["title"] for chapter in plan["chapters"]] == [
        title for title, _ in BOOK
    ]
    assert [(chapter["startPage"], chapter["endPage"]) for chapter in plan["chapters"]] == [
        (1, 1),
        (2, 2),
        (3, 3),
    ]
    assert plan["sourceTitle"] == "book"

    second = store.extract_chunks(doc, start_page=2, end_page=2)
    text = " ".join(chunk["text"] for chunk in second["chunks"])
    assert "lungs exchange oxygen" in text
    assert "kidneys" not in text


def test_epub2_ncx_contents_are_read(tmp_path):
    source = build_epub(tmp_path / "old.epub", nav=False, ncx=True)
    store = Store(tmp_path / "documents")
    doc = store.create_epub_path(source, "old.epub")
    plan = chapters.build_plan(doc)
    assert plan["strategy"] == "toc"
    assert plan["chapterCount"] == 3
    assert plan["chapters"][1]["title"] == "Chapter 2: The Lungs"


def test_epub_without_contents_falls_back_to_headings(tmp_path):
    source = build_epub(tmp_path / "plain.epub", nav=False)
    store = Store(tmp_path / "documents")
    doc = store.create_epub_path(source, "plain.epub")
    plan = chapters.build_plan(doc)
    assert plan["strategy"] in ("toc", "headings")
    assert [chapter["title"] for chapter in plan["chapters"]] == [
        title for title, _ in BOOK
    ]


def test_a_part_heading_does_not_rename_the_chapters_under_it(tmp_path):
    items = """    <li><span>Part One: The Chest</span>
      <ol>
        <li><a href="ch1.xhtml">Chapter 1: The Heart</a></li>
        <li><a href="ch2.xhtml">Chapter 2: The Lungs</a></li>
        <li><a href="ch3.xhtml">Chapter 3: The Kidneys</a></li>
      </ol>
    </li>"""
    source = build_epub(tmp_path / "parts.epub", nav_items=items)
    store = Store(tmp_path / "documents")
    doc = store.create_epub_path(source, "parts.epub")
    plan = chapters.build_plan(doc)
    assert [chapter["title"] for chapter in plan["chapters"]] == [
        "Chapter 1: The Heart",
        "Chapter 2: The Lungs",
        "Chapter 3: The Kidneys",
    ]
    assert [(chapter["startPage"], chapter["endPage"]) for chapter in plan["chapters"]] == [
        (1, 1),
        (2, 2),
        (3, 3),
    ]


def test_appendix_titles_do_not_narrow_the_chapters(tmp_path):
    """A book of "Strategy one…" with appendices must not split into appendices."""
    items = """    <li><span>Part One</span>
      <ol>
        <li><a href="ch1.xhtml">Strategy one</a></li>
        <li><a href="ch2.xhtml">Strategy two</a></li>
        <li><a href="ch3.xhtml">Appendix A: Numbers</a></li>
        <li><a href="ch4.xhtml">Appendix B: Tables</a></li>
      </ol>
    </li>"""
    book = [(f"Chapter {number}", f"Body of part {number}. " * 20) for number in range(1, 5)]
    source = build_epub(tmp_path / "strategies.epub", book=book, nav_items=items)
    store = Store(tmp_path / "documents")
    doc = store.create_epub_path(source, "strategies.epub")
    plan = chapters.build_plan(doc)
    assert [chapter["title"] for chapter in plan["chapters"]] == [
        "Strategy one",
        "Strategy two",
        "Appendix A: Numbers",
        "Appendix B: Tables",
    ]


def test_navigation_pages_are_not_chapters(tmp_path):
    items = """    <li><a href="ch1.xhtml">Cover</a></li>
    <li><a href="ch1.xhtml">Contents</a></li>
    <li><a href="ch1.xhtml">Chapter 1: The Heart</a></li>
    <li><a href="ch2.xhtml">Chapter 2: The Lungs</a></li>
    <li><a href="ch2.xhtml">Index</a></li>"""
    source = build_epub(
        tmp_path / "front.epub", book=BOOK[:2], nav_items=items
    )
    store = Store(tmp_path / "documents")
    doc = store.create_epub_path(source, "front.epub")
    plan = chapters.build_plan(doc)
    assert [chapter["title"] for chapter in plan["chapters"]] == [
        "Chapter 1: The Heart",
        "Chapter 2: The Lungs",
    ]


def test_epub_document_survives_a_restart(tmp_path):
    source = build_epub(tmp_path / "book.epub")
    root = tmp_path / "documents"
    doc_id = Store(root).create_epub_path(source, "book.epub").id

    reloaded = Store(root).require(doc_id)
    assert reloaded.format == "epub"
    assert len(reloaded.pages) == 3
    assert reloaded.summary()["format"] == "epub"


def test_a_file_that_is_not_an_epub_is_rejected(tmp_path):
    broken = tmp_path / "book.epub"
    broken.write_text("not a zip", encoding="utf-8")
    store = Store(tmp_path / "documents")
    with pytest.raises(ValueError, match="isn't an EPUB"):
        store.create_epub_path(broken, "book.epub")


def test_epub_upload_plans_chapters_and_splits(client, tmp_path):
    source = build_epub(tmp_path / "book.epub")
    with source.open("rb") as handle:
        uploaded = client.post(
            "/api/documents",
            files={"file": ("book.epub", handle, "application/epub+zip")},
        )
    assert uploaded.status_code == 200, uploaded.text
    doc = uploaded.json()
    assert doc["kind"] == "pdf"
    assert doc["format"] == "epub"
    assert doc["pageCount"] == 3

    plan = client.get(f"/api/documents/{doc['id']}/chapters")
    assert plan.status_code == 200, plan.text
    assert plan.json()["chapterCount"] == 3

    folder = tmp_path / "chapters"
    split = client.post(
        f"/api/documents/{doc['id']}/split", json={"output_dir": str(folder)}
    )
    assert split.status_code == 200, split.text
    payload = split.json()
    assert payload["chapterCount"] == 3
    assert len(list(folder.glob("*.md"))) == 3
    assert (folder / "manifest.json").is_file()
