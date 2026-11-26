# Anki Scribe — a multi-role review

**Scope:** the repository at `C:\Users\mahmo\Desktop\anki-scribe` (v0.1.0), read end to end — 4,147 lines of Python across 12 modules, 4,396 lines of browser JavaScript across 13 files, 2,016 lines of CSS, 500 lines of HTML, 32 HTTP routes, 1,783 lines of tests (97 tests, all green in 9.0 s).

**Method:** the same product reviewed from thirteen seats in the company, re-read through ten mental models, then reduced to a plan. Findings marked **[verified]** were reproduced against the running code, not just read. Sections disagree with each other in places — deliberately.

**One-line verdict:** a *high-craft prototype with product-grade polish and prototype-grade infrastructure*. The generation engine is good. What decides whether it survives a real semester — memory, verification, distribution, and a security boundary that actually holds — is missing.

---

## 1. Scorecard

| Dimension | Score | Why |
| --- | --- | --- |
| Product clarity | 8/10 | A real wedge, named and defended. The user, the job and the moment are obvious. |
| Learning efficacy | 5/10 | Cards are text-only, unverified, unbounded, and blind to interference. No image cards. No feedback from review outcomes. |
| UX craft | 7/10 | Real design taste: own icon set, consistent tokens, native `dialog`, toasts, keyboard support in study mode. Undermined by nine native `confirm`/`prompt` calls, no undo, and one refused gesture. |
| Accessibility | 3/10 | Measured contrast down to 1.85:1, input borders at 1.32:1, text selection is mouse-only, and none of the long async operations announces itself. |
| Security & privacy | **2/10** | The code's *output* hygiene is good (escaped cards, key never echoed, loopback bind). The *boundary* does not exist: **a demonstrated end-to-end chain that sends the stored API key to an arbitrary host**, plus confirmed arbitrary local file read and HTML injection in the exported study sheet. |
| Reliability | 4/10 | Atomic writes and request-epoch guards done properly — then a corrupt `library.json` prevents startup entirely, and a corrupt `drafts.json` silently erases the drafts. |
| Performance | 5/10 | Caching where it was thought about, absent where it hurts: 26 s cold extraction on 120 pages, OCR inside request handlers, whole-file JSON rewrites per keystroke. |
| Test coverage | 4/10 | 97 genuine tests on the pure parsers and the API; **zero** tests for 4,396 lines of JavaScript; the riskiest seams are mocked or never executed. |
| Operability | 3/10 | Zero logging in the backend. 27 `except Exception`. No request ids, no version surface, no diagnostics. |
| Distribution | 2/10 | Needs `uv` + Python + Anki + AnkiConnect + a funded key + Windows — and PyMuPDF is AGPL-or-commercial, which blocks redistribution as configured. |
| Maintainability | 5/10 | Clean module names and small functions, undone by an 838-line `store.py` god object, one 10-file dependency cycle in a global JS scope, no git, no CI, no linter, no types. |
| Documentation | 7/10 | The README is excellent *and* a symptom: 283 lines to explain a five-step flow. |

The gaps concentrate in two places: **what happens after the cards are made**, and **how the thing reaches a student who is not its author** — plus one place where a single middleware turns a 2 into an 8.

---

## 2. What the software actually is

### 2.1 Shape

```
                     +----------------------------------------------+
  PDF / photo / SRT  |  FastAPI on 127.0.0.1:8777   (32 routes)     |
  -----------------> |                                              |
                     |  store.py    PDF text+lines+tables, renders  |
                     |  ocr.py      Windows OCR -> RapidOCR         |
                     |  transcript  cue parsing, merge, timestamps  |
                     |  chapters    TOC -> headings -> LLM outline  |
                     |  llm.py      DeepSeek chat, prompt, validate |
                     |  anki.py     AnkiConnect -> addNotes         |
                     |  study.py    PDF + standalone HTML sheets    |
                     +------+--------------+---------------+--------+
                            |              |               |
       %LOCALAPPDATA%\AnkiScribe         DeepSeek        AnkiConnect
       config.json  library.json         chat API        127.0.0.1:8765
       drafts.json  documents\*/          (text only)
```

The browser is one page with 13 plain scripts loaded in declared order and no build step (`index.html:486-498`). State is a single global `state` object (`core.js:12-63`) mutated in place by every module.

### 2.2 The core loop

1. Open a file → text lines with pixel boxes, or transcript segments.
2. Drag across the page → the selected line range becomes `state.selection`.
3. **Generate cards** → one DeepSeek call → JSON cards with `question`/`answer`/`extra`/`tags`/`evidence`.
4. Review → edit inline, untick what you don't want.
5. **Send to Anki** → grouped by deck, 100 per `addNotes` batch.

Or skip 2–3 and run **Auto from whole file**: plan chapters (TOC → headings → LLM), then walk chapters × chunks calling `/api/generate` once per chunk, in a browser `for` loop (`auto.js:200-334`).

### 2.3 What is genuinely good, and worth protecting

Not consolation prizes — these are why the rest of the review is worth writing.

- **Card sanitisation is correct and well-tested.** Model output is escaped first, then only `b/i/u/em/strong/sub/sup` are restored (`llm.py:74-102`), so Anki fields are not injectable. Study-sheet *cards* are escaped (`study.py:607-636`). The four `innerHTML` uses in the client are static SVG templates; every variable string goes through `textContent` (`library.js:174-187`, `cards.js:260-267`).
- **Writes are atomic.** Every JSON store does temp-write + `replace` (`config.py:76-79`, `drafts.py:44-48`, `library.py:142-147`, `store.py:271-278`).
- **Race guards exist.** Async handlers carry a request epoch and drop stale responses (`drafts.js:27-43`, `coverage.js:176-192`); long runs use an `AbortController` (`auto.js:112`).
- **The library stores paths, not copies** (`library.py:217-244`). Originals are never moved or modified.
- **Coverage mapped back onto the page** is the most novel thing in the product, and nobody in this category does it.
- **The PDF study sheet is a real design solution**, not a hack: it avoids optional-content layers precisely because Chrome and Edge ignore them, and uses bidirectional links instead (`study.py:1-8`, `README.md:145-158`).
- **`create_app(store=…, settings=…, library=…, drafts=…)`** (`main.py:120-130`) is the best engineering decision in the repo — it makes every route testable with real temp directories, and it is why 97 tests exist at all.
- **The suite is fast** (9 s), which removes every excuse for not gating on it.

---

## 3. Findings by role

Thirteen seats. Each has a mandate, its sharpest observations, and the action it would take Monday.

### 3.1 Product manager — "the retention cliff"

**My mandate:** decide what this is, who returns tomorrow, and why.

The wedge is sharp and honest: *"When I leave a lecture, I want the lecture turned into reviewable cards before the memory decays, so I pass the exam without re-reading."* Everything up to the first successful push is coherent. Then the loop ends.

1. **The app destroys its own record at the moment of success. [verified by reading]** `pushToAnki` deletes each pushed card from `state.cards` as its batch succeeds (`deck.js:537-538`). Coverage is derived from `state.cards` (`coverage.js:81-93`), highlighting too (`drafts.js:173-203`), and drafts persist `state.cards` (`drafts.js:91-95`). Mechanically: **the moment your cards arrive in Anki, the meter resets to "0% — No cards yet — generate to start covering this file", and every teal highlight vanishes.** The reward for finishing is being told you have done nothing.
2. **The best asset never crosses the boundary.** Every card carries a verbatim `evidence` quote and a page or timestamp. Provenance is used for highlighting and then dropped: the Anki note receives only `Front`/`Back`/`Text`/`Back Extra` (`anki.py:89-112`). In Anki — where the student will live for four years — a card cannot say which lecture, which page, or which sentence it came from.
3. **There is no second-visit reason that isn't the first visit.** No "lectures not yet carded", no "340 unreviewed cards from this week", no review statistics, no reminder. The library is a file list, not a progress model (`library.py`).
4. **Every dependency is a churn point.** Windows → Anki desktop → AnkiConnect → DeepSeek account → funded key → `uv` → Python. Seven steps before the first card, and steps 1 and 6 exclude most of the intended audience (`README.md:57-98`, `run.bat`).
5. **Positioning is the model vendor's name.** DeepSeek appears in the value proposition, the header pill, the settings tab and the error messages. If the vendor doubles its price, the product has no story left; if a competitor matches generation quality, everything left is the workflow — which is where the investment belongs.

