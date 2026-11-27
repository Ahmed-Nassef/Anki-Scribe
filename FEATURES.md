# Anki Scribe — feature plan

A build plan derived from the review in [REVIEW.md](REVIEW.md). Every feature below is scoped against the code as it exists: where it hooks in, what data it needs, what it costs, and how we know it worked.

---

## Status — wave 1 shipped

| Ticket | State | What landed | Deviation from plan |
|---|---|---|---|
| **A1** sent ledger | ✅ | `app/sent.py`, `GET`/`DELETE /api/sent`, note ids captured from `addNotes`, 5,000 per source / 200 sources | Written server-side **inside** the push rather than by a second client call — one request, one truth, and a failed ledger write can never look like a failed push |
| **B1** evidence verification | ✅ | `evidence_supported()` in `llm.py`; every card carries `verified`; a **check** badge and a count in the header | `strict=` exists on the API but has no UI toggle yet |
| **B2** provenance fields | ✅ | `Anki Scribe Basic`/`Cloze` note types with `Source`, `Page`, `Quote`, `QuestionId`; stock fallback when the collection refuses | Preflight creates the note type too, so the first *Send* click does it |
| **B3** push preflight | ✅ | `canAddNotes` behind `POST /api/anki/preflight`; a real modal with **Send new** / **Send all** and per-deck counts | The modal is new markup rather than a native confirm |
| **C2** undo | ✅ | remove, clear and untick are reversible; `Ctrl+Z` / `Ctrl+Shift+Z`; toast action + header button | In memory only (20 operations); not persisted across reloads |
| **A2** coverage continuity | ✅ | Coverage, teal highlights and the draft count all read `drafts ∪ ledger`, so a push no longer resets the meter; library rows now carry `sentCount` and `draftCount` and render them as **"42 in Anki · 3 drafts"** | Coverage *percentage* stays client-side; the library shows counts, not per-source coverage |
| **C1** triage mode | ✅ | Full-screen pass in a new `triage.js`: one card, its quote beside it, answer hidden until `Space`; `A` accept, `X` reject, `J`/`K` move, `U` undo; `Shift+A`/`Shift+X` for the rest | No inline editing inside triage — `E` still means the review card. Triage order is now driven by B4 |
| **B4** likely-wrong ranking | ✅ | `risk.js`: unverified quote (+5), vague/short question (+3), long or >3 cloze deletions (+3), near-duplicate in the batch (+2, blocked by two rarest tokens), negation mismatch (+1), no tags (+1). "N to check" chip opens triage filtered to flagged cards; the reason is the badge tooltip and the triage footer | Heuristic, not a verdict — near-duplicate detection is blocked hashing, so it can miss a pair that shares neither of its two rarest tokens. Covered by 8 executable tests |
| **B1** strict mode | ✅ | "Only keep cards that quote the source" sends `strict: true` from both manual and whole-file generation, persisted in `localStorage` | Off by default; the toggle lives under the card-count row |
| **E2** card styles | ✅ | Five presets (Balanced, Mechanism, Clinical vignette, Tables & lists, Exam trap) appended to the system prompt, persisted in `localStorage`, shared by manual and whole-file runs | "Extra instructions" free text from the plan is not built yet |
| **C4** regenerate one card | ✅ | Triage rewrite row: sharper / simpler / clinical / shorter / as cloze, plus `R`. Rewrites from the card's own evidence quote, so it cannot leave the source; the swap is a single undoable `replace` | Available in triage only — the review list has no per-card rewrite button |
| **D3** objective coverage | ✅ | `app/objectives.py` detects a heading + 3–12 items on a page, slide or segment (and rolls over onto the next one). Panel above Review shows **4 / 7 covered** with **generate** on the misses, scoped to that page | Coverage is a local token-recall estimate, not the model-mapped version from the plan; no manual "add an objective" yet |
| **D1** figure cards | ✅ | Drag a box in Figure mode → `app/figures.py` crops to the picture containing it, writes a masked and a revealed PNG, and fills the answer from the text layer. Push uploads both via `storeMediaFile`, so the note works with **no add-on** | PDF pages only (no photos or transcripts). Study-sheet exports show the text, not the image |
| **D2** PPTX import | ✅ | `app/presentations.py` reads a `.pptx` with the **standard library** (zip + XML): slides in deck order, shape text at its real position, table rows, embedded pictures. It writes a synthetic PDF, so every existing feature works on slides — objectives detection included | No new dependency (PyPI was unreachable, which forced the better design). Fonts and exact layout are approximated, not rendered |
| **G1** books by chapter | ✅ | `app/epub.py` reads an EPUB in spine order and writes a synthetic PDF whose outline is the book's own contents; `app/split.py` + **Save chapters** writes one Markdown file per chapter with a `manifest.json`; `MAX_PAGES` 300 → 1,500, upload cap 40 → 200 MB | See §5b. The page image is the text, not the book's design; fixed-layout EPUBs are refused with a message |
| **H1** click the highlight | ✅ | Teal lines carry `data-card-uids`; clicking one scrolls the review panel to the owning card and flashes it, cycling when several cards quote the line | A drag or an active text selection is ignored, so selecting highlighted text still works |
| **H2** pictures on a card | ✅ | `app/images.py` + crop/upload/serve endpoints; **Add picture** on any card (crop the page or upload a file), a **Show on front** tick, **Replace**; travels to Anki as media | One picture per card; cropping needs a PDF page |
| **H3** memory at book scale | ✅ | The review list keeps one slot per card and builds only the cards within ~900 px of the viewport (≤ 80 built); the page viewer releases page images outside the same band and reloads them on return | Measured on 1,000 cards: 72,115 → 5,393 DOM nodes at rest, and a 10-render burst no longer leaves ~770,000 detached nodes. Scroll-through of a 120-page book keeps 2–3 page images alive instead of all 120 |
| **H4** formula handling | ✅ | `app/formats.py`: Unicode math alphanumerics folded back to letters (NFKC), superscripts/subscripts as `^{…}`/`_{…}`, formula lines detected from math-font spans or symbol density and sent as `$…$` with LaTeX Greek/operators | A sentence that mentions σ is left as prose. Stacked fractions still extract in reading order; a table or formula a card depends on is best cropped as a picture |
| **H5** data safety | ✅ | `app/storage.py` (atomic writes + `.bak` fallback + heal), `app/instance.py` (one instance per data folder via `instance.lock`), `/api/health` returns a data-folder fingerprint and `run.py` only attaches to a server whose fingerprint matches | Repairs a damaged file from its backup; a server using another data folder is never adopted |
| **F3** diagnostics | ✅ | Rotating log (`anki-scribe.log`, 5 × 1 MB) plus `GET /api/diagnostics` and `/bundle` (zip: redacted snapshot + README + log), and a **Download diagnostics** button in Settings. Unhandled errors now return `(ref abc123)` instead of a traceback | The log records names and counts, not card or page text, by design |
| **F2** single instance | ✅ (half) | `run.py` now looks for a running instance across the whole port range before choosing a free port, so a second launch attaches to the first instead of sharing its JSON files | The onboarding wizard half is not built |
| + fix | ✅ | Study-sheet metadata line escaped; `library.json` that is valid JSON but not an object no longer stops startup | Found while working; two lines each |
| **F5** hide answers on the PDF page | ✅ | `app/answers.py` finds each ticked card's cloze deletion, names, numbers or answer clause on its source page; the viewer overlays an opaque, type-coloured blank with a legend, click reveals it and clicking the revealed text hides it again. Blanks are coloured by LLM card type (date, dose, number, procedure, definition, mechanism, compare, list, application, fact), manual hides are neutral, and **AI fill** asks DeepSeek for exact quotes the local matcher missed. Titles, contents pages and table structure are skipped; **Hide selection** stores manual blanks in `masks.json`, and `R`/`H` reveal or hide everything | Automatic masks are recomputed from cards, not stored. AI fill is an explicit button and costs a DeepSeek call. A basic card whose answer is too paraphrased falls back to its short evidence quote, or is left for manual hiding |
| **F6** FSRS-6 study plan | ✅ | `app/fsrs.py` implements the 21-weight FSRS-6 formulas against the MIT py-fsrs reference; `app/planner.py` simulates a day-by-day plan from exam date, study items, a daily start/end window and study weekdays. **Library → Plan selected** counts drafts, pushed cards and manual hides across several files; the modal shows new/review load, peak time, warnings, a copyable table, a **Files** column allocating each day's new items by file, a **Plan by file** summary, configurable **sessions and breaks**, an **hour-by-hour** breakdown and a **Calendar .ics** download with alarms. Items include Q&A cards, each distinct cloze deletion, figure cards and hand-hidden answers | Day-level FSRS simulation: no minute-level learning steps, one expected rating for every review. The Files column allocates new items only; reviews stay aggregate. Existing cards are treated as new even though history is shown; the plan stops the day before the exam |
| **F7** automatic OCR for scanned PDFs | ✅ | On upload or first open, every page without a text layer is rendered and OCR'd in a daemon thread (`Store.start_ocr`); the client polls `/api/documents/{id}/ocr`, shows a progress strip, **Stop** and **Retry**, then reloads visible page text layers. Lines and `ocr_done` are persisted in `meta.json`, so reopening does not OCR again | Uses Windows OCR first and RapidOCR as fallback; a missing language pack is reported and can be retried after installing it. OCR runs locally and can take a few seconds per page |
| **F9** focused study mode | ✅ | `focus.js` adds a full-screen reader with a minimal HUD: hidden answers are enabled on entry, **Space** toggles answers, **R/H** reveal/hide, arrows/PageUp/PageDown/J/K move pages, **?** shows shortcuts, **Esc** exits, and a HUD button requests browser fullscreen. The side panel, top bar, page toolbar, legend and OCR strip are hidden by an `is-studying` body class. Masks stay solid-coloured; a revealed mask fades to 34% opacity instead of disappearing, so the answer is readable and the blank remains findable | Keyboard-first by design; the HUD remains a small visible strip rather than disappearing completely. Click-to-reveal and click-again-to-hide continue to work inside the page |
| **F10** persistent batch jobs | ✅ | `app/batch_jobs.py` stores jobs in `batch_jobs.json`, processes one library file at a time in a daemon thread, uses `store.extract_chunks` + `llm.generate_cards`, merges server-side drafts with uid/source metadata, and records progress after each chunk. `POST/GET /api/batch-jobs`; the client polls the job, and the Store resumes queued/running jobs at startup. Interrupted files are safe to retry because the draft merge de-duplicates | Uses section chunks rather than the client's chapter-plan path, so chapter labels are page ranges rather than the book outline. A fatal API-key/balance error stops the job; individual chunk failures are skipped and reported |
| **F11** Anki review history and leeches | ✅ | `anki.read_review_history` joins sent-ledger note ids through AnkiConnect `notesInfo` + `cardsInfo`; the **Leeches** dialog shows reviewed/lapsed/leech totals, cards with 4+ lapses, deck and source, and **Show page** for the open file. The plan modal shows the same history totals | Read-only: no adaptive rescheduling and no rewrite/suspend/regenerate action from the leech dialog yet |
| **F12** study sessions and analytics | ✅ | The existing Study dialog now grades **Again/Hard/Good/Easy** (`1`–`4`), reveals with Space, and schedules each card on the local server: Again in 10 minutes, Hard/Good/Easy at increasing day intervals with an ease factor. Due cards sort first, then new cards. Live header shows time, recall and streak; the summary shows the grade mix and best streak; **Stats** shows sessions, cards reviewed, days studied, current streak, retention, average time, due and new counts. Stored server-side in `study_reviews.json`; browser localStorage remains a fallback. | The scheduler is intentionally lightweight; it is not the FSRS-6 exam plan. Sent cards are included alongside drafts |

