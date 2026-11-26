import base64
import io

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

import app.main as main_module
from app import figures
from app.config import Settings
from app.drafts import DraftStore
from app.library import Library
from app.main import create_app
from app.sent import SentStore
from app.store import Store


def text_pdf(tmp_path, label="Mitral valve"):
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((60, 200), label, fontsize=12)
    source = tmp_path / "page.pdf"
    source.write_bytes(pdf.tobytes())
    pdf.close()
    return Store(tmp_path / "documents").create_pdf_path(source, "page.pdf")


def picture_pdf(tmp_path):
    buffer = io.BytesIO()
    Image.new("RGB", (80, 80), (200, 210, 205)).save(buffer, "PNG")
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_image(pymupdf.Rect(100, 100, 300, 300), stream=buffer.getvalue())
    source = tmp_path / "figure.pdf"
    source.write_bytes(pdf.tobytes())
    pdf.close()
    return Store(tmp_path / "documents").create_pdf_path(source, "figure.pdf")


def client_for(tmp_path):
    app = create_app(
        store=Store(tmp_path / "documents"),
        settings=Settings(api_key="sk-test", anki_url="http://127.0.0.1:9"),
        library=Library(tmp_path / "library.json"),
        drafts=DraftStore(tmp_path / "drafts.json"),
        sent=SentStore(tmp_path / "sent.json"),
    )
    return TestClient(app, base_url="http://127.0.0.1")


# A box in page-image pixels around the text at y=200pt (x2 on the page image).
TEXT_BOX = {"page": 0, "x0": 100, "y0": 380, "x1": 400, "y1": 430}


def test_build_writes_two_pngs(tmp_path):
    doc = text_pdf(tmp_path)
    result = figures.build(doc, 0, TEXT_BOX)

    assert figures.valid_name(result["masked"])
    assert figures.valid_name(result["revealed"])
    assert result["masked"].endswith("-m.png")
    assert result["revealed"].endswith("-r.png")
    for name in (result["masked"], result["revealed"]):
        path = doc.directory / name
        assert path.is_file()
        with Image.open(path) as image:
            assert image.width > 20 and image.height > 20
            assert image.format == "PNG"


def test_build_suggests_the_label_inside_the_box(tmp_path):
    doc = text_pdf(tmp_path, "Mitral valve")
    result = figures.build(doc, 0, TEXT_BOX)
    assert "Mitral valve" in result["suggested"]


def test_build_ignores_text_outside_the_box(tmp_path):
    doc = text_pdf(tmp_path, "Mitral valve")
    far = {"page": 0, "x0": 900, "y0": 1500, "x1": 1100, "y1": 1560}
    assert figures.build(doc, 0, far)["suggested"] == ""


def test_build_uses_the_picture_that_contains_the_selection(tmp_path):
    doc = picture_pdf(tmp_path)
    # The picture occupies 200..600 in page pixels on both axes.
    result = figures.build(doc, 0, {"page": 0, "x0": 300, "y0": 300, "x1": 360, "y1": 360})
    with Image.open(doc.directory / result["masked"]) as image:
        # The crop is the picture, not the 60px selection.
        assert image.width >= 350


def test_build_rejects_a_tiny_box(tmp_path):
    doc = text_pdf(tmp_path)
    with pytest.raises(ValueError, match="bigger box"):
        figures.build(doc, 0, {"page": 0, "x0": 100, "y0": 380, "x1": 104, "y1": 384})


def test_build_rejects_a_missing_page(tmp_path):
    doc = text_pdf(tmp_path)
    with pytest.raises(ValueError, match="page"):
        figures.build(doc, 5, TEXT_BOX)


def test_figure_path_refuses_traversal(tmp_path):
    doc = text_pdf(tmp_path)
    for name in ("../secret.png", "..\\x.png", "fig-abc.png", "/etc/passwd"):
        with pytest.raises(ValueError):
            figures.figure_path(doc, name)


def test_api_creates_and_serves_a_figure(tmp_path):
    client = client_for(tmp_path)
    uploaded = client.post(
        "/api/documents",
        files={"file": ("page.pdf", open(text_pdf(tmp_path).source, "rb").read(), "application/pdf")},
    )
    doc_id = uploaded.json()["id"]

    response = client.post(f"/api/documents/{doc_id}/figures", json=TEXT_BOX)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert "Mitral" in payload["suggested"] or "valve" in payload["suggested"]

    image = client.get(f"/api/documents/{doc_id}/figures/{payload['masked']}")
    assert image.status_code == 200
    assert image.headers["content-type"] == "image/png"
    assert image.content.startswith(b"\x89PNG")


def test_api_rejects_a_bad_figure_name(tmp_path):
    client = client_for(tmp_path)
    uploaded = client.post(
        "/api/documents",
        files={"file": ("page.pdf", open(text_pdf(tmp_path).source, "rb").read(), "application/pdf")},
    )
    doc_id = uploaded.json()["id"]
    response = client.get(f"/api/documents/{doc_id}/figures/..%5Csecret.png")
    assert response.status_code in (400, 404)


def test_api_rejects_a_tiny_selection(tmp_path):
    client = client_for(tmp_path)
    uploaded = client.post(
        "/api/documents",
        files={"file": ("page.pdf", open(text_pdf(tmp_path).source, "rb").read(), "application/pdf")},
    )
    doc_id = uploaded.json()["id"]
    response = client.post(
        f"/api/documents/{doc_id}/figures",
        json={"page": 0, "x0": 10, "y0": 10, "x1": 12, "y1": 12},
    )
    assert response.status_code == 400


def test_push_uploads_figure_media(tmp_path, monkeypatch):
    doc = text_pdf(tmp_path)
    built = figures.build(doc, 0, TEXT_BOX)
    captured = {}

    def fake_push(settings, deck, cards, extra_tags="", media=None):
        captured["media"] = media
        captured["notes"] = cards
        return {
            "deck": deck,
            "total": len(cards),
            "created": len(cards),
            "duplicates": 0,
            "noteIds": list(range(len(cards))),
        }

    monkeypatch.setattr(main_module.anki, "push_cards", fake_push)
    client = client_for(tmp_path)
    response = client.post(
        "/api/anki/push",
        json={
            "deck": "Deck",
            "cards": [
                {
                    "mode": "figure",
                    "question": "Which valve is covered?",
                    "answer": "Mitral valve",
                    "uid": "fig-1",
                    "figure": {
                        "docId": doc.id,
                        "masked": built["masked"],
                        "revealed": built["revealed"],
                    },
                }
            ],
        },
    )
    media = captured["media"]
    assert response.status_code == 200, response.text
    assert len(media) == 2
    names = {item["filename"] for item in media}
    assert names == {built["masked"], built["revealed"]}
    decoded = base64.b64decode(media[0]["data"])
    assert decoded.startswith(b"\x89PNG")
