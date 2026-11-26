"""Study sheets: a questions-first PDF and a standalone HTML page.

Both formats hide the answers. The HTML page reveals them in place; the PDF has
no portable "toggle text" feature, so each question is a link that jumps to its
answer in a key at the end, and every answer links back.

The same payload feeds both builders, so numbering and grouping always match.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import pymupdf
from pydantic import BaseModel, Field

# -- palette (matches the app's styles.css) --------------------------------

INK = (0.118, 0.145, 0.133)
MUTED = (0.435, 0.451, 0.424)
FAINT = (0.588, 0.596, 0.561)
LINE = (0.894, 0.871, 0.82)
ACCENT = (0.059, 0.463, 0.431)
ACCENT_INK = (0.027, 0.267, 0.247)
ACCENT_SOFT = (0.882, 0.949, 0.933)

# -- page geometry (A4) ----------------------------------------------------

PAGE_W = 595.28
PAGE_H = 841.89
MARGIN_X = 46.0
TOP = 46.0
BOTTOM = 62.0
CONTENT_W = PAGE_W - 2 * MARGIN_X
BADGE_W = 20.0
TEXT_INDENT = 34.0

Q_SIZE = 10.4
Q_LEAD = 14.0
A_SIZE = 10.4
A_LEAD = 14.0


# -- payload ---------------------------------------------------------------


class StudyCard(BaseModel):
    kind: Literal["basic", "cloze"] = "basic"
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(default="", max_length=8000)
    detail: str = Field(default="", max_length=4000)


class StudySection(BaseModel):
    title: str = Field(default="", max_length=200)
    cards: list[StudyCard] = Field(min_length=1, max_length=200)


class StudyBody(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    source: str = Field(default="", max_length=500)
    deck: str = Field(default="", max_length=300)
    generated: str = Field(default="", max_length=40)
    sections: list[StudySection] = Field(min_length=1, max_length=60)


@dataclass(frozen=True)
class _Entry:
    n: int
    kind: str
    question: str
    answer: str
    detail: str


def _clean(value: str) -> str:
    """Strip control characters and tidy whitespace without losing paragraphs."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    text = "".join(ch if ch == "\n" or ch >= " " else " " for ch in text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _flatten(body: StudyBody) -> list[tuple[str, list[_Entry]]]:
    numbered: list[tuple[str, list[_Entry]]] = []
    n = 0
    for section in body.sections:
        entries: list[_Entry] = []
        for card in section.cards:
            n += 1
            entries.append(
                _Entry(
                    n=n,
                    kind=card.kind,
                    question=_clean(card.question) or "Untitled card",
                    answer=_clean(card.answer),
                    detail=_clean(card.detail),
                )
            )
        numbered.append((_clean(section.title), entries))
    return numbered


def _footer_meta(body: StudyBody, count: int, section_count: int) -> list[str]:
    parts = [body.source or "Study sheet"]
    parts.append(f"{count} card{'' if count == 1 else 's'}")
    if section_count > 1:
        parts.append(f"{section_count} sections")
    if body.generated:
        parts.append(body.generated)
    return parts


def filename(body: StudyBody, suffix: str) -> str:
    """ASCII-safe download name; the browser can still pick a nicer one."""
    stem = re.sub(r"[^A-Za-z0-9]+", "-", body.title).strip("-").lower()
    stem = stem[:60] or "study-sheet"
    return f"{stem}-study.{suffix}"


# -- fonts -----------------------------------------------------------------

_FONT_FILES: dict[bool, Path | None] = {}


def _font_file(bold: bool) -> Path | None:
    if bold in _FONT_FILES:
        return _FONT_FILES[bold]
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
    found: Path | None = None
    for directory in (Path(r"C:\Windows\Fonts"), Path("/usr/share/fonts/truetype/dejavu")):
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                found = candidate
                break
        if found:
            break
    _FONT_FILES[bold] = found
    return found