### Bugs fixed this pass

| Bug | Fix |
| --- | --- |
| **U1** opening a file mid-generation attributed cards to the wrong document and could delete them | Source is captured before the request; the result is discarded if the document changed, and opening a file during generation is refused with a Stop hint |
| **U2** no way to cancel the primary generate button | `AbortController` + a **Stop generating** button; aborts cleanly with a "Generation stopped" toast |
| **U6** a failed autosave was silent | One throttled error toast ("Couldn't save your drafts to disk") instead of a `console.warn` nobody sees |
| **U7** the confirm claimed cards would be cleared, contradicting autosave | Warns only when drafts genuinely have not reached disk |
| **U11** `Ctrl+Enter` fired behind three dialogs | Any open `dialog` now owns the keyboard |
| **U15** a page whose text failed said "still reading" forever | Distinguishes an error from loading, with a truthful message |
| Study-sheet injection | `source`/`generated` in the exported sheet's metadata line are escaped (HTML only — the PDF builder keeps them literal) |
| Startup crash | A `library.json` that is valid JSON but not an object is skipped instead of raising `AttributeError` before the server starts |
| Bookkeeping | Drafts, the sent ledger, the library and config now quarantine an unreadable file as `*.corrupt-<ts>` instead of silently starting empty and overwriting it |
| Security | `TrustedHostMiddleware` (any `Host` that is not loopback is rejected — closes DNS rebinding), `openapi_url=None` |
| Robustness | PDF pages larger than 3000 pt are refused at upload instead of allocating a multi-gigabyte pixmap; unparseable URLs are rejected when saved and reported as 400 rather than 500 |

