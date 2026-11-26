"""Tests for finding card answers inside a PDF page."""

from __future__ import annotations

from types import SimpleNamespace

import pymupdf
import pytest

from app import answers


def make_pdf(tmp_path, pages: list[list[tuple[str, float, float, int]]]):
    pdf = pymupdf.open()
    for entries in pages:
        page = pdf.new_page(width=720, height=450)
        for text, x, y, size in entries:
            page.insert_text((x, y), text, fontsize=size)
    path = tmp_path / "lecture.pdf"
    path.write_bytes(pdf.tobytes())
    pdf.close()
    return path


def doc_for(path, page_count):
    return SimpleNamespace(pages=[None] * page_count, source=str(path))


def card(uid, **extra):
    base = {
        "uid": uid,
        "mode": "basic",
        "question": "A question",
        "answer": "An answer",
        "source": {"pages": [0, 0], "quote": ""},
    }
    base.update(extra)
    return base


def texts(result):
    return [mask["text"].lower() for mask in result["masks"]]


def test_cloze_term_is_masked_where_it_appears(tmp_path):
    path = make_pdf(
        tmp_path,
        [
            [
                ("The Formats", 46, 60, 26),
                ("The Banking Directive regulates banks in Europe.", 46, 150, 13),
                ("The Financial Services Directive also applies.", 46, 185, 13),
            ]
        ],
    )
    result = answers.build_masks(
        doc_for(path, 1),
        [
            card(
                "c1",
                mode="cloze",
                text="The {{c1::Banking Directive}} regulates banks.",
                source={
                    "pages": [0, 0],
                    "quote": "The Banking Directive regulates banks in Europe.",
                },
            )
        ],
    )
    assert result["stats"]["maskedCards"] == 1
    assert len(result["masks"]) == 1
    mask = result["masks"][0]
    assert mask["page"] == 0
    assert mask["kind"] == "cloze"
    assert mask["text"] == "Banking Directive"
    assert mask["boxes"]
    for box in mask["boxes"]:
        assert 0 <= box["x"] < 1
        assert 0 <= box["y"] < 1
        assert 0 < box["w"] <= 1
        assert 0 < box["h"] <= 1


def test_heading_is_never_masked(tmp_path):
    path = make_pdf(
        tmp_path,
        [[("Deal Formats", 46, 50, 28), ("The Banking Directive regulates banks.", 46, 150, 13)]],
    )
    result = answers.build_masks(
        doc_for(path, 1),
        [
            card(
                "title-card",
                mode="cloze",
                text="{{c1::Formats}}",
                source={"pages": [0, 0], "quote": "Deal Formats"},
            )
        ],
    )
    assert result["masks"] == []
    assert result["stats"]["maskedCards"] == 0


def test_basic_answer_hides_the_specific_phrase_not_the_paragraph(tmp_path):
    path = make_pdf(
        tmp_path,
        [
            [
                ("The Formats", 46, 50, 26),
                ("Brazil and Russia also use the European format.", 46, 150, 13),
                ("European banks are universal and can provide any service.", 46, 185, 13),
            ]
        ],
    )
    result = answers.build_masks(
        doc_for(path, 1),
        [
            card(
                "basic",
                answer="Brazil and Russia also use the European format.",
                source={
                    "pages": [0, 0],
                    "quote": "Brazil and Russia also use the European format.",
                },
            )
        ],
    )
    found = texts(result)
    assert "brazil and russia" in found
    assert all("also use the european format" not in text for text in found)
    assert result["stats"]["maskedCards"] == 1


def test_quote_page_is_preferred_over_the_rest_of_the_range(tmp_path):
    path = make_pdf(
        tmp_path,
        [
            [("First page", 46, 50, 26), ("The Banking Directive regulates banks.", 46, 150, 13)],
            [("Second page", 46, 50, 26), ("Metoprolol blocks beta-1 receptors.", 46, 150, 13)],
        ],
    )
    result = answers.build_masks(
        doc_for(path, 2),
        [
            card(
                "paged",
                mode="cloze",
                text="Metoprolol blocks {{c1::beta-1}} receptors.",
                source={
                    "pages": [0, 1],
                    "quote": "Metoprolol blocks beta-1 receptors.",
                },
            )
        ],
    )
    assert [mask["page"] for mask in result["masks"]] == [1]


