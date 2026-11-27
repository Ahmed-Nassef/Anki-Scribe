"""AnkiConnect client: decks, note types, preflight and addNotes."""

from __future__ import annotations

import html
import re
from typing import Any

import httpx

from .config import Settings
from .llm import clean_html, clean_tags

# Media files we are willing to reference from a note.
MEDIA_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,80}\.png$")

CONNECTION_HINT = (
    "Couldn't reach Anki. Open Anki on this computer and install the AnkiConnect "
    "add-on (Tools > Add-ons > Get Add-ons, code 2055492159), then restart Anki."
)

# Our own note types carry the provenance Anki Scribe already collected, so a
# card in a four-year-old collection can still say which lecture and which
# sentence it came from. Stock Basic/Cloze remain the fallback.
MODEL_BASIC = "Anki Scribe Basic"
MODEL_CLOZE = "Anki Scribe Cloze"
STOCK_BASIC = "Basic"
STOCK_CLOZE = "Cloze"

BASIC_FIELDS = ("Front", "Back", "Extra", "Source", "Page", "Quote", "QuestionId")
CLOZE_FIELDS = ("Text", "Back Extra", "Source", "Page", "Quote", "QuestionId")

_SOURCE_FOOTER = (
    '{{#Source}}<div class="aki-source">{{Source}}'
    "{{#Page}} \u00b7 {{Page}}{{/Page}}"
    "{{#Quote}}<q>{{Quote}}</q>{{/Quote}}</div>{{/Source}}"
)

_MODEL_CSS = """
.card { font-family: -apple-system, "Segoe UI", Roboto, sans-serif; font-size: 17px;
        line-height: 1.5; color: #1e2522; background: #fffdf8; text-align: left; }
hr#answer { border: none; border-top: 1px solid #d2cab8; margin: 14px 0; }
.aki-extra { color: #4b514c; font-style: italic; margin-top: 8px; }
.aki-source { margin-top: 12px; font-size: 12px; color: #6f736c;
              border-top: 1px dashed #d2cab8; padding-top: 6px; }
.aki-source q { font-style: italic; }
"""


class AnkiError(RuntimeError):
    pass


def _invoke(settings: Settings, action: str, **params: Any) -> Any:
    payload = {"action": action, "version": 6, "params": params}
    try:
        response = httpx.post(settings.anki_url, json=payload, timeout=30.0)
    except httpx.InvalidURL as exc:
        raise AnkiError("That AnkiConnect URL isn't a valid URL.") from exc
    except httpx.RequestError as exc:
        raise AnkiError(f"{CONNECTION_HINT} ({settings.anki_url})") from exc
    if response.status_code != 200:
        raise AnkiError(
            f"AnkiConnect answered HTTP {response.status_code}. Restart Anki and try again."
        )
    try:
        data = response.json()
    except ValueError as exc:
        raise AnkiError("AnkiConnect sent something that wasn't JSON.") from exc
    if data.get("error"):
        raise AnkiError(str(data["error"]))
    return data.get("result")


def deck_names(settings: Settings) -> list[str]:
    decks = _invoke(settings, "deckNames") or []
    return sorted(str(deck) for deck in decks)


def create_deck(settings: Settings, name: str) -> str:
    name = name.strip()
    if not name:
        raise AnkiError("Deck name can't be empty.")
    _invoke(settings, "createDeck", deck=name)
    return name


def rename_deck(settings: Settings, old_name: str, new_name: str) -> str:
    old_name = old_name.strip()
    new_name = new_name.strip()
    if not old_name or not new_name:
        raise AnkiError("Both the old and new deck names are required.")
    _invoke(settings, "renameDeck", oldName=old_name, newName=new_name)
    return new_name


def status(settings: Settings) -> dict:
    try:
        version = _invoke(settings, "version")
        decks = deck_names(settings)
        models = _invoke(settings, "modelNames") or []
    except AnkiError as exc:
        return {
            "connected": False,
            "version": None,
            "decks": [],
            "models": [],
            "message": str(exc),
        }
    return {
        "connected": True,
        "version": version,
        "decks": decks,
        "models": sorted(str(model) for model in models),
        "message": "",
    }


# -- note types ----------------------------------------------------------