def _font(bold: bool) -> pymupdf.Font:
    path = _font_file(bold)
    if path:
        return pymupdf.Font(fontfile=str(path))
    return pymupdf.Font("hebo" if bold else "helv")


def _wrap(value: str, font: pymupdf.Font, size: float, width: float) -> list[str]:
    """Greedy word wrap; long words are broken rather than overflowing."""
    lines: list[str] = []
    for block in _clean(value).split("\n"):
        words = block.split(" ")
        words = [word for word in words if word]
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if font.text_length(candidate, size) <= width:
                current = candidate
                continue
            if current:
                lines.append(current)
                current = ""
            if font.text_length(word, size) <= width:
                current = word
                continue
            chunk = ""
            for character in word:
                if chunk and font.text_length(chunk + character, size) > width:
                    lines.append(chunk)
                    chunk = character
                else:
                    chunk += character
            current = chunk
        if current:
            lines.append(current)
    return lines or [""]


# -- PDF -------------------------------------------------------------------


class _Sheet:
    def __init__(self, body: StudyBody, sections: list[tuple[str, list[_Entry]]]):
        self.body = body
        self.sections = sections
        self.doc = pymupdf.open()
        self.regular = _font(False)
        self.bold = _font(True)
        regular_path = _font_file(False)
        bold_path = _font_file(True)
        self.names = ("F0", "F1") if regular_path and bold_path else ("helv", "hebo")
        self.page = None
        self.y = 0.0
        self.index = -1
        self.question_links: list[tuple[int, pymupdf.Rect, int]] = []
        self.back_links: list[tuple[int, pymupdf.Rect, int]] = []
        self.question_at: dict[int, tuple[int, float]] = {}
        self.answer_at: dict[int, tuple[int, float]] = {}

    # -- page plumbing --------------------------------------------------

    def new_page(self):
        page = self.doc.new_page(width=PAGE_W, height=PAGE_H)
        for name, bold in ((self.names[0], False), (self.names[1], True)):
            path = _font_file(bold)
            if path:
                page.insert_font(fontname=name, fontfile=str(path))
        self.page = page
        self.index += 1
        self.y = TOP
        return page

    def ensure(self, height: float) -> bool:
        if self.page is None or self.y + height > PAGE_H - BOTTOM:
            self.new_page()
            return False
        return True

    def text(self, x, y, value, *, bold=False, size=Q_SIZE, color=INK, align="left"):
        if not value:
            return
        font = self.bold if bold else self.regular
        if align == "middle":
            x -= font.text_length(value, size) / 2
        elif align == "right":
            x -= font.text_length(value, size)
        self.page.insert_text(
            (x, y),
            value,
            fontname=self.names[1] if bold else self.names[0],
            fontsize=size,
            color=color,
        )

    def width(self, value, bold=False, size=Q_SIZE) -> float:
        font = self.bold if bold else self.regular
        return font.text_length(value, size)

    def badge(self, x: float, top: float, number: int) -> float:
        label = str(number)
        width = max(BADGE_W, self.width(label, True, 8.2) + 11)
        rect = pymupdf.Rect(x, top, x + width, top + 15.5)
        self.page.draw_rect(rect, color=None, fill=ACCENT_SOFT, width=0, radius=0.42)
        self.text(x + width / 2, top + 11.2, label, bold=True, size=8.2, color=ACCENT_INK, align="middle")
        return width

    # -- cover ----------------------------------------------------------

    def cover(self) -> None:
        self.new_page()
        self.text(MARGIN_X, 96, "ANKI SCRIBE \u00b7 STUDY SHEET", bold=True, size=7.8, color=ACCENT)
        y = 128.0
        for line in _wrap(self.body.title, self.bold, 21.0, CONTENT_W)[:3]:
            self.text(MARGIN_X, y, line, bold=True, size=21.0, color=INK)
            y += 26
        meta = _footer_meta(self.body, self.count, len(self.sections))
        self.text(MARGIN_X, y + 4, "  \u00b7  ".join(meta), size=9.0, color=MUTED)
        if self.body.deck:
            self.text(MARGIN_X, y + 20, f"Deck: {self.body.deck}", size=9.0, color=MUTED)

        hint_top = y + 34
        hint = pymupdf.Rect(MARGIN_X, hint_top, PAGE_W - MARGIN_X, hint_top + 44)
        self.page.draw_rect(hint, color=None, fill=ACCENT_SOFT, width=0, radius=0.18)
        self.text(MARGIN_X + 12, hint_top + 17, "Answers are in the key at the end.", bold=True, size=8.8, color=ACCENT_INK)
        self.text(
            MARGIN_X + 12,
            hint_top + 31,
            "Click any question to jump to its answer, then \u201cBack to question\u201d to return.",
            size=8.4,
            color=ACCENT_INK,
        )
        self.y = hint_top + 58
        self.page.draw_line((MARGIN_X, self.y), (PAGE_W - MARGIN_X, self.y), color=LINE, width=0.8)
        self.y += 18

    # -- questions ------------------------------------------------------

    def section(self, title: str, continued: bool = False) -> None:
        if not title:
            return
        label = f"{title} (continued)" if continued else title
        lines = _wrap(label, self.bold, 12.4, CONTENT_W)
        self.ensure(14 + len(lines) * 17 + 60)
        top = self.y
        y = top + 13
        for line in lines:
            self.text(MARGIN_X, y, line, bold=True, size=12.4, color=ACCENT_INK)
            y += 17
        self.page.draw_line((MARGIN_X, y - 9), (PAGE_W - MARGIN_X, y - 9), color=ACCENT, width=1.2)
        self.y = y + 7

    def question(self, entry: _Entry, section_title: str) -> None:
        lines = _wrap(entry.question, self.regular, Q_SIZE, CONTENT_W - TEXT_INDENT)
        pill_h = 15.5
        height = 10 + len(lines) * Q_LEAD + 8 + pill_h + 14
        if not self.ensure(height) and section_title:
            self.section(section_title, continued=True)

        top = self.y
        self.badge(MARGIN_X, top + 1, entry.n)
        baseline = top + 12.4
        for line in lines:
            self.text(MARGIN_X + TEXT_INDENT, baseline, line, size=Q_SIZE, color=INK)
            baseline += Q_LEAD

        pill_top = baseline - Q_LEAD + 8
        label = "Show answer \u2192"
        pill_w = self.width(label, False, 8.2) + 16
        pill = pymupdf.Rect(MARGIN_X + TEXT_INDENT, pill_top, MARGIN_X + TEXT_INDENT + pill_w, pill_top + pill_h)
        self.page.draw_rect(pill, color=None, fill=ACCENT_SOFT, width=0, radius=0.5)
        self.text(pill.x0 + 8, pill_top + 10.8, label, size=8.2, color=ACCENT_INK)

        block = pymupdf.Rect(MARGIN_X, top - 4, PAGE_W - MARGIN_X, pill_top + pill_h + 1)
        self.question_links.append((self.index, block, entry.n))
        self.question_links.append((self.index, pill, entry.n))
        self.question_at[entry.n] = (self.index, max(0.0, top - 12))

        self.page.draw_line(
            (MARGIN_X, pill_top + pill_h + 9),
            (PAGE_W - MARGIN_X, pill_top + pill_h + 9),
            color=LINE,
            width=0.6,
        )
        self.y = pill_top + pill_h + 20

    # -- answers --------------------------------------------------------

    def answers_header(self) -> None:
        self.new_page()
        self.text(MARGIN_X, self.y + 24, "Answers", bold=True, size=19.0, color=INK)
        self.text(
            MARGIN_X,
            self.y + 42,
            "Click \u201cBack to question\u201d to jump back to the card it belongs to.",            size=9.0,
            color=MUTED,
        )
        self.page.draw_line((MARGIN_X, self.y + 52), (PAGE_W - MARGIN_X, self.y + 52), color=LINE, width=0.8)
        self.y += 70

    def answers_section(self, title: str, continued: bool = False) -> None:
        if not title:
            return
        label = f"{title.upper()} (CONTINUED)" if continued else title.upper()
        line = label[:110]
        self.ensure(44)
        self.text(MARGIN_X, self.y + 8, line, bold=True, size=8.0, color=FAINT)
        self.y += 18

    def answer(self, entry: _Entry, section_title: str) -> None:
        lines = _wrap(entry.answer or "No answer was recorded for this card.", self.regular, A_SIZE, CONTENT_W - TEXT_INDENT)
        detail_lines = (
            _wrap(entry.detail, self.regular, 8.6, CONTENT_W - TEXT_INDENT) if entry.detail else []
        )
        back_label = "\u2190 Back to question"
        height = 10 + len(lines) * A_LEAD + (len(detail_lines) * 11.8 + 6 if detail_lines else 0) + 22
        if not self.ensure(height):
            if section_title:
                self.answers_section(section_title, continued=True)

        top = self.y
        self.badge(MARGIN_X, top + 1, entry.n)
        baseline = top + 12.4
        for line in lines:
            self.text(MARGIN_X + TEXT_INDENT, baseline, line, size=A_SIZE, color=INK)
            baseline += A_LEAD
        if detail_lines:
            baseline += 2
            for line in detail_lines:
                self.text(MARGIN_X + TEXT_INDENT, baseline, line, size=8.6, color=MUTED)
                baseline += 11.8

        back_top = baseline + 3
        back_w = self.width(back_label, False, 8.2) + 14
        back = pymupdf.Rect(PAGE_W - MARGIN_X - back_w, back_top, PAGE_W - MARGIN_X, back_top + 15)
        self.page.draw_rect(back, color=None, fill=ACCENT_SOFT, width=0, radius=0.5)
        self.text(back.x0 + 7, back_top + 10.6, back_label, size=8.2, color=ACCENT)
        self.back_links.append((self.index, back, entry.n))

        self.page.draw_line(
            (MARGIN_X, back_top + 21),
            (PAGE_W - MARGIN_X, back_top + 21),
            color=LINE,
            width=0.6,
        )
        self.y = back_top + 32
        self.answer_at[entry.n] = (self.index, max(0.0, top - 12))

    # -- finish ---------------------------------------------------------

    def finish(self) -> bytes:
        total = len(self.doc)
        for index in range(total):
            page = self.doc[index]
            page.draw_line(
                (MARGIN_X, PAGE_H - 38),
                (PAGE_W - MARGIN_X, PAGE_H - 38),
                color=LINE,
                width=0.6,
            )
            self._text_on(
                page, MARGIN_X, PAGE_H - 24, "Anki Scribe \u00b7 study sheet", size=7.6, color=FAINT
            )
            self._text_on(
                page,
                PAGE_W - MARGIN_X,
                PAGE_H - 24,
                f"{index + 1} / {total}",
                size=7.6,
                color=FAINT,
                align="right",
            )

        for page_no, rect, number in self.question_links:
            target = self.answer_at.get(number)
            if not target:
                continue
            target_page, target_y = target
            self.doc[page_no].insert_link(
                {
                    "kind": pymupdf.LINK_GOTO,
                    "from": rect,
                    "page": target_page,
                    "to": pymupdf.Point(MARGIN_X, target_y),
                    "zoom": 0,
                }
            )
        for page_no, rect, number in self.back_links:
            target = self.question_at.get(number)
            if not target:
                continue
            target_page, target_y = target
            self.doc[page_no].insert_link(
                {
                    "kind": pymupdf.LINK_GOTO,
                    "from": rect,
                    "page": target_page,
                    "to": pymupdf.Point(MARGIN_X, target_y),
                    "zoom": 0,
                }
            )

        self.doc.set_metadata(
            {
                "title": self.body.title,
                "author": "Anki Scribe",
                "subject": "Question and answer study sheet",
                "creator": "Anki Scribe",
                "producer": "Anki Scribe (PyMuPDF)",
            }
        )
        raw = self.doc.tobytes(garbage=4, deflate=True)
        return _subset(raw)

    def _text_on(self, page, x, y, value, *, size=8.0, color=FAINT, align="left"):
        if align == "right":
            x -= self.regular.text_length(value, size)
        page.insert_text(
            (x, y),
            value,
            fontname=self.names[0],
            fontsize=size,
            color=color,
        )

    # expose the card count for the cover
    @property
    def count(self) -> int:
        return sum(len(entries) for _, entries in self.sections)


