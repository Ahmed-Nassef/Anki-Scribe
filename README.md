> Tracking repository for the Anki Scribe learning system: card generation,
> hidden-answer study view, automatic OCR, FSRS-6 planning across files,
> persistent batch jobs, Anki review history, focus mode and graded study
> sessions with analytics.

# Anki Scribe

Select text on a lecture PDF, a photo of your notes, an EPUB book, or a video
transcript. DeepSeek turns it into question/answer or cloze cards. Review them,
then send them straight to Anki.

Built for med school: no retyping answers, no writing questions by hand.

## What it does

- **PDFs** keep their real text layer, so selection is crisp even at high zoom.
- **EPUB books** open with their own chapters, reading order and table of
  contents. The book is laid out as pages at import, so selection, highlights,
  chapters and objectives work exactly as they do on a PDF — and a textbook is
  read chapter by chapter instead of being asked for whole.
- **Big files are not turned away**: a PDF of up to 1,500 pages opens like any
  lecture, and a 40 MB ceiling is now 200 MB, because a textbook is not a
  handout.
- **PowerPoint decks** open directly. Each slide is laid out as a page — text in
  its own position, tables as text, pictures embedded — so selection, chapters,
  objectives and figure cards all work on lectures you never exported to PDF.
  This is a faithful reading of the deck, not a rendering of it: fonts and
  precise placement may differ from PowerPoint.
- **Photos of textbook pages** are read locally with Windows OCR (fast,
  offline), with RapidOCR as a fallback if the Windows language pack is
  missing.
- **Scanned PDFs are OCR'd automatically** — every image-only page is read in
  the background as soon as the file is uploaded or opened, not just the page
  you happen to be looking at. A progress strip above the pages shows how many
  are done; **Stop** pauses the run and **Retry** resumes the remaining pages.
  The extracted lines are saved in the document's metadata, so reopening the
  file does not OCR it again.
- **Subtitles and transcripts**: open `.srt`, `.vtt`, `.txt` or `.md` files as a
  readable cue list. Select a passage or click a timestamp, and card sources use
  the timestamp instead of a page number.
- **DeepSeek** writes atomic, exam-focused cards from the selected passage.
- **Live AI credit**: the header shows your DeepSeek account balance; click it to
  refresh, and it updates after each generation. Settings shows the same balance
  with granted and topped-up amounts.
- **Auto from whole file** reads every page's text **and detected tables**,
  generates cards section by section with live progress, and skips duplicates
  across sections. **Batch** does the same for several library files in one
  queue: tick the files, choose Q&A or Cloze, and it opens, generates and saves
  each one in turn.
- **Chapter-aware generation**: for long PDFs, EPUB books and transcripts, Anki
  Scribe finds chapters from the table of contents/bookmarks, headings, or a
  model-planned outline, then generates one chapter at a time instead of asking
  for the whole file at once.
- **Chapters on disk**: **Save chapters** writes the same split the model gets —
  one Markdown file per chapter plus a `manifest.json` — so a book can also be
  fed to any LLM outside Anki Scribe.
- **Source deck hierarchy**: every source gets its own subtree. Cards go under
  the parent deck, then the source title, then the chapter/subtitle:
  `Anki Scribe::Cardiology Lecture::Chapter 3::Beta Blockers`.
- **Coverage check**: Review shows how much of the file's text is covered by
  cards, and flags pages with images or very little text so you can check the
  original figures.
- **Draft persistence and source map**: cards, edits, selected state and deck
  paths are saved per source file. Reopen the file and the drafts come back,
  with teal highlights on text that already has a card, so gaps are visible.
- **Path-based library**: remember files by their real location, without copying
  them. Group them, drag files between groups, search, and reopen them later.
- **Review before Anki**: edit any question, answer, extra note or tag, and
  deselect cards you don't want. Every card shows its page or timestamp and a
  short source quote; click the pill to jump to the source. **Triage** does the
  same job one card at a time, with the source quote beside the question and the
  answer hidden, so you are deciding rather than reading.
- **Study sheets**: quiz yourself with the answers hidden. **Study** shows one
  card at a time — chapter and question first, answer on click (or Space).
  **Save PDF** and **Save HTML** export the same ticked cards, grouped under
  their chapters, with every answer hidden until you ask for it.
- **Hide answers on the page itself**: the PDF viewer masks the answer text of
  every ticked card where it actually appears. The slide's title, tables,
  numbering and bullet structure stay visible; click a blank to reveal it, and
  click the revealed text again to hide it. Blanks are **coloured by the card's
  LLM-assigned type** — dates, doses, numbers, procedures, definitions,
  mechanisms, comparisons, lists, applications and plain facts — with a legend
  above the pages. **AI fill** asks DeepSeek for exact page quotes for the few
  cards the local matcher missed; it is one extra click, not a replacement for
  the automatic masks. You can also select any text and press **Hide
  selection** to add your own blank.