def _model_spec(mode: str) -> tuple[str, tuple[str, ...], bool, str, str]:
    if mode == "cloze":
        return (
            MODEL_CLOZE,
            CLOZE_FIELDS,
            True,
            "{{cloze:Text}}",
            "{{cloze:Text}}"
            '{{#Back Extra}}<div class="aki-extra">{{Back Extra}}</div>{{/Back Extra}}'
            + _SOURCE_FOOTER,
        )
    return (
        MODEL_BASIC,
        BASIC_FIELDS,
        False,
        "{{Front}}",
        "{{FrontSide}}<hr id=answer>{{Back}}"
        '{{#Extra}}<div class="aki-extra">{{Extra}}</div>{{/Extra}}'
        + _SOURCE_FOOTER,
    )


def _create_model(settings: Settings, mode: str) -> None:
    name, fields, is_cloze, front, back = _model_spec(mode)
    _invoke(
        settings,
        "createModel",
        modelName=name,
        inOrderFields=list(fields),
        isCloze=is_cloze,
        css=_MODEL_CSS,
        cardTemplates=[{"Name": "Card 1", "Front": front, "Back": back}],
    )


def resolve_model(settings: Settings, mode: str, available: list[str]) -> str | None:
    """Return our note type, creating it if needed; None means use a stock type.

    Never raises for a missing model: a push must still work on a collection
    where model creation is blocked.
    """
    name = _model_spec(mode)[0]
    if name in available:
        return name
    try:
        _create_model(settings, mode)
    except AnkiError:
        return None
    return name


# -- note building -------------------------------------------------------


def _split_tags(raw: str) -> list[str]:
    return clean_tags(raw)


def _source_fields(card: dict) -> tuple[str, str, str, str]:
    source = card.get("source")
    source = source if isinstance(source, dict) else {}
    label = str(card.get("sourceLabel") or source.get("label") or source.get("file") or "")
    page = str(card.get("sourcePage") or source.get("pageLabel") or source.get("label") or "")
    quote = str(card.get("evidence") or source.get("evidence") or source.get("quote") or "")
    question_id = str(card.get("uid") or card.get("id") or "")
    return label[:120], page[:60], quote[:500], question_id[:64]


def _media_name(value: Any) -> str:
    text = str(value or "")
    return text if MEDIA_NAME.match(text) else ""


def _note_for(
    card: dict,
    mode: str,
    tags: list[str],
    deck: str,
    model: str | None,
) -> dict:
    label, page, quote, question_id = _source_fields(card)
    custom = model is not None

    image_front = ""
    image_back = ""
    if mode == "figure":
        figure = card.get("figure") if isinstance(card.get("figure"), dict) else {}
        masked = _media_name(figure.get("masked"))
        revealed = _media_name(figure.get("revealed"))
        if masked:
            image_front = f'<img src="{masked}">'
        if revealed:
            image_back = f'<img src="{revealed}">'
    else:
        # A picture the user attached to this card: front for "identify this",
        # back for "explain this".
        image = card.get("image") if isinstance(card.get("image"), dict) else {}
        name = _media_name(image.get("name"))
        if name:
            tag = f'<img src="{name}">'
            if str(image.get("side") or "front").lower() == "back":
                image_back = tag
            else:
                image_front = tag

    if mode == "cloze":
        text = clean_html(card.get("text", ""))
        if "{{c" not in text or "::" not in text:
            raise AnkiError("A cloze card is missing its {{c1::...}} deletion.")
        extra = clean_html(card.get("extra", ""))
        if image_front:
            text = f"{image_front}<br>{text}"
        if image_back:
            extra = f"{image_back}<br>{extra}" if extra else image_back
        if custom:
            fields = {
                "Text": text,
                "Back Extra": extra,
                "Source": clean_html(label),
                "Page": clean_html(page),
                "Quote": clean_html(quote),
                "QuestionId": question_id,
            }
        else:
            if label:
                text = f'{text}<br><br><i>{clean_html(label)} {clean_html(page)}</i>'
            fields = {"Text": text, "Back Extra": extra}
        note_model = model or STOCK_CLOZE
    else:
        front = clean_html(card.get("question", ""))
        back = clean_html(card.get("answer", ""))
        has_image = bool(image_front or image_back)
        if not has_image and (not front or not back):
            raise AnkiError("A card is missing its question or answer.")
        if image_front:
            front = f"{image_front}<br>{front}" if front else image_front
        if image_back:
            back = f"{image_back}<br>{back}" if back else image_back
        extra = clean_html(card.get("extra", ""))
        if custom:
            fields = {
                "Front": front,
                "Back": back,
                "Extra": extra,
                "Source": clean_html(label),
                "Page": clean_html(page),
                "Quote": clean_html(quote),
                "QuestionId": question_id,
            }
        else:
            if extra:
                back = f"{back}<br><br><i>{extra}</i>"
            if label:
                back = (
                    f"{back}<br><br><span style=\"font-size:11px;opacity:.65\">"
                    f"{clean_html(label)} {clean_html(page)}</span>"
                )
            fields = {"Front": front, "Back": back}
        note_model = model or STOCK_BASIC
    return {
        "deckName": deck,
        "modelName": note_model,
        "fields": fields,
        "tags": tags,
        "options": {"allowDuplicate": False, "duplicateScope": "deck"},
    }