**What I'd do Monday.** Write one sentence on the wall — *"the collection is the product; the generator is a feature"* — and let it delete work. Then: a `sent` ledger per source (§3.9.3) so the app remembers what it covered; `source`+`page`+`evidence` in the note (§3.2); and exactly one return-visit affordance — a per-source row: **"Lecture 3 · 42 cards sent · 12 % uncovered"**.

**What I'd say out loud:** the generator is a commodity and the review step is the bottleneck. The UI is built like a printer (big button, progress bar); the user's real work is a mailroom — triage 30 items, accept 22, fix 3, reject 5. Stop optimising the printer.

### 3.2 Learning scientist — "cards that survive thirty days"

**My mandate:** the student should still know this in six weeks, and should not learn anything false.

The prompt is better than most: atomic facts, standalone questions, no preamble, "use only facts in the excerpt", a verbatim evidence quote (`llm.py:22-41`). Someone who knows this domain wrote it. Five things undercut it.

1. **Nothing verifies the evidence.** The model is asked for a verbatim quote (rule 9, `llm.py:37`), the client stores it (`cards.js:112-116`), the UI displays it (`cards.js:276-283`) — and **no code ever checks it is a substring of the source.** For spaced repetition this is not cosmetic: a hallucinated card is not a bad card, it is a *permanently installed* bad card. The fix is ten lines and local (`evidence.lower() in excerpt.lower()`, else drop or re-ask) and it is the highest value-per-line change in the repository.
2. **The note type refuses the good fields.** `_note_for` hardcodes `Basic`/`Cloze` into `Front`/`Back`/`Text`/`Back Extra` (`anki.py:89-112`). Med students work in collections customised over years — sources, lecture numbers, images, exam tags. Writing into a stock note type makes these second-class notes in their own collection and discards provenance. Create or accept an `Anki Scribe` note type (`Question, Answer, Extra, Source, Page, Quote`) and fall back to `Basic` when absent.
3. **Two-column pages are interleaved before the model sees them. [verified]** `_compose_page` sorts page items by `y0` alone (`store.py:568-577`). On a two-column textbook page both columns share baselines, so the text alternates left/right. Reproduced: four left and four right lines at identical baselines compose to `LEFT alpha / RIGHT one / LEFT beta / RIGHT two / …`. The OCR path already solves exactly this with gutter detection (`ocr.py:33-56`); the PDF text path never calls it. Robbins, Harrison's, Guyton — the default layout of the target material.
4. **Rolling subtitles are duplicated. [verified]** `_merge` appends a cue unless the new text is an exact duplicate or a *suffix* of the previous (`transcript.py:85-100`). YouTube-style rolling captions repeat the previous line as a *prefix* of the next, so nothing matches and text accumulates:

   ```
   in : "the heart is" / "the heart is a pump" / "the heart is a pump that moves blood" / "that moves blood to the lungs"
   out: "the heart is the heart is a pump the heart is a pump that moves blood that moves blood to the lungs"
   ```

   The whole transcript collapses into one triplicated segment, and every card and evidence quote inherits it. Fix: detect prefix overlap and splice.
5. **There is no pacing, and Anki's scheduler will punish the deck tree.** A 300-page PDF yields roughly one 3,500-character section per 4–5 pages (`chapters.py:56-60`, `auto.js:203`) at up to 25 cards each — thousands of cards from one file. Worse, the default output is a **subdeck per chapter** (`deck.js:31-61`), and in Anki every deck carries its own "new cards/day" limit. Twelve chapters × 20 new/day = 240 new cards a day. The tool manufactures the overload it exists to prevent. The flat mode already exists ("Send cards directly here") and should be the recommended default, with chapter as a *tag and a field*.

**Two more, from the literature rather than the code.**

- **Image occlusion is the missing half of the product.** Figures, flowcharts, ECGs, histology, anatomy, pathway diagrams are the highest-yield content in medical school and are *unreachable*: images are only counted for the coverage warning (`store.py:618-633`), never read. The app even tells the user to go check the diagrams by hand (`coverage.js:53-67`). "Select a region on a figure → occlusion card" is a bigger feature than everything in the backlog, and the one that would change the tool's category.
- **Automating card construction deletes a study act, and that must be a decision.** The generation effect is real: writing the question is encoding. A tool that removes it has to put *some* productive difficulty back, or it produces students with decks they cannot answer. The app owns the right primitive and doesn't use it: the study sheet reveals on click with no attempt. Add "type your answer, then reveal", and it stops being a card factory and becomes rehearsal.

**Illustrative card quality for the same fact** (constructed, not from a run):

| | Card | Verdict |
| --- | --- | --- |
| ✗ | Q: What does metoprolol do? A: It is a beta blocker. | No discrimination — every beta blocker answers it. |
| ~ | Q: Metoprolol belongs to which drug class? A: β1-selective beta blocker. | Correct but definitional; interferes with atenolol, bisoprolol. |
| ✓ | Q: A patient with asthma needs rate control for AF. Why metoprolol over propranolol? A: β1-selectivity — less β2 blockade, so less bronchospasm. | Tests the discriminating mechanism: what exams ask and what transfers. |

The prompt asks for the third in spirit ("mechanism, cause, consequence, clinical relevance") but gives the model no contrast, no sibling cards and no examples, so it lands on the second most of the time. The interference problem is structural: cards are generated per chunk, in isolation, with no knowledge of the siblings they will be confused with (`auto.js:241-333`).

### 3.3 UX designer — "where the floor gives way"

**My mandate:** the student should never wonder what just happened.

**Five places the flow breaks:**

1. **Drag-and-drop from Explorer is refused, deliberately.** `events.js:265-274` catches every file drop and shows a notice explaining that browsers don't expose the path. The most natural gesture in the product is answered with a paragraph of technical explanation. Solvable (accept the drop into the cache; or use `getAsFileSystemHandle`).
2. **No undo, on a screen whose main verb is deletion.** The `×` removes a card immediately (`events.js:217-223`) and autosave persists it 450 ms later (`drafts.js:83-86`). Same for **Clear all**, guarded only by a native confirm (`events.js:164-169`). There is no undo stack anywhere in 4,396 lines of client code.
3. **Nine blocking browser dialogs** (`confirm` ×6, `prompt` ×3) in an app with a proper `dialog` system. The highest-stakes decision in auto mode — "generate chapter by chapter?" — dumps up to 8 chapter titles as bullets (`auto.js:169-188`), blocks the thread behind a frozen progress bar, and cannot be reviewed in any meaningful way.
4. **The long-running flow can look hung for minutes.** Auto mode's only feedback during a chapter is a static "Reading chapter 3 of 12…" (`auto.js:221-225`). On a scanned 200-page PDF, every page's OCR runs inside that single `/api/extract` request (`store.py:794-798`), sequentially, with no per-page progress, and the client's `AbortController` cancels the fetch while the server keeps working. The client `api()` helper has no timeout at all (`core.js:71-86`).
5. **Selection is line-granular and must be corrected in a textarea.** Acknowledged in the README (`README.md:183`), but the UI offers "trim it in the Selection box" rather than word-level selection.

**The interaction defect register** — every entry is user-visible, with a line number:

| # | Defect | Evidence | Severity |
| --- | --- | --- | --- |
| U1 | **Opening a file mid-generation corrupts the result.** `generateCards` reads `state.selection.location` and `state.doc` *after* awaiting the API (`cards.js:56-58`, `97`), while `openLibraryFile` guards `state.auto.running` but **not** `state.generating` (`library.js:607-611`). Generate from A, open B, and A's cards are appended to B's draft with an empty location — then B's async restore replaces `state.cards` wholesale (`drafts.js:54`) and deletes them. | `cards.js:43-60`, `drafts.js:54` | **High — silent data loss** |
| U2 | **No cancel on the primary generate button.** Auto has an `AbortController`; single-selection generate has no cancel, no elapsed time, no model feedback. A slow call freezes the filled primary button. | `cards.js:33-44` | High |
| U3 | **Review has no triage.** One flat list, one bulk action ("Clear all"), no select-all, no filter, no chapter grouping — for runs that produce 100+ cards. Deselecting 40 cards is 40 clicks on an 18 px target. | `cards.js:188-198` | High |
| U4 | **"Send to Anki" is ~400 tab stops away** at 60 cards: the push bar sits after the whole list, and every card adds 5+ stops. Each successful batch re-renders and drops focus. | `index.html:229-237`, `deck.js:538` | High |
| U5 | **Push partial failure is unknowable.** Succeeded batches delete their cards inside the loop; if batch 3 of 4 throws, the catch shows only `error.message` and never the counts or the decks that succeeded. | `deck.js:537-539`, `570-575` | High |
| U6 | **The autosave that matters can silently fail.** `saveDraftsNow` swallows errors to `console.warn`; on unload it prefers `sendBeacon`, which returns false above ~64 KB, then falls back to `fetch(keepalive)` with the same cap — also swallowed. The server accepts 2,000 cards and the client caps nothing, so a long auto run can lose everything on close without a signal. | `drafts.js:96-111` | High |
| U7 | **One of the confirms is a lie.** "Opening a new file will clear the cards you haven't sent yet" contradicts autosave and restore. Teaching users to click through confirms is how the real one gets ignored. | `library.js:555-560` | Medium |
| U8 | **The deck dialog is a dead end when Anki is closed** — it says click Refresh, and the only Refresh button is behind the modal. | `deck.js:232` | Medium |
| U9 | **The "exact deck" switch is invisible outside the modal.** It persists in `localStorage`; afterwards the only cue is a label swapping "Parent deck" → "Deck location". | `deck.js:67-73`, `341-346` | Medium |
| U10 | **There is no way to close a document.** The welcome screen is a one-shot; `loadDocument` hides the empty state and nothing restores it. | `documents.js:22` | Medium |
| U11 | **`Ctrl+Enter` fires behind three of five dialogs** (deck, coverage, study) — including a side path that stacks a second dialog. | `events.js:250-258` | Medium |
| U12 | **Failure history evaporates.** Section errors are toasts capped at four visible nodes that self-hide in 5–9 s; on a 20-section file you cannot reconstruct which sections failed. | `auto.js:279-284`, `core.js:147` | Medium |
| U13 | **The whole-file progress bar can move backwards** — the total starts as an estimate and grows while the fill is `n/total`. | `auto.js:246-255` | Low |
| U14 | **The UI contradicts itself on readiness.** "Send to Anki" stays enabled while the header says Anki is offline; `state.pushing` is missing from `updateSelectionUi`, so delete and generate stay live during a push. | `cards.js:349`, `documents.js:503-505` | Medium |
| U15 | **Two permanent "still loading" lies.** A page whose text call failed reports "Still reading this page" forever; card-locate busy-polls 20 s with no busy state and stacks pollers. | `documents.js:513`, `source.js:29` | Low |

**Smaller, real:** the PDF zoom magnifies a bitmap even though the README sells "crisp at high zoom" (`README.md:11` vs `store.py:884-886`); nothing tells the user what a whole-file run will cost before it runs; and deck hierarchy — the thing that decides where a card lands — is 8.5 px grey text (`styles.css:1170-1178`), so chapters 1 and 9 look identical.

**What I'd keep.** The design system is genuinely good: one palette, one radius scale, three shadows, a real serif/sans/mono stack, hand-drawn SVG icons instead of an icon font. The study dialog is the best screen in the app — answer hidden, `Space` to reveal, `←`/`→` to move, `aria-live` on the answer region (`index.html:450-482`). That screen is proof the team can do first-class interaction design when a flow is actually finished.

### 3.4 Accessibility specialist — "measured, not asserted"

**My mandate:** WCAG 2.2 AA, or precisely where it fails.

Computed from the actual tokens (`styles.css:1-27`) with the WCAG 2.x relative-luminance formula:

| Pair | Ratio | Requirement | Verdict |
| --- | --- | --- | --- |
| `--ink` on `--surface` | 15.38:1 | 4.5 | pass |
| `--ink` on `--bg` | 13.49:1 | 4.5 | pass |
| `--accent-ink` on `--accent-soft` | 9.51:1 | 4.5 | pass |
| `--danger` on `--danger-soft` | 5.75:1 | 4.5 | pass |
| credit-pill text `#7c5a17` on `--gold-soft` | 5.65:1 | 4.5 | pass |
| `--accent` on surface | 5.38:1 | 4.5 | pass |
| `--muted` on `--surface-2` | **4.36:1** | 4.5 | **fail** |
| `--ok` on `--bg` | **4.33:1** | 4.5 | **fail** |
| `--muted` on `--bg` | **4.17:1** | 4.5 | **fail** |
| `--muted-2` on surface | **2.88:1** | 4.5 | **fail** |
| `--muted-2` on `--bg` | **2.52:1** | 4.5 | **fail** |
| unselected card at `opacity:.62` — ink | **4.48:1** | 4.5 | **fail** |
| unselected card at `.62` — `--muted-2` | **1.85:1** | 4.5 | **fail** |
| study answer label | **3.62:1** | 4.5 | **fail** |
| input border `#e4ded1` on surface | **1.32:1** | 3.0 (1.4.11) | **fail** |
| checkbox border `#d2cab8` on surface | **1.60:1** | 3.0 (1.4.11) | **fail** |

The palette's *text* colours were chosen with care — ink, accent, danger and the credit pill all pass comfortably. Every failure is in the quiet layer, and the quiet layer is where this app does its explaining.

`--muted-2` is not decorative. It is the colour of every form label (8.5 px), the card's deck destination (`styles.css:1170-1178`), the evidence quote (10 px), push result text (`1555-1561`), coverage notes, the privacy promise, library paths (9 px), the `Parent::Child` tip (9 px) and transcript timestamps. Those strings answer **which deck a card goes to** and **whether the push worked** — the two questions the product exists to answer. And `opacity:.62` drops the deck label to 1.85:1 in exactly the state where the user is deciding whether to re-tick a card.

Beyond colour:

- **Text selection is mouse-only.** Page text is a transparent overlay of absolutely-positioned spans (`styles.css:617-632`, `documents.js:252-278`) that are not focusable. The only keyboard path is the per-page "Select page" chip — one tab stop per page, so 200 stops to reach the panel in a 200-page PDF, because every page node is built up front (`documents.js:143-174`). WCAG 2.1.1 exposure on the app's central interaction.
- **The card checkbox has no visible focus.** `.tick input` is `opacity:0; width:0; height:0` (`styles.css:1093`), so the global `:focus-visible` ring paints on a 0×0 box; only `:checked + span` is styled (`styles.css:1104-1112`). Library search is the same: `outline: 0` with no `:focus-within` (`styles.css:1341-1361`).
- **Three inputs have no programmatic label** — the selection textarea, library search, pasted-path input rely on placeholders (`index.html:129`, `299`, `306`).
- **No long async operation announces itself.** `#autoStatus` rewrites every section (`auto.js:247-255`), `#uploadText` says "Reading your file…", the OCR badge appears (`documents.js:223`), `#pushStatus` counts batches (`deck.js:540-543`) — none has `role="status"`/`aria-live`, and `aria-busy` appears nowhere. Toasts and the study answer *are* live regions, so this is inconsistency rather than policy.
- **Both progress bars expose no value.** `role="progressbar"` with no `aria-valuenow` (`index.html:180`, `476`); JS only sets `style.width` (`auto.js:21`, `study.js:263`).
- **Cards are anonymous in a list.** Each `<article>` has no heading and no accessible name (`cards.js:210-213`), and every checkbox is labelled identically "Include this card" (`cards.js:228`) — forty identical controls in a rotor.
- **The deck list declares a listbox and ignores the keyboard contract.** Items do carry `role="option"`/`aria-selected` (`deck.js:250-251`), but there is no roving tabindex, no arrow keys, no `aria-activedescendant` — and every pick calls `replaceChildren()` (`deck.js:223`), throwing focus to `<body>`.
- **Study mode hijacks Space** from a focused button (`study.js:344-348`): tab to "Next →", press Space, and you reveal an answer instead of advancing.
- **`prefers-reduced-motion` is handled in CSS and bypassed in JS.** The media query is correct and even sets `scroll-behavior: auto !important` (`styles.css:1805-1812`), but four call sites pass `behavior:"smooth"` explicitly (`source.js:142`, `documents.js:319`, `328`, `study.js:324`).
- **No `forced-colors` guard for the transparent text layer** (`styles.css:622`).
- **Hit targets below 24×24** (2.5.8): card remove 22×22, the tick 18×18, every `.text-btn` ~19 px tall, `.cue-time` 20 px, toast close ~12×15. The destructive target is among the smallest.