**268 tests passing** (was 97). No dependency was added — `python-pptx` was the plan, but PyPI is unreachable here, and reading the OOXML directly with `zipfile` + `ElementTree` turned out to be the better design anyway: no lxml, no XlsxWriter, and the parser is 200 lines we can test exhaustively. The EPUB reader follows the same rule: `zipfile` + `ElementTree`, no `ebooklib`.

Every ticket in waves 1–3 is shipped, D2 is in, and F3 and the single-instance half of F2 are done. What remains: **F1** server-side jobs, the **onboarding wizard**, **F4** study-sheet upgrades, and the per-run API token.

---

## 1. How I chose these

The product is a pipeline: **find text → make cards → verify them → get them into Anki → retain them.** Value leaks at six joints, and every feature is placed on one of them.

```
 leak                          evidence                                   feature that plugs it
 ─────────────────────────────────────────────────────────────────────────────────────────────
 1  Push erases the record     deck.js:537 → coverage.js:81                A1  sent ledger
                                                                          A2  coverage that survives
 2  Provenance dies at Anki    anki.py:89-112 (Front/Back only)            B2  Source/Page/Quote fields
                                                                          E1  leech loop
 3  Nothing verifies a card    llm.py:37 asks, nothing checks              B1  evidence verification
                                                                          B3  push preflight
                                                                          B4  "likely wrong" ranking
 4  Review is a slog           cards.js:188, no bulk, no undo              C1  triage mode
                                                                          C2  undo
                                                                          C3  bulk + filter
 5  Figures are unreachable    store.py:618 counts images, never reads     D1  figure cards
     Slides are unsupported    only .pdf/.png/.jpg/.srt/.vtt/.txt/.md      D2  PPTX import
     No target to hit          coverage counts pages, not facts            D3  objective coverage
 6  Nothing gets better        no feedback from review results             E1  leech loop
     Runs die with the tab     auto.js:200 is a browser for-loop           F1  server-side jobs
     First run is brutal       uv + Python + Anki + key, 7 steps           F2  onboarding
```

**Scoring** — value to the student (1–5), uniqueness/moat (1–5), effort in developer-days, and risk (technical or product uncertainty).

| # | Feature | Value | Moat | Effort | Risk | Wave |
|---|---|---|---|---|---|---|
| A1 | Sent ledger + note-id capture | 5 | 4 | 1.5 d | low | **1** |
| B1 | Evidence verification + badge | 5 | 4 | 0.5 d | low | **1** |
| B2 | `Source`/`Page`/`Quote` note fields | 4 | 4 | 0.5 d | low | **1** |
| B3 | Push preflight (`canAddNotes`) | 4 | 2 | 0.5 d | low | **1** |
| C2 | Undo stack | 4 | 1 | 0.5 d | low | **1** |
| A2 | Coverage that survives + library progress | 5 | 3 | 1 d | low | **2** |
| C1 | Triage mode | 5 | 4 | 2.5 d | medium | **2** |
| C3 | Bulk select, filter, chapter grouping | 4 | 1 | 1 d | low | **2** |
| D1 | Figure cards (occlusion without the add-on) | 5 | 5 | 4 d | medium | **2** |
| D3 | Study-objective coverage | 5 | 5 | 2 d | low | **2** |
| E2 | Card-style presets + custom instructions | 4 | 2 | 0.5 d | low | **2** |
| B4 | "Likely wrong" ranking | 4 | 3 | 1 d | low | **3** |
| C4 | Regenerate one card | 4 | 2 | 1 d | low | **3** |
| E1 | Leech loop (read review results back) | 5 | 5 | 3.5 d | medium | **3** |
| A3 | "Already covered" guard | 3 | 3 | 1 d | low | **3** |
| E3 | Cost preview + usage capture + cap | 4 | 2 | 1 d | low | **3** |
| F1 | Server-side jobs, progress, resume | 4 | 2 | 5 d | medium | **3** |
| A4 | Resume an interrupted run | 3 | 2 | 1 d | low | *(with F1)* |
| D2 | PPTX import via synthetic PDF | 5 | 4 | 3 d | medium | **4** |
| F2 | Onboarding wizard + single instance | 5 | 1 | 2 d | low | **4** |
| F3 | Diagnostics bundle + logging | 3 | 1 | 1 d | low | **4** |
| F4 | Study sheet: type-to-reveal, MD/CSV export, AnkiWeb sync | 4 | 2 | 1 d | low | **4** |
| F5 | Hide answers on the PDF page itself | 5 | 4 | 1.5 d | low | **4** |
| F6 | FSRS-6 study plan: exam date, study window, multi-file scope and hourly blocks | 5 | 4 | 1.5 d | low | **4** |
| F7 | Automatic OCR for scanned PDFs | 5 | 4 | 1 d | low | **4** |
| F8 | Batch generation across library files | 5 | 4 | 0.5 d | low | **4** |
| F9 | Focused study mode with keyboard navigation | 5 | 3 | 0.5 d | low | **4** |
| F10 | Persistent server batch jobs + resume | 5 | 4 | 1 d | medium | **4** |
| F11 | Anki review history + leech list | 5 | 4 | 0.5 d | medium | **4** |
| F12 | Study card grading, due schedule and analytics | 5 | 4 | 1 d | medium | **4** |

Waves 1–2 are ~14 days and double as the 1.0 hardening from the review: they make the cards trustworthy and the app remember, which is the difference between a demo and a tool.

---

## 2. Wave 1 — trust foundations (≈4 days)

Small, unglamorous, and everything else stands on them.

### A1 · Sent ledger + note-id capture

**Problem.** After a push the app knows nothing about what it sent (`deck.js:537-538` deletes the cards; `anki.py:146-153` counts note ids and throws them away). Coverage, highlighting and every future feature need a memory.

**Build.** A second store beside drafts, `sent.json`, keyed the same way (`os.path.normcase(abspath)`), holding one record per pushed card:

```json
{"path": "…\\lecture3.pdf", "cards": [{
  "id": "…", "noteId": 1712345678901, "deck": "Anki Scribe::Lecture 3",
  "mode": "basic", "question": "…", "fingerprint": "…",
  "source": {"kind": "selection", "page": 4, "lines": [12, 18], "quote": "…"},
  "pushedAt": 1763580000.0, "tags": ["cardiology"]
}]}
```

`push_cards` must return the `addNotes` id list alongside the counts, and the client must pair ids back to cards **before** deleting them. Cap at 5,000 records per source and prune oldest, same policy as drafts.

**Acceptance.** Push 10 cards → reopen the file → the ledger still lists 10 with note ids; `drafts.json` is empty; nothing in the UI claims the file is uncovered.

### B1 · Evidence verification

**Problem.** The prompt asks for a verbatim quote (`llm.py:37`); nothing checks it. A hallucinated card is a permanently installed error.

**Build.** In `parse_cards` (`llm.py:136-176`), after sanitising: normalise both sides (casefold, collapse whitespace, strip soft hyphens and ligatures — `store.normalize_text` already does the hard part) and require the evidence to appear in the excerpt. Drop the card, or mark it `"verified": false` and let strict mode drop it. Store the flag on the card; show a small shield / "+" badge next to the evidence quote in review (`cards.js:276-283`); count them in the header: **"38 cards · 2 unverified"**.

**Acceptance.** A fixture excerpt with one paraphrased evidence quote yields 1 unverified card, 0 in strict mode; a 60-page real PDF yields ≥95 % verified.

**Why it is cheap.** It runs on data already in memory, costs no tokens, and turns the product's best claim ("every card can be traced to a sentence") into a fact.

### B2 · `Source`, `Page`, `Quote` note fields

**Problem.** Provenance dies at the Anki boundary (`anki.py:89-112`). In a four-year collection a card must be able to say where it came from.

**Build.** On first push, call `createModel` for an **Anki Scribe Basic** note type with `Front, Back, Extra, Source, Page, Quote, QuestionId`, plus a Cloze variant; remember the id in settings. If the user would rather keep stock types, fall back to appending a small `<div class="source">` line to `Back`. **Never break a push because the model is missing** — try to create, else degrade.

`Page` is the pill label (`Page 4`, `00:12–00:18`), `Quote` the verified evidence, `QuestionId` the ledger id that makes E1 possible.

**Acceptance.** A pushed card in Anki shows the lecture name, page, and quoted sentence; the note type is created once and reused; stock-type fallback still produces valid notes.

### B3 · Push preflight

**Problem.** Duplicates are discovered *after* the push, then the cards are deleted either way, so the user cannot tell what actually happened.

**Build.** Call `canAddNotes` with the built notes before `addNotes` (same payload shape), and show a dry-run summary:

```
42 selected · 34 new · 6 already in this deck · 2 already in your collection
[ Send 34 ]  [ Review the 8 ]  [ Send all ]
```

Then `addNotes` only the approved subset, and report created/skipped/failed per deck with a link to the failures. Set `duplicateScope: "collection"` as an option, since the current `"deck"` scope (`anki.py:111`) misses the same fact arriving from another lecture.

**Acceptance.** Re-pushing a batch reports "0 new, 42 already there" and leaves the drafts intact until the user chooses; a mixed batch reports exact counts.

### C2 · Undo stack

**Problem.** The `×` is one click and final (`events.js:217-223`); "Clear all" is one native confirm from wiping a session.

**Build.** Every mutating card action pushes an inverse op onto `state.undo` (last 20, persisted inside the draft record): `remove` ↔ `restore(index, card)`, `clear` ↔ `restore(all)`, `edit` ↔ `restore(field, value)`, `select` ↔ `restore(uid, state)`. `Ctrl+Z` / `Ctrl+Shift+Z`, a toast with an **Undo** button for 6 s after destructive actions, and an "Undo" entry in the review header showing the last action's name.

**Acceptance.** Delete a card, press `Ctrl+Z`, the card returns in its original position with its selection state; reload and undo still works.

---

## 3. Wave 2 — the two features that change what the app is (≈11 days)

### D1 · Figure cards — image occlusion without the add-on

**The gap.** Every med-school subject is diagrammatic — pathways, anatomy, histology, ECGs, flowcharts. The app detects images only to warn you to check them by hand (`store.py:618-633`, `coverage.js:53-67`). This is the largest unused surface in the product, and it is the feature that would move Anki Scribe out of the "text summariser" category.

**Why not Image Occlusion Enhanced.** It is an add-on with its own note types; depending on it doubles the install friction the product can least afford. We can produce stock `Basic` notes whose fields contain images we upload ourselves — no add-on, works on AnkiWeb and mobile.

**What the student does.** On any page, click **Figure**, drag a rectangle around a label or structure, and choose:
- **Hide this label** → the card shows the figure with that region covered, and asks for the name.
- **Explain this figure** → the card asks what the diagram shows and why it matters (no masking).

**What we build.**

1. **Region selection overlay** — a drag layer above the existing line overlay (`documents.js:206-278`, `styles.css:617-632`), emitting a rect in page-image pixel space (the same space as `page.lines`, so no new coordinate system).
2. **Context box** — the card image should be the *figure*, not a crop of a label. `Page.get_image_info()` (already used in `store.py:622`) gives raster bboxes: pick the one containing the rect, else pad the rect by 12 % and use that. Vector figures fall back to the padded rect.
3. **Server endpoint** `POST /api/figure` → returns two PNGs plus a suggested answer:
   ```python
   pix = pdf_page.get_pixmap(clip=box, dpi=200)
   # masked:  white fill + 1.5px accent border over the mapped rect
   # revealed: accent border only
   ```
   For the suggested answer, take the text lines whose centres fall inside the rect — diagram labels are usually real text in the PDF layer. "We found **mitral valve** in this region — use it?" is a delightful, nearly free touch.
4. **Anki media** — `storeMediaFile` with base64 data for both PNGs (`_as_fig_<hash>_m.png` / `_r.png`), then build the note:
   ```
   Front:  <img src="_as_fig_ab12_m.png"><br>Which structure is covered?
   Back:   <img src="_as_fig_ab12_r.png"><br>Mitral valve<br><i>…one-line context…</i>
   ```
   Anki copies media into the collection on add, so our files are disposable.
5. **Draft support** — before Anki is reachable, the crop lives under the document directory and review shows a thumbnail. The card carries `mode: "figure"` and reuses the whole existing edit/tick/push path.