def build_notes(
    settings: Settings,
    deck: str,
    cards: list[dict],
    extra_tags: str = "",
    available_models: list[str] | None = None,
) -> list[dict]:
    if available_models is None:
        available_models = _invoke(settings, "modelNames") or []
    base_tags = _split_tags(extra_tags) + _split_tags(settings.default_tags)
    # Figure cards use the basic note type, so they must not create a second
    # model just because their mode string differs.
    def model_key(mode: str) -> str:
        return "cloze" if mode == "cloze" else "basic"

    models = {
        key: resolve_model(settings, key, available_models)
        for key in {model_key(card.get("mode", "basic")) for card in cards}
    }
    for key, model in models.items():
        if model is not None:
            continue
        stock = STOCK_CLOZE if key == "cloze" else STOCK_BASIC
        if stock not in available_models:
            raise AnkiError(
                f"Your Anki collection has no '{stock}' note type. "
                "Enable it under Tools > Manage Note Types."
            )
    notes: list[dict] = []
    for card in cards:
        mode = card.get("mode", "basic")
        notes.append(
            _note_for(
                card,
                mode,
                base_tags + clean_tags(card.get("tags", [])),
                deck,
                models.get(model_key(mode)),
            )
        )
    return notes


def preflight(
    settings: Settings,
    deck: str,
    cards: list[dict],
    extra_tags: str = "",
) -> dict:
    """Ask Anki which of these cards it would actually accept.

    ``canAddNotes`` answers exactly that, so the user sees duplicates before
    anything is written instead of discovering them after the cards are gone.
    """
    deck = deck.strip()
    if not deck:
        raise AnkiError("Pick a deck name first.")
    if not cards:
        raise AnkiError("There are no cards to check.")
    notes = build_notes(settings, deck, cards, extra_tags)
    results = _invoke(settings, "canAddNotes", notes=notes)
    if not isinstance(results, list) or len(results) != len(notes):
        raise AnkiError("AnkiConnect returned an unexpected preflight answer.")
    accepted = [bool(value) for value in results]
    addable = sum(1 for value in accepted if value)
    return {
        "total": len(accepted),
        "addable": addable,
        "duplicates": len(accepted) - addable,
        "results": accepted,
        "models": sorted({note["modelName"] for note in notes}),
    }


def _store_media(settings: Settings, media: list[dict] | None) -> int:
    """Upload figure images before the notes that reference them."""
    stored = 0
    for item in media or []:
        if not isinstance(item, dict):
            continue
        name = _media_name(item.get("filename"))
        data = str(item.get("data") or "")
        if not name or not data:
            continue
        _invoke(settings, "storeMediaFile", filename=name, data=data)
        stored += 1
    return stored


