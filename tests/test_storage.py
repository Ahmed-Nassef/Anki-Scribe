import json

from app import storage


def test_write_keeps_the_previous_file_as_a_backup(tmp_path):
    path = tmp_path / "store.json"
    storage.write_json(path, {"a": 1})
    assert not storage.backup_path(path).exists()

    storage.write_json(path, {"a": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == {"a": 2}
    assert json.loads(storage.backup_path(path).read_text(encoding="utf-8")) == {"a": 1}


def test_read_falls_back_to_the_backup(tmp_path):
    path = tmp_path / "store.json"
    storage.write_json(path, {"key": "first"})
    storage.write_json(path, {"key": "second"})
    path.write_text("{ this is not json", encoding="utf-8")

    payload, source = storage.read_json(path)
    assert source == "backup"
    assert payload == {"key": "first"}


def test_read_reports_missing_and_unreadable(tmp_path):
    path = tmp_path / "store.json"
    assert storage.read_json(path) == (None, "missing")

    path.write_text("nope", encoding="utf-8")
    assert storage.read_json(path) == (None, "unreadable")


def test_heal_restores_without_destroying_the_backup(tmp_path):
    path = tmp_path / "store.json"
    storage.write_json(path, {"key": "first"})
    storage.write_json(path, {"key": "second"})
    path.write_text("broken", encoding="utf-8")

    payload, _ = storage.read_json(path)
    storage.heal(path, payload)
    assert json.loads(path.read_text(encoding="utf-8")) == {"key": "first"}
    assert storage.read_json(path) == ({"key": "first"}, "live")