**Acceptance.** Select a region on a slide figure → a draft card appears with a thumbnail and a suggested answer → push → the card renders in Anki desktop *and* AnkiWeb with both images, no add-on installed. Works on a page with a text layer and on a scanned page (no suggested answer).

**Effort.** 4 days (1 overlay, 1 endpoint + rendering, 1 Anki media + note building, 1 UI/review/draft plumbing). **Risk:** media upload failures are the main unknown — degrade to "text-only card with the quote".

### D3 · Study-objective coverage

**The gap.** Coverage is measured in pages (`coverage.js:81-93`), which is a proxy the model will happily game by padding. Medical courses hand students an explicit target: the learning objectives. Hitting them is what "covered the lecture" actually means.

**Build.**
1. **Detect** — at import, scan for an objectives block: a page whose first lines match `/^(lecture |learning |course )?objectives?\b/i` or `/by the end of (this|the) (lecture|session)/i`, followed by 3–10 bullets; or a slide titled "Objectives"/"Learning outcomes". Store `{page, items: [...]}` on the document.
2. **Map** — after a generation run, one cheap model call with the objectives plus the generated questions returns `{objectiveIndex: [cardIds]}`. Fall back to token overlap (no cost, lower precision) when there is no key.
3. **Show** — a checklist above Review, collapsible per chapter:

```
Learning objectives (4/7 covered)
 ✓ Describe the phases of the cardiac cycle
 ✓ Explain the Frank–Starling relationship
 ✗ Differentiate restrictive from constrictive pericarditis   [generate]
…
```

Clicking **generate** opens a targeted run scoped to the pages that discuss it.

**Acceptance.** A synthetic lecture with 5 objectives yields 5 rows; mapping accuracy ≥80 % on a hand-labelled sample; an objective with no matching card offers a one-click run.

**Why it wins.** It replaces a vanity metric with a syllabus, it is nearly free (the objectives are in the document already), and no competitor does it.

### C1 · Triage mode

**The bottleneck.** Generation is cheap; accepting 40 cards is not. Review today is a flat column with 5 tab stops per card (`cards.js:188-198`).

**Build.** A full-screen surface (a `dialog`, like study) that shows **one card and its source side by side**:

```
┌───────────────────────────────────────────────┬──────────────────────────────┐
│  Page 4 · lines 12–18            [verified ✓] │  Q: Why is metoprolol preferred
│  ─────────────────────────────────────────────│     over propranolol in asthma?
│  … Beta-1 selectivity means less bronchospasm │
│    than propranolol, which also blocks beta-2 │  A: β1-selectivity → less β2
│    receptors in the airway …                  │     blockade → less bronchospasm
│  ▓▓▓▓▓▓▓▓▓▓ (evidence highlighted)       │
│                                               │  Extra: asthma + AF scenario
└───────────────────────────────────────────────┴──────────────────────────────┘
  [A] accept  [X] reject  [E] edit  [R] regenerate  [U] undo     12 / 40 · 4.2 s/card
```

- `Space` reveals the answer (answers start hidden, like the study sheet — it is a rehearsal, not a read-through).
- `A`/`X` accept or reject and advance; `J`/`K` move without deciding; `E` focuses the question field in place; `U` undoes.
- Bulk keys: `Shift+A` accept all remaining verified, `Shift+X` reject all unverified.
- A live footer: "38 accepted · 2 rejected · 12 s/card".

Implement it as a **reducer over `state.cards`** — no new data, just a cursor, a filter and a key handler; the accept/reject actions call the same code paths `events.js:195-223` already uses.

**Acceptance.** 40 generated cards can be triaged to a final set without touching the mouse; median < 4 s/card; every mutation is undoable; leaving the mode preserves the draft.

### A2 · Coverage that survives

**Build.** Recompute `coverageModel()` (`coverage.js:70-118`) over `drafts ∪ ledger`, deduplicated by source unit. `renderCoverage` then reports two numbers:

```
Text coverage  87 %   ·   Facts with verified evidence  64 %
```

and after a push it stays, showing **"42 cards sent"** instead of resetting to zero. Add a per-source line in the Library:

```
Cardiology Lecture 3.pdf   42 cards · 12 % uncovered · last opened 3 days ago
```

**Acceptance.** Push everything, then reopen: coverage and highlights are unchanged; the library row shows the sent count; deleting the ledger entry (Clear all → also clear ledger) resets it.

### C3 · Bulk select, filter, chapter grouping

**Build.** A sticky toolbar over the card list: search box, filter chips (mode, tag, chapter, verified/unverified), select-all / none / invert, and collapsible chapter sections (`<details>` grouped by `source.chapterPath`). Move the push bar into the toolbar's sticky footer so it stays reachable — this alone fixes the 400-tab-stop problem (`index.html:229-237`).

**Acceptance.** Filter to "unverified" and select-all; 2,000 cards render in under 300 ms; the push button is reachable in ≤5 tab stops from the top of the panel.

### E2 · Card-style presets

**Build.** A `<select>` beside the mode toggle: **Balanced · Mechanism · Clinical vignette · Drug/facts table · Exam trap** — plus a free-text "Extra instructions" field saved per source. Each preset is a prompt fragment appended to the system message (`llm.py:353-366`); the fragment set lives in one dict so it is testable without a model call.

Example — *Exam trap*: "Write cards that discriminate between confusable options: name the alternative in the question and make the answer explain why the alternative is wrong."

**Acceptance.** Selecting a preset changes the outgoing system message (unit-testable), and the preset survives reopening the file.

---

## 4. Wave 3 — the loop and the governor (≈8 days)

### E1 · Leech loop — read review results back

**The moat.** Every competitor stops at "cards created". Anki knows which ones *failed*, and we will have `QuestionId` in the note (B2) to link back.

**Build.**
1. On open (or a "Check my deck" button): `findCards` for `tag:anki-scribe` (we already tag every note), then `cardsInfo` for the ids.
2. Match each note to a ledger record by `QuestionId`; compute lapses, reps, ease, interval.
3. Show a **Review health** panel:

```
Your cards from this app — 214 notes
 Leeches (≥4 lapses): 12        Average ease: 2.1 (low)
 Worst: "Which β-blocker is β1-selective?" — 7 lapses — Lecture 3, p.4
 [ Regenerate these 12 ]   [ Show all ]
```

