"""Executable tests for the client-side risk scorer.

The scorer is pure: it reads ``state.cards`` and returns a map. That makes it
runnable outside a browser, so these tests execute the real ``risk.js`` under
Node instead of re-implementing its rules in Python. They skip when Node is not
installed — the app does not need Node, only this test does.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

NODE = shutil.which("node")
RISK_JS = Path(__file__).resolve().parent.parent / "app" / "static" / "js" / "risk.js"

pytestmark = pytest.mark.skipif(
    NODE is None or not RISK_JS.exists(), reason="needs Node and risk.js"
)

HARNESS = """
const fs = require("fs");
const vm = require("vm");
globalThis.state = { cards: JSON.parse(fs.readFileSync(process.argv[1], "utf8")) };
vm.runInThisContext(fs.readFileSync(process.argv[2], "utf8"), { filename: "risk.js" });
const risk = computeRisk();
const scores = {};
for (const card of state.cards) {
  const entry = risk.get(card.uid) || { score: 0, reasons: [] };
  scores[card.uid] = { score: entry.score, reasons: entry.reasons.map((r) => r.label) };
}
console.log(JSON.stringify({ scores, order: riskyCards().map((card) => card.uid) }));
"""


def score(cards: list[dict]) -> dict:
    # The fixture goes through a file: a 2,000-card batch is far past the
    # Windows command-line limit.
    with tempfile.TemporaryDirectory() as folder:
        fixture = Path(folder) / "cards.json"
        fixture.write_text(json.dumps(cards), encoding="utf-8")
        result = subprocess.run(
            [NODE, "-e", HARNESS, str(fixture), str(RISK_JS)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def card(uid: str, question: str = "Which receptor does metoprolol block?", **extra) -> dict:
    base = {
        "uid": uid,
        "mode": "basic",
        "question": question,
        "answer": "Beta-1",
        "extra": "",
        "tags": ["cardiology"],
        "verified": True,
    }
    base.update(extra)
    return base


def test_clean_card_is_not_flagged():
    data = score([card("clean", "Which receptor does metoprolol block in the heart?")])
    assert data["scores"]["clean"]["score"] == 0
    assert data["order"] == []


def test_unverified_quote_scores_highest():
    data = score(
        [
            card("clean", "Which receptor does metoprolol block in the heart?"),
            card("bad", "Which receptor does metoprolol block in the heart", verified=False),
        ]
    )
    assert data["scores"]["bad"]["score"] >= 5
    assert "the quote is not in the source" in data["scores"]["bad"]["reasons"]
    assert data["order"][0] == "bad"


def test_vague_question_and_missing_tags_are_both_reported():
    data = score([card("vague", "Why?", tags=[])])
    reasons = data["scores"]["vague"]["reasons"]
    assert "a question this short rarely stands alone" in reasons
    assert "no tags" in reasons
    assert data["scores"]["vague"]["score"] == 4


def test_long_cloze_deletion_is_flagged():
    text = "One {{c1::very long deletion that runs to eight words easily}} here"
    data = score(
        [
            {
                "uid": "cloze",
                "mode": "cloze",
                "question": "",
                "text": text,
                "answer": "",
                "tags": ["x"],
                "verified": True,
            }
        ]
    )
    assert "a deletion longer than six words" in data["scores"]["cloze"]["reasons"]


def test_near_duplicate_pair_is_flagged_in_both_directions():
    data = score(
        [
            card("a", "Which receptor does metoprolol block in the heart?"),
            card("b", "Which receptor does metoprolol block in the heart tissue?"),
        ]
    )
    assert "overlaps another card in this batch" in data["scores"]["a"]["reasons"]
    assert "overlaps another card in this batch" in data["scores"]["b"]["reasons"]


def test_distinct_cards_are_not_treated_as_duplicates():
    data = score(
        [
            card("a", "Which receptor does metoprolol block in the heart?"),
            card("b", "What is the first-line treatment for anaphylaxis?"),
        ]
    )
    assert data["scores"]["a"]["reasons"] == []
    assert data["scores"]["b"]["reasons"] == []


def test_order_puts_the_worst_card_first():
    data = score(
        [
            card("fine", "Which receptor does metoprolol block in the heart?"),
            card("notags", "What is the loading dose of amiodarone in cardiac arrest?", tags=[]),
            card("bad", "What is the loading dose of amiodarone in cardiac arrest", verified=False),
        ]
    )
    assert data["order"][0] == "bad"
    assert "fine" not in data["order"]


def test_a_two_thousand_card_batch_stays_fast():
    cards = [
        card(f"c{index}", f"What is fact number {index} about topic {index}?")
        for index in range(2000)
    ]
    data = score(cards)
    assert len(data["scores"]) == 2000