**Fix order:** real labels on three inputs (10 min); lift `--muted-2` to ≈`#6b6d66` and stop using it for operational text (30 min); drop `opacity:.62` for a border/badge (15 min); visible focus for the tick and library search (20 min); `role="status"` on three nodes and `aria-valuenow` on two bars (45 min); arrow keys on the deck list (1 h); a `forced-colors` guard (15 min). About a day and a half, and it moves the score from 3 to 8.

### 3.5 Security & privacy engineer — "the local-only assumption *is* the security model, and it fails"

**My mandate:** name the adversary before naming the mitigation. These were probed against the running app, not inferred.

**1. The credential-theft chain is complete and demonstrated. [verified]** `PUT /api/settings` accepts any `base_url` (`main.py:527-535`, `config.py:114-118`); `_chat` then POSTs `Authorization: Bearer <stored key>` plus the full prompt to that URL (`llm.py:264-283`). In a live probe, repointing `base_url` at a local listener caused the next generation to arrive carrying the stored key and the lecture text, and the upstream 400 body was reflected back to the client for 200 characters. Nothing between those three lines asks who is calling. This is Critical because it is remote, silent, and one request long.

**2. There is no caller-identity control at all. [verified]** No `TrustedHostMiddleware`, no `Origin` check, no CORS policy, no CSRF token, no session token in 32 routes (`main.py:120-540`), and `/openapi.json` is live with 25 paths even though `docs_url` and `redoc_url` are disabled (`main.py:126`). Probes confirmed: `OPTIONS /api/settings` → 405 with no `Access-Control-*` headers; `PUT /api/settings` with `text/plain` or form encoding → 422, because FastAPI parses JSON only — **so classic form CSRF against the JSON routes does fail.** That is the only thing standing in the way, and **DNS rebinding walks around it**: a hostile page whose hostname resolves to 127.0.0.1 becomes same-origin and inherits the whole API. Note also that `POST /api/documents` is `multipart/form-data`, a *simple* request — it executes cross-origin without a preflight, so even without rebinding an arbitrary page can push files into the cache.

**3. Arbitrary local file read, end to end. [verified]** `POST /api/library/import` accepts any path (`library.py:35-39`, `217-244`); import errors are a path-existence oracle that echoes the full path; `POST /api/library/files/{id}/open` then returns the file *body* — a probe read a `.txt` and got its contents back inside `segments` (`main.py:391-433`). UNC paths additionally make `Path.is_file()` authenticate over SMB, which leaks NTLMv2 hashes.

**4. The env-var key is silently persisted. [verified]** `DEEPSEEK_API_KEY` is held in memory only (`config.py:61-63`), but any later settings save writes it into `config.json` (`config.py:72-79`). A user who deliberately kept the key off disk gets it written on the first preference change.

**5. The exported study sheet is injectable. [verified]** `_footer_meta` (`study.py:109-116`) puts `body.source` and `body.generated` into the meta line, and `build_html` interpolates it raw (`study.py:642`, `670`). A probe produced `<img src=x onerror="alert(1)">` and `<script>alert(2)</script>` in the exported file. The *cards* are escaped correctly; the meta line was missed — and "standalone HTML the student opens on their phone" is precisely the wrong place to miss it. A filename is attacker-influenced by anyone who can hand the student a PDF.

**6. A malformed URL escapes the error handling. [verified]** `http://[::1` passes the `startswith` check (`config.py:114-126`), then `httpx.InvalidURL` — which subclasses `Exception`, **not** `RequestError` — escapes `_chat`/`_invoke` and becomes an unhandled 500 on `/api/generate`, `/api/anki/status` and `/api/anki/push`.

**7. Resource ceilings are missing where geometry is attacker-controlled. [verified]** An 800-byte PDF with a 3000×3000 pt MediaBox produced a 6000×6000 px pixmap in 0.76 s with no clamp (`store.py:337-341`, `882-887`) — a 200-inch page is a multi-gigabyte allocation. `MAX_IMAGE_SIDE = 4000` guards photos only (`store.py:26`, `411`). Meanwhile upload is streamed with a running 40 MB check inside the loop (`main.py:170-175`), but multipart is fully spooled before that check runs and there is no `Content-Length` pre-check.

**8. Two instances corrupt each other. [verified by reading]** The port scan finds the first free port, so a second launch on a later port coexists (`run.py:41-47`). Both then do read-modify-write on the same `config.json`/`drafts.json`/`library.json` using the *same* `.tmp` name (`config.py:76-79`, `drafts.py:41-48`, `library.py:142-147`), and each prunes the other's documents (`store.py:294-300`).

**9. Corrupt state is mishandled in both directions. [verified]** A `library.json` containing `[]` raises `AttributeError: 'list' object has no attribute 'get'` at `library.py:96` and **the app never starts**. A corrupt JSON *object* is the opposite failure: silently treated as empty, then overwritten on the next save (`drafts.py:31-34`, `config.py:51-55`, `library.py:89-96`).

**10. The native picker is an unbounded, remotely triggerable dialog. [verified]** `POST /api/library/pick` runs `picker.pick_files()` on a worker thread and blocks indefinitely in a modal Tk dialog (probe exceeded 120 s). Any caller that can reach the API can pop a dialog in the user's session and park a thread (`main.py:377-389`, `picker.py:26-37`); concurrent picks race a toolkit that expects a single thread.

**11. Consent arrives after the data leaves.** `GET /api/documents/{id}/chapters` calls the model with up to 18,000 characters of per-page snippets when the local plan falls back (`main.py:244-263`, `chapters.py:344-363`) — and the UI's "generate chapter by chapter?" confirmation only appears *after* that request returns (`auto.js:138-192`). Declining the run does not unsend the outline, and `README.md:201-202` ("Only the text you select … is sent") is not strictly true.

| # | Severity | Evidence | Scenario | Minimal fix |
| --- | --- | --- | --- | --- |
| 1 | **Critical** | `main.py:527-535`, `config.py:114-118`, `llm.py:264-283` | Repoint `base_url` → key + lecture text sent to attacker; upstream errors reflected | Pin/allow-list the destination, require a token on `PUT`, never echo upstream bodies |
| 2 | **Critical** | `main.py:126`, `run.py:15` | DNS rebinding → full API: read drafts, rewrite settings, push cards, burn credit | Host + Origin middleware, per-run token, `openapi_url=None` |
| 3 | High | `library.py:217-244`, `main.py:391-433` | Read any `.txt/.srt/.pdf` as text; UNC → NTLMv2 | Restrict imports to user-picked paths; reject UNC/device paths |
| 4 | High | `config.py:38`, `61-63`, `72-79` | Key written to disk against the user's intent | DPAPI/Credential Manager; explicit "save key" |
| 5 | High | `study.py:109-116`, `642`, `670` | Filename → script execution in the exported sheet | Escape `meta`; add a CSP meta tag |
| 6 | High | `main.py:170-175`, `store.py:337-351`, `403-413` | Spooled multipart, pre-clamp image decode, 2.5 GB pixmap | `Content-Length` pre-check, pixel caps, page-rect clamp, out-of-process parsing |
| 7 | High | `main.py:353-366`, `452-456` | Unauthenticated cost/DoS: 120 s × 2 LLM calls, 60 × 200-card sheet payloads | Rate limit, body caps, request tokens |
| 8 | Medium | `run.py:41-47` + all JSON stores | Two instances → lost drafts, `FileNotFoundError` on replace | Single-instance mutex, unique temp names, file locks |
| 9 | Medium | `library.py:89-96` etc. | `[]` in `library.json` → app won't start; corrupt object → silent wipe | `isinstance` guards, quarantine to `.corrupt-<ts>`, surface the error |
| 10 | Medium | `main.py:377-389` | Remote-triggered modal dialog, parked worker | Require a user gesture, serialize with a lock, bound the wait |
| 11 | Medium | `main.py:244-263`, `chapters.py:344-363` | Document outline (up to 18k chars) sent to the model *before* the user confirms the run | Move planning behind the confirmation, or make it opt-in |