4. **Regenerate** re-runs generation on the source range with a contrast prompt: *"These facts were repeatedly forgotten. Write cards that contrast the confusable options rather than restating definitions."* The new cards go through the normal draft → triage → push path, and the old notes are tagged `anki-scribe::superseded` (never deleted automatically — that is the user's collection).
5. **Aggregate hints** (the part that compounds): if cards containing a number lapse 3× more often than the rest, show a one-line finding and offer to change the preset. Nothing leaves the machine; no embeddings; all arithmetic.

**Acceptance.** With a fixture collection of 50 notes (12 leeches), the panel reports exactly 12 and links each to its source page; regenerate produces a draft batch scoped to those ranges; superseded notes are tagged, not deleted.

**Effort.** 3.5 d (1 AnkiConnect calls + matching, 1.5 panel + regenerate flow, 1 aggregation + tests). **Risk:** `cardsInfo` shapes vary by AnkiConnect version — parse defensively, and treat the whole feature as unavailable when the action errors.

### B4 · "Likely wrong" ranking

**Build.** A local score per card, no model call:

| Signal | Weight |
|---|---|
| Evidence not found in the excerpt | +5 |
| Cloze deletion longer than 6 words, or >3 deletions | +3 |
| Question under 5 words, or contains "this"/"the text" | +3 |
| ≥0.8 token-Jaccard with another card in the batch (interference) | +2 |
| Answer contains a negation the question does not | +1 |
| No tags | +1 |

Sort Review by it, show a **"5 to check"** chip that opens triage mode filtered to the top scores.

**Acceptance.** On a fixture batch with 3 planted defects, all 3 rank in the top 3; the score is deterministic and covered by unit tests.

### C4 · Regenerate one card

**Build.** `POST /api/generate/one` with `{card, excerpt, nudge}` where `nudge ∈ {simpler, clinical, cloze, shorter, more-specific}`. One call, one card, same validation as the batch path. Replace in place (same `uid`, same position) so undo restores the old text via C2.

**Acceptance.** Regenerating keeps the card's position and selection; a failed regeneration leaves the original untouched and says so.

### A3 · "Already covered" guard

**Build.** Before `/api/generate` runs, fingerprint the selection (normalised token set) and compare against the ledger for that source: if a sent card's `fingerprint` overlaps ≥70 %, show a non-blocking notice — *"You already have 3 cards from this passage. Generate anyway / Show them"*. Also offer "check my whole collection" via `findNotes` when Anki is connected.

**Acceptance.** Regenerating the same page twice warns the second time; "Show them" scrolls to those cards in the ledger view.

### E3 · Cost preview, usage capture, cap

**Build.**
1. Read `usage` from every chat response and store it on the run (`llm.py:296-303` currently discards it).
2. Before a whole-file run: estimate `chars / 3.8` input tokens plus ~700 per section, show **"≈ 130k in / 80k out · about ¥0.4 · 65 sections"** next to the chapter list, with a **cap** input ("stop at ¥2").
3. After the run: a one-line report in the auto panel and a per-source total in the Library.
4. Check `finish_reason == "length"` and retry with a smaller count instead of paying twice for a doomed parse (`llm.py:369-390`).

**Acceptance.** A run's reported tokens match the sum of the API `usage` fields; a cap of 1 section aborts after one section with the cards already generated kept.

### F1 · Server-side jobs (+ A4 resume)

**Build.**
- `POST /api/jobs` `{docId, chapters, mode, preset, cap}` → `{jobId}`; a worker thread walks chapters × chunks, writing cards into the draft store as it goes.
- `GET /api/jobs/{id}` → `{state, section, total, cards, failures, cost}`; `DELETE` cancels cooperatively.
- Persist `jobs.json` so closing the tab and reopening the file resumes: the client sees `state: "paused"` and offers **Resume from chapter 7**.
- The client loop in `auto.js:200-334` becomes a poller; the extraction and OCR work moves off the request thread at the same time.

**Acceptance.** Start a 20-section run, close the tab, reopen: 8 sections' cards are there and Resume continues at 9. Cancel mid-section leaves the completed cards. Two tabs cannot start the same job twice.

---

## 5. Wave 4 — reach and polish (≈7 days)

### D2 · PPTX import via a synthetic PDF

**Why this way.** Slides are the actual format of a med-school lecture, and the app rejects them (`ALLOWED_SUFFIXES`, `library.py:17-27`). Rendering PowerPoint properly needs an office suite. But we do not need fidelity — we need *a page with text at positions*, which is exactly what the existing pipeline consumes.

**Build.**
1. `python-pptx` (new, pure-Python dependency) reads each slide: slide size → page size in points; every shape with text → a line with `x0/y0/x1/y1` from its EMU geometry; every picture shape → `page.insert_image`.
2. Compose a synthetic PDF with PyMuPDF: `new_page(width, height)`, `insert_textbox` per shape with the shape's own font size, `insert_image` for pictures. Store it as the document's `source.pdf`.
3. Nothing downstream changes: rendering, line overlay, selection, chapters, figure cards, extraction all work because it is now just a PDF. `kind` can stay `"pdf"` with `origin: "pptx"` for messaging.
4. Same trick extends to `.docx` later (paragraph → text box); low value, leave it.

**Acceptance.** A 30-slide deck imports in under 5 s, renders 30 pages, text selection lines line up with the drawn text, and a figure card can be made from a slide picture. Speaker notes are exposed as an optional extra excerpt ("speaker notes" appended to the slide text) — a small touch that wins lectures where the bullets are thin.

**Risk.** Font metrics differ from PowerPoint, so text may wrap differently; acceptable because our overlay uses our own insertion geometry, and the page is ours, not the original.

### F2 · Onboarding + single instance

**Build.** A first-run wizard as a real `dialog`: paste key → **Test** (calls `/api/ai/balance`) → detect AnkiConnect with a copyable add-on code and a retry button → pick a deck → drop a sample PDF → generate 5 cards. Then a persistent "setup incomplete" chip instead of silent failure. Alongside it: an OS mutex so a second launch focuses the first window (fixes the shared `.tmp` corruption in REVIEW §3.5.8), `fsync` + `.bak` on the JSON stores, and corrupt-file quarantine.

**Acceptance.** A clean machine with no key and Anki closed can complete the wizard to a first card in under 3 minutes; launching twice does not corrupt drafts.

### F3 · Diagnostics bundle

**Build.** Rotating log (`%LOCALAPPDATA%\AnkiScribe\anki-scribe.log`, 5 × 1 MB) with request ids and per-run summaries; a **Diagnostics** button that writes a zip — version, redacted settings, last 200 log lines, document list with sizes, last run summary — and an `error ref: 7f3a` shown in toasts instead of raw exception strings.

**Acceptance.** Reproducing a failed generation from the bundle alone is possible without asking the user a question.

### F4 · Study sheet upgrades

**Build.** (a) **Type-to-reveal** in the study dialog and the exported HTML: an input, then reveal, then a self-grade (again/hard/good) that is stored locally — the retrieval-practice fix from the review. (b) **Export Markdown / CSV** so a broken AnkiConnect never traps the work. (c) **AnkiWeb sync** after a push (`sync` action), with a one-line "synced" confirmation — 15 minutes of work that saves the user a manual step every session.

---

## 5b. Books — PDF and EPUB (shipped)

Everything above assumed a lecture: one file, ten to forty pages, one sitting. A
textbook breaks three assumptions at once — it is 600–1,300 pages (the PDF cap
was 300), it often arrives as an EPUB (a format the app refused), and its
structure is a contents page rather than a title on slide one. The fix is not
"read a bigger file": it is to make a **chapter** the unit of work, both for the
model and for the user.

**Build.**

1. **`app/epub.py` — an EPUB reader with no dependency.** A book is a zip of
   XHTML plus a package document. The spine gives reading order; the EPUB 3
   `nav` document (or the EPUB 2 `toc.ncx`) gives contents. The text is laid out
   line by line onto A4 pages with PyMuPDF and kept twice: as a synthetic PDF, so
   page images, selection, highlights, objectives and figure crops keep working,
   and as `Page.lines`, so the stored text is the book's own characters rather
   than whatever a PDF text layer recovers. The contents entries become the PDF
   outline and every chapter starts a new page — that is what makes a chapter a
   page range. Advance widths are cached per glyph: `Font.text_length` re-encodes
   every character (≈11 µs), which made a 585-page import take 48 s instead of 7.
2. **Book-scale limits.** `MAX_PAGES` 300 → 1,500 and `MAX_UPLOAD_BYTES` 40 MB →
   200 MB (`store.py`). Page images on a long book are evicted beyond the newest
   60, so a 600-page book cannot grow a multi-gigabyte cache.
3. **Two costs that had to disappear first.** Importing a 769-page illustrated PDF
   took 82 s and splitting it took six minutes, and neither was the contents page
   (that parses in 0.1 s). `get_text("dict")` was decoding every picture on every
   page only for `extract_pdf_lines` to throw the pictures away — `flags` without
   `TEXT_PRESERVE_IMAGES` took it from 147 ms to 6 ms a page. And `find_tables()`
   is a half-second layout analysis per page, so table detection now runs only up
   to 250 pages (books keep the cell text in reading order, without the Markdown
   grid) and is skipped for synthetic EPUB/PPTX pages. A path import is also
   reused by source + mtime, so reopening a textbook does not extract it again.
4. **A better chapter level.** `chapters._pick_candidates` chooses which level of
   an outline is the chapter level: the level whose titles announce themselves
   ("Chapter 4", "Unit II") wins, otherwise the deepest level that still leaves
   2–40 units. Before, a book with parts over chapters split at parts, and one
   with chapters over sections split at sections. A bare "CHAPTER 12" now takes
   the title printed on the line below it instead of every chapter being called
   "Chapter 12". The EPUB reader applies the same idea to the book's own
   contents, and drops navigation entries ("Cover", "Contents", "Index") so a
   deck is never called "Cover".
5. **`app/split.py` + `POST /api/documents/{id}/split`** — the same chapter plan,
   written to disk: numbered Markdown files with YAML front matter, page markers
   and a `manifest.json` (title, path, page range, characters, order). The client
   exposes it as **Save chapters** with an **Open folder** action; a re-split
   removes the files the previous run left behind.

**Acceptance (measured).** A 769-page PDF textbook imports in 6 s → 769 pages,
22 chapters, and splits to 22 files in 0.1 s (was 82 s and 370 s). A 585-page
EPUB imports in 7 s → 585 pages, 6 chapters, 1.9 M characters. A 101-essay
collection imports as 173 pages and 103 chapters, then splits to 103 files in
0.1 s. Four real books from this machine — a Springer volume, a Pearson
textbook, a 37-strategy trading book and an essay collection — all get their own
chapter list. Splitting makes no model calls: it reads the pages already in the
cache.

**Risk.** The page image is a rendering of the text, not the book's design —
tables survive as cell text, figures do not. Non-Latin scripts are stored as
logical text (so the cards are correct) but are drawn without full bidirectional
shaping, which makes an Arabic page image approximate. Fixed-layout EPUBs,
comics and image-only books have no text and are refused with a message pointing
at PDF + OCR.

---

## 5c. Two ways to close the loop by hand (shipped)

**Click the highlight, not just the pill.** The teal source map was one-way: a
card could jump to its quote, but the quote could not jump back to the card.
`applyDraftHighlights` now records every card that owns a line
(`data-card-uids`), and a click on a teal line scrolls the review panel to that
card and flashes it. A drag or a real text selection is ignored, so selecting
highlighted text still works; a line shared by several cards cycles through
them on repeated clicks.

**A picture on any card.** Until now the figure tool was the only way to get an
image into Anki, and it always made a *new* masked card. `app/images.py` adds the
plain case: **Add picture** crops a region of the page under the cursor or takes
a PNG/JPG/WEBP from disk, and attaches it to a card that already exists, with a
**Show on front** tick. Files are stored beside the figures (`img-<hash>.png`),
served from `/api/documents/{id}/images/{name}`, and travel to Anki through the
same media upload as figures — `anki._note_for` puts the `<img>` on `Front` or
`Back` (or `Text`/`Back Extra` on a cloze card). **Replace** re-crops in place.

**Verified in a real browser.** A headless Chrome run on a seeded document
confirmed: clicking a highlighted line flashes the matching card and scrolls the
panel; two cards on one line cycle `card-one → card-three → card-one`; Add
picture → menu → crop-drag replaces the image; upload through the hidden file
input adds a second image; the front/back tick reaches `state.cards`; no console
errors. The backend is covered by `tests/test_images.py` — crop, upload
conversion, unsafe media names, note fields and the push media list.

**Memory at book scale.** A 1,000-card whole-book run used to build 1,000 cards
× ~72 nodes = 72,115 DOM nodes and re-build all of them on every action; ten
renders left ~770,000 detached nodes and ~460,000 layout objects waiting for GC,
which on a Chromium browser reachable at 2–3 GB. Two structural changes fixed
it: the review list keeps a slot per card and builds only the ~80 nearest the
viewport, and the page viewer drops a page image once it is 900 px away (each
1200×1600 page is ~8 MB decoded, and a 120-page scroll used to keep every one).
Measured after the change: 5,393 nodes at rest with 1,000 cards, 30 ms for
`renderCards()`, 2–3 page images alive while scrolling the whole book, and the
same highlight-click and image flows working with cards built on demand.

**The empty-app incident.** A launch of `run.bat` found port 8777 taken by an
unrelated project, scanned the range, and attached to a leftover test server on
8798 that was serving a *temporary* data folder — so the app looked wiped while
`%LOCALAPPDATA%\AnkiScribe` was untouched. That session's work (298 cards, one
library file, a re-entered key) was recovered from the temp folder and merged
back. Three changes close the hole: `/api/health` reports a fingerprint of the
data folder and an instance is adopted only when the fingerprint matches;
`instance.lock` keeps one process per data folder; and every JSON store writes
atomically with a `.bak` the app falls back to and repairs from. One more fix was
needed for the recovery to be visible: drafts for EPUB/PPTX are keyed by the file
the user opened (`originPath`), not by the synthetic cache document that is
rebuilt under a new id.