def _subset(data: bytes) -> bytes:
    """Re-save with only the glyphs used; the embedded UI font is large."""
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
        doc.subset_fonts()
        result = doc.tobytes(garbage=4, deflate=True)
        doc.close()
        return result
    except Exception:
        return data


def build_pdf(body: StudyBody) -> bytes:
    sections = _flatten(body)
    sheet = _Sheet(body, sections)
    sheet.cover()
    for title, entries in sections:
        sheet.section(title)
        for entry in entries:
            sheet.question(entry, title)
    sheet.answers_header()
    for title, entries in sections:
        sheet.answers_section(title)
        for entry in entries:
            sheet.answer(entry, title)
    return sheet.finish()


# -- HTML ------------------------------------------------------------------

_HTML_CSS = """
:root{
  --bg:#f1eee6;--surface:#fffdf8;--surface-2:#f7f3ea;--ink:#1e2522;--muted:#6f736c;
  --muted-2:#96988f;--line:#e4ded1;--line-strong:#d2cab8;--accent:#0f766e;
  --accent-strong:#0b5b55;--accent-soft:#e1f2ee;--accent-ink:#07443f;
  --sans:"Segoe UI",system-ui,-apple-system,sans-serif;
  --serif:"Iowan Old Style","Palatino Linotype","Book Antiqua",Georgia,serif;
  --mono:"Cascadia Code",Consolas,ui-monospace,monospace;
}
*{box-sizing:border-box}
html{color-scheme:light}
body{margin:0;background:var(--bg);color:var(--ink);font-family:var(--sans);font-size:15px;line-height:1.55;-webkit-font-smoothing:antialiased}
.sheet{max-width:880px;margin:0 auto;padding:44px 22px 90px}
.eyebrow{margin:0 0 8px;font-size:10px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:var(--accent)}
h1{margin:0;font-family:var(--serif);font-size:clamp(26px,4vw,36px);font-weight:600;letter-spacing:-.02em;line-height:1.15}
.meta{margin:8px 0 0;font-size:12.5px;color:var(--muted)}
.tools{position:sticky;top:0;z-index:5;display:flex;flex-wrap:wrap;align-items:center;gap:7px;margin:20px 0 6px;padding:9px 0;background:linear-gradient(var(--bg) 70%,rgba(241,238,230,0));backdrop-filter:blur(6px)}
.tools button{font:inherit;font-size:12px;font-weight:600;padding:6px 11px;border:1px solid var(--line-strong);border-radius:9px;background:var(--surface);color:var(--ink);cursor:pointer}
.tools button:hover{background:#fff;border-color:#c2b9a5}
.tip{margin-left:auto;font-size:11px;color:var(--muted-2)}
@media (max-width:640px){.tip{display:none}}
kbd{font-family:var(--mono);font-size:10px;padding:1px 5px;border:1px solid var(--line-strong);border-bottom-width:2px;border-radius:4px;background:var(--surface-2);color:var(--muted)}
.chapter{margin-top:34px}
.chapter h2{margin:0 0 10px;font-family:var(--serif);font-size:20px;font-weight:600;color:var(--accent-ink);letter-spacing:-.01em}
.chapter h2::after{content:"";display:block;width:44px;height:2px;margin-top:7px;background:var(--accent);opacity:.45}
.card{margin:0 0 10px;border:1px solid var(--line);border-radius:14px;background:var(--surface);box-shadow:0 1px 2px rgba(30,37,34,.05);overflow:hidden;break-inside:avoid}
.card.is-open{border-color:#bcd9d3;box-shadow:0 6px 18px rgba(15,118,110,.08)}
.ask{display:flex;align-items:flex-start;gap:13px;width:100%;padding:14px 15px;border:0;background:none;color:inherit;font:inherit;text-align:left;cursor:pointer}
.ask:hover{background:#fff}
.ask:focus-visible{outline:2px solid var(--accent);outline-offset:-2px}
.num{flex:0 0 auto;min-width:23px;margin-top:1px;padding:1px 7px;border-radius:999px;background:var(--accent-soft);color:var(--accent-ink);font-size:11px;font-weight:800;text-align:center;font-variant-numeric:tabular-nums}
.q{flex:1;min-width:0;font-size:15.5px;font-weight:600;line-height:1.45}
.chev{flex:0 0 auto;margin-top:1px;padding:2px 9px;border-radius:999px;background:var(--surface-2);color:var(--muted);font-size:10.5px;font-weight:700;letter-spacing:.02em;text-transform:uppercase}
.card.is-open .chev{background:var(--accent);color:#fff}
.answer{padding:2px 16px 16px 51px;border-top:1px dashed var(--line);background:linear-gradient(#fbfaf5,#fffdf8);cursor:pointer}
.answer p{margin:10px 0 0;font-size:14.5px;line-height:1.55;color:var(--accent-ink);font-weight:600}
.answer .detail{margin-top:6px;font-size:12.5px;font-weight:400;color:var(--muted)}
.blank{display:inline-block;min-width:54px;padding:0 6px;border-bottom:2px solid var(--accent);color:var(--muted-2);font-weight:600;text-align:center}
.foot{margin-top:46px;padding-top:14px;border-top:1px solid var(--line);font-size:11px;color:var(--muted-2)}
@media print{
  body{background:#fff}
  .sheet{max-width:none;padding:0}
  .tools,.tip,.chev{display:none !important}
  .card{border:0;border-bottom:1px solid #ddd;border-radius:0;box-shadow:none;margin:0}
  .ask{padding:10px 0}
  .answer{display:block !important;border:0;padding:0 0 12px 36px;background:none}
  .chapter{break-before:page}
  .chapter:first-of-type{break-before:auto}
  .num{background:none}
}
"""