def push_cards(
    settings: Settings,
    deck: str,
    cards: list[dict],
    extra_tags: str = "",
    media: list[dict] | None = None,
) -> dict:
    deck = deck.strip()
    if not deck:
        raise AnkiError("Pick a deck name first.")
    if not cards:
        raise AnkiError("There are no cards to send.")

    available_models = _invoke(settings, "modelNames") or []
    notes = build_notes(settings, deck, cards, extra_tags, available_models)

    _invoke(settings, "createDeck", deck=deck)
    _store_media(settings, media)
    results = _invoke(settings, "addNotes", notes=notes) or []
    if not isinstance(results, list):
        raise AnkiError("AnkiConnect returned an unexpected addNotes answer.")
    note_ids = [int(value) if value else None for value in results]
    created = sum(1 for note_id in note_ids if note_id)
    duplicates = sum(1 for note_id in note_ids if not note_id)
    return {
        "deck": deck,
        "total": len(notes),
        "created": created,
        "duplicates": duplicates,
        "noteIds": note_ids,
    }


def _plain_field(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def read_review_history(settings: Settings, note_ids: list[int]) -> dict:
    """Read Anki's reps/lapses for notes that Anki Scribe pushed.

    AnkiConnect exposes notesInfo and cardsInfo. Note ids are durable in the
    sent ledger, so this joins a source file to its real review state without
    guessing from deck names.
    """
    ids = [int(note_id) for note_id in note_ids if note_id]
    if not ids:
        return {
            "totals": {
                "notes": 0,
                "cards": 0,
                "learned": 0,
                "new": 0,
                "lapsed": 0,
                "leeches": 0,
            },
            "leeches": [],
        }
    notes: list[dict] = []
    for start in range(0, len(ids), 500):
        chunk = ids[start : start + 500]
        result = _invoke(settings, "notesInfo", notes=chunk)
        if isinstance(result, list):
            notes.extend(note for note in result if isinstance(note, dict))
    card_ids: list[int] = []
    by_note: dict[int, list[int]] = {}
    for note in notes:
        note_id = int(note.get("noteId") or 0)
        cards = note.get("cards") if isinstance(note.get("cards"), list) else []
        by_note[note_id] = [int(card_id) for card_id in cards]
        card_ids.extend(by_note[note_id])
    infos: list[dict] = []
    for start in range(0, len(card_ids), 500):
        chunk = card_ids[start : start + 500]
        result = _invoke(settings, "cardsInfo", cards=chunk)
        if isinstance(result, list):
            infos.extend(info for info in result if isinstance(info, dict))
    note_by_card: dict[int, dict] = {}
    for note in notes:
        note_id = int(note.get("noteId") or 0)
        for card_id in by_note.get(note_id, []):
            note_by_card[card_id] = note
    learned = 0
    new = 0
    lapsed = 0
    leeches: list[dict] = []
    for info in infos:
        card_id = int(info.get("cardId") or 0)
        note = note_by_card.get(card_id, {})
        reps = int(info.get("reps") or 0)
        lapses = int(info.get("lapses") or 0)
        card_type = int(info.get("type") or 0)
        if reps > 0:
            learned += 1
        if card_type == 0:
            new += 1
        if lapses > 0:
            lapsed += 1
        fields = note.get("fields") if isinstance(note.get("fields"), dict) else {}
        front = next(
            (
                _plain_field(value.get("value") if isinstance(value, dict) else value)
                for key, value in fields.items()
                if str(key).lower() in {"front", "text", "question"}
            ),
            "",
        )
        back = next(
            (
                _plain_field(value.get("value") if isinstance(value, dict) else value)
                for key, value in fields.items()
                if str(key).lower() in {"back", "answer", "extra"}
            ),
            "",
        )
        if lapses >= 4:
            leeches.append(
                {
                    "noteId": int(note.get("noteId") or 0),
                    "cardId": card_id,
                    "deck": str(info.get("deckName") or ""),
                    "model": str(note.get("modelName") or ""),
                    "front": front[:500],
                    "back": back[:500],
                    "reps": reps,
                    "lapses": lapses,
                    "interval": int(info.get("interval") or 0),
                    "due": info.get("due"),
                }
            )
    leeches.sort(key=lambda entry: (-entry["lapses"], -entry["reps"], entry["front"]))
    return {
        "totals": {
            "notes": len(notes),
            "cards": len(infos),
            "learned": learned,
            "new": new,
            "lapsed": lapsed,
            "leeches": len(leeches),
        },
        "leeches": leeches[:100],
    }
