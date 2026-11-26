"""Tests for the manual-hidden-text store."""

from __future__ import annotations

import json

import pytest

from app.masks import MAX_BOXES_PER_MASK, MaskStore, clean_mask, clean_masks


def sample_mask(identifier="manual-1", **extra):
    base = {
        "id": identifier,
        "text": "Banking Directive",
        "boxes": [{"page": 0, "x": 0.1, "y": 0.2, "w": 0.3, "h": 0.04}],
    }
    base.update(extra)
    return base


def test_round_trip(tmp_path):
    store = MaskStore(tmp_path / "masks.json")
    saved = store.put("C:/notes/lecture.pdf", [sample_mask()])
    assert saved["masks"][0]["id"] == "manual-1"
    assert saved["masks"][0]["boxes"][0]["x"] == 0.1

    loaded = store.get("C:/notes/lecture.pdf")
    assert loaded["masks"] == saved["masks"]
    assert loaded["updatedAt"] > 0


def test_paths_are_normalized(tmp_path):
    store = MaskStore(tmp_path / "masks.json")
    store.put("C:/notes/lecture.pdf", [sample_mask()])
    assert store.get("c:\\notes\\lecture.pdf")["masks"]
    assert store.get("C:/notes/OTHER.pdf")["masks"] == []


def test_clear(tmp_path):
    store = MaskStore(tmp_path / "masks.json")
    store.put("C:/notes/lecture.pdf", [sample_mask()])
    store.delete("C:/notes/lecture.pdf")
    assert store.get("C:/notes/lecture.pdf")["masks"] == []


def test_boxes_are_clamped_to_the_page():
    mask = clean_mask(
        sample_mask(
            boxes=[{"page": 0, "x": 0.9, "y": 0.95, "w": 0.5, "h": 0.5}]
        )
    )
    box = mask["boxes"][0]
    assert box["x"] + box["w"] <= 1.0
    assert box["y"] + box["h"] <= 1.0
    assert box["w"] > 0
    assert box["h"] > 0


def test_missing_boxes_are_rejected():
    with pytest.raises(ValueError):
        clean_mask({"id": "x", "text": "y", "boxes": []})


def test_invalid_coordinates_are_rejected():
    with pytest.raises(ValueError):
        clean_mask(
            sample_mask(
                boxes=[{"page": 0, "x": "left", "y": 0, "w": 0.1, "h": 0.1}]
            )
        )


def test_missing_id_is_rejected():
    with pytest.raises(ValueError):
        clean_mask({"text": "a", "boxes": sample_mask()["boxes"]})


def test_masks_are_deduplicated_by_id():
    masks = clean_masks([sample_mask("a"), sample_mask("a"), sample_mask("b")])
    assert [mask["id"] for mask in masks] == ["a", "b"]


def test_boxes_are_capped():
    boxes = [
        {"page": 0, "x": 0.01 * index, "y": 0.1, "w": 0.005, "h": 0.02}
        for index in range(MAX_BOXES_PER_MASK + 8)
    ]
    assert len(clean_mask(sample_mask(boxes=boxes))["boxes"]) == MAX_BOXES_PER_MASK


def test_unreadable_file_is_quarantined(tmp_path):
    path = tmp_path / "masks.json"
    path.write_text("{not json", encoding="utf-8")
    store = MaskStore(path)
    assert store.get("C:/notes/lecture.pdf")["masks"] == []
    assert list(tmp_path.glob("masks.json.corrupt-*"))


def test_backup_is_used_when_the_live_file_is_damaged(tmp_path):
    path = tmp_path / "masks.json"
    store = MaskStore(path)
    store.put("C:/notes/lecture.pdf", [sample_mask()])
    # A second write is what creates the .bak of the first good file.
    store.put("C:/notes/lecture.pdf", [sample_mask("manual-2")])
    path.write_text("{broken", encoding="utf-8")
    recovered = MaskStore(path)
    assert recovered.get("C:/notes/lecture.pdf")["masks"][0]["id"] == "manual-1"


def test_saved_file_is_valid_json(tmp_path):
    path = tmp_path / "masks.json"
    store = MaskStore(path)
    store.put("C:/notes/lecture.pdf", [sample_mask()])
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert list(payload) == [r"c:\notes\lecture.pdf"]
