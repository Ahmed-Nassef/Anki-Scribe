# Roadmap

Anki Scribe is a local study system: import a lecture, generate cards, hide the
answers on the page, and plan the work up to an exam. This file tracks what is
done and what is still missing. It is deliberately blunt: “✅” means shipped and
tested, not “mostly working”.

## Built

- PDF, EPUB, PowerPoint, photo and transcript import
- Automatic background OCR for scanned PDFs, with progress, Stop and Retry
- Q&A and cloze generation, quality gate, triage, risk ranking and undo
- Hidden answers with type colours, a legend, click-again-to-hide and AI fill
- Library, groups, batch generation and multi-file planning
- **Persistent server-side batch queue**: files are processed in a daemon
  thread, progress is stored in `batch_jobs.json`, and an interrupted job
  resumes after restart. The browser may close without stopping it.
- FSRS-6 study plan with exam date, daily start/end window, All day, and
  **per-file allocation** of new items across the table and hourly blocks
- **Study sessions and breaks**: configurable session length and break length,
  plus a **Calendar .ics** download with a 10-minute alarm per session
- **Anki review history and leeches**: reads `notesInfo`/`cardsInfo` for pushed
  note ids, shows reviewed/lapsed/leech totals, lists cards with 4+ lapses, and
  moves to the source page when it is the open file
- **Focused study mode**: full-screen pages, minimal HUD, keyboard-first
  navigation and answer control (see below)
- Anki push, deck picker, coverage, source map, figure cards
- Study-sheet Markdown export, diagnostics, single instance, local data safety

## Not built yet

| Priority | Feature | Gap |
| --- | --- | --- |
| High | True FSRS intraday steps | Sessions have breaks and a calendar file, but the scheduler still models day-level FSRS intervals. It does not schedule minute-level learning steps or a second recall pass inside the day. |
| High | Adaptive plan from Anki history | History and leeches are read and shown, but the planner still treats every item as new. It does not subtract learned cards, reschedule due reviews, or build a leech-repair plan. |
| High | Leech repair loop | Leeches are listed and can open their source page, but there is no regenerate/rewrite/retire action from the leech dialog. |
| Medium | Cost preview and usage cap | Batch and multi-file runs can use a lot of DeepSeek credit with no estimate beforehand and no hard cap. |
| Medium | Study-sheet type-to-reveal and AnkiWeb sync | Markdown export exists; the interactive type-to-reveal sheet and AnkiWeb sync do not. |
| Medium | Onboarding wizard | The single-instance half is built; the first-run wizard is not. |
| Medium | Bulk card selection, filtering and chapter grouping | No chapter grouping, no bulk filter by type/status, no bulk rewrite. |
| Medium | Review-list per-card rewrite | Rewrite exists only in triage, not on a card in the review list. |
| Medium | Custom generation instructions | Style presets exist; free-text “extra instructions” do not. |
| Low | Figure and vision cards | Figures work only on PDF pages, one picture per card, and no model reading of the figure to suggest an answer. |
| Low | OCR robustness | No deskew/denoise, handwriting support, language picker or better borderless-table OCR. |
| Low | More formats | Fixed-layout EPUB/comics, DOCX and video/audio transcription are unsupported. |
| Low | Progress analytics | No retention/adherence tracking, streaks or cross-file card search. |
| Low | Remote/security hardening | Local-only Host check; no accounts or multi-user boundary. Not needed for a local app, blocking for hosting. |

## Focused study mode

The normal screen is built for generating cards: a side panel, a toolbar, answer
controls and a pager. Focus mode removes all of it and keeps the pages plus a
small HUD.

- **Enter:** the **Study mode** button in the page toolbar or `F`
- **Answers:** `Space` toggles all hidden answers; `R` reveals; `H` hides;
  clicking a blank and then the revealed text still toggles it
- **Pages:** `Right`/`PageDown`/`J` next; `Left`/`PageUp`/`K` previous
- **Help:** `?` opens the shortcut card
- **Exit:** `Esc`, `F`, or **Exit** in the HUD
- **Fullscreen:** the `⛶` HUD button uses browser fullscreen
- Focus mode turns hidden answers on when entering (if the file has cards) and
  restores the previous answer setting when leaving.

## Recommended order

The originally planned high-priority infrastructure is shipped: batch jobs now
live on the server and resume, the plan allocates new items by file, sessions
have breaks and export to `.ics`, and real Anki lapses are visible.

What remains at the top of the list:

1. Make the planner consume Anki history: mark learned items separately and
   schedule their real due dates instead of treating everything as new.
2. Add minute-level learning steps and a same-day recall pass, so the hourly
   view models FSRS rather than only workload.
3. Close the leech loop: rewrite, suspend or regenerate a leech directly from
   the Leeches dialog.
4. Add cost preview and a spending cap before large batch runs.
