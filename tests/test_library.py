import json

import pytest

from app.library import UNSORTED_ID, Library, LibraryError


def make_file(tmp_path, name="lecture.pdf", content=b"%PDF-1.4"):
    path = tmp_path / name
    path.write_bytes(content)
    return path


def test_add_file_saves_location_only(tmp_path):
    source = make_file(tmp_path)
    library = Library(tmp_path / "library.json")
    file, added = library.add_file(str(source))

    assert added is True
    assert file.path == str(source)
    assert file.group_id == UNSORTED_ID
    stored = json.loads((tmp_path / "library.json").read_text(encoding="utf-8"))
    assert stored["files"][0]["path"] == str(source)
    assert source.read_bytes() == b"%PDF-1.4"


def test_duplicate_path_is_not_added_twice(tmp_path):
    source = make_file(tmp_path)
    library = Library(tmp_path / "library.json")
    first, added = library.add_file(str(source))
    second, added_again = library.add_file(str(source))
    assert added is True
    assert added_again is False
    assert first.id == second.id
    assert len(library.snapshot()["files"]) == 1


def test_groups_move_and_delete(tmp_path):
    source = make_file(tmp_path)
    library = Library(tmp_path / "library.json")
    file, _ = library.add_file(str(source))
    group = library.create_group("Cardiology")

    library.move_file(file.id, group.id)
    assert library.snapshot()["files"][0]["groupId"] == group.id

    library.rename_group(group.id, "Cardio")
    assert library.snapshot()["groups"][0]["name"] == "Cardio"

    library.delete_group(group.id)
    snapshot = library.snapshot()
    assert snapshot["files"][0]["groupId"] == UNSORTED_ID
    assert all(entry["id"] != group.id for entry in snapshot["groups"])


def test_group_names_are_unique_and_unsorted_is_reserved(tmp_path):
    library = Library(tmp_path / "library.json")
    library.create_group("Cardiology")
    with pytest.raises(LibraryError):
        library.create_group("cardiology")
    with pytest.raises(LibraryError):
        library.create_group("Unsorted")


def test_snapshot_marks_missing_files(tmp_path):
    source = make_file(tmp_path)
    library = Library(tmp_path / "library.json")
    library.add_file(str(source))
    source.unlink()
    assert library.snapshot()["files"][0]["exists"] is False


def test_persistence_roundtrip(tmp_path):
    source = make_file(tmp_path)
    path = tmp_path / "library.json"
    library = Library(path)
    file, _ = library.add_file(str(source))
    group = library.create_group("Neuro")
    library.move_file(file.id, group.id)
    library.touch(file.id)

    reopened = Library(path)
    snapshot = reopened.snapshot()
    assert len(snapshot["files"]) == 1
    assert snapshot["files"][0]["groupId"] == group.id
    assert snapshot["lastOpenedFileId"] == file.id


def test_valid_json_that_is_not_an_object_does_not_crash(tmp_path):
    path = tmp_path / "library.json"
    path.write_text("[]", encoding="utf-8")
    library = Library(path)
    snapshot = library.snapshot()
    assert snapshot["files"] == []
    assert [group["id"] for group in snapshot["groups"]] == [UNSORTED_ID]


def test_unknown_entry_shapes_are_skipped(tmp_path):
    path = tmp_path / "library.json"
    path.write_text(
        json.dumps({"groups": [1, None], "files": ["nope", {"id": "a"}]}),
        encoding="utf-8",
    )
    assert Library(path).snapshot()["files"] == []
