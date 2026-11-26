import json

import pytest

from app.config import Settings
from app.llm import (
    CARD_STYLES,
    LLMError,
    _chat,
    clean_html,
    clean_tags,
    evidence_supported,
    generate_cards,
    get_balance,
    identify_chapters,
    parse_cards,
    plain_text,
    regenerate_card,
)


def test_clean_html_allows_basic_formatting_only():
    cleaned = clean_html("<b>Mitral</b> valve & <script>alert(1)</script>")
    assert cleaned == "<b>Mitral</b> valve &amp; &lt;script&gt;alert(1)&lt;/script&gt;"
    assert "<br>" in clean_html("line one\nline two")


def test_identify_chapters_parses_json(monkeypatch):
    def fake_chat(settings, messages):
        assert "Outline" in messages[1]["content"]
        return json.dumps(
            {
                "chapters": [
                    {"title": "Foundations", "subtitle": "Cells", "start": 1, "end": 4},
                    {"title": "Cardiology", "subtitle": "", "start": 5, "end": 9},
                ]
            }
        )

    monkeypatch.setattr("app.llm._chat", fake_chat)
    result = identify_chapters(
        Settings(api_key="sk-test"),
        "Lecture",
        "[Page 1] Foundations",
        "pages",
        9,
    )
    assert result[0]["title"] == "Foundations"
    assert result[1]["start"] == 5


def test_get_balance_reads_deepseek_response(monkeypatch):
    calls = {}

    class Response:
        status_code = 200

        def json(self):
            return {
                "is_available": True,
                "balance_infos": [
                    {
                        "currency": "CNY",
                        "total_balance": "110.00",
                        "granted_balance": "10.00",
                        "topped_up_balance": "100.00",
                    }
                ],
            }

    def fake_get(url, headers, timeout):
        calls["url"] = url
        calls["headers"] = headers
        return Response()

    monkeypatch.setattr("app.llm.httpx.get", fake_get)
    settings = Settings(api_key="sk-test", base_url="https://api.deepseek.com/v1")
    result = get_balance(settings)
    assert calls["url"] == "https://api.deepseek.com/user/balance"
    assert calls["headers"]["Authorization"] == "Bearer sk-test"
    assert result == {
        "isAvailable": True,
        "balances": [
            {"currency": "CNY", "total": "110.00", "granted": "10.00", "toppedUp": "100.00"}
        ],
    }


def test_get_balance_requires_key():
    with pytest.raises(LLMError) as caught:
        get_balance(Settings())
    assert caught.value.status_code == 400


def test_clean_tags_splits_and_sanitizes():
    tags = clean_tags("Cardiology, beta-blockers, , Cardiology, weird tag")
    assert tags == ["Cardiology", "beta-blockers", "weird", "tag"]


def test_plain_text_strips_formatting_tags():
    assert plain_text("A <b>bold</b> answer<br>with a break") == "A bold answer\nwith a break"
    assert plain_text("5 < 10") == "5 < 10"


def test_parse_basic_cards_from_fenced_json():
    payload = """```json
    {"cards": [
      {"question": "What do beta blockers do?", "answer": "<b>Slow heart rate</b>", "extra": "Think metoprolol.", "tags": ["cardiology"], "evidence": "Beta blockers lower heart rate."},
      {"question": "", "answer": "dropped", "tags": []}
    ]}
    ```"""
    cards = parse_cards(payload, "basic")
    assert len(cards) == 1
    assert cards[0]["question"] == "What do beta blockers do?"
    assert cards[0]["answer"] == "Slow heart rate"
    assert cards[0]["tags"] == ["cardiology"]
    assert cards[0]["evidence"] == "Beta blockers lower heart rate."


def test_parse_cloze_requires_deletions():
    good = json.dumps(
        {"cards": [{"text": "The {{c1::mitral valve}} prevents backflow.", "tags": ["cardio"]}]}
    )
    cards = parse_cards(good, "cloze")
    assert cards[0]["text"] == "The {{c1::mitral valve}} prevents backflow."

    bad = json.dumps({"cards": [{"text": "No deletion here", "tags": []}]})
    with pytest.raises(ValueError):
        parse_cards(bad, "cloze")


def test_parse_empty_cards_is_valid():
    assert parse_cards('{"cards": []}', "basic") == []


def test_parse_limits_card_count():
    payload = json.dumps(
        {
            "cards": [
                {"question": f"Q{i}", "answer": "A", "tags": []} for i in range(10)
            ]
        }
    )
    cards = parse_cards(payload, "basic", limit=3)
    assert len(cards) == 3


def test_generate_cards_calls_chat_and_parses(monkeypatch):
    captured = {}

    def fake_chat(settings, messages):
        captured["messages"] = messages
        return json.dumps(
            {
                "cards": [
                    {
                        "question": "Which receptor do beta blockers block?",
                        "answer": "<b>Beta-1 adrenergic</b> receptors.",
                        "extra": "",
                        "tags": ["cardiology"],
                    }
                ]
            }
        )

    monkeypatch.setattr("app.llm._chat", fake_chat)
    settings = Settings(api_key="sk-test")
    result = generate_cards(
        settings, "Beta blockers block beta-1 receptors in the heart.", filename="lecture.pdf"
    )
    assert result["cards"][0]["tags"] == ["cardiology"]
    assert "lecture.pdf" in captured["messages"][1]["content"]
    assert "question/answer" in captured["messages"][1]["content"]


