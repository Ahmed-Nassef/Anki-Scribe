"""Persistent batch generation jobs, without a real DeepSeek request."""

from __future__ import annotations

import time

import pymupdf

from app import batch_jobs
from app.config import Settings
from app.drafts import DraftStore
from app.library import Library
from app.sent import SentStore
from app.store import Store


def make_pdf(tmp_path, text="Beta blockers reduce heart rate."):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 100), text, fontsize=13)
    path = tmp_path / "lecture.pdf"
    path.write_bytes(pdf.tobytes())
    pdf.close()
    return path


def fake_generate(settings, text, **kwargs):
    return {
        "cards": [
            {
                "type": "definition",
                "question": "What do beta blockers do?",
                "answer": "They reduce heart rate.",
                "evidence": "Beta blockers reduce heart rate.",
                "tags": ["pharm"],
            }
        ],
        "mode": kwargs.get("mode", "basic"),
        "model": "fake",
        "unverified": 0,
        "strict": False,
        "style": "balanced",
    }


def test_batch_job_generates_cards_and_persists(tmp_path, monkeypatch):
    path = make_pdf(tmp_path)
    library = Library(tmp_path / "library.json")
    file, _ = library.add_file(str(path))
    drafts = DraftStore(tmp_path / "drafts.json")
    sent = SentStore(tmp_path / "sent.json")
    store = Store(tmp_path / "documents")
    jobs = batch_jobs.BatchJobStore(
        store,
        library,
        drafts,
        sent,
        Settings(api_key="sk-test"),
        path=tmp_path / "batch_jobs.json",
    )
    monkeypatch.setattr(batch_jobs.llm, "generate_cards", fake_generate)

    job = jobs.create([file.id], start=False)
    assert job["status"] == "queued"
    result = jobs.run_sync(job["id"])
    assert result["status"] == "completed"
    assert result["cards"] == 1
    assert result["results"][0]["ok"] is True
    saved = drafts.get(file.path)["cards"]
    assert len(saved) == 1
    assert saved[0]["mode"] == "basic"
    assert saved[0]["source"]["pages"] == [0, 0]
    assert saved[0]["uid"]

    # A new store reads the same job from disk.
    again = batch_jobs.BatchJobStore(
        store,
        library,
        drafts,
        sent,
        Settings(api_key="sk-test"),
        path=tmp_path / "batch_jobs.json",
    )
    assert again.status(job["id"])["status"] == "completed"


def test_batch_job_skips_duplicate_cards(tmp_path, monkeypatch):
    path = make_pdf(tmp_path)
    library = Library(tmp_path / "library.json")
    file, _ = library.add_file(str(path))
    drafts = DraftStore(tmp_path / "drafts.json")
    sent = SentStore(tmp_path / "sent.json")
    store = Store(tmp_path / "documents")
    jobs = batch_jobs.BatchJobStore(
        store,
        library,
        drafts,
        sent,
        Settings(api_key="sk-test"),
        path=tmp_path / "batch_jobs.json",
    )
    monkeypatch.setattr(batch_jobs.llm, "generate_cards", fake_generate)
    job = jobs.create([file.id], start=False)
    jobs.run_sync(job["id"])
    job2 = jobs.create([file.id], start=False)
    second = jobs.run_sync(job2["id"])
    assert second["status"] == "completed"
    assert len(drafts.get(file.path)["cards"]) == 1


def test_batch_job_survives_as_running_and_resumes(tmp_path, monkeypatch):
    path = make_pdf(tmp_path)
    library = Library(tmp_path / "library.json")
    file, _ = library.add_file(str(path))
    drafts = DraftStore(tmp_path / "drafts.json")
    sent = SentStore(tmp_path / "sent.json")
    store = Store(tmp_path / "documents")
    jobs = batch_jobs.BatchJobStore(
        store,
        library,
        drafts,
        sent,
        Settings(api_key="sk-test"),
        path=tmp_path / "batch_jobs.json",
    )
    monkeypatch.setattr(batch_jobs.llm, "generate_cards", fake_generate)
    job = jobs.create([file.id], start=False)
    # Simulate a process dying while the job was marked running.
    with jobs._lock:
        jobs._jobs[job["id"]]["status"] = "running"
        jobs._save()
    resumed = batch_jobs.BatchJobStore(
        store,
        library,
        drafts,
        sent,
        Settings(api_key="sk-test"),
        path=tmp_path / "batch_jobs.json",
    )
    resumed.resume()
    deadline = time.time() + 5
    status = resumed.status(job["id"])
    while status["status"] in {"queued", "running"} and time.time() < deadline:
        time.sleep(0.02)
        status = resumed.status(job["id"])
    assert status["status"] == "completed"


def test_batch_job_can_send_fresh_cards_to_anki(tmp_path, monkeypatch):
    path = make_pdf(tmp_path)
    library = Library(tmp_path / "library.json")
    file, _ = library.add_file(str(path))
    drafts = DraftStore(tmp_path / "drafts.json")
    sent = SentStore(tmp_path / "sent.json")
    store = Store(tmp_path / "documents")
    jobs = batch_jobs.BatchJobStore(
        store,
        library,
        drafts,
        sent,
        Settings(api_key="sk-test"),
        path=tmp_path / "batch_jobs.json",
    )
    monkeypatch.setattr(batch_jobs.llm, "generate_cards", fake_generate)

    def fake_push(settings, deck, cards, tags="", media=None):
        return {
            "deck": deck,
            "total": len(cards),
            "created": len(cards),
            "duplicates": 0,
            "noteIds": [701],
        }

    monkeypatch.setattr(batch_jobs.anki, "push_cards", fake_push)
    job = jobs.create(
        [file.id],
        send_to_anki=True,
        deck="Anki Scribe",
        start=False,
    )
    result = jobs.run_sync(job["id"])
    assert result["sent"] == 1
    assert result["cards"] == 1
    assert sent.count(file.path) == 1
    assert drafts.get(file.path)["cards"] == []
    assert result["results"][0]["sent"] == 1