**What is already right, and shouldn't be touched:** the key is never returned by `GET /api/settings` (only a last-4 hint); `clean_html` escapes before re-allowing a tiny tag set, so Anki fields are not injectable; tags are sanitised; JSON stores use temp+replace; OCR is local; no route deletes a user file on disk; the client builds DOM with `textContent`. The *craft* is sound — it is the boundary that is missing.

**If I had one week:** a middleware requiring a per-run random token and a `Host`/`Origin` allow-list (half a day), a destination allow-list validated with `httpx.URL` at `PUT` time plus no upstream-body echoing (half a day), escaping `meta` (five minutes), `isinstance` guards and corrupt-file quarantine (half a day), and resource ceilings (two days). That turns the score from 2 to 7.

### 3.6 Site reliability engineer — "you cannot debug what you did not record"

**My mandate:** mean time to diagnosis.

1. **Not one log statement in the backend.** No `import logging` anywhere in `app/` (verified), one `print` in `run.py`, and `access_log=False` (`run.py:80`). When a user reports "it froze at chapter 3", the only evidence on the machine is whatever the console happened to print. No request id, no correlation between a generation and a balance change, and `llm.py:368-390` discards the model's unparseable reply.
2. **Corrupt state is fatal or silent, never explicit.** A `library.json` of `[]` crashes startup (`library.py:96`); a corrupt JSON object is treated as empty and overwritten on the next save (`drafts.py:28-39`, `config.py:51-56`). Atomic replacement protects against *torn* writes, not *invalid* ones, and there is no `.bak`.
3. **A 502 taxonomy that flattens everything.** 27 `except Exception` clauses. Malformed model output, unreachable DeepSeek, an unreadable PDF, an OCR failure and a bug in `main.py` all surface as the same red toast, because handlers rewrite exceptions into `str(exc)` and the client prints them verbatim (`core.js:78-84`). Settings writes that fail on disk leave memory updated and disk stale, and return a generic 500.
4. **No version, no build id, no readiness.** Health returns `{"ok": true, "app": "anki-scribe"}` (`main.py:140-142`) while `__version__ = "0.1.0"` sits unused. It does not check that the data directory is writable, that disk has room, or that the key works — and the browser opens after a fixed wait even if startup failed (`run.py:41-47`).
5. **Crash recovery is better than it looks.** Drafts flush on `visibilitychange` and `beforeunload` via `sendBeacon` (`events.js:276-279`); auto runs are resumable by re-running. But because the run is a browser loop, closing a tab mid-run leaves half a file carded with no marker of where it stopped.

**What I'd ship in a week:** structured logs to `%LOCALAPPDATA%\AnkiScribe\anki-scribe.log` (rotating, 5 files) covering app start + version, every file opened, every generation (chars in, cards out, tokens, latency, model, retry count), every push (deck, created, duplicates, failures) and every exception with a short id shown to the user as `error ref: 7f3a`. One `.bak` per JSON store and a quarantine path for corrupt files. That turns a support ticket into a diagnosis.

### 3.7 Performance engineer — "the work that is repeated, blocking, or unbounded"

**My mandate:** find it and say which thread it runs on.

1. **Cold extraction is slow enough to look broken. [verified]** `extract_chunks` on a 120-page dense PDF took **26.2 s** cold and 0.000 s warm — `find_tables()` runs per page per extract (`store.py:798`, `502-565`). Because auto mode extracts each chapter with different ranges, the cache key (`store.py:756-763`) never hits across chapters, so the cold path is the *normal* path for a big file.
2. **Every OCR page rewrites the whole document under a global lock. [verified]** `_save_meta` serialises all pages and lines — 0.8 MB, 13.8 ms — on each page's OCR (`store.py:271-278`, `913`), inside the store lock.
3. **OCR runs inline in request handlers.** Scanned pages are OCR-ed inside `/api/extract`, page by page (`store.py:793-802`); photos inside the upload request (`store.py:414-417`). A 200-page scan is one request with 200 OCR passes and zero progress. Idle-looking servers doing minutes of work are the most common cause of "the app is broken".
4. **`coverage()` reopens the PDF and walks every page** on every call (`store.py:609-648`), and the client calls it after every generation and every auto run.
5. **Draft persistence is O(all drafts) per edit.** Every keystroke burst rewrites the entire `drafts.json` — up to 200 sources × 2,000 cards — 450 ms after typing stops (`drafts.py:41-48`).
6. **Caches are unbounded.** `_extract_cache` grows one entry per page-range/`max_chars` tuple; `_page_locks` is never cleaned when a document is deleted; page PNGs have no LRU and no delete route, up to gigabytes per document × 15 (`store.py:24-25`, `280-285`, `294-305`). `_prune` runs `rmtree` **under the global lock** and prunes by `created_at`, so a document open in the UI can vanish mid-session into 404s.
7. **Startup grows with the cache.** `Store._load` parses every `meta.json`, each containing every line of every page with four floats (`store.py:197-206`, `245-269`).
8. **Already right:** page renders are cached and double-checked under a lock (`store.py:870-897`); extract chunks are cached per parameter tuple; the client does not re-fetch lines it already has.

**Targets to hold the team to:** first page interactive < 1.5 s for a 100-page PDF; no HTTP request longer than 20 s; coverage cached and invalidated on card change; drafts written per-source; startup < 300 ms with 15 cached documents.

### 3.8 QA lead — "the irreversible path is the untested path"

**My mandate:** the tests should fail before the user does.

The suite is real: **97 tests, green in 9.0 s**, good breadth on the pure parsers (ligatures, soft hyphens, cue merging, table markdown, cloze parsing, UTF-16 transcripts, chapter normalisation), and an app factory that makes routes testable. The gaps are where the money is.

| Risk path | What actually runs | Verdict |
| --- | --- | --- |
| **AnkiConnect push / duplicates** | All 5 Anki tests monkeypatch `_invoke` (`test_anki.py:47`) | **Weak.** HTTP status, non-JSON body, `error` field and timeout in `anki.py:22-38` never execute; no fake server anywhere; `addNotes` returning `None`s, a short list or an error is untested, and `created + duplicates` can silently under-report `total` |
| **OCR fallback** | `lines_from_winocr` and `order_lines` only; a scanned-PDF test patches `app.store.ocr_lines` (`test_store.py:151`) | **Weak.** Engine dispatch (`ocr.py:169-174`), the Windows→RapidOCR fallback, `_rapidocr_lines` and `_coerce_entry` never run. `Store.create_image` — the phone-photo headline feature — is never called by any test |
| **Chapter planning** | 8 tests: TOC, subtitles→deck paths, headings, fallback, LLM proposals, gap normalisation | **Best covered.** Gaps: overlapping proposals, duplicate TOC entries, >30 leaves |
| **Study sheets** | PDF link graph, HTML escaping of cards, API contract | **Medium.** No golden files; and it missed the `meta`-line injection (§3.5.5) entirely — the one test that mattered |
| **Malformed model output** | Fenced JSON, empty cards, bad cloze, limit, 401 | **Narrow.** No truncated JSON, prose-only, wrong types, 402/429/500 mapping, or retry-then-succeed |
| **Limits and corruption** | — | **Untested:** 40 MB upload, 300-page cap, 15-document prune, 8 MB transcript, password PDFs, corrupt JSON, `[]` in `library.json`, `MAX_DRAFTS` eviction |
| **Concurrency** | One test that OCR doesn't deadlock | **One test.** No parallel uploads, renders, extracts or draft PUTs; no two-instance test |
| **Security** | — | **Zero.** No test asserts that `PUT /api/settings` cannot point at an attacker, or that the study sheet escapes a hostile filename |
| **Frontend** | — | **Zero.** 4,396 lines, no `package.json`, no runner, no config |

