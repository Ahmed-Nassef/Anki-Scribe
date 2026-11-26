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
- FSRS-6 study plan with exam date, daily start/end window, All day, and
  hour-by-hour workload blocks
- **Focused study mode**: full-screen pages, minimal HUD, keyboard-first
  navigation and answer control (see below)
- Anki push, deck picker, coverage, source map, figure cards
- Study-sheet Markdown export, diagnostics, single instance, local data safety

## Not built yet

| Priority | Feature | Gap |
| --- | --- | --- |
| High | Server-side job queue and resume | Batch generation is a browser queue. Closing the tab or restarting stops it; there is no resume-after-crash. |
| High | Per-file schedule allocation | Multi-file planning sums items into one schedule. It does not say “Week 1 from 08:00–09:00, Week 2 from 09:00–10:00.” |
| High | True intraday schedule | The hourly view is a workload estimate. It has no breaks, real FSRS steps within a day, calendar `.ics` export or reminders. |
| High | Anki review-history / leech loop | The plan treats every item as new. It cannot read actual reviews, lapses or leeches, so it cannot adapt to what the student really knows. |
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

For the current exam workflow, do these first:

1. Server-side job queue and resume, so a multi-file generation survives a
   closed tab.
2. Per-file allocation in the plan, so a combined schedule says which file and
   page range fills each block.
3. Reading Anki review history, so the plan adapts instead of treating every
   card as new.
4. Cost preview and a spending cap before large batch runs.