def test_generate_cards_whole_file_requests_dense_cards(monkeypatch):
    captured = {}

    def fake_chat(settings, messages):
        captured["messages"] = messages
        return json.dumps(
            {
                "cards": [
                    {
                        "question": "What is private equity?",
                        "answer": "Capital invested in private companies.",
                        "extra": "",
                        "tags": ["private-equity"],
                        "evidence": "private equity",
                    }
                ]
            }
        )

    monkeypatch.setattr("app.llm._chat", fake_chat)
    result = generate_cards(
        Settings(api_key="sk-test"),
        "Private equity and venture capital are related concepts. " * 3,
        whole_file=True,
    )
    assert result["cards"]
    prompt = captured["messages"][1]["content"]
    assert "covering every bullet" in prompt
    assert "at most 25" in prompt
    assert "do not summarize, merge separate facts" in prompt


def test_generate_cards_requires_key():
    with pytest.raises(LLMError):
        generate_cards(Settings(api_key=""), "x" * 40)


def test_generate_cards_rejects_short_selection():
    with pytest.raises(LLMError):
        generate_cards(Settings(api_key="sk-test"), "too short")


def test_chat_uses_openai_compatible_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": '{"cards":[]}'}}]}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured["json"] = kwargs["json"]
        captured["headers"] = kwargs["headers"]
        return FakeResponse()

    monkeypatch.setattr("app.llm.httpx.post", fake_post)
    content = _chat(
        Settings(api_key="sk-test", base_url="https://api.deepseek.com/"),
        [{"role": "user", "content": "hello"}],
    )
    assert content == '{"cards":[]}'
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["json"]["model"] == "deepseek-chat"
    assert captured["json"]["response_format"] == {"type": "json_object"}


def test_chat_maps_401_to_friendly_error(monkeypatch):
    class Unauthorized:
        status_code = 401
        text = ""

        @staticmethod
        def json():
            return {"error": {"message": "invalid key"}}

    monkeypatch.setattr("app.llm.httpx.post", lambda *args, **kwargs: Unauthorized())
    with pytest.raises(LLMError, match="rejected that API key"):
        _chat(Settings(api_key="sk-bad"), [{"role": "user", "content": "hello"}])

# -- evidence verification ------------------------------------------------


def test_evidence_supported_tolerates_typography():
    excerpt = "Metoprolol is cardioselective, so it causes less bronchospasm than propranolol."
    assert evidence_supported("Metoprolol is cardioselective", excerpt)
    assert evidence_supported("metoprolol   is cardioselective", excerpt)
    assert evidence_supported(
        "Metoprolol is cardioselective \u2014 so it causes less bronchospasm", excerpt
    )
    assert not evidence_supported("Metoprolol is a beta blocker", excerpt)
    assert not evidence_supported("is cardio", excerpt)
    assert not evidence_supported("", excerpt)


def test_parse_cards_marks_evidence_against_the_excerpt():
    payload = json.dumps(
        {
            "cards": [
                {
                    "question": "Q1",
                    "answer": "A1",
                    "evidence": "beta blockers reduce heart rate",
                },
                {
                    "question": "Q2",
                    "answer": "A2",
                    "evidence": "an invented sentence that is not in the source",
                },
                {"question": "Q3", "answer": "A3", "evidence": ""},
            ]
        }
    )
    excerpt = "Beta blockers reduce heart rate by blocking beta-1 receptors."
    cards = parse_cards(payload, "basic", excerpt=excerpt)
    assert [card["verified"] for card in cards] == [True, False, False]


def test_strict_mode_drops_unverified_cards():
    payload = json.dumps(
        {
            "cards": [
                {"question": "Q1", "answer": "A1", "evidence": "beta blockers reduce heart rate"},
                {"question": "Q2", "answer": "A2", "evidence": "invented words here"},
            ]
        }
    )
    excerpt = "Beta blockers reduce heart rate by blocking beta-1 receptors."
    cards = parse_cards(payload, "basic", excerpt=excerpt, strict=True)
    assert len(cards) == 1
    assert cards[0]["question"] == "Q1"


def test_generate_cards_reports_unverified_count(monkeypatch):
    def fake_chat(settings, messages):
        return json.dumps(
            {
                "cards": [
                    {"question": "Q1", "answer": "A1", "evidence": "beta blockers reduce heart rate"},
                    {"question": "Q2", "answer": "A2", "evidence": "this is not in the text at all"},
                ]
            }
        )

    monkeypatch.setattr("app.llm._chat", fake_chat)
    result = generate_cards(
        Settings(api_key="sk-test"),
        "Beta blockers reduce heart rate by blocking beta-1 receptors in the heart.",
    )
    assert result["unverified"] == 1
    assert result["strict"] is False
    assert [card["verified"] for card in result["cards"]] == [True, False]