**Formulas.** A PDF text layer does not hand over an equation: it hands over
``𝐴``, ``𝝁``, ``²`` in reading order, and a model reads that as noise.
`app/formats.py` folds the Unicode back to letters (NFKC), writes superscripts
and subscripts as ``^{…}``/``_{…}``, and — when a line was set in a math font or
is mostly symbols with no prose word in it — sends the line as ``$…$`` with
Greek and operators as LaTeX. The test is deliberately strict: over 2,621 lines
of a marketing textbook it wrapped nothing, while a LaTeX paper yielded 28
formula lines. Tables are deliberately not reconstructed from borders — a crop
through **Add picture** keeps every row and column as an image, which is what a
card can be graded against.

---

## 6. Sequencing

```
week  1  2  3  4  5  6  7  8  9 10 11 12
A1 ██
B1 ██
B2 ██
B3 ██
C2 ██
      A2 ██
      C1 ███
      D1 █████
      D3 ███
      E2 ██
            B4 ███
            E1 ████████
            E3 ███
            F1 ███████████
                  D2 ████████
                  F2 ██████
                  F3 ███
                  F4 ███
```

**Parallelism.** A1/B1/B2/B3/C2 are one person for four days and unblock everything else. Then two tracks: *learning* (D1, D3, E1) and *interface* (C1, C3, A2, E2). F1 is a third, infrastructure track and can start any time after A1.

