import io

import pymupdf
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import anki, images
from app.config import Settings
from app.drafts import DraftStore
from app.library import Library
from app.main import _card_media, create_app
from app.sent import SentStore
from app.store import Store


def make_pdf(path, pages: int = 1):
    pdf = pymupdf.open()
    for index in range(pages):
        page = pdf.new_page(width=600, height=800)
        page.insert_text((60, 80), f"Figure on page {index + 1}", fontsize=16)
        page.draw_rect(pymupdf.Rect(60, 120, 300, 260), color=(0, 0, 0), width=2)
    pdf.save(path)
    pdf.close()
    return path


@pytest.fixture
def doc(tmp_path):
    store = Store(tmp_path / "documents")
    return store, store.create_pdf_path(make_pdf(tmp_path / "notes.pdf"), "notes.pdf")


def png_bytes(size=(80, 60), colour=(180, 40, 40)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, colour).save(buffer, "PNG")
    return buffer.getvalue()


def test_crop_writes_a_png_for_the_selection(doc):
    store, document = doc
    result = images.crop(
        document, 0, {"x0": 100, "y0": 100, "x1": 400, "y1": 300}
    )
    assert result["name"].startswith("img-") and result["name"].endswith(".png")
    assert result["page"] == 0
    assert result["width"] > 0 and result["height"] > 0

    path = images.image_path(document, result["name"])
    with Image.open(path) as opened:
        assert opened.format == "PNG"
        assert opened.mode == "RGB"


def test_crop_rejects_a_tiny_box(doc):
    store, document = doc
    with pytest.raises(ValueError, match="bigger box"):
        images.crop(document, 0, {"x0": 10, "y0": 10, "x1": 14, "y1": 14})


def test_upload_keeps_an_existing_picture_as_png(doc):
    store, document = doc
    result = images.store_upload(document, png_bytes(size=(120, 90)))
    path = images.image_path(document, result["name"])
    with Image.open(path) as opened:
        assert opened.format == "PNG"
        assert opened.size == (120, 90)


def test_upload_converts_a_jpeg_and_strips_alpha(doc):
    store, document = doc
    buffer = io.BytesIO()
    Image.new("RGBA", (100, 50), (0, 0, 0, 0)).save(buffer, "PNG")
    transparent = images.store_upload(document, buffer.getvalue())
    with Image.open(images.image_path(document, transparent["name"])) as opened:
        assert opened.mode == "RGB"

    jpeg = io.BytesIO()
    Image.new("RGB", (60, 40), (10, 90, 160)).save(jpeg, "JPEG")
    result = images.store_upload(document, jpeg.getvalue())
    assert result["name"].endswith(".png")


def test_upload_rejects_a_file_that_is_not_an_image(doc):
    store, document = doc
    with pytest.raises(ValueError, match="Couldn't read that image"):
        images.store_upload(document, b"definitely not a picture")


def test_image_names_are_guarded(doc):
    store, document = doc
    with pytest.raises(ValueError):
        images.image_path(document, "../../config.json")
    assert images.valid_name("img-0123456789ab.png")
    assert not images.valid_name("fig-0123456789ab-m.png")


def base_card(**overrides):
    card = {
        "question": "What is shown?",
        "answer": "A red blood cell.",
        "extra": "",
        "uid": "card-1",
        "image": {"name": "img-0123456789ab.png", "side": "front"},
    }
    card.update(overrides)
    return card


def test_image_goes_on_the_front_by_default():
    note = anki._note_for(base_card(), "basic", [], "Deck", None)
    assert note["fields"]["Front"].startswith('<img src="img-0123456789ab.png">')
    assert "img-" not in note["fields"]["Back"]


def test_image_can_sit_on_the_back():
    note = anki._note_for(
        base_card(image={"name": "img-0123456789ab.png", "side": "back"}),
        "basic",
        [],
        "Deck",
        None,
    )
    assert note["fields"]["Back"].startswith('<img src="img-0123456789ab.png">')
    assert "img-" not in note["fields"]["Front"]


def test_image_on_a_cloze_card_keeps_the_deletion():
    card = base_card(
        text="The {{c1::mitochondrion}} makes ATP.",
        question="",
        answer="",
        image={"name": "img-0123456789ab.png", "side": "back"},
    )
    note = anki._note_for(card, "cloze", [], "Deck", None)
    assert '{{c1::mitochondrion}}' in note["fields"]["Text"]
    assert note["fields"]["Back Extra"].startswith('<img src="img-0123456789ab.png">')


def test_a_card_with_only_an_image_is_allowed():
    card = base_card(question="", answer="")
    note = anki._note_for(card, "basic", [], "Deck", None)
    assert note["fields"]["Front"].startswith("<img")


def test_an_unsafe_media_name_is_ignored():
    card = base_card(image={"name": "../config.png", "side": "front"})
    note = anki._note_for(card, "basic", [], "Deck", None)
    assert "img" not in note["fields"]["Front"]
    assert "../" not in note["fields"]["Front"]


def test_the_push_media_list_includes_attached_images(doc):
    store, document = doc
    result = images.crop(document, 0, {"x0": 100, "y0": 100, "x1": 400, "y1": 300})
    media = _card_media(
        store, [{"image": {"docId": document.id, "name": result["name"]}}]
    )
    assert [entry["filename"] for entry in media] == [result["name"]]
    assert media[0]["data"]


@pytest.fixture
def client(tmp_path):
    app = create_app(
        store=Store(tmp_path / "documents"),
        settings=Settings(api_key="", anki_url="http://127.0.0.1:9"),
        library=Library(tmp_path / "library.json"),
        drafts=DraftStore(tmp_path / "drafts.json"),
        sent=SentStore(tmp_path / "sent.json"),
    )
    return TestClient(app, base_url="http://127.0.0.1")


def test_image_endpoints_round_trip(client, tmp_path):
    source = make_pdf(tmp_path / "notes.pdf")
    with source.open("rb") as handle:
        uploaded = client.post(
            "/api/documents", files={"file": ("notes.pdf", handle, "application/pdf")}
        )
    assert uploaded.status_code == 200, uploaded.text
    doc_id = uploaded.json()["id"]

    cropped = client.post(
        f"/api/documents/{doc_id}/images/crop",
        json={"page": 0, "x0": 100, "y0": 100, "x1": 400, "y1": 300},
    )
    assert cropped.status_code == 200, cropped.text
    name = cropped.json()["name"]
    served = client.get(f"/api/documents/{doc_id}/images/{name}")
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"

    uploaded_image = client.post(
        f"/api/documents/{doc_id}/images",
        files={"file": ("picture.png", png_bytes(), "image/png")},
    )
    assert uploaded_image.status_code == 200, uploaded_image.text
    assert uploaded_image.json()["name"].endswith(".png")

    missing = client.get(f"/api/documents/{doc_id}/images/img-000000000000.png")
    assert missing.status_code == 404
