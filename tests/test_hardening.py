"""Tests for the hardening pass: host validation, size ceilings, bad URLs and
corrupt-file quarantine. Each one corresponds to a defect from the review."""

from __future__ import annotations

import json

import pymupdf
import pytest
from fastapi.testclient import TestClient

import app.main as main_module
from app.config import Settings, quarantine_file
from app.drafts import DraftStore
from app.llm import LLMError, _chat
from app.library import Library, UNSORTED_ID
from app.sent import SentStore
from app.main import create_app
from app.store import MAX_PAGE_POINTS, Store


def make_client(tmp_path, **overrides):
    app = create_app(
        store=Store(tmp_path / "documents"),
        settings=overrides.get("settings")
        or Settings(api_key="sk-test", anki_url="http://127.0.0.1:9"),
        library=Library(tmp_path / "library.json"),
        drafts=DraftStore(tmp_path / "drafts.json"),
        sent=SentStore(tmp_path / "sent.json"),
    )
    return TestClient(app, base_url="http://127.0.0.1")


# -- host validation (DNS rebinding) -------------------------------------


def test_foreign_host_header_is_rejected(tmp_path):
    client = make_client(tmp_path)
    response = client.get("/api/health", headers={"host": "evil.example"})
    assert response.status_code == 400


def test_loopback_host_is_accepted(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/api/health").status_code == 200
    assert (
        client.get("/api/health", headers={"host": "localhost"}).status_code == 200
    )


def test_openapi_schema_is_not_exposed(tmp_path):
    client = make_client(tmp_path)
    assert client.get("/openapi.json").status_code == 404


# -- page geometry -------------------------------------------------------


def oversized_pdf() -> bytes:
    pdf = pymupdf.open()
    pdf.new_page(width=MAX_PAGE_POINTS + 500, height=MAX_PAGE_POINTS + 500)
    data = pdf.tobytes()
    pdf.close()
    return data


def test_oversized_page_is_refused_at_upload(tmp_path):
    client = make_client(tmp_path)
    response = client.post(
        "/api/documents",
        files={"file": ("huge.pdf", oversized_pdf(), "application/pdf")},
    )
    assert response.status_code == 400
    assert "can't be rendered" in response.json()["detail"]


def test_normal_page_still_uploads(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=595, height=842)
    page.insert_text((60, 80), "Beta blockers reduce heart rate.", fontsize=12)
    data = pdf.tobytes()
    pdf.close()

    client = make_client(tmp_path)
    response = client.post(
        "/api/documents",
        files={"file": ("a4.pdf", data, "application/pdf")},
    )
    assert response.status_code == 200, response.text


# -- malformed URLs ------------------------------------------------------


def test_settings_reject_an_unparseable_url(tmp_path):
    client = make_client(tmp_path)
    for field in ("base_url", "anki_url"):
        response = client.put("/api/settings", json={field: "http://[::1"})
        assert response.status_code == 400, field
        assert "valid URL" in response.json()["detail"]


def test_chat_reports_a_bad_base_url_instead_of_crashing():
    with pytest.raises(LLMError) as caught:
        _chat(
            Settings(api_key="sk-test", base_url="http://[::1"),
            [{"role": "user", "content": "hello"}],
        )
    assert caught.value.status_code == 400


# -- corrupt state quarantine -------------------------------------------


def test_corrupt_drafts_are_moved_aside(tmp_path):
    path = tmp_path / "drafts.json"
    path.write_text('{"half": tru', encoding="utf-8")

    store = DraftStore(path)

    assert store.get(str(tmp_path / "x.pdf"))["cards"] == []
    assert not path.exists()
    quarantined = list(tmp_path.glob("drafts.json.corrupt-*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_text(encoding="utf-8").startswith('{"half"')


def test_corrupt_sent_ledger_is_moved_aside(tmp_path):
    path = tmp_path / "sent.json"
    path.write_text("not json at all", encoding="utf-8")

    store = SentStore(path)

    assert store.sources() == []
    assert list(tmp_path.glob("sent.json.corrupt-*"))


def test_corrupt_library_is_moved_aside(tmp_path):
    path = tmp_path / "library.json"
    path.write_text("{", encoding="utf-8")

    library = Library(path)

    assert library.snapshot()["groups"][0]["id"] == UNSORTED_ID
    assert list(tmp_path.glob("library.json.corrupt-*"))


def test_quarantine_helper_survives_a_missing_file(tmp_path):
    assert quarantine_file(tmp_path / "nothing.json") is None


def test_corrupt_config_falls_back_to_defaults(tmp_path, monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    path = tmp_path / "config.json"
    path.write_text("{{{{", encoding="utf-8")

    settings = Settings.load(path)

    assert settings.base_url == "https://api.deepseek.com"
    assert list(tmp_path.glob("config.json.corrupt-*"))