Three process footguns worth naming: `conftest.py:5` uses `os.environ.setdefault` + `mkdtemp` without cleanup (five orphan temp dirs on this machine, and a developer with `ANKI_SCRIBE_DATA` set silently redirects the suite); `addopts = "-q"` means `pytest -q` becomes `-qq` and **prints no pass/fail summary at all**; and there is no coverage measurement, so "how much is tested" is a guess.

**The test matrix I'd require before 1.0:**

| Area | Cases that must exist |
| --- | --- |
| Security | hostile `base_url`, missing token, `Host` mismatch, UNC import, hostile filename in a study sheet |
| Extraction | 2-column page, rotated page, scanned page OCR, oversized page, password PDF, 0-page PDF |
| Transcript | rolling captions, overlapping cues, no-timecode text, UTF-16, 10 MB file |
| Generation | truncated JSON, fenced JSON, extra prose, zero cards, 402/429/401, retry-then-succeed |
| Push | duplicates only, mixed, one failure mid-batch, missing note type, `::` in a deck name |
| Drafts | corrupt file, `[]` file, two instances, concurrent writes, prune at 200 |
| Client | push → coverage after push, undo, keyboard-only pass, 300-page scroll |

### 3.9 Architect / tech lead — "one god object, one global scope, one copy of the truth"

**My mandate:** what will hurt when this triples in size.

1. **`store.py` is 838 lines doing six jobs** — PDF parsing, line extraction, table detection, rendering, OCR orchestration, caching, chunking, coverage statistics. It is the module every feature touches and the one with the most subtle invariants: `_page_locks`, `_extract_cache`, mutation of `page.lines` inside `render_page` (`store.py:889-896`) followed by a `_save_meta` that serialises the whole document.
2. **The client has no module boundary, and the coupling is measurable.** 13 files in declared order, 176 top-level symbols, all implicit globals, zero exports. There are **54 directed file-to-file edges and 1,165 cross-file identifier references**, and Tarjan's algorithm finds **one strongly-connected component of 10 of the 13 files** — everything except `core`, `events` and `app` is mutually recursive. `events.js` alone calls 60 distinct symbols from 11 files. The README says the scripts load "in dependency order" (`README.md:283`); that describes an intention, not an enforced or acyclic structure. A missing script is silent at boot and throws only when its feature is first clicked.
3. **Two copies of the truth: the draft cards and the Anki collection.** After a push, the app's model of what it has done is gone while Anki's is permanent. Any feature that asks "have I covered this lecture?" needs a third store — a **sent ledger** — which does not exist. This is the most important structural decision left in the product, and it is also the fix for §3.1.1.
4. **No version control at all.** `git rev-parse` fails; there is no `.git`. No `LICENSE`, no `CHANGELOG`, no `.github/`, no linter config, no type checking on 4,147 fully-annotated lines that would largely pass `mypy`. For a codebase with this much care in its exception messages, the absence of history is the biggest risk to it existing in a year.
5. **No dependency pinning at the edge.** `pyproject.toml` uses lower bound ranges; `uv.lock` pins for `uv` users, but `run.bat` runs `uv sync` **without `--frozen`** (`run.bat:21`) and only when `.venv` is absent — so an install can silently re-resolve away from the lock and an existing install never picks up a fix.
6. **The long job belongs on the server.** Whole-file generation is a client `for` loop: closing the tab stops the work, two tabs can double-spend, progress dies with the page, and retrying after a partial failure regenerates everything. One `POST /api/jobs` with progress and resumption would remove a whole class of bugs — and would let OCR leave the request path at the same time.
7. **The ADR I'd record now:**

   > **Do not add a bundle step.** The no-build frontend is a feature: it is why the app starts in a second and why one person can edit it. Instead add the two things a bundler would have bought — a test runner, and a namespace convention (one global object per file, no cross-file free variables) — and keep the deploy story.

### 3.10 Support lead — "what the ticket will say"

**My mandate:** the five emails that arrive next month, and whether the product could answer them.

| Ticket (verbatim shape) | Root cause in code | Diagnosable today? |
| --- | --- | --- |
| "It said 'couldn't plan chapters' and made 400 cards in one deck called Part 1." | LLM chapter call failed → `_fallback_plan` names chapters "Part N" (`chapters.py:274-330`) | No — the failure reason lives only in the response (`main.py:262-263`) |
| "I sent 40 cards and my coverage meter went to zero." | §3.1.1, `deck.js:537-538` | No — it reads as a rendering quirk, not a design flaw |
| "It's been 'Reading chapter 2 of 9' for ten minutes." | 26 s cold extraction + inline OCR (`store.py:794-798`) | No — no per-page timing, no request log |
| "The app won't start any more." | `[]` in `library.json` → `AttributeError` (`library.py:96`) | No — there is no log, and nothing names the file |
| "My DeepSeek key stopped working / I was charged for cards I didn't make." | §3.5.1, `base_url` rewrite | **Never** — nothing records the destination of a request |
| "The same cards came twice in two decks." | `duplicateScope: "deck"` (`anki.py:111`) + a new deck per chapter | Insight needed; not discoverable from the UI |

The support *content* that exists is good: `CONNECTION_HINT` names the add-on and its code (`anki.py:12-15`), and the README troubleshooting table is honest and specific (`README.md:216-235`). The gap is that every diagnosis requires the user to be a developer.

**What I'd build for myself:** a **Diagnostics** button that writes a redacted bundle — version, settings without the key, last 200 log lines, document list with sizes, last generation summary — to a zip the user can attach.

### 3.11 Cost controller — "the meter runs while nobody is looking"

**My mandate:** what does one lecture cost, and can the user see it coming?

1. **Token usage is thrown away.** `_chat` reads `choices[0].message.content` and ignores `usage` entirely; `finish_reason` is never checked (`llm.py:296-303`). The app cannot say what a run cost, cannot detect a truncated response (which presents as "unusable cards" and triggers a *second* full-price call), and cannot warn before a 300-page run.
2. **A failed parse silently doubles the bill.** `generate_cards` retries by re-sending the whole conversation plus the failed turn (`llm.py:369-390`). After a truncation the retry usually truncates again — paying twice for the same failure.
3. **The credit pill is the wrong instrument.** Balance is account-level and whole-app: useful as a smoke alarm, useless as a budget, because 12 cards from page 4 and a 300-page run look identical until after the fact.
4. **The cheapest lever is unused.** Chapter planning and card generation share one model (`config.py:15`). Planning is a routing task a much cheaper tier handles.
5. **Nothing is cached between runs.** Auto mode's recovery advice is "run the file again", which re-generates every chapter — a 90 %-complete run costs 100 % a second time.
6. **There is no rate limit or request budget,** so a stuck client loop or a hostile page (§3.5.2) can spend the balance without the owner present.

**Estimate to hold in your head:** a 3,500-character section plus a ~700-token system prompt is roughly 1.5–2 k input and 0.8–1.5 k output tokens for ~10–25 cards. A 300-page file at ~4.5 pages/section is ~65 sections ≈ 130 k input / 80 k output per complete run, doubled on a retry. Cheap in absolute terms — which is exactly why it should be *shown* rather than feared: "This file will use about 130 k input tokens. Continue?"

### 3.12 Legal & compliance — "the four documents that don't exist"

**My mandate:** what happens when this leaves one person's laptop.