def test_a_table_of_contents_is_not_masked(tmp_path):
    path = make_pdf(
        tmp_path,
        [
            [
                ("Content", 46, 50, 26),
                ("1. Management Fees and Carried Interest", 46, 120, 13),
                ("2. Closed-End Funds in Europe", 46, 145, 13),
                ("3. Investment Firms and Banks", 46, 170, 13),
                ("4. Limited Partnerships in the US", 46, 195, 13),
                ("5. The SBIC Experience in the US", 46, 220, 13),
                ("6. Funds and VCT in the UK", 46, 245, 13),
            ]
        ],
    )
    result = answers.build_masks(
        doc_for(path, 1),
        [
            card(
                "toc",
                mode="cloze",
                text="{{c1::Management Fees}}",
                source={"pages": [0, 0], "quote": "Management Fees and Carried Interest"},
            )
        ],
    )
    assert result["masks"] == []


def test_duplicate_terms_from_two_cards_are_one_mask(tmp_path):
    path = make_pdf(
        tmp_path,
        [[("The Banking Directive regulates banks.", 46, 150, 13)]],
    )
    cards = [
        card("a", mode="cloze", text="{{c1::Banking Directive}}", source={"pages": [0, 0]}),
        card("b", mode="cloze", text="{{c1::Banking Directive}}", source={"pages": [0, 0]}),
    ]
    result = answers.build_masks(doc_for(path, 1), cards)
    assert len(result["masks"]) == 1


def test_cards_without_an_answer_are_ignored(tmp_path):
    path = make_pdf(tmp_path, [[("A page with a fact.", 46, 150, 13)]])
    result = answers.build_masks(
        doc_for(path, 1),
        [card("empty", question="", answer="", source={"pages": [0, 0]})],
    )
    assert result["masks"] == []
    assert result["stats"]["cards"] == 0


def test_build_masks_is_empty_without_documents_or_cards(tmp_path):
    path = make_pdf(tmp_path, [[("Text", 46, 150, 13)]])
    assert answers.build_masks(doc_for(path, 0), [])["masks"] == []
    assert answers.build_masks(doc_for(path, 1), [])["masks"] == []


# -- pure term extraction --------------------------------------------------


def test_cloze_terms_are_read_in_order():
    assert answers.cloze_terms("A {{c1::bank}} lends to {{c2::firms}}.") == ["bank", "firms"]


def test_cloze_without_deletions_is_empty():
    assert answers.cloze_terms("A plain sentence.") == []


def test_answer_terms_keep_names_and_numbers_together():
    terms = answers.answer_terms(
        "The European Union format is regulated by an EU Directive.",
        "there are two formats, each having its regulation",
    )
    assert "European Union" in terms
    assert "EU Directive" in terms


def test_answer_terms_do_not_return_a_whole_paragraph():
    answer = (
        "The financial benefit is generated through the injection of cash in return "
        "for shares of the venture-backed company, and it has a positive effect on "
        "the cost of capital for the whole fund."
    )
    terms = answers.answer_terms(answer, "")
    assert all(len(term.split()) <= 10 for term in terms)
    # With no quote and no name or number, a paraphrased paragraph is left for
    # manual hiding rather than covered in random single-word blanks.
    assert terms == []


def test_answer_terms_ignore_sentence_initial_grammar_words():
    terms = answers.answer_terms(
        "Approval by both the local and central authorities.",
        "before a financial institution becomes active, there must be an approval by both the local and central authorities",
    )
    assert "Approval" not in terms
    assert any("approval by both" in term.lower() for term in terms)