**Dependency order that actually matters:** A1 → (A2, A3, E1); B2 → E1; B1 → B4; C1 → C3; F1 → A4.

---

## 7. What we deliberately do not build

Each of these is a real request someone will make, and each would dilute the loop.

- **A chat interface.** The value is the pipeline, not a conversation. A chat box invites the student to read instead of review.
- **Our own scheduler / a mobile app.** Anki already owns spacing, and AnkiDroid/AnkiMobile already exist. Every hour spent re-implementing review is an hour not spent on the loop only we can do.
- **Cloud sync or accounts.** The "your files never leave this machine" claim is the product's best privacy asset, especially for medical content.
- **A general card editor.** Triage plus inline edit plus undo is enough; a WYSIWYG editor is a tarpit.
- **AI-generated images.** Figure cards should use the student's own figures, which are the ones on the exam. Generating illustrations invites confidently wrong anatomy.
- **Multi-user, classroom, LMS integration.** A different product with a different buying centre; revisit after the single-student loop retains.

---

## 8. How we will know it worked

Instrument locally (anonymous, opt-in, or simply computed from the ledger) and put the numbers on one screen:

| Metric | Today | Target after wave 3 |
|---|---|---|
| Time from file-open to first card in Anki | not measured | < 10 min median |
| Cards pushed ÷ cards generated | ~unknown, untracked | > 60 % |
| Cards edited before push | untracked | < 25 % (automation should be good enough not to need edits) |
| Unverified cards reaching Anki | unknown | 0 in strict mode |
| Return within 7 days | untracked | > 40 % |
| Leeches at 30 days per 100 cards | untracked | < 8 and falling |
| Sources with a figure card | 0 | > 25 % of sources |

If *cards pushed ÷ generated* stays below a third after C1 and B1, the generation quality is the problem and the next wave is prompts, not features. That is the honest tripwire, and it is the number to look at every week.

---

## 9. First sprint, concretely

Five tickets, four days, and the app is materially more trustworthy:

1. **`sent.json` store** + `push_cards` returns ids + client pairs and deletes after (`deck.js:537`) — *1.5 d*
2. **Evidence verification** in `parse_cards` + badge in `cards.js` — *0.5 d*
3. **Anki Scribe note type** with `Source`/`Page`/`Quote` + stock fallback — *0.5 d*
4. **`canAddNotes` preflight** with a dry-run summary — *0.5 d*
5. **Undo stack** + `Ctrl+Z` + undo-toast — *0.5 d*

None of these add a screen. All five make the next twenty features possible or honest.

## 10. Card quality gate (feature 001, shipped)

Spec-driven build (`specs/001-card-quality-gate/`). Introduced one module,
`app/cards_quality.py`, that answers two questions about every card and is used
by both the generator and the push path:

- **What does this card test?** One of `definition`, `mechanism`, `compare`,
  `application`, `enumeration`, `number`. Returned with every generated card;
  the review header shows the mix.
- **What is wrong with it?** `empty_side`, `open_ended`, `answer_leak` and
  `cloze_overloaded` are blocking; `list_answer`, `vague_question`,
  `bare_number`, `untagged` and `interference_pair` are warnings.

`POST /api/anki/push` and `/api/anki/preflight` refuse a batch that contains a
blocking fault, before AnkiConnect is called, and return
`{error: "blocked_cards", message, blocked: [...]}`. `allow_blocked: true` is the
explicit override, and the push dialog offers it after listing the cards.

The generation prompts now state the same rules (closed questions, no answer
echo, one cloze deletion, a type per card), so most defects are never produced —
and the cloze rule no longer contradicts itself ("1-3 deletions" versus "one
fact per card").

Measured: 334 tests green (66 of them new). `evaluate_batch()` on 1,000 cards takes well under
the 250 ms budget.
