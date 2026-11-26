"""Behavioural tests for the draft autosave.

Runs the real ``drafts.js`` under Node with stubbed globals, because the bug
these guard against is invisible from Python: a ``keepalive`` request whose body
is over 64 KiB is rejected by the browser before it leaves the page, which is
what silently stopped drafts saving once a whole-file run passed ~80 cards.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

NODE = shutil.which("node")
DRAFTS_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "drafts.js"

pytestmark = pytest.mark.skipif(
    NODE is None or not DRAFTS_JS.exists(), reason="needs Node and drafts.js"
)

HARNESS = """
const fs = require("fs");
const code = fs.readFileSync(process.argv[1], "utf8");
const fixtures = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));

const calls = [];
let beaconCalls = 0;
let beaconResult = false;

const fakeState = {
  drafts: { ready: true, path: "C:/lectures/lecture.pdf", saveTimer: null },
  doc: { filename: "lecture.pdf" },
  cards: [],
  library: { files: [] },
  sent: { cards: [] },
};
const fakeApi = async (path, options) => {
  calls.push({
    path,
    keepalive: Boolean(options && options.keepalive),
    bytes: String((options && options.body) || "").length,
  });
  return {};
};
const fakeNavigator = {
  sendBeacon() {
    beaconCalls += 1;
    return beaconResult;
  },
};
const factory = new Function(
  "navigator", "state", "api", "toast", "console", "Blob",
  code + "\\nreturn { saveDraftsNow };"
);
const drafts = factory(fakeNavigator, fakeState, fakeApi, () => {}, console, Blob);

async function phase(cards, beacon, beaconReturns) {
  fakeState.cards = cards;
  calls.length = 0;
  beaconCalls = 0;
  beaconResult = beaconReturns;
  await drafts.saveDraftsNow({ beacon });
  return { calls: calls.slice(), beaconCalls };
}

(async () => {
  const out = {
    normal: await phase(fixtures.large, false, false),
    beaconSmallOk: await phase(fixtures.small, true, true),
    beaconSmallRefused: await phase(fixtures.small, true, false),
    beaconLarge: await phase(fixtures.large, true, true),
  };
  console.log(JSON.stringify(out));
})();
"""


def card(index: int) -> dict:
    return {
        "uid": f"card-{index}",
        "mode": "basic",
        "selected": True,
        "verified": True,
        "question": "Which receptor does metoprolol block selectively in the heart?",
        "answer": "Beta-1, which is why it spares the airway.",
        "extra": "",
        "tags": ["cardiology"],
        "evidence": "Metoprolol is cardioselective, so it causes less bronchospasm.",
        "source": {
            "kind": "chunk",
            "label": "Pages 4-5",
            "file": "Cardiology Lecture 3.pdf",
            "pages": [3, 4],
            "location": [],
            "segments": [],
            "quote": "q" * 260,
            "sourceTitle": "Cardiology Lecture 3",
            "chapterPath": ["Beta blockers"],
            "deckPath": ["Cardiology Lecture 3", "Beta blockers"],
        },
    }


@pytest.fixture(scope="module")
def phases() -> dict:
    fixtures = {
        "small": [card(0)],
        # Roughly 117 KB, well past the 64 KiB keepalive ceiling.
        "large": [card(index) for index in range(120)],
    }
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "fixtures.json"
        path.write_text(json.dumps(fixtures), encoding="utf-8")
        result = subprocess.run(
            [NODE, "-e", HARNESS, str(DRAFTS_JS), str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_a_normal_save_never_uses_keepalive(phases):
    call = phases["normal"]["calls"][0]
    assert call["path"] == "/api/drafts"
    assert call["bytes"] > 65_536
    assert call["keepalive"] is False


def test_the_unload_flush_uses_send_beacon_when_it_fits(phases):
    phase = phases["beaconSmallOk"]
    assert phase["beaconCalls"] == 1
    assert phase["calls"] == []


def test_the_unload_flush_falls_back_to_a_keepalive_fetch(phases):
    phase = phases["beaconSmallRefused"]
    assert phase["beaconCalls"] == 1
    assert len(phase["calls"]) == 1
    assert phase["calls"][0]["keepalive"] is True


def test_a_large_unload_flush_skips_both_keepalive_paths(phases):
    phase = phases["beaconLarge"]
    # sendBeacon would be refused and a keepalive fetch would throw, so neither
    # is attempted; the debounced save has already written this batch.
    assert phase["beaconCalls"] == 0
    assert len(phase["calls"]) == 1
    assert phase["calls"][0]["keepalive"] is False
