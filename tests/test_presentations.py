"""Presentation import: a deck becomes a synthetic PDF, then behaves like one."""

from __future__ import annotations

import io
import zipfile

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import presentations
from app.config import Settings
from app.drafts import DraftStore
from app.library import Library
from app.main import create_app
from app.sent import SentStore
from app.store import Store

P_NS = "http://schemas.openxmlformats.org/presentationml/2006/main"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"


def text_shape(text: str, x: int, y: int, cx: int, cy: int) -> str:
    return f"""
      <p:sp>
        <p:spPr>
          <a:xfrm><a:off x="{x}" y="{y}"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>
        </p:spPr>
        <p:txBody><a:p><a:r><a:t>{text}</a:t></a:r></a:p></p:txBody>
      </p:sp>"""


def table_frame(rows: list[list[str]]) -> str:
    body = ""
    for row in rows:
        cells = "".join(
            f"<a:tc><a:txBody><a:p><a:r><a:t>{cell}</a:t></a:r></a:p></a:txBody></a:tc>"
            for cell in row
        )
        body += f"<a:tr>{cells}</a:tr>"
    return f"""
      <p:graphicFrame>
        <p:xfrm><a:off x="914400" y="1828800"/><a:ext cx="5486400" cy="1828800"/></p:xfrm>
        <a:graphic><a:graphicData><a:tbl>{body}</a:tbl></a:graphicData></a:graphic>
      </p:graphicFrame>"""


def picture_shape(rid: str) -> str:
    return f"""
      <p:pic>
        <p:spPr>
          <a:xfrm><a:off x="1828800" y="1828800"/><a:ext cx="2743200" cy="1828800"/></a:xfrm>
        </p:spPr>
        <p:blipFill><a:blip r:embed="{rid}"/></p:blipFill>
      </p:pic>"""


def slide_xml(shapes: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<p:sld xmlns:p="{P_NS}" xmlns:a="{A_NS}" xmlns:r="{R_NS}">'
        f"<p:cSld><p:spTree>{shapes}</p:spTree></p:cSld></p:sld>"
    )


def make_pptx(path, slides: list[str], with_image: bool = False):
    """Write a minimal but structurally correct .pptx."""
    ids = "".join(
        f'<p:sldId id="{255 + index}" r:id="rId{index}"/>'
        for index in range(1, len(slides) + 1)
    )
    presentation = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<p:presentation xmlns:p="{P_NS}" xmlns:r="{R_NS}">'
        f"<p:sldIdLst>{ids}</p:sldIdLst>"
        '<p:sldSz cx="12192000" cy="6858000"/>'
        "</p:presentation>"
    )
    rels = "".join(
        f'<Relationship Id="rId{index}" Type="{R_NS}/slide" '
        f'Target="slides/slide{index}.xml"/>'
        for index in range(1, len(slides) + 1)
    )
    presentation_rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Relationships xmlns="{REL_NS}">{rels}</Relationships>'
    )

    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("ppt/presentation.xml", presentation)
        archive.writestr("ppt/_rels/presentation.xml.rels", presentation_rels)
        for index, body in enumerate(slides, start=1):
            archive.writestr(f"ppt/slides/slide{index}.xml", slide_xml(body))
        if with_image:
            buffer = io.BytesIO()
            Image.new("RGB", (64, 64), (190, 205, 200)).save(buffer, "PNG")
            archive.writestr("ppt/media/image1.png", buffer.getvalue())
            archive.writestr(
                "ppt/slides/_rels/slide2.xml.rels",
                '<?xml version="1.0" encoding="UTF-8"?>'
                f'<Relationships xmlns="{REL_NS}">'
                f'<Relationship Id="rId9" Type="{R_NS}/image" '
                'Target="../media/image1.png"/></Relationships>',
            )
    return path


def deck(tmp_path, slides=None, with_image=False):
    if slides is None:
        slides = [
            text_shape("Cardiology Lecture 3", 914400, 457200, 9144000, 900000),
            text_shape("Beta blockers reduce heart rate", 914400, 1600200, 9144000, 1200000)
            + (picture_shape("rId9") if with_image else ""),
        ]
    return make_pptx(tmp_path / "lecture.pptx", slides, with_image=with_image)