# -- card styles ---------------------------------------------------------


@pytest.fixture
def run_with_style(monkeypatch):
    """Run generate_cards and expose the system prompt it sent."""
    captured = {}

    def fake_chat(settings, messages):
        captured["system"] = messages[0]["content"]
        return json.dumps(
            {
                "cards": [
                    {
                        "question": "Which receptor?",
                        "answer": "Beta-1",
                        "evidence": "beta blockers reduce heart rate",
                    }
                ]
            }
        )

    monkeypatch.setattr("app.llm._chat", fake_chat)

    def run(style: str) -> dict:
        captured["result"] = generate_cards(
            Settings(api_key="sk-test"),
            "Beta blockers reduce heart rate by blocking beta-1 receptors in the heart.",
            style=style,
        )
        return captured

    return run


def test_each_style_reaches_the_system_prompt(run_with_style):
    for style in ("mechanism", "clinical", "table", "trap"):
        captured = run_with_style(style)
        assert "Card style:" in captured["system"], style
        assert CARD_STYLES[style] in captured["system"], style


def test_balanced_style_leaves_the_prompt_alone(run_with_style):
    captured = run_with_style("balanced")
    assert "Card style:" not in captured["system"]
    assert captured["result"]["style"] == "balanced"


def test_unknown_style_falls_back_to_balanced(run_with_style):
    captured = run_with_style("does-not-exist")
    assert "Card style:" not in captured["system"]
    assert captured["result"]["style"] == "balanced"


# -- regenerating one card -----------------------------------------------

QUOTE = "Metoprolol is cardioselective, so it causes less bronchospasm than propranolol."


def test_regenerate_rewrites_from_the_saved_quote(monkeypatch):
    captured = {}

    def fake_chat(settings, messages):
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        return json.dumps(
            {
                "cards": [
                    {
                        "question": "Why is metoprolol safer in asthma?",
                        "answer": "It is cardioselective.",
                        "evidence": "Metoprolol is cardioselective",
                    }
                ]
            }
        )

    monkeypatch.setattr("app.llm._chat", fake_chat)
    result = regenerate_card(
        Settings(api_key="sk-test"),
        QUOTE,
        question="What does metoprolol do?",
        answer="It blocks beta receptors.",
        nudge="simpler",
    )
    assert result["mode"] == "basic"
    assert result["nudge"] == "simpler"
    assert "Metoprolol is cardioselective" in captured["user"]
    assert "Question: What does metoprolol do?" in captured["user"]
    assert "Make it simpler" in captured["user"]
    assert result["card"]["verified"] is True


def test_regenerate_cloze_nudge_switches_mode(monkeypatch):
    def fake_chat(settings, messages):
        assert "{{c1::" in messages[0]["content"] or "cloze" in messages[0]["content"].lower()
        return json.dumps(
            {
                "cards": [
                    {
                        "text": "Metoprolol is {{c1::cardioselective}}, so less bronchospasm.",
                        "evidence": "Metoprolol is cardioselective",
                    }
                ]
            }
        )

    monkeypatch.setattr("app.llm._chat", fake_chat)
    result = regenerate_card(Settings(api_key="sk-test"), QUOTE, nudge="cloze")
    assert result["mode"] == "cloze"
    assert result["card"]["text"].startswith("Metoprolol is {{c1::")


def test_regenerate_keeps_cloze_mode_for_a_cloze_card(monkeypatch):
    def fake_chat(settings, messages):
        return json.dumps(
            {
                "cards": [
                    {
                        "text": "Metoprolol is {{c1::cardioselective}}.",
                        "evidence": "Metoprolol is cardioselective",
                    }
                ]
            }
        )

    monkeypatch.setattr("app.llm._chat", fake_chat)
    result = regenerate_card(
        Settings(api_key="sk-test"),
        QUOTE,
        mode="cloze",
        cloze_text="Metoprolol is {{c1::cardioselective}}.",
        nudge="shorter",
    )
    assert result["mode"] == "cloze"
    assert result["nudge"] == "shorter"


def test_regenerate_rejects_a_missing_quote():
    with pytest.raises(LLMError) as caught:
        regenerate_card(Settings(api_key="sk-test"), "too short")
    assert caught.value.status_code == 400


def test_regenerate_unknown_nudge_falls_back(monkeypatch):
    def fake_chat(settings, messages):
        return json.dumps(
            {
                "cards": [
                    {
                        "question": "Q?",
                        "answer": "A",
                        "evidence": "Metoprolol is cardioselective",
                    }
                ]
            }
        )

    monkeypatch.setattr("app.llm._chat", fake_chat)
    result = regenerate_card(Settings(api_key="sk-test"), QUOTE, nudge="nonsense")
    assert result["nudge"] == "improve"


def test_regenerate_surfaces_unparseable_output(monkeypatch):
    monkeypatch.setattr("app.llm._chat", lambda settings, messages: "no json here")
    with pytest.raises(LLMError, match="usable rewrite"):
        regenerate_card(Settings(api_key="sk-test"), QUOTE)

