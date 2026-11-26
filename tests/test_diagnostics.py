import io
import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app import diagnostics
from app.config import Settings
from app.drafts import DraftStore
from app.library import Library
from app.main import create_app
from app.sent import SentStore
from app.store import Store

SECRET = "sk-live-very-secret-key-1234"


def parts(tmp_path):
    return {
        "settings": Settings(
            api_key=SECRET,
            base_url="https://api.deepseek.com/v1",
            anki_url="http://127.0.0.1:8765",
        ),
        "store": Store(tmp_path / "documents"),
        "sent": SentStore(tmp_path / "sent.json"),
        "drafts": DraftStore(tmp_path / "drafts.json"),
        "library": Library(tmp_path / "library.json"),
    }


def test_snapshot_never_contains_the_api_key(tmp_path):
    built = parts(tmp_path)
    payload = diagnostics.snapshot(**built)
    blob = json.dumps(payload)
    assert SECRET not in blob
    assert payload["settings"]["hasKey"] is True
    assert payload["settings"]["keyHint"] == "1234"


def test_snapshot_trims_urls_to_scheme_and_host(tmp_path):
    built = parts(tmp_path)
    payload = diagnostics.snapshot(**built)
    # The port is kept on purpose: it is the first thing to check for AnkiConnect.
    assert payload["settings"]["baseUrl"] == "https://api.deepseek.com"
    assert payload["settings"]["ankiUrl"] == "http://127.0.0.1:8765"


def test_snapshot_reports_versions_and_counts(tmp_path):
    built = parts(tmp_path)
    built["drafts"].put(str(tmp_path / "a.pdf"), "a.pdf", [{"uid": "1"}, {"uid": "2"}])
    built["sent"].append(str(tmp_path / "a.pdf"), "a.pdf", [{"id": "s1"}])

    payload = diagnostics.snapshot(**built)
    assert payload["app"]["name"] == "anki-scribe"
    assert payload["app"]["version"]
    assert payload["app"]["python"]
    assert payload["drafts"] == {"sources": 1, "cards": 2}
    assert payload["sent"] == {"sources": 1, "cards": 1}
    assert payload["documents"] == []


def test_snapshot_survives_a_broken_store(tmp_path):
    built = parts(tmp_path)

    class Broken:
        def list(self):
            raise RuntimeError("store is on fire")

    built["store"] = Broken()
    payload = diagnostics.snapshot(**built)
    assert "store is on fire" in payload["documents"][0]["error"]


def test_bundle_is_a_zip_with_the_expected_files(tmp_path):
    payload = diagnostics.snapshot(**parts(tmp_path))
    log_file = tmp_path / "anki-scribe.log"
    log_file.write_text("2026-01-01 10:00:00 INFO starting\n", encoding="utf-8")

    data = diagnostics.bundle(payload, log_file)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = set(archive.namelist())
        assert names == {"diagnostics.json", "README.txt", "anki-scribe.log"}
        assert SECRET not in archive.read("diagnostics.json").decode("utf-8")
        assert "starting" in archive.read("anki-scribe.log").decode("utf-8")


def test_bundle_without_a_log_file(tmp_path):
    payload = diagnostics.snapshot(**parts(tmp_path))
    data = diagnostics.bundle(payload, tmp_path / "missing.log")
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert "anki-scribe.log" not in archive.namelist()


@pytest.fixture
def client(tmp_path):
    built = parts(tmp_path)
    app = create_app(
        store=built["store"],
        settings=built["settings"],
        library=built["library"],
        drafts=built["drafts"],
        sent=built["sent"],
    )
    return TestClient(app, base_url="http://127.0.0.1")


def test_diagnostics_endpoint_returns_json(client):
    response = client.get("/api/diagnostics")
    assert response.status_code == 200
    payload = response.json()
    assert SECRET not in response.text
    assert payload["app"]["name"] == "anki-scribe"


def test_diagnostics_bundle_endpoint_is_a_zip(client):
    response = client.get("/api/diagnostics/bundle")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "anki-scribe-diagnostics.zip" in response.headers["content-disposition"]
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert "diagnostics.json" in archive.namelist()
        assert SECRET not in archive.read("diagnostics.json").decode("utf-8")


def test_logging_setup_writes_a_file(tmp_path):
    from app.logging_setup import LOGGER_NAME, configure_logging

    path = configure_logging(tmp_path)
    import logging

    logging.getLogger(LOGGER_NAME).info("hello from a test")
    assert path.is_file()
    assert "hello from a test" in path.read_text(encoding="utf-8")