# -- conversion ----------------------------------------------------------


def test_a_deck_becomes_a_page_per_slide(tmp_path):
    source = deck(tmp_path)
    target = tmp_path / "out.pdf"
    assert presentations.convert(source, target) == 2

    with pymupdf.open(target) as pdf:
        assert pdf.page_count == 2
        # 16:9 at 960 x 540 points.
        assert round(pdf[0].rect.width) == 960
        assert round(pdf[0].rect.height) == 540
        assert "Cardiology Lecture 3" in pdf[0].get_text()
        assert "Beta blockers reduce heart rate" in pdf[1].get_text()


def test_table_text_survives(tmp_path):
    source = deck(tmp_path, [table_frame([["Metoprolol", "Beta-1"], ["Propranolol", "Beta-2"]])])
    target = tmp_path / "out.pdf"
    presentations.convert(source, target)
    with pymupdf.open(target) as pdf:
        text = pdf[0].get_text()
    assert "Metoprolol" in text and "Beta-1" in text
    assert "Propranolol" in text
    # A table survives as a Markdown grid, not a run-on row.
    assert "| Metoprolol | Beta-1 |" in text
    assert "| --- | --- |" in text


def test_pictures_are_embedded(tmp_path):
    source = deck(tmp_path, with_image=True)
    target = tmp_path / "out.pdf"
    presentations.convert(source, target)
    with pymupdf.open(target) as pdf:
        assert pdf[1].get_image_info()


def test_shape_without_geometry_keeps_its_text(tmp_path):
    shapes = """
      <p:sp>
        <p:txBody><a:p><a:r><a:t>A title with no explicit position</a:t></a:r></a:p></p:txBody>
      </p:sp>"""
    source = deck(tmp_path, [shapes])
    target = tmp_path / "out.pdf"
    presentations.convert(source, target)
    with pymupdf.open(target) as pdf:
        assert "A title with no explicit position" in pdf[0].get_text()


def test_not_a_zip_is_rejected(tmp_path):
    source = tmp_path / "fake.pptx"
    source.write_bytes(b"this is not a deck")
    with pytest.raises(ValueError, match="PowerPoint"):
        presentations.convert(source, tmp_path / "out.pdf")


def test_a_deck_without_slides_is_rejected(tmp_path):
    source = tmp_path / "empty.pptx"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("ppt/presentation.xml", "<p:presentation/>")
    with pytest.raises(ValueError, match="no slides"):
        presentations.convert(source, tmp_path / "out.pdf")


# -- through the store and the API --------------------------------------


def test_store_imports_a_presentation_as_a_document(tmp_path):
    source = deck(tmp_path)
    store = Store(tmp_path / "documents")
    doc = store.create_presentation_path(source, "lecture.pptx")

    assert doc.kind == "pdf"
    assert doc.filename == "lecture.pptx"
    assert len(doc.pages) == 2
    assert doc.source.is_file()
    assert any("Cardiology" in line["text"] for line in doc.pages[0].lines)


def test_api_upload_accepts_pptx_and_serves_lines(tmp_path):
    source = deck(tmp_path)
    app = create_app(
        store=Store(tmp_path / "documents"),
        settings=Settings(api_key="sk-test", anki_url="http://127.0.0.1:9"),
        library=Library(tmp_path / "library.json"),
        drafts=DraftStore(tmp_path / "drafts.json"),
        sent=SentStore(tmp_path / "sent.json"),
    )
    client = TestClient(app, base_url="http://127.0.0.1")

    response = client.post(
        "/api/documents",
        files={"file": ("lecture.pptx", source.read_bytes(), "application/vnd.ms-powerpoint")},
    )
    assert response.status_code == 200, response.text
    doc = response.json()
    assert doc["kind"] == "pdf"
    assert doc["pageCount"] == 2

    lines = client.get(f"/api/documents/{doc['id']}/pages/0/lines").json()
    texts = " ".join(line["text"] for line in lines["lines"])
    assert "Cardiology" in texts


def test_library_accepts_a_pptx_path(tmp_path):
    source = deck(tmp_path)
    library = Library(tmp_path / "library.json")
    file, added = library.add_file(str(source))
    assert added is True
    assert file.name == "lecture.pptx"