@pytest.mark.parametrize("bad", [None, "", "   "])
def test_answer_terms_tolerate_empty_input(bad):
    assert answers.answer_terms(bad) == []  # type: ignore[arg-type]


def test_answer_terms_keep_a_bare_number():
    assert answers.answer_terms(42) == ["42"]  # type: ignore[arg-type]


def test_rotated_page_keeps_boxes_inside_the_page(tmp_path):
    pdf = pymupdf.open()
    page = pdf.new_page(width=600, height=800)
    page.insert_text((60, 120), "The Banking Directive regulates banks.", fontsize=13)
    page.set_rotation(90)
    path = tmp_path / "rotated.pdf"
    path.write_bytes(pdf.tobytes())
    pdf.close()
    result = answers.build_masks(
        doc_for(path, 1),
        [
            card(
                "rotated",
                mode="cloze",
                text="{{c1::Banking Directive}}",
                source={
                    "pages": [0, 0],
                    "quote": "The Banking Directive regulates banks.",
                },
            )
        ],
    )
    assert len(result["masks"]) == 1
    for box in result["masks"][0]["boxes"]:
        assert 0 <= box["x"] <= 1
        assert 0 <= box["y"] <= 1
        assert box["x"] + box["w"] <= 1.0001
        assert box["y"] + box["h"] <= 1.0001


def test_each_mask_names_the_card_that_owns_it(tmp_path):
    path = make_pdf(
        tmp_path,
        [[("Brazil and Russia also use the European format.", 46, 150, 13)]],
    )
    result = answers.build_masks(
        doc_for(path, 1),
        [
            card(
                "basic-1",
                answer="Brazil and Russia also use the European format.",
                source={"pages": [0, 0], "quote": "Brazil and Russia also use the European format."},
            )
        ],
    )
    assert result["masks"]
    assert all(mask["uids"] == ["basic-1"] for mask in result["masks"])


def test_two_cards_with_the_same_blank_share_it(tmp_path):
    path = make_pdf(
        tmp_path,
        [[("The Banking Directive regulates banks.", 46, 150, 13)]],
    )
    cards = [
        card("a", mode="cloze", text="{{c1::Banking Directive}}", source={"pages": [0, 0]}),
        card("b", mode="cloze", text="{{c1::Banking Directive}}", source={"pages": [0, 0]}),
    ]
    result = answers.build_masks(doc_for(path, 1), cards)
    assert len(result["masks"]) == 1
    assert result["masks"][0]["uids"] == ["a", "b"]


@pytest.mark.parametrize(
    "card, expected",
    [
        ({"type": "number", "answer": "2024"}, "date"),
        ({"type": "number", "answer": "5 mg twice a day"}, "dose"),
        ({"type": "number", "answer": "42"}, "number"),
        ({"type": "definition", "answer": "A bank is a financial institution."}, "definition"),
        ({"type": "mechanism", "answer": "It blocks beta-1."}, "mechanism"),
        ({"type": "compare", "answer": "Metoprolol is beta-1 selective; carvedilol is not."}, "compare"),
        ({"type": "enumeration", "answer": "Banks, funds and firms."}, "list"),
        ({"type": "application", "answer": "Use it in a patient with asthma."}, "application"),
        ({"type": "definition", "question": "What is the procedure for inserting a line?", "answer": "Sterilise the site first."}, "procedure"),
        ({"type": "", "answer": "The cost of capital."}, "fact"),
    ],
)
def test_card_categories(card, expected):
    assert answers.card_category(card) == expected


def test_mask_carries_its_category(tmp_path):
    path = make_pdf(tmp_path, [[("The dose is 5 mg twice a day.", 46, 150, 13)]])
    result = answers.build_masks(
        doc_for(path, 1),
        [
            card(
                "dose",
                answer="The dose is 5 mg twice a day.",
                type="number",
                source={"pages": [0, 0], "quote": "The dose is 5 mg twice a day."},
            )
        ],
    )
    assert result["masks"]
    assert result["masks"][0]["category"] == "dose"