- **Focused study mode**: press **Study mode** in the page toolbar or **F**.
  The side panel, toolbar, pager and legends disappear; the pages fill the
  screen with a small HUD. **Space** reveals or hides all answers, **R/H**
  reveal/hide, **Right/PageDown** and **Left/PageUp** move a page, **?** shows
  the shortcuts, and **Esc** leaves. Clicking a blank still reveals it, and
  clicking the revealed text hides it again. In study mode a revealed answer
  keeps a faint tint instead of the cover vanishing, so the blank is still
  findable; the page itself uses plain, solid covers in this mode.
- **Study cards**: active recall, not just text hiding. Open **Study** above the
  review list or **Quiz** in the study HUD to get one card at a time. Reveal the
  answer, grade it **Again / Hard / Good / Easy** (`1`–`4`), and the next card
  appears. Grades update a server-side due date and interval per card; due cards are
  shown first, then new ones. The header tracks session time, recall percentage
  and streak; the end screen shows the grade mix and time, and **Stats** keeps
  lifetime sessions, days studied, retention and due/new counts.
- **Study plan**: give it an exam date, the number of study items you need to
  learn and the hours you can study each day, or select several Library files
  and press **Plan selected**. It counts Q&A cards, every distinct cloze
  deletion, figure cards and answers you hid by hand. It builds a day-by-day
  **FSRS-6** schedule — new items, reviews due, time per day, and an
  hour-by-hour breakdown when you want one — and tells you up front whether the
  deadline is realistic. **Copy plan** gives you a Markdown table.
- **Deck control**: the field at the bottom is the **parent deck**. **Browse**
  opens a location chooser with your existing deck tree, an optional existing
  child subdeck, and a free-text path such as `medicine::lecture::optional`.
  You can also send cards directly to the chosen deck instead of adding
  source/chapter subdecks. **+ New subdeck** creates one; the pencil renames the
  current deck in Anki.
