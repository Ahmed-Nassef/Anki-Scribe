from pathlib import Path

import pytest

from app.store import Store
from app.transcript import format_time, parse_transcript, read_transcript


SRT = """1
00:00:01,000 --> 00:00:04,000
Beta blockers <i>reduce</i> heart rate.

2
00:00:12,000 --> 00:00:15,500
Metoprolol is cardioselective.
"""

VTT = """WEBVTT

NOTE this is a comment

cue-1
00:01.000 --> 00:03.000
<h1>Heart failure</h1>
ACE inhibitors reduce afterload.

00:20.000 --> 00:22.000
They also reduce mortality.
"""


def test_parse_srt_preserves_timestamps_and_cleans_markup():
    segments = parse_transcript(SRT)
    assert len(segments) == 2
    assert segments[0]["start"] == 1.0
    assert segments[0]["end"] == 4.0
    assert segments[0]["text"] == "Beta blockers reduce heart rate."
    assert segments[1]["label"] == "00:12\u201300:16"
    assert segments[1]["startLabel"] == "00:12"


def test_parse_vtt_and_merge_short_gaps():
    segments = parse_transcript(VTT)
    assert len(segments) == 2
    assert segments[0]["text"] == "Heart failure ACE inhibitors reduce afterload."
    assert segments[0]["start"] == 1.0
    assert segments[1]["text"] == "They also reduce mortality."


def test_parse_plain_text_into_segments():
    segments = parse_transcript(
        "First paragraph about beta blockers.\n\nSecond paragraph about ACE inhibitors."
    )
    assert len(segments) == 2
    assert segments[0]["start"] is None
    assert segments[0]["label"] == "Segment 1"
    assert segments[1]["text"].startswith("Second")


def test_format_time():
    assert format_time(65) == "01:05"
    assert format_time(3661) == "1:01:01"
    assert format_time(None) == ""


def test_read_transcript_rejects_empty(tmp_path):
    path = tmp_path / "empty.srt"
    path.write_text("", encoding="utf-8")
    with pytest.raises(ValueError):
        read_transcript(path)


def test_read_transcript_accepts_utf16(tmp_path):
    path = tmp_path / "utf16.srt"
    path.write_bytes(SRT.encode("utf-16"))
    segments = read_transcript(path)
    assert len(segments) == 2
    assert segments[0]["text"].startswith("Beta blockers")


def test_store_transcript_summary_extract_and_coverage(tmp_path):
    path = tmp_path / "lecture.srt"
    path.write_text(SRT, encoding="utf-8")
    store = Store(tmp_path / "documents")
    doc = store.create_transcript(path, "lecture.srt")

    assert doc.kind == "transcript"
    assert len(doc.segments) == 2
    assert doc.has_timestamps is True
    assert doc.duration == 15.5
    summary = doc.summary()
    assert summary["kind"] == "transcript"
    assert summary["segmentCount"] == 2
    assert summary["segments"][0]["text"].startswith("Beta blockers")

    extract = store.extract_chunks(doc)
    assert extract["kind"] == "transcript"
    assert extract["segmentCount"] == 2
    assert extract["chunks"]
    assert extract["chunks"][0]["segments"] == [1, 2]
    assert "--- 00:01\u201300:04 ---" in extract["chunks"][0]["text"]

    coverage = store.coverage(doc)
    assert coverage["kind"] == "transcript"
    assert coverage["unit"] == "segments"
    assert coverage["contentPages"] == 2
    assert coverage["textPages"] == 2
    assert coverage["imagePages"] == 0
    assert coverage["textCharacters"] > 0