1. **PyMuPDF is AGPL-3.0-or-commercial. [verified]** The installed metadata reads *"Dual Licensed - GNU AFFERO GPL 3.0 or Artifex Commercial License"* (pymupdf 2.1). Distributing a bundled binary under AGPL obliges source availability for the combined work, or a commercial licence from Artifex. This is not a code problem and not fixable by adding a LICENSE file — it gates every distribution plan in §3.13 and should be decided before more engineering, not after.
2. **No LICENSE.** All rights reserved by default: nobody may legally copy, fork or contribute, and "open source" cannot be claimed.
3. **No terms, no privacy notice, no disclaimer.** Three regulated-adjacent things are in play: a credential, third-party copyrighted text sent to a model vendor, and possibly patient-identifiable content in photographed notes. Three paragraphs — data flow, key storage, "generated cards can be wrong — verify against the source", "no medical advice" — are the minimum. The README's privacy section is accurate, but it is a *description*, not a *commitment*.
4. **Medical-content liability is unmitigated in the product itself.** Spaced repetition installs errors; a hallucinated card is worse than a missing one. Surfacing the evidence quote *inside the Anki card* is both a learning feature and a liability control, because it makes every card self-verifying at review time.
5. **Embedded assets.** The study PDF reads and embeds a Windows system font (`study.py:131-152`, `481-490`); redistribution terms deserve a check alongside the AGPL decision.

### 3.13 Release engineer — "there is no version 1.0, there is a checkout"

**My mandate:** can a stranger run this on Tuesday.

1. **The install is a developer install.** `run.bat` requires `uv` on `PATH`, downloads a toolchain, and prints terminal instructions on failure. A second-year med student will not do this and cannot debug it — the README's own troubleshooting already contains an `icacls` incantation for sandboxed folders (`README.md:235`), a sentence no user should ever read.
2. **Windows-only by construction.** `winocr` is imported by hard path (`ocr.py:114`), the OCR language is hardcoded `"en"` (`ocr.py:120`), and there is no Linux/macOS story (RapidOCR alone would make it portable — a product decision, not a port).
3. **No packaging, no update path, no migration.** `pyproject.toml` has no `[build-system]` and `[tool.uv] package = false`, so the app cannot even `pip install`; distribution is "copy the folder, double-click". No version check, no updater, and no `drafts.json`/`library.json`/`meta.json` schema migration, so the first schema change silently breaks the second cohort.
4. **No crash reporting and no funnel.** There is no way to learn that 40 % of users stop at the API-key screen. Every roadmap decision is currently a guess dressed as judgement.
5. **The honest version of "1.0"** — one signed `.exe` that bundles Python, the locked dependencies and the model client, opens the browser tab, stores data in `%LOCALAPPDATA%`, checks for updates, and asks for the key in a wizard with a "test key" button. Roughly 3–5 days with PyInstaller, and worth more than any feature in §5.2.

**Estimates:** a *minimum credible* 1.0 — git, licence decision, CI, honest tests on the risky seams, logging, signed installer, update path — is **15–20 developer-days**. A fully defensible 1.0 is **35–45 developer-days (7–9 weeks solo)**, plus a stranger beta.

---

## 4. Mental models that reframe this

Ten lenses, each ending in a decision rather than an observation.

**1. Theory of constraints — the bottleneck moved and the UI didn't.** Generation is no longer scarce: one call yields 10–25 cards in seconds. The scarce resource is attention during acceptance. Speeding up generation by 10 % is worth nothing; making 30 cards triageable in two minutes is worth a lot. **Decision:** build review mode for triage — `j/k/a/r/x`, accept-all-above-confidence, duplicate clusters, and a "most likely to be wrong" sort keyed on failed evidence checks and cloze length.

**2. Jobs-to-be-done — the hire is "lecture → reviewable", not "write me cards".** The product hires well at the start of that job and quits at 80 %. **Decision:** instrument the job, not the features. The number to move is *time from file-open to cards-in-Anki*, plus the completion rate of that journey.

**3. Kano — you are competing on must-be's while shipping delighters.** Source highlighting, coverage and the study sheet are genuinely distinctive. The must-be's are unglamorous and failing: no undo, an install nobody can do, a meter that resets on success, a transcript parser that breaks on the most common caption format, a settings endpoint that will hand your key to whoever asks. **Decision:** freeze new delighters for one release and clear the must-be debt.

**4. Inversion (pre-mortem) — it is twelve months later and nobody uses it.** Most likely causes, in order: (a) the install defeated them; (b) the first auto run dumped 600 mediocre cards into their collection and they never trusted it again; (c) AnkiConnect broke and the app blamed them; (d) the vendor's pricing or API changed; (e) a card was wrong once and repetition made them *confidently* wrong. **Decision:** each is a gate on 1.0, not a line in a risk register.

**5. Second-order effects — automating the study act deletes the study.** First order: cards in 30 seconds. Second order: no encoding from writing them, a deck they didn't build, interference between near-identical auto-cards, deck bloat → leeches → distrust → back to re-reading. **Decision:** keep one act of effort per card — "type the answer, then reveal" in the study sheet, or "AI proposes, you ratify with a keystroke" in review.

**6. Goodhart's law — the coverage meter is a proxy, and it will be gamed.** Coverage counts pages with at least one card (`coverage.js:81-93`), and auto cards carry a whole chunk's page range (`auto.js:289-293`) so `cardSourceUnits` credits several pages per card (`coverage.js:41-49`). "87 %" means "87 % of pages were touched by a chunk", not "87 % of facts are covered" — while the prompt pushes the model toward 25 cards per section. **Decision:** report two numbers instead of one — *facts with verified evidence*, and *pages with figures that were never carded*. The second is the honest gap in a med-school workflow, and nobody measures it.

**7. Closed-loop control — the system has no feedback term.** The app generates, pushes, and never learns. Anki knows everything it needs: `cardReviews`, lapses, ease. A closed loop: tag pushed cards → two weeks later read the lapses → "these 8 cards from Lecture 3 keep failing, regenerate them with a contrast prompt" → the generator improves on *this student's* data. No competitor has it, it uses only AnkiConnect, and it is the natural moat once generation is a commodity. **Decision:** put the tag and the ledger in now; the loop is a Later, but it is the Later that matters.

**8. Cynefin — this is complex, and the app is built as if it were complicated.** Card quality cannot be known until a student reviews it three weeks later; the app treats every step as a deterministic process with a rule. **Decision:** add a safe-to-fail feedback channel — a one-tap "this one confused me" *after* the card is in Anki — that flows into the ledger. Probe, sense, respond, instead of more prompt rules.

**9. Chesterton's fence, inverted — the README is a code smell you can read.** 283 lines of documentation for a five-step flow, including an `icacls` entry for a sandboxed-folder bug and a paragraph explaining why drag-and-drop doesn't work. Documentation that exists to explain a workaround is a design defect wearing a costume. **Decision:** every time a README paragraph is added, ask whether the paragraph is cheaper than the fix.

**10. Loss aversion — deletion costs twice what creation earns.** The `×` is one click and irreversible; "Clear all" is one native confirm away from wiping a session. The entire value proposition is *not retyping*. **Decision:** an undo stack (last 20 operations, persisted with drafts) is not a nice-to-have; it is the cheapest available trust.

---

## 5. The plan

### 5.1 Now — fourteen changes, roughly two weeks

Ordered by (impact ÷ effort). Every one is small and independently shippable.

