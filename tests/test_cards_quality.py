"""Tests for the card quality rules (feature 001)."""

from __future__ import annotations

import time

import pytest

from app import cards_quality as cq


_counter = 0


def uid() -> str:
    global _counter
    _counter += 1
    return f"c{_counter}"


def basic(question: str, answer: str, tags=("cardiology",), **extra) -> dict:
    card = {
        "uid": uid(),
        "mode": "basic",
        "question": question,
        "answer": answer,
        "tags": list(tags),
    }
    card.update(extra)
    return card


def cloze(text: str, tags=("cardiology",), **extra) -> dict:
    card = {"uid": uid(), "mode": "cloze", "text": text, "tags": list(tags)}
    card.update(extra)
    return card


def codes(card: dict) -> list[str]:
    return [fault["code"] for fault in cq.evaluate_card(card)]


def has(card: dict, code: str) -> bool:
    return code in codes(card)


def fault(card: dict, code: str) -> dict:
    for item in cq.evaluate_card(card):
        if item["code"] == code:
            return item
    raise AssertionError(f"{code} not in {codes(card)}")


# -- vocabulary ----------------------------------------------------------


def test_vocabulary_is_closed_and_has_a_default():
    assert cq.TYPES == (
        "definition",
        "mechanism",
        "compare",
        "application",
        "enumeration",
        "number",
    )
    assert cq.DEFAULT_TYPE in cq.TYPES


@pytest.mark.parametrize(
    "value, expected",
    [
        ("mechanism", "mechanism"),
        ("  COMPARE  ", "compare"),
        ("essay", cq.DEFAULT_TYPE),
        ("", cq.DEFAULT_TYPE),
        (None, cq.DEFAULT_TYPE),
        (7, cq.DEFAULT_TYPE),
    ],
)
def test_card_type_normalises(value, expected):
    assert cq.card_type({"type": value}) == expected


def test_card_type_missing_reads_as_default():
    assert cq.card_type({}) == cq.DEFAULT_TYPE


# -- clean cards stay clean ---------------------------------------------


CLEAN_CARDS = [
    basic(
        "How does metoprolol differ from carvedilol in heart failure?",
        "Metoprolol blocks beta-1 only, while carvedilol also blocks alpha-1.",
    ),
    basic(
        "Which enzyme converts angiotensin I to angiotensin II?",
        "ACE, mostly in the lungs.",
    ),
    cloze("{{c1::Metoprolol}} is the beta-1 selective blocker used in heart failure."),
    basic(
        "Why does a beta-1 blocker slow the heart?",
        "It reduces sympathetic drive to the sinoatrial node.",
    ),
]


@pytest.mark.parametrize("card", CLEAN_CARDS, ids=lambda card: card.get("question", card.get("text"))[:40])
def test_clean_cards_have_no_faults(card):
    assert codes(card) == []


# -- blocking rules ------------------------------------------------------


def test_empty_basic_card_blocks_on_both_sides():
    found = codes(basic("", ""))
    assert "empty_side" in found


def test_empty_cloze_card_blocks():
    assert has(cloze(""), "empty_side")


def test_picture_card_may_have_an_empty_answer_side():
    card = basic("Identify the structure in the image.", "", image={"name": "x.png"})
    assert "empty_side" not in codes(card)


@pytest.mark.parametrize(
    "question",
    [
        "Explain the mechanism of action of beta blockers.",
        "Describe the pathway that raises blood pressure.",
        "Discuss when to use a loop diuretic.",
        "List the causes of a raised jugular venous pressure.",
        "Which of the following causes a fixed split S2?",
    ],
)
def test_open_ended_question_blocks(question):
    card = basic(question, "They reduce sympathetic outflow.")
    assert has(card, "open_ended")
    assert fault(card, "open_ended")["severity"] == cq.BLOCKING


def test_yes_no_answer_is_a_leak():
    card = basic("Does metoprolol reduce mortality in heart failure?", "Yes, it does.")
    assert has(card, "answer_leak")
    assert fault(card, "answer_leak")["severity"] == cq.BLOCKING


def test_answer_words_all_in_question_is_a_leak():
    card = basic(
        "Which receptor does atropine block, muscarinic or nicotinic?",
        "Muscarinic receptor.",
    )
    assert has(card, "answer_leak")


def test_restating_the_question_is_a_leak():
    card = basic(
        "What effect does atropine have on heart rate in sinus bradycardia?",
        "Atropine increases heart rate in sinus bradycardia.",
    )
    assert fault(card, "answer_leak")["detail"] == "the answer restates the question"


def test_definition_card_is_not_a_leak():
    card = basic("What is preload?", "Preload is the ventricular stretch at end-diastole.")
    assert "answer_leak" not in codes(card)


def test_cloze_with_four_deletions_blocks():
    card = cloze(
        "{{c1::Amitriptyline}}, {{c2::diazepam}}, {{c3::morphine}} and {{c4::prednisolone}}."
    )
    assert fault(card, "cloze_overloaded")["detail"] == "4 deletions"


def test_cloze_deletion_longer_than_eight_words_blocks():
    deletion = "a deletion that runs on and on and on for far too long"
    assert len(cq.words(deletion)) > cq.MAX_DELETION_WORDS
    card = cloze("The {{c1::" + deletion + "}} blocker causes harm.")
    assert "cloze_overloaded" in codes(card)


