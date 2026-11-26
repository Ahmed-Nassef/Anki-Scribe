import pymupdf

from app.objectives import detect
from app.store import Page, Store


def make_pdf(tmp_path, pages: list[list[str]]):
    """Build a PDF from one list of text lines per page, then load it as a document."""
    pdf = pymupdf.open()
    for lines in pages:
        page = pdf.new_page(width=595, height=842)
        y = 80
        for line in lines:
            page.insert_text((60, y), line, fontsize=11)
            y += 18
    data = pdf.tobytes()
    pdf.close()

    source = tmp_path / "lecture.pdf"
    source.write_bytes(data)
    return Store(tmp_path / "documents").create_pdf_path(source, "lecture.pdf")


OBJECTIVE_BLOCK = [
    "Cardiology Lecture 3",
    "Learning objectives",
    "\u2022 Describe the phases of the cardiac cycle in order",
    "\u2022 Explain the Frank-Starling relationship and its limits",
    "\u2022 Differentiate restrictive from constrictive pericarditis",
    "\u2022 List the first-line drugs for acute decompensated heart failure",
    "The cardiac cycle begins with atrial systole.",
]


def test_detects_a_bulleted_objectives_block(tmp_path):
    doc = make_pdf(tmp_path, [["Cover"], OBJECTIVE_BLOCK])
    objectives = detect(doc)
    assert len(objectives) == 4
    assert objectives[0]["text"] == "Describe the phases of the cardiac cycle in order"
    assert objectives[0]["label"] == "Page 2"
    assert all(obj["unit"] == 1 for obj in objectives)


def test_accepts_numbered_and_indented_items(tmp_path):
    block = [
        "By the end of this lecture you should be able to:",
        "1. Recognise ST elevation on a 12-lead ECG",
        "2. Name the territories of the three coronary arteries",
        "3. Explain why time is muscle in STEMI",
    ]
    doc = make_pdf(tmp_path, [block])
    objectives = detect(doc)
    assert len(objectives) == 3
    assert objectives[0]["text"].startswith("Recognise ST elevation")


def test_ignores_prose_without_a_heading(tmp_path):
    doc = make_pdf(
        tmp_path,
        [
            [
                "This page talks about the heart.",
                "Bullet-like sentences are not objectives here.",
                "Nothing to collect on this page at all.",
            ]
        ],
    )
    assert detect(doc) == []


def test_requires_at_least_three_items(tmp_path):
    doc = make_pdf(
        tmp_path,
        [
            [
                "Learning objectives",
                "\u2022 Only one objective is listed here",
                "The rest of the page is prose that continues on.",
            ]
        ],
    )
    assert detect(doc) == []


def test_collects_items_that_run_onto_the_next_page(tmp_path):
    doc = make_pdf(
        tmp_path,
        [
            ["Learning objectives", "\u2022 Describe the phases of the cardiac cycle"],
            [
                "\u2022 Explain the Frank-Starling relationship and its limits",
                "\u2022 Differentiate restrictive from constrictive pericarditis",
            ],
        ],
    )
    objectives = detect(doc)
    assert len(objectives) == 3


def test_stops_at_the_next_heading(tmp_path):
    doc = make_pdf(
        tmp_path,
        [
            [
                "Learning objectives",
                "\u2022 Describe the phases of the cardiac cycle in order",
                "\u2022 Explain the Frank-Starling relationship and its limits",
                "\u2022 Differentiate restrictive from constrictive pericarditis",
                "Learning objectives",
                "\u2022 This second block must not be appended to the first one",
            ]
        ],
    )
    objectives = detect(doc)
    assert len(objectives) == 3


def test_transcript_objectives(tmp_path):
    store = Store(tmp_path / "documents")
    text = (
        "Welcome to lecture three.\n\n"
        "Learning objectives\n\n"
        "Describe the phases of the cardiac cycle in order\n\n"
        "Explain the Frank-Starling relationship and its limits\n\n"
        "Differentiate restrictive from constrictive pericarditis\n"
    )
    source = tmp_path / "lecture.txt"
    source.write_text(text, encoding="utf-8")
    doc = store.create_transcript_path(source, "lecture.txt")

    objectives = detect(doc)
    assert len(objectives) == 3
    assert objectives[0]["label"].startswith("Segment")