| # | Change | Why | Where | Effort |
| --- | --- | --- | --- | --- |
| 1 | **Escape the study-sheet meta line** | A hostile filename becomes script execution in an offline file | `study.py:642`, `670` | 5 min |
| 2 | **`isinstance` guards + corrupt-file quarantine** (`.corrupt-<ts>`, one `.bak`, surface the error) | `[]` in `library.json` currently stops the app from starting | `library.py:89-96`, others | 4 h |
| 3 | **Per-run API token + `Host`/`Origin` middleware + `openapi_url=None`** | Closes rebinding and the remote dialog trigger | `main.py:120-130`, `run.py` | half d |
| 4 | **Allow-list the model destination**; never echo upstream bodies | The demonstrated key-exfiltration chain | `config.py:114-118`, `llm.py:264-283` | half d |
| 5 | **`git init` + `LICENSE` + CI** running `pytest`, `ruff`, `mypy` | There is no history of this codebase, and the suite runs in 9 s | repo | 3 h |
| 6 | **Decide the PyMuPDF licence** and add `THIRD-PARTY-NOTICES` | Gates every distribution plan | `pyproject.toml` | 1 d + legal |
| 7 | **Verify the evidence quote** — drop or re-ask cards whose `evidence` is not in the excerpt | The only thing between the student and a permanently installed false fact | `llm.py:136-176` | 2 h |
| 8 | **Keep a sent ledger** so coverage and highlights survive a push and a reopen | Fixes the "meter resets on success" reward bug; makes the source map permanent | `deck.js:537`, `drafts.js`, `coverage.js:81` | 1 d |
| 9 | **`Source`, `Page`, `Quote` in the note** via an `Anki Scribe` note type with a `Basic` fallback | Provenance is the best asset and dies at the boundary | `anki.py:89-112` | 4 h |
| 10 | **Fix U1** — capture doc id and selection *before* the await; discard on mismatch | Silent cross-document data loss on the primary flow | `cards.js:43-60` | 1 h |
| 11 | **Fix rolling-caption merging** — prefix/suffix splice | The most common subtitle format produces triplicated text | `transcript.py:85-100` | 2 h |
| 12 | **Fix two-column reading order** — reuse the existing gutter detection | Textbook pages are interleaved before the model sees them | `store.py:568-577` | half d |
| 13 | **Undo** for card removal and Clear all | Cheapest available trust; deletion is final | `events.js:164-223` | 4 h |
| 14 | **Logging + `error ref` + a11y pass** | Turns a support ticket into a lookup; fixes measured exclusions | `styles.css:8`, `index.html`, new module | 2.5 d |

### 5.2 Next — six bets, one to two months

| Bet | What | Why now |
| --- | --- | --- |
| **A. Distribution** | PyInstaller build, first-run wizard (key → test → balance → first file), update check | The funnel is the binding constraint on everything else (§3.13) |
| **B. Server-side jobs** | `POST /api/jobs` + progress + resumable whole-file runs; OCR off the request path | Removes the 26 s-and-growing request class and lets runs survive a closed tab (§3.7, §3.9.6) |
| **C. Triage-grade review** | Keyboard-first accept/reject, confidence sort, duplicate clusters, batch tag/deck edits | Attacks the real bottleneck (§4.1) |
| **D. Image cards** | Region select on a figure → occlusion card; or "explain this diagram" → Q/A with the figure | The highest-yield content in med school is unreachable (§3.2) |
| **E. Budgets, not balances** | Read `usage`, show cost before and after, a per-file cap, cheaper tier for planning, a request budget | Turns the anxiety pill into a tool and closes an abuse path (§3.11) |
| **F. A cards-per-day governor** | Estimate implied new cards/day from the deck tree; recommend flat deck + tags; warn above 50 | Prevents the tool from manufacturing overload (§3.2.5) |

### 5.3 Later — the two that decide the category

1. **The closed loop** (§4.7): tag → read back lapses → regenerate the failures. The first feature that gets *better* the longer it is used, and not copyable by a prompt-only competitor.
2. **Make verification the product, not the prompt.** A card that shows its source sentence, a click to the page, a confidence score, and a one-key "this is wrong" that teaches the ledger. The differentiator is not "AI writes cards" — it is "these cards are trustworthy and traceable", which is exactly what a student cannot get from a chat window.

### 5.4 Stop doing

- **Stop shipping a settings endpoint without caller identity.** It is the single highest-leverage fix in the repo.
- **Stop deleting the evidence at the finish line.** Until #8 ships, warn in the UI.
- **Stop defaulting to a subdeck per chapter.** (§3.2.5)
- **Stop silently resetting corrupt JSON** without a message. (§3.6.2)
- **Stop growing the README to explain workarounds.** Fix the workaround.
- **Do not add a frontend framework or a build step** until a test runner exists (§3.9.7).
- **Do not add providers, modes or card types** before the review path is durable.

---

## 6. What I could not verify

- **Real generation quality.** No API key was used and no DeepSeek call was made. Prompt-level conclusions come from reading the prompts, the validation code and the client wiring. The three-tier card example in §3.2 is labelled as constructed.
- **AnkiConnect against a real collection** — note-type availability, duplicate scoping across subdecks, `addNotes` partial-failure semantics. The `duplicateScope: "deck"` claim follows AnkiConnect's documented semantics and the call site (`anki.py:111`), not an experiment.
- **OCR accuracy on real photos.** `winocr` was never exercised. The two-column *PDF* interleaving was reproduced; the OCR gutter heuristic was only read.
- **Windows-only paths** (`picker.py`, `run.bat`, the `icacls` failure mode) were read, not run — except that a `/api/library/pick` probe did open a native dialog, which was closed.
- **Coverage instrumentation.** None exists, so "how much is tested" beyond the per-path table in §3.8 is unquantified.

---

## Appendix A — the reproduced defects

**A.1 Two-column interleaving** (`store.py:568-577`). One-page PDF, four left and four right lines at identical baselines, through the real `extract_pdf_lines` and `Store._compose_page`:

```
raw   : ['LEFT alpha', 'RIGHT one', 'LEFT beta', 'RIGHT two', 'LEFT gamma', 'RIGHT three', 'LEFT delta', 'RIGHT four']
composed:
LEFT alpha
RIGHT one
LEFT beta
RIGHT two
LEFT gamma
RIGHT three
LEFT delta
RIGHT four
```

**A.2 Rolling-caption accumulation** (`transcript.py:85-100`). Four consecutive YouTube-style cues through the real `parse_transcript`:

```
0 'the heart is the heart is a pump the heart is a pump that moves blood that moves blood to the lungs'
```

**A.3 Study-sheet injection** (`study.py:109-116`, `642`, `670`). `build_html` with `source='<img src=x onerror="alert(1)">'` and `generated='<script>alert(2)</script>'` emitted:

```
<p class="meta"><img src=x onerror="alert(1)">  ·  1 card  ·  <script>alert(2)</script></p>
```

Cards are escaped; the meta line is not.

**A.4 Corrupt `library.json` prevents startup** (`library.py:96`). A file containing `[]`:

```
AttributeError: 'list' object has no attribute 'get'
```

**A.5 Push resets coverage and highlighting** (`deck.js:537-538` → `coverage.js:81-93`, `drafts.js:173-203`). Read from code, not executed: pushed cards are removed from `state.cards`, and every coverage figure, source highlight and persisted draft derives from `state.cards`, so the meter falls to "No cards yet" at the moment of success. A Playwright test would confirm it in five lines — which is itself the point.

A.1–A.4 were run against the project's own `.venv`; A.5 is a code-path argument. No source file was modified.

## Appendix B — the numbers

| | |
| --- | --- |
| Backend | 4,147 lines, 12 modules, 32 routes |
| Frontend | 4,396 lines JS (13 files, no build), 2,016 CSS, 500 HTML, 176 globals, 141 DOM ids |
| Client coupling | 54 directed file edges, 1,165 cross-file references, one 10-of-13-file dependency cycle |
| Tests | 1,783 lines, **97 tests passing in 9.0 s**; 0 lines covering JS |
| Largest module | `store.py`, 838 lines |
| Error handling | 27 `except Exception`, 0 logging statements |
| Runtime | Python 3.12, FastAPI 0.162.6, Starlette 1.10.0, httpx 0.28.1, PyMuPDF 2.1, pytest 9.2.0 |
| Licence posture | PyMuPDF AGPL-3.0-or-commercial; no project LICENSE |
| Distribution | Windows + Anki + AnkiConnect + funded DeepSeek key + `uv` |
| Version control | none |
| Effort to a defensible 1.0 | 35–45 developer-days, plus a stranger beta |