_HTML_JS = """
(function(){
  var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
  function setOpen(card, open){
    var answer = card.querySelector('.answer');
    var button = card.querySelector('.ask');
    var chev = card.querySelector('.chev');
    card.classList.toggle('is-open', open);
    answer.hidden = !open;
    button.setAttribute('aria-expanded', String(open));
    chev.textContent = open ? 'Hide' : 'Show';
  }
  cards.forEach(function(card){
    card.querySelector('.ask').addEventListener('click', function(){
      setOpen(card, !card.classList.contains('is-open'));
    });
    card.querySelector('.answer').addEventListener('click', function(){ setOpen(card, false); });
  });
  document.querySelectorAll('[data-act]').forEach(function(button){
    button.addEventListener('click', function(){
      var act = button.getAttribute('data-act');
      if (act === 'print') { window.print(); return; }
      cards.forEach(function(card){ setOpen(card, act === 'reveal'); });
    });
  });
  var focusIndex = -1;
  document.addEventListener('keydown', function(event){
    if (event.ctrlKey || event.metaKey || event.altKey) return;
    var key = event.key.toLowerCase();
    if (key === 'r') { cards.forEach(function(card){ setOpen(card, true); }); }
    else if (key === 'h') { cards.forEach(function(card){ setOpen(card, false); }); }
    else if (key === 'j' || key === 'k') {
      if (!cards.length) return;
      focusIndex = focusIndex < 0 ? 0 : Math.max(0, Math.min(cards.length - 1, focusIndex + (key === 'j' ? 1 : -1)));
      var card = cards[focusIndex];
      card.querySelector('.ask').focus();
      card.scrollIntoView({block: 'center', behavior: 'smooth'});
      event.preventDefault();
    }
  });
})();
"""


