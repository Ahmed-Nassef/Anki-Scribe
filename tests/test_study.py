import pymupdf
import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.drafts import DraftStore
from app.library import Library
from app.main import create_app
from app.store import Store
from app.study import StudyBody, build_html, build_pdf, filename


def make_body(cards=None, title="Cardiology Lecture 3"):
    return StudyBody(
        title=title,
        source="lecture-3.pdf",
        deck="Anki Scribe::Cardiology",
        generated="15 Nov 2026",
        sections=[
            {
                "title": "Chapter 1",
                "cards": cards
                or [
                    {
                        "kind": "basic",
                        "question": "QUESTIONALPHA what do beta blockers do?",
                        "answer": "ANSWEROMEGA they slow the heart.",
                        "detail": "Evidence quote.",
                    },
                    {
                        "kind": "cloze",
                        "question": "Start at a [ \u2026 ] dose.",
                        "answer": "Start at a LOWDOSE.",
                        "detail": "",
                    },
                ],
            }
        ],
    )


def page_texts(data: bytes) -> list[str]:
    doc = pymupdf.open(stream=data, filetype="pdf")
    return [page.get_text().replace("\u2010", "-") for page in doc]


def answer_start(texts: list[str]) -> int:
    for index, text in enumerate(texts):
        if text.lstrip().startswith("Answers"):
            return index
    raise AssertionError("no answer key page found")


def test_pdf_keeps_answers_off_the_question_pages():
    data = build_pdf(make_body())
    texts = page_texts(data)
    split = answer_start(texts)

    question_pages = " ".join(texts[:split])
    answer_pages = " ".join(texts[split:])

    assert "QUESTIONALPHA" in question_pages
    assert "LOWDOSE" not in question_pages
    assert "ANSWEROMEGA" not in question_pages
    assert "ANSWEROMEGA" in answer_pages
    assert "LOWDOSE" in answer_pages
    assert "Answers" in texts[split]


def test_pdf_questions_link_to_their_answers_and_back():
    data = build_pdf(make_body())
    doc = pymupdf.open(stream=data, filetype="pdf")
    texts = [page.get_text() for page in doc]
    split = answer_start([t.replace("\u2010", "-") for t in texts])

    forward = []
    backward = []
    for index, page in enumerate(doc):
        for link in page.get_links():
            assert link["kind"] == pymupdf.LINK_GOTO
            if index < split:
                forward.append((index, link["page"]))
            else:
                backward.append((index, link["page"]))

    # Two clickable regions per question (the card and its "Show answer" pill).
    assert len(forward) == 4
    assert all(target >= split for _, target in forward)
    assert len(backward) == 2
    assert all(target < split for _, target in backward)
    assert {target for _, target in forward} == set(range(split, doc.page_count))


def test_pdf_paginates_and_survives_long_text():
    cards = [
        {
            "kind": "basic",
            "question": f"Question {n} " + ("long wording " * 40),
            "answer": f"Answer {n} " + ("detailed explanation " * 45),
            "detail": "extra " * 60,
        }
        for n in range(1, 13)
    ]
    data = build_pdf(make_body(cards=cards))
    doc = pymupdf.open(stream=data, filetype="pdf")
    assert doc.page_count >= 4
    texts = [page.get_text().replace("\u2010", "-") for page in doc]
    split = answer_start(texts)
    # Every question number is on a question page, every answer text is in the key.
    assert "Question 12" in " ".join(texts[:split])
    assert "Answer 12" in " ".join(texts[split:])


def test_html_hides_answers_and_escapes_content():
    body = make_body(
        cards=[
            {
                "kind": "basic",
                "question": '<script>alert("x")</script> & what is it?',
                "answer": "The <b>answer</b> & more",
                "detail": "",
            }
        ]
    )
    markup = build_html(body)
    assert "<script>alert" not in markup
    assert "&lt;script&gt;" in markup
    assert "The &lt;b&gt;answer&lt;/b&gt; &amp; more" in markup
    assert 'id="a1" hidden' in markup
    assert 'aria-expanded="false"' in markup
    assert 'data-act="reveal"' in markup
    assert markup.count('class="card"') == 1


def test_html_groups_sections_and_numbers_cards_in_order():
    body = StudyBody(
        title="Lecture",
        sections=[
            {"title": "Alpha", "cards": [{"question": "First?", "answer": "One."}]},
            {"title": "Beta", "cards": [{"question": "Second?", "answer": "Two."}]},
        ],
    )
    markup = build_html(body)
    assert markup.index("<h2>Alpha</h2>") < markup.index("First?")
    assert markup.index("First?") < markup.index("<h2>Beta</h2>")
    assert markup.index("Second?") < markup.index("Two.")
    assert '<span class="num">1</span>' in markup
    assert '<span class="num">2</span>' in markup


def test_filename_is_ascii_and_safe():
    body = StudyBody(title="Cardiology: Lecture / 3", sections=[{"cards": [{"question": "Q?"}]}])
    assert filename(body, "pdf") == "cardiology-lecture-3-study.pdf"
    assert filename(StudyBody(title="\u0645\u062d\u0627\u0636\u0631\u0629", sections=[{"cards": [{"question": "Q?"}]}]), "html") == "study-sheet-study.html"


@pytest.fixture
def client(tmp_path):
    app = create_app(
        store=Store(tmp_path / "documents"),
        settings=Settings(api_key="sk-test-key", anki_url="http://127.0.0.1:9"),
        library=Library(tmp_path / "library.json"),
        drafts=DraftStore(tmp_path / "drafts.json"),
    )
    return TestClient(app, base_url="http://127.0.0.1")


def test_api_returns_pdf_and_html(client):
    payload = {
        "title": "Lecture 3",
        "source": "lecture-3.pdf",
        "sections": [
            {
                "title": "Chapter 1",
                "cards": [{"kind": "basic", "question": "What?", "answer": "That."}],
            }
        ],
    }
    pdf = client.post("/api/study/pdf", json=payload)
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert "lecture-3-study.pdf" in pdf.headers["content-disposition"]
    assert pdf.content.startswith(b"%PDF")

    page = client.post("/api/study/html", json=payload)
    assert page.status_code == 200, page.text
    assert page.headers["content-type"].startswith("text/html")
    assert "lecture-3-study.html" in page.headers["content-disposition"]
    assert "What?" in page.text


def test_api_rejects_an_empty_sheet(client):
    response = client.post("/api/study/pdf", json={"title": "Empty", "sections": []})
    assert response.status_code == 422


def test_html_escapes_the_metadata_line():
    body = make_body()
    body.source = '<img src=x onerror="alert(1)">'
    body.generated = '<script>alert(2)</script>'
    page = build_html(body)
    assert "<img src=x" not in page
    assert "<script>alert(2)</script>" not in page
    assert "&lt;script&gt;alert(2)&lt;/script&gt;" in page


def test_pdf_keeps_metadata_as_plain_text():
    # The PDF is not markup, so the same field must stay literal there.
    body = make_body()
    body.source = "<b>not bold</b>"
    pdf = build_pdf(body)
    assert pdf.startswith(b"%PDF")
    document = pymupdf.open(stream=pdf, filetype="pdf")
    text = "".join(page.get_text() for page in document)
    document.close()
    assert "<b>not bold</b>" in text