def test_cloze_with_a_hint_annotation_parses():
    card = cloze("{{c1::Beta-1::receptor subtype}} selective blockers reduce mortality.")
    assert "cloze_overloaded" not in codes(card)
    assert "empty_side" not in codes(card)


# -- warnings ------------------------------------------------------------


def test_list_answer_warns_but_does_not_block():
    card = basic(
        "Which drug classes are first line in hypertension?",
        "ACE inhibitors, ARBs, calcium channel blockers and thiazides.",
    )
    assert fault(card, "list_answer")["severity"] == cq.WARNING
    assert cq.blocking_faults(cq.evaluate_card(card)) == []


def test_short_question_warns():
    assert has(basic("What causes MI?", "Plaque rupture."), "vague_question")


def test_question_pointing_at_the_text_warns():
    card = basic("What is the mechanism described in this?", "Sympathetic drive.")
    assert has(card, "vague_question")


def test_bare_number_warns():
    card = basic("What percentage of patients relapse within one year?", "40")
    assert fault(card, "bare_number")["detail"] == "40"


def test_number_with_a_unit_does_not_warn():
    card = basic("What percentage of patients relapse within one year?", "40 percent")
    assert "bare_number" not in codes(card)


def test_untagged_warns():
    card = basic("Which enzyme converts angiotensin I to angiotensin II?", "ACE.", tags=())
    assert has(card, "untagged")


# -- ordering ------------------------------------------------------------


def test_faults_are_sorted_blocking_first():
    card = cloze("", tags=())
    found = cq.evaluate_card(card)
    severities = [item["severity"] for item in found]
    assert severities == sorted(
        severities, key=lambda severity: cq._SEVERITY_RANK[severity]
    )
    assert found[0]["severity"] == cq.BLOCKING


def test_evaluation_is_deterministic():
    card = basic("What causes MI?", "Plaque rupture.", tags=())
    assert cq.evaluate_card(card) == cq.evaluate_card(dict(card))


# -- batch rules ---------------------------------------------------------


def test_near_identical_fronts_interfere():
    left = basic(
        "In heart failure with reduced ejection fraction, which beta blocker improves "
        "survival by blocking beta-1 receptors?",
        "Metoprolol.",
    )
    right = basic(
        "In heart failure with reduced ejection fraction, which beta blocker improves "
        "survival by blocking alpha-1 receptors?",
        "Carvedilol.",
    )
    faults = cq.evaluate_batch([left, right])
    assert any(item["code"] == "interference_pair" for item in faults[0])
    assert any(item["code"] == "interference_pair" for item in faults[1])


def test_distinct_fronts_do_not_interfere():
    left = basic("Which enzyme converts angiotensin I to angiotensin II?", "ACE.")
    right = basic("Why does atropine cause tachycardia?", "It blocks vagal tone.")
    faults = cq.evaluate_batch([left, right])
    assert all(not item for item in faults)


def test_one_card_cannot_interfere_with_itself():
    card = basic("Which enzyme converts angiotensin I to angiotensin II?", "ACE.")
    assert cq.evaluate_batch([card]) == [[]]


# -- annotation and reporting -------------------------------------------


def test_annotate_cards_sets_type_and_faults_without_mutating_input():
    original = basic("Why does a beta-1 blocker slow the heart?", "Sympathetic drive falls.")
    original["type"] = "mechanism"
    annotated = cq.annotate_cards([original])
    assert annotated[0]["type"] == "mechanism"
    assert annotated[0]["faults"] == []
    assert "faults" not in original


def test_annotate_cards_defaults_a_missing_type():
    annotated = cq.annotate_cards([basic("Which enzyme converts angiotensin I?", "ACE.")])
    assert annotated[0]["type"] == cq.DEFAULT_TYPE


def test_blocked_cards_reports_only_blocking_ones_with_context():
    leaky = basic("Does metoprolol reduce mortality?", "Yes.")
    clean = basic("Which enzyme converts angiotensin I to angiotensin II?", "ACE.")
    report = cq.blocked_cards([clean, leaky])
    assert report["count"] == 1
    assert [item["uid"] for item in report["cards"]] == [leaky["uid"]]
    assert report["cards"][0]["question"].startswith("Does metoprolol")
    assert report["cards"][0]["faults"][0]["code"] == "answer_leak"


def test_blocked_cards_is_capped_but_counts_everything():
    cards = [basic("Does metoprolol reduce mortality?", "Yes.", tags=("x",)) for _ in range(60)]
    report = cq.blocked_cards(cards)
    assert report["count"] == 60
    assert len(report["cards"]) == cq.MAX_BLOCKED_REPORTED


def test_type_counts_omit_missing_types():
    cards = [basic("A?", "B."), basic("A?", "B."), basic("A?", "B.")]
    cards[0]["type"] = "compare"
    assert cq.type_counts(cards) == {"compare": 1, "definition": 2}


# -- performance ---------------------------------------------------------


def test_evaluating_a_thousand_cards_is_fast():
    cards = []
    for index in range(1_000):
        cards.append(
            basic(
                f"Why does drug {index} lower blood pressure in chronic heart failure?",
                f"It blocks receptor {index} on the vessel wall.",
            )
        )
    started = time.perf_counter()
    cq.evaluate_batch(cards)
    elapsed = time.perf_counter() - started
    assert elapsed < 0.25, f"took {elapsed:.3f}s"