def _paragraphs(value: str, css_class: str) -> str:
    escaped = html.escape(value or "").replace("\n", "<br>")
    return '<p class="{}">{}</p>'.format(css_class, escaped)


def _answer_html(entry: _Entry) -> str:
    answer = entry.answer or "No answer was recorded for this card."
    parts = [_paragraphs(answer, "a")]
    if entry.detail:
        parts.append(_paragraphs(entry.detail, "detail"))
    return "".join(parts)


def _card_html(entry: _Entry) -> str:
    return (
        '      <article class="card" id="c{n}">\n'
        '        <button type="button" class="ask" aria-expanded="false" aria-controls="a{n}">\n'
        '          <span class="num">{n}</span>\n'
        '          <span class="q">{question}</span>\n'
        '          <span class="chev">Show</span>\n'
        "        </button>\n"
        '        <div class="answer" id="a{n}" hidden>\n'
        "          {answer}\n"
        "        </div>\n"
        "      </article>"
    ).format(
        n=entry.n,
        question=html.escape(entry.question),
        answer=_answer_html(entry),
    )


def build_html(body: StudyBody) -> str:
    sections = _flatten(body)
    count = sum(len(entries) for _, entries in sections)
    # The HTML sheet is a web page: every metadata part is escaped here. The
    # PDF builder takes the same list raw, because PDF is not markup.
    meta = "  \u00b7  ".join(
        html.escape(part) for part in _footer_meta(body, count, len(sections))
    )
    deck = ""
    if body.deck:
        deck = '<p class="meta">Deck: {}</p>'.format(html.escape(body.deck))

    chapters: list[str] = []
    for title, entries in sections:
        cards = "\n".join(_card_html(entry) for entry in entries)
        heading = "<h2>{}</h2>\n".format(html.escape(title)) if title else ""
        chapters.append('  <section class="chapter">\n{}{}\n  </section>'.format(heading, cards))
    chapters_html = "\n".join(chapters)
    sheet_title = html.escape(body.title)
    noscript = '<noscript><style>.answer{display:block !important}</style></noscript>'

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>{sheet_title} \u2014 study sheet</title>
<style>{_HTML_CSS}</style>
</head>
<body>
<div class="sheet">
  <header>
    <p class="eyebrow">Anki Scribe \u00b7 study sheet</p>
    <h1>{sheet_title}</h1>
    <p class="meta">{meta}</p>
    {deck}
    <div class="tools">
      <button type="button" data-act="reveal">Reveal all</button>
      <button type="button" data-act="hide">Hide all</button>
      <button type="button" data-act="print">Print</button>
      <span class="tip">Click a card to show its answer &middot; <kbd>R</kbd> reveal &middot; <kbd>H</kbd> hide &middot; <kbd>J</kbd>/<kbd>K</kbd> move</span>
    </div>
  </header>
  <main>
{chapters_html}
  </main>
  <p class="foot">Generated by Anki Scribe \u2014 answers stay hidden until you open a card. This file works offline; no server needed.</p>
</div>
{noscript}
<script>{_HTML_JS}</script>
</body>
</html>
"""


__all__ = ["StudyBody", "StudyCard", "StudySection", "build_pdf", "build_html", "filename"]