- **AnkiConnect** creates the deck if needed and adds the cards directly.
- **Triage**: one card at a time with its quote beside it and the answer hidden.
  **Space** reveals, **A** accepts, **X** rejects, **J**/**K** move, **U** undoes.
  Cards whose quote could not be verified are shown first, because they are the
  ones most likely to be wrong.
- **Sent history**: every pushed card is remembered with its Anki note id, so
  coverage and the teal highlights survive a push. Reopen a lecture and you see
  what is already done instead of a blank slate.
- **Library progress**: each library row shows how much work a file holds —
  "42 in Anki · 3 drafts" — without opening it.
- **Card styles:** *Balanced*, *Mechanism*, *Clinical vignette*, *Tables & lists*
  and *Exam trap* change what the model optimises for — a mechanism card, a short
  patient scenario, one row per card, or a card that names the confusable
  alternative. The choice applies to manual and whole-file generation and is
  remembered between sessions.
- **Card types and a quality gate**: every card is labelled with what it
  tests — *definition*, *mechanism*, *compare*, *application*,
  *enumeration* or *number* — and the review header shows the mix, so a deck
  that is all definitions is visible at a glance. Each card is also checked
  locally for the defects that make a card unusable: an answer that is already
  in the question, a question that asks for an essay, an overloaded cloze, or a
  list masquerading as one fact. The blocking ones stop a push until you fix
  the card or explicitly send it anyway.
- **Figure cards**: click **Figure** in the page toolbar and drag a box over a
  diagram, a table or a label. Anki Scribe cuts the figure out around your box,
  covers the part you selected, and makes a card from the pair — so the answer
  is a picture, not a sentence. Both images travel to Anki as media, which means
  the card works on desktop and on mobile with no add-on installed. If the label
  is real text in the PDF, the answer is filled in for you; if it isn't, type it.
- **A picture on any card**: every card has **Add picture** — crop a region of
  the page you are looking at, or upload a PNG/JPG/WEBP. A **Show on front**
  tick decides whether the picture is the prompt or part of the answer, and
  **Replace** changes it later. It travels to Anki as media the same way a
  figure does. Tables are usually better captured this way than read as text —
  a cropped table keeps its rows and columns exactly.
- **Formulas** are cleaned up before they reach the model. A text layer hands
  over `𝐴`, `𝝁`, `²` where the page printed *A*, *μ*, *²*; Anki Scribe folds
  those back to letters, writes superscripts and subscripts as `^{…}`/`_{…}`,
  and sends a line the page set as a formula as `$…$` with Greek and operators
  as LaTeX (`$CO = HR \times SV$`). A sentence that merely mentions σ stays
  prose instead of being mistaken for an equation.
- **Objective coverage**: if the lecture states its learning objectives, Anki
  Scribe finds them and shows a checklist — **4 / 7 covered** — with a
  **generate** button on each one still missing. Coverage stops being a page
  count and becomes the syllabus the exam is built from.
- **Rewrite a card**: in triage, rewrite the card on screen as sharper, simpler,
  clinical, shorter, or as a cloze deletion — always from the quote it was built
  on, so the rewrite cannot wander outside the source. **Ctrl+Z** puts the old
  card back.
- **Cards you can check**: each card's evidence quote is verified against the
  source text. A card whose quote cannot be found is marked **check**, and a
  local ranking (unverified quote, vague question, long deletion, near-duplicate,
  no tags) drives a **"N to check"** chip. Tick *Only keep cards that quote the
  source* to drop unverifiable cards instead of flagging them.
- **Duplicate preflight**: before sending, Anki Scribe asks Anki which cards it
  already has, then lets you send only the new ones.
- **Undo**: removing a card, clearing a batch or unticking one is reversible
  with **Ctrl+Z** (**Ctrl+Shift+Z** to redo).
- **Provenance in Anki**: cards are written to `Anki Scribe Basic` / `Anki Scribe
  Cloze` note types with `Source`, `Page`, `Quote` and `QuestionId` fields, and
  fall back to the stock `Basic`/`Cloze` types if your collection cannot create
  note types. Either way the deck, the lecture and the sentence travel with the
  card.
- **Basic** and **Cloze** modes, with duplicate protection inside the deck.

## Requirements

- Windows 10/11.
- [Anki desktop](https://apps.ankiweb.net/) with the **AnkiConnect** add-on
  (code `2055492159`).
- A DeepSeek API key (or any OpenAI-compatible chat endpoint).
- [uv](https://docs.astral.sh/uv/) — the run script uses it to install Python
  dependencies on first launch.
- An English OCR language pack for Windows (standard on English installs;
  RapidOCR takes over if it's absent).

## Run it

Double-click **`run.bat`**.

The first launch downloads the Python dependencies (a minute or two). After
that, Anki Scribe opens at <http://127.0.0.1:8777> in your default browser.
Keep the console window open while you use it; close it to stop.

From a terminal:

```bat
uv sync
.venv\Scripts\python.exe run.py
```

Anki Scribe binds to `127.0.0.1` only and is not reachable from other computers.

## First-time setup

1. **AnkiConnect.** Open Anki → *Tools → Add-ons → Get Add-ons…* → enter
   `2055492159` → restart Anki. Leave Anki running while you use the app.
2. **DeepSeek key.** Click the gear icon, paste your key from
   [platform.deepseek.com/api_keys](https://platform.deepseek.com/api_keys),
   and save. The status pill in the header should turn green once Anki is
   reachable.
3. **Make cards.** Click **Open file** (or **Library → Add files**), choose a
   PDF, EPUB book, slide deck, image, subtitle or transcript file. Either drag
   across one passage and click **Generate cards**, or click **Auto from whole
   file** to process every page/table or transcript section. Review the drafts,
   choose the deck, and click **Send to Anki**.

## Using it well

- **Library:** files are remembered by their location, not copied. **Add
  files** opens a native file picker; **New group** creates a group; drag the
  dotted grip on a file row onto a group to move it (or use the group dropdown).
  **Library → Add path** accepts a pasted path if the file dialog doesn't open.
  Removing a file from the library never deletes it from disk.
- **Dragging from Explorer:** Windows browsers often don't expose the original
  path of an external dragged file. If the path is available, it is imported
  into the group; otherwise Anki Scribe shows a clear notice and keeps the
  location-only options (**Add files** / **Add path**) available.
- **Missing files:** if a file is moved or renamed outside the app, its row
  shows **Missing**. Put it back, or remove it and add it again from its new
  location.
- **Batch files:** open **Library**, tick several files, then press **Generate
  selected**. The batch runs on the server, not in the browser tab: it opens
  each file, extracts it into sections, generates cards, merges them into that
  file's drafts, and writes progress to `batch_jobs.json`. You can close the tab
  or restart the app; the job resumes on the next start. The progress panel says
  which file is running and the final summary counts cards and failures.
  **Send to Anki** is ticked by default: as each file finishes, its fresh cards
  are pushed to the current deck, duplicates are reported, and blocked cards
  stay in that file's drafts for fixing. Untick it to review everything first.
  **Select all** picks every available file; missing files are disabled. Stop
  cancels the current job, and cards already generated are kept. This is the
  expensive route: one DeepSeek run per file.
- **Plan several files:** tick the files and press **Plan selected** instead.
  The plan modal counts drafts, pushed cards, clozes and manual hides in every
  selected file, then builds one combined schedule. The same modal is available
  as **Study plan** above Review for the file you have open.
- **Large files:** *Auto from whole file* first plans chapters, then generates
  one chapter at a time. It prefers the PDF/EPUB table of contents, then clear
  headings, then a compact model-planned outline. If no structure is found, it
  falls back to manageable parts. You see the chapter list before generation and
  can stop at any point. A long file uses more DeepSeek credits.
- **Books:** drop an `.epub` on **Open file** or add it from the Library. Anki
  Scribe reads its spine in reading order, lays the text out as pages, and uses
  the book's own contents as the chapter list, so decks become
  `Parent::Book title::Chapter 3`. Fonts, colours and pictures are not
  reproduced — the page is the book's text, which is what selection, highlights
  and cards need. A 600-page book imports in a few seconds and is cached; a
  1,000-page PDF goes through the same chapter plan. Fixed-layout EPUBs, comics
  and scans have no text layer: export those to PDF, where OCR reads them page
  by page.
- **Big batches stay light:** a whole-book run can produce a thousand cards, so
  the review list builds only the cards near what you are looking at (about
  eighty at most) and the page viewer drops page images once they are well
  outside the viewport. A 1,000-card run stays at a few thousand DOM nodes
  instead of seventy thousand, and scrolling a long book does not keep every
  page's picture decoded in memory.
- **Save chapters:** the button under *Auto from whole file* writes the chapter
  split to `%LOCALAPPDATA%\AnkiScribe\splits\<book>\` — `01 - Chapter One.md`,
  `02 - …`, plus `manifest.json` with the title, page range, size and order of
  every file. Each file starts with a short YAML block (book, chapter, title,
  pages) and keeps `--- Page N ---` markers, so another tool — or another LLM —
  can pick up a chapter without the app. **Open folder** shows it in Explorer.
  The folder is rewritten when you split the same book again, so stale chapters
  do not linger.
- **Whole file:** each chapter is sent in section-sized chunks (about 3,500
  characters for PDFs, 6,000 for transcripts), including tables converted to
  Markdown. Each section can yield up to 25 cards; a failed section is reported
  and skipped so the rest of the file still runs. Cards already generated are
  kept if you stop.
- **Tables:** tables with ruled borders in PDFs are detected and passed to the
  model as Markdown rows, so it can make cards from the column relationships.
  Borderless tables and photos of tables are still read as text, but the
  structure may be less exact. Detection is a half-second layout pass per page,
  so it runs for files up to 250 pages; a longer book keeps its table text in
  reading order without the Markdown grid. When a card depends on a table, the
  reliable route is **Add picture → Crop from this page**: the crop keeps every
  row and column as an image the card can be graded against.
- **Formulas:** a line the page set as a formula is marked `$…$` and its Greek
  letters and operators become LaTeX (`\sigma`, `\times`, `10^{-6}`); math
  letters that came through as `𝐴`/`𝝁` are folded back to `A`/`μ`. A stacked
  fraction is still extracted in reading order across its lines, so a formula
  that matters for the card can also be cropped as a picture.
- **Deck tree:** the bottom field is the **parent deck**. Auto-generated cards
  are placed under `Parent::Source title::Chapter` (and `::Subtitle` when the
  contents provide one). Manual cards go under `Parent::Source title`, or the
  matching chapter when a chapter plan is already loaded. Every card shows its
  deck under the source quote, and **Send to Anki** creates/sends to all needed
  decks. **Browse** lets you pick any existing location, optionally add one of
  its existing children (for example `medicine::lecture::optional`), or type a
  new path. Tick **Send cards directly here** to skip the automatic source and
  chapter subdecks.
- **Source location:** every draft card shows its page or timestamp pill and the
  passage it came from. Click the pill to jump back and highlight the source
  lines or transcript segment. Manual selections are located exactly;
  whole-file cards use the quote the model returns, falling back to the section
  range.
- **Objectives:** a lecture that opens with "Learning objectives" gets a
  checklist above Review. It is detected on the page (or slide, or transcript
  segment), so nothing is sent anywhere to build it, and the ticks are estimated
  from the cards you already have — the estimate is deliberately forgiving.
  **generate** on a missing one writes cards from that page only.
- **Figure cards:** click **Figure** (it stays on until you click it again), drag
  a box, and a draft card appears with the masked figure, the uncovered version
  and the label Anki Scribe found in that area. Edit the question or answer like
  any other card, then send. Figures need a PDF page; photos and transcripts
  don't produce them. The images are stored in the document cache and uploaded
  to Anki the first time you send a card that uses them.
- **Pictures on a card:** **Add picture** on any card offers **Crop from this
  page** — the page you are looking at gets a crosshair, drag a box, **Esc**
  cancels — or **Upload a file** for a PNG/JPG/WEBP you already have. The
  picture sits in the card with a **Show on front** tick: front for "identify
  this", back for "explain this". **Replace** swaps it, **Remove picture** drops
  it. Like figures, the file stays in the document cache until you send the card,
  then it is uploaded to Anki as media.
- **Click a highlight:** the teal lines are links back to their cards. Click one
  and the review panel scrolls to the card and flashes it; if several cards quote
  that line, clicking again cycles through them. Drag or select the text and the
  click is ignored, so selecting a highlighted passage still works.
- **Triage:** click **Triage 40** above the card list. You get one card at a
  time, its source quote on the left and the answer hidden; **Space** reveals,
  **A** keeps the card, **X** drops it, **J**/**K** move without deciding, **U**
  undoes the last decision, **Shift+A**/**Shift+X** sweep the rest, **Esc**
  leaves. The worst cards come first — the ranking puts an unverified quote at
  the top, then a vague question, a long cloze deletion, a near-duplicate of
  another card, or a missing tag. Click **N to check** to triage only those.
  It is the same tick state as the review list, so the two always agree.
- **Drafts:** cards, edits, selected state and deck paths are saved per source
  file under `%LOCALAPPDATA%\AnkiScribe\drafts.json`. Reopening or restarting the
  app restores them automatically; nothing is sent to Anki until you click
  **Send to Anki**. **Clear all** removes that source's drafts, and **Undo** (or
  **Ctrl+Z**) brings them back.
- **Sent history:** once cards reach Anki they move from drafts to
  `%LOCALAPPDATA%\AnkiScribe\sent.json`, keyed by the same source file and
  carrying their Anki note ids. That is what keeps the coverage meter and the
  teal highlights correct after a push, and it is what a later version will use
  to read your review results back. **Clear history** forgets the record for one
  source without touching Anki; it asks twice.
- **Quality faults:** cards that cannot be answered as written trigger a red
  **blocked** banner above the list. **Review blocked** filters the list to
  those cards, which get a red border and badge; fix the card and the red state
  clears. **Push anyway** is an explicit bypass. Warnings (a short question, an
  untagged card, two cards with nearly the same front) are shown but never
  block. Types and faults are decided by the server on the cards as submitted,
  so edits are always honoured. Secondary actions such as **Stats**,
  **Study plan**, **Leeches** and **Clear** live under **More** in the Review
  header.
- **Unverified cards:** if the quote a card cites is not in the source, the card
  wears a **check** badge and the Review header counts it. Check those against
  the page before sending, or generate again.
- **Sending:** **Send to Anki** first asks Anki which cards it would accept, so
  a batch that is already half in your collection shows **"12 new · 6 already
  in Anki"** and lets you send only the new ones. Nothing leaves your drafts
  until a send succeeds.
- **Study sheets:** tick the cards you want, then use the row above Review.
  **Study** flips through them with the answer hidden: **Space** reveals,
  **←** / **→** move, **Esc** closes. **Save HTML** writes one self-contained
  file that reveals each answer in place on any device or browser, offline and
  without Anki Scribe running. **Save PDF** writes a print-friendly sheet with
  the questions and chapter headings first and the answers in a key at the end;
  every question is a clickable link to its answer, and every answer's
  **← Back to question** link returns. That route works in Chrome, Edge,
  Firefox, Acrobat, Preview and mobile viewers — PDF's only in-place toggle
  (optional-content layers) is deliberately avoided because it needs Acrobat
  and would leave the answers permanently invisible in Chrome and Edge.
  Cloze cards export as the sentence with the deletion blanked out, and the
  answer shows the filled sentence. Untick a card and it drops out of the study
  view and both exports.
- **Study on the page itself:** the **Hide answers** toggle above the pages
  masks each ticked card's answer where it appears on the slide — not a
  re-rendered card, the actual page. The title, table headers, numbering and
  the rest of each bullet stay readable. Click a blank to reveal it; **Reveal
  all** / **Hide all** (or <kbd>R</kbd> / <kbd>H</kbd>) act on every page.
  **Hide selection** appears as soon as you select text inside the page: it
  hides exactly that selection, even when no card points at it, and **Clear
  marks** removes those manual blanks. Automatic masks come from the cards —
  cloze deletions, plus the specific names, numbers and clauses in a Q&A
  answer — and are recomputed when a card is edited or deleted. Contents pages
  and headings are left alone, because they orient you rather than test you.
  Untick a card and its answer stays visible. The toggle is remembered in this
  browser; manual hides are saved per file.
- **Blocked cards:** the quality gate refuses a push when a card has an empty
  side, an open-ended question, an answer leaked into the question, or more than
  three/too-long cloze deletions. A red banner above the list shows the count
  with **Review blocked** and **Push anyway**. Review blocked filters the list to
  those cards; they get a red left border and a red `blocked` badge, with the
  reason in the toast/badge. Fix the card and the red state clears. Batch
  auto-send leaves blocked cards in drafts instead of pushing them.
- **Study mode:** click **Study mode** above the pages (or press <kbd>F</kbd>).
  The page gets the whole window and the generation UI disappears. A small
  HUD shows the file, page and hidden-answer count. Use <kbd>Space</kbd> to
  reveal/hide all answers, <kbd>R</kbd>/<kbd>H</kbd> for all pages,
  <kbd>→</kbd>/<kbd>PageDown</kbd> or <kbd>J</kbd> for the next page,
  <kbd>←</kbd>/<kbd>PageUp</kbd> or <kbd>K</kbd> for the previous, and
  <kbd>?</kbd> for the shortcut card. <kbd>Esc</kbd> or **Exit** leaves.
  The HUD's fullscreen button uses browser fullscreen. Entering study mode turns
  hidden answers on when the file has cards; leaving restores your previous
  setting.
- **Study cards:** click **Study** above the review list, or **Quiz** in the
  study HUD. One card is shown at a time; **Space** reveals the answer, and
  **1–4** grade it Again, Hard, Good or Easy. The next card advances
  automatically. The header shows elapsed time, recall percentage and current
  streak; the final panel shows the grade mix, average time and best streak.
  Grades update a server-side interval/due date per card, so due cards sort before new
  ones on the next session. **Stats** above Review shows lifetime sessions,
  cards reviewed, days studied, current streak, retention, average time, due
  now and new cards. The history lives in `study_reviews.json` in the app data
  folder; the browser keeps a fallback copy. This is a lightweight server-side
  schedule for study sessions; the separate Study plan remains the exam-level
  FSRS view.
- **Study plan:** click **Study plan** above Review. It asks for the exam date,
  how many study items you still need to learn, your daily study window
  (start and end time, or **All day** for 00:00–23:59), which weekdays you
  study, and how many days before the exam should stay review-only. To plan
  several files together, open **Library**, tick them, and press **Plan
  selected** — the modal counts drafts, pushed cards and hand-hidden answers
  across every selected file, and the table gets a **Files** column that splits
  each day's new items by file. A **Plan by file** summary shows what is planned
  and what is beyond the current item count.
  A study item is one schedulable card: a Q&A card, a figure card, **each
  distinct cloze deletion**, or an answer you hid by hand. The plan walks
  FSRS-6 forward: each day it reviews the items that are due, then introduces
  that day's share of new items, so the table shows **new items, reviews,
  minutes and items learned**. It uses one expected recall (Good by default)
  and no extra intraday reviews, because this is a day-level plan;
  every review is assumed to be recalled, so a lapse would add workload. It
  also stops on the day before the exam, so exam morning is not scheduled.
  For a one-day plan, set the exam date to tomorrow and the buffer to 0; the
  **Hour-by-hour** panel splits that day's workload across your study window,
  with configurable **session length** and **break** (50/10 by default).
  **Calendar .ics** downloads the study sessions with a 10-minute alarm;
  import it into Google Calendar, Outlook or Apple Calendar. If the plan does
  not fit, it says how many minutes the heaviest day needs and
  how many items actually fit at your pace — or you can add days, widen the
  window or shorten the review buffer. **Copy plan** copies the summary and
  table as Markdown. It can read reviewed/lapsed/leech totals from Anki for the
  selected files, but it still treats every item as new in the schedule;
  cards already scheduled in Anki keep their own reviews. The
  FSRS-6 math is adapted from the MIT-licensed
  [py-fsrs](https://github.com/open-spaced-repetition/py-fsrs) reference.
- **Leeches:** the **Leeches** link above Review reads Anki's real review
  history for cards pushed from this file. It shows cards with four or more
  lapses, their review and lapse counts, the deck and source; if the source is
  the page that is open, **Show page** jumps straight there.
- **Source map:** teal-highlighted text already has a card — **click the
  highlighted line and the review panel jumps to that card** and flashes it
  (a line quoted by several cards cycles through them). Clicking a card's
  page/timestamp pill goes the other way and turns its source gold.
  Unhighlighted text and the coverage meter show what still needs attention.
  Highlights are derived from each card's exact selection or evidence quote;
  page-level chunk cards
  also outline the page so you can see their range.
- **AI credit:** the gold pill in the header is your remaining DeepSeek balance
  (CNY or USD, whichever your account uses). It refreshes on its own after a
  generation; click it to check again. The balance is the account credit from
  DeepSeek, not an estimate of how many cards are left.
- **Coverage:** the meter above Review estimates how much extracted text sits on
  pages that have at least one card. Whole-file cards are planned by page range,
  so the meter switches to **Page coverage** for them; use the teal source
  highlights to judge exact fact coverage. **N pages to check** lists pages with
  images, scans, or little text; text extraction cannot read labels inside
  figures, so compare those pages with the original. Whole-file runs also raise a
  notification when pages need a visual check. Transcripts show segment coverage
  instead.
- **Transcripts:** open an `.srt`, `.vtt`, `.txt` or `.md` file like any other
  file. Cues are merged into readable segments. Drag over the transcript to
  select text, or click a timestamp to select that whole segment. Cards show a
  timestamp pill such as `00:12–00:18`; click it to jump back and highlight the
  segment. **Auto from whole file** reads the transcript section by section.
- **Whole slide:** hover a page and click **Select page**. Useful for slides
  with one concept each.
- **Selection is line-level.** If a drag catches an extra line, trim the text
  in the Selection box before generating.
- **Card count:** *Auto* lets the model decide; pick a number if you want a
  fixed set.
- **Cloze syntax:** cards use `{{c1::term}}`. You can edit the text directly;
  Anki hides whatever is inside the braces.
- **Tags:** `Extra tags` on the push bar applies to the whole batch. Every card
  also gets its topic tags and your default tags from Settings.
- **Duplicates:** AnkiConnect skips cards that already exist in the chosen
  deck. If you re-send a batch, nothing is duplicated.
- **Photos:** shoot straight-on in good light, fill the frame with the page,
  and avoid shadows. HEIC isn't supported — convert to JPG/PNG first.
- **Scanned PDFs:** OCR starts on upload and runs through every scanned page in
  the background. The progress strip above the pages says how many are done;
  text can be selected as each page finishes. If OCR stops, press **Retry**.
  Photos of pages are OCR'd immediately when opened.

## Your data

Everything lives in `%LOCALAPPDATA%\AnkiScribe`:

- **One instance per data folder.** A second launch looks for a running instance
  and attaches to it, but only if that instance serves *this* data folder — a
  server started with a different folder (a test run, a second copy) is ignored.
  An `instance.lock` file in the data folder stops two processes from ever
  writing the same files.
- **Every save is recoverable.** `config.json`, `drafts.json`, `sent.json` and
  `library.json` are written atomically and the previous good version is kept
  beside them as `*.bak`. If a file is damaged, the app loads the backup and
  repairs the file; only when both are unreadable is the damaged one set aside
  as `*.corrupt-<timestamp>`.
- **Nothing is deleted on startup.** The document cache is pruned to the newest
  15 sources; that only removes thumbnails and extracted text, never your cards,
  key or library.
- `ANKI_SCRIBE_DATA` overrides the folder (the tests use it). If you set it by
  hand, remember that it points the app at a *different* data folder.

## Privacy

- PDFs, photos, transcripts, attached pictures and generated drafts stay on this
  computer.
- Only the text you select (or the file text in whole-file mode) is sent to
  DeepSeek for generation.
- The API key is stored in plain text at
  `%LOCALAPPDATA%\AnkiScribe\config.json`. That folder is local to your Windows
  account; don't share it.
- The library stores only file paths and group names in
  `%LOCALAPPDATA%\AnkiScribe\library.json`. Original files are never moved or
  modified. Preview images and extracted text are cached under
  `%LOCALAPPDATA%\AnkiScribe\documents` for speed; deleting that folder only
  clears the cache.
- Draft cards and their edits are stored locally in
  `%LOCALAPPDATA%\AnkiScribe\drafts.json`, and the record of what was already
  pushed in `sent.json` (source path, page, quote, the card as it was sent, and
  the Anki note id). Deleting either file removes local bookkeeping only; cards
  already sent to Anki are unaffected.
- **Save chapters** writes a book's text to
  `%LOCALAPPDATA%\AnkiScribe\splits\<book>\` as Markdown. That folder is local and
  is never uploaded anywhere; delete it when a split is no longer needed.
- A rolling log is written to `%LOCALAPPDATA%\AnkiScribe\anki-scribe.log`
  (five files, 1 MB each) and contains file names, counts and errors — not your
  card text or page text. **Settings → Download diagnostics** produces a zip of
  that log plus versions and counts, with the API key removed, for a bug report.
- This is an independent tool, not affiliated with Anki or DeepSeek.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| “Couldn't reach Anki” | Open Anki, confirm the AnkiConnect add-on is installed, then click the Anki status pill to retry. Check the AnkiConnect URL in Settings if you changed the port. |
| “Invalid host header” or the page loads but every action fails | Something is reaching the app under a hostname that isn't `127.0.0.1` or `localhost`. Open <http://127.0.0.1:8777> directly. This is deliberate: it stops a hostile web page from driving your local app. |
| “DeepSeek rejected that API key” | Re-paste the key in Settings. Keys from the DeepSeek platform usually start with `sk-`. |
| “Insufficient balance” | Top up the DeepSeek account or switch the base URL/model in Settings → Advanced. |
| Header shows “AI ?” | The balance endpoint only works with DeepSeek. Check the key, your internet connection, and the base URL; custom OpenAI-compatible endpoints may not expose `/user/balance`. |
| File dialog doesn't open | Use **Library → Add path** and paste the full path. The dialog needs a normal Windows desktop session. |
| A library file shows Missing | The file was moved/renamed. Put it back at the saved path, or remove it from the library and add it again from its new location. |
| OCR text looks broken | Use a sharper, straighter photo; crop to the text; increase resolution. PDFs with a real text layer are always better. |
| A page has no selectable text | Check the OCR progress strip above the pages. If it says OCR stopped, press **Retry**; if it already finished, the scan is too low quality — use a sharper, straighter scan. |
| **Plan selected** says the server is older | The client counted the files directly from their drafts, sent history and manual hides; the plan still works. Restart Anki Scribe to load the newest server and automatic OCR. |
| A slide deck looks different from PowerPoint | Decks are read, not rendered: text keeps its position, size and order, but fonts and exact spacing are approximated. Export to PDF if the layout matters. |
| A transcript has no readable text | Make sure it is `.srt`, `.vtt`, `.txt` or `.md`; subtitles need timestamp lines with `-->`. Plain text is split into paragraphs. |
| Transcript characters look wrong | Save it as UTF-8. Windows-1252, UTF-16 and Latin-1 are also tried automatically. |
| Chapters look wrong or generic “Part” names | Add PDF bookmarks/headings, or let the model plan chapters with a valid API key. If no structure is found, the app splits the file into parts. |
| An EPUB won't open | It must be a reflowable EPUB with real text. Fixed-layout books, comics and image-only EPUBs are refused with a message — convert them to PDF and let OCR read the pages. |
| “That PDF has 1,800 pages (max 1,500)” | The file is past the page ceiling. Split it into volumes, or raise `MAX_PAGES` in `app/store.py`. |
| Saved chapters went to an unexpected folder | They default to `%LOCALAPPDATA%\AnkiScribe\splits\<book>`. The toast's **Open folder** button shows exactly where they went. |
| Cards went to an unexpected deck | The bottom deck field is the parent. The app appends `Source title::Chapter` below it; select the source title as the parent to make it the top level. |
| Tables missing from whole-file cards | Only bordered tables are auto-detected. Use a PDF rather than a photo, or select the table manually and generate from that selection. For a table a card depends on, crop it with **Add picture**. |
| A formula reads out of order | Display equations arrive from the PDF in reading order across their lines, so a stacked fraction can come out jumbled. Formula lines are still marked `$…$` and their symbols normalised; when the card depends on the formula, crop it as a picture. |
| Browser didn't open | Go to <http://127.0.0.1:8777>. If that port is busy, the console prints the port it chose. |
| Cards won't add | Make sure the deck name is valid and the Basic/Cloze note types weren't renamed in Anki. Anki Scribe tries to create its own note types first and falls back to the stock ones. |
| A card has a **check** badge | Its quote was not found in the source text, so the model paraphrased or invented it. Compare the card with the page before sending, or generate that passage again. |
| A card's picture is missing | Pictures live in the document cache; if that source was pruned or deleted, **Replace** the picture. A send uploads media before the notes, so a failed upload stops the whole batch instead of creating notes with broken images. |
| Clicking highlighted text does nothing | The line must have a card that is still in the review list (sending removes it). Drag or select the text and the click is ignored on purpose. |
| **Send to Anki** asks about existing cards | That's the preflight: Anki already has some of these. **Send new** keeps the collection clean; **Send all** forces the whole batch. |
| “Couldn't write to its data folder” — nothing opens, drafts don't save | Some sandboxed tools mark the folder they run in as low-integrity. Every `.exe` inside then starts restricted, so `python.exe` can't write `%LOCALAPPDATA%\AnkiScribe`. Close Anki Scribe, run `icacls ".venv\Scripts\*.exe" /setintegritylevel Medium` in the project folder, and start it again. |
| The app opens with no key and an empty library | It attached to an instance serving a different data folder (for example a test run left on a later port). Close it and start `run.bat` again: the launcher now only attaches to an instance serving *this* folder. The real data is still in `%LOCALAPPDATA%\AnkiScribe`. |
| A settings or drafts file was damaged | The app loads the last good `*.bak` copy and repairs the file. If both copies are unreadable, the damaged one is kept as `*.corrupt-<timestamp>` rather than overwritten. |

## Development

```bat
uv sync
.venv\Scripts\python.exe -m pytest
.venv\Scripts\python.exe -m uvicorn app.main:create_app --factory --port 8777
```

Structure:

```
app/
  main.py        FastAPI routes, static files
  store.py       PDF text/table extraction, rendering, OCR fallback, path docs
  epub.py        EPUB → synthetic PDF, with the book's own contents as chapters
  transcript.py  subtitle/transcript parsing and timestamp segmentation
  chapters.py    table-of-contents/heading/LLM chapter planning
  split.py       one Markdown file per chapter, plus a manifest
  storage.py     atomic JSON writes with a .bak fallback
  instance.py    one instance per data folder (lock file)
  objectives.py  learning-objective detection
  presentations.py .pptx parser that writes a synthetic PDF
  figures.py     figure crops, masking and reveal images
  images.py      pictures attached to a card: page crops and uploads
  formats.py     formula detection and LaTeX-style math normalisation
  diagnostics.py redacted support bundle
  logging_setup.py rotating file log
  library.py     path-only file library, groups, persistence
  drafts.py      per-source draft-card persistence
  sent.py        per-source record of cards already pushed to Anki
  answers.py     find card answers on the PDF page for the study overlay
  masks.py       manual hidden-text persistence
  fsrs.py        FSRS-6 intervals used by the study plan
  planner.py     day-by-day new/review/time plan from an exam date
  batch_jobs.py  persistent server-side batch generation and resume
  reviews.py     server-side study grades, due dates and session analytics
  picker.py      native Windows file picker
  ocr.py         Windows OCR + RapidOCR fallback and two-column reading order
  llm.py         DeepSeek client, prompts, JSON/card validation
  cards_quality.py card types and quality faults, shared by generation and push
  anki.py        AnkiConnect client, note building, duplicate handling
  study.py       study-sheet PDF (clickable answer key) and standalone HTML
  config.py      settings + local data directory
  static/
    index.html   the browser shell
    css/         styles
    js/
      core.js      shared state, DOM refs and helpers
      risk.js      likely-wrong ranking for review and triage
      settings.js  settings + DeepSeek balance
      drafts.js    per-source draft restoration and source highlights
      deck.js      deck location tree, hierarchy and Anki push
      library.js   path library, groups and file opening
      documents.js PDF/transcript viewers, pages and selection
      source.js    source lookup and highlighting
      answers.js   hidden-answer overlays and manual hides
      plan.js      FSRS-6 study-plan dialog
      ocr.js       automatic OCR progress and retry
      focus.js     distraction-free study mode
      leeches.js   Anki review history and leech list
      cards.js     generation, review cards and editing
      study.js     study view, cloze masking and sheet export
      auto.js      chapter-aware whole-file generation
      coverage.js  coverage meter and page checks
      triage.js    one-card-at-a-time review pass
      objectives.js learning-objective coverage
      events.js    DOM event wiring
      app.js       startup/bootstrap only
run.py           port selection + browser launch
run.bat          double-click launcher
tests/           unit and API tests
```

See [ROADMAP.md](ROADMAP.md) for what is shipped and what is still missing.

There is no frontend build step: the browser loads these plain scripts in dependency order.
