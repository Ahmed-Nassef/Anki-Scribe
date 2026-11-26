"""Executable tests for the study-plan item counter.

The counter is pure enough to run outside a browser: it reads ``state`` and
returns the breakdown. These tests execute the real ``plan.js`` with stubs, the
same way the risk-scorer tests run ``risk.js``.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

NODE = shutil.which("node")
PLAN_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "plan.js"

pytestmark = pytest.mark.skipif(
    NODE is None or not PLAN_JS.exists(), reason="needs Node and plan.js"
)

HARNESS = """
const fs = require("fs");
const vm = require("vm");
const fixture = JSON.parse(fs.readFileSync(process.argv[1], "utf8"));
globalThis.state = {
  cards: fixture.cards,
  sent: { cards: fixture.sent || [] },
  answers: { manual: fixture.manual || [] },
  plan: { request: 0, result: null, payload: null },
};
globalThis.sourceCards = () => state.cards.concat(state.sent.cards);
globalThis.toast = () => {};
globalThis.api = async () => ({});
globalThis.els = {};
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), { filename: "plan.js" });
console.log(JSON.stringify({ items: planItemBreakdown(), text: planBreakdownText(planItemBreakdown()) }));
"""


def count(items, sent=None, manual=None):
    payload = {"cards": items}
    if sent is not None:
        payload["sent"] = sent
    if manual is not None:
        payload["manual"] = manual
    with tempfile.TemporaryDirectory() as folder:
        fixture = Path(folder) / "items.json"
        fixture.write_text(json.dumps(payload), encoding="utf-8")
        result = subprocess.run(
            [NODE, "-e", HARNESS, str(fixture), str(PLAN_JS)],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_basic_cards_count_one_each():
    data = count(
        [
            {"uid": "a", "mode": "basic", "question": "Q1"},
            {"uid": "b", "mode": "basic", "question": "Q2"},
        ]
    )
    assert data["items"] == {"basic": 2, "cloze": 0, "figure": 0, "manual": 0, "total": 2}


def test_each_distinct_cloze_deletion_counts():
    data = count(
        [
            {
                "uid": "c",
                "mode": "cloze",
                "text": "A {{c1::bank}} lends to {{c2::firms}} and {{c3::people}}.",
            }
        ]
    )
    assert data["items"]["cloze"] == 3
    assert data["items"]["total"] == 3


def test_repeated_cloze_number_counts_once():
    data = count(
        [
            {
                "uid": "c",
                "mode": "cloze",
                "text": "The {{c1::AMC}} manages the {{c1::AMC}} fund.",
            }
        ]
    )
    assert data["items"]["cloze"] == 1


def test_cloze_without_braces_still_counts_once():
    data = count([{"uid": "c", "mode": "cloze", "text": "A plain cloze note."}])
    assert data["items"]["cloze"] == 1


def test_figure_cards_count():
    data = count([{"uid": "f", "mode": "figure", "answer": "label"}])
    assert data["items"]["figure"] == 1
    assert data["items"]["total"] == 1


def test_manual_hidden_answers_count_once_each():
    data = count(
        [{"uid": "a", "mode": "basic", "question": "Q"}],
        manual=[
            {"id": "manual-1", "text": "answer", "boxes": []},
            {"id": "manual-2", "text": "another", "boxes": []},
            {"id": "manual-2", "text": "duplicate id", "boxes": []},
        ],
    )
    assert data["items"]["manual"] == 2
    assert data["items"]["total"] == 3


def test_unticked_cards_are_not_counted():
    data = count(
        [
            {"uid": "a", "mode": "basic", "selected": False, "question": "Q"},
            {"uid": "b", "mode": "basic", "selected": True, "question": "Q"},
        ]
    )
    assert data["items"]["total"] == 1


def test_sent_cards_and_drafts_are_deduplicated_by_uid():
    data = count(
        [{"uid": "a", "mode": "basic", "question": "Q"}],
        sent=[
            {"uid": "a", "mode": "basic", "question": "Q"},
            {"uid": "b", "mode": "basic", "question": "Q2"},
        ],
    )
    assert data["items"]["basic"] == 2


def test_breakdown_text_names_every_kind():
    data = count(
        [
            {"uid": "a", "mode": "basic", "question": "Q"},
            {"uid": "c", "mode": "cloze", "text": "{{c1::one}} {{c2::two}}"},
            {"uid": "f", "mode": "figure"},
        ],
        manual=[{"id": "m", "text": "hidden", "boxes": []}],
    )
    assert data["items"]["total"] == 5
    assert data["text"] == "5 study items: 1 Q&A + 2 cloze + 1 figure + 1 hidden"


def test_manual_hides_can_be_planned_with_no_cards():
    data = count([], manual=[{"id": "m", "text": "hidden", "boxes": []}])
    assert data["items"]["total"] == 1
