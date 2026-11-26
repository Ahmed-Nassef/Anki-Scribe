# Anki Scribe Constitution

Anki Scribe turns lecture sources into Anki cards, locally, for one student.
These principles decide what we build and what we refuse to build. Every plan
must pass a Constitution Check before implementation.

## Core Principles

### I. Learning Over Volume

The product succeeds when a student needs **fewer, better cards**, not when it
produces more. A card that will not be understood is worse than no card.

- No feature may have "more cards" as its primary effect.
- Generation must prefer **omission** over a weak card: an empty section is
  acceptable, a vague card is not.
- Any claim that learning improved must be measured against review data, not
  asserted from card counts.

### II. Evidence or Nothing

Every card must carry a short, verbatim quote from the source it was built from.

- The evidence check is a **gate**, not decoration: a card whose quote cannot be
  found in the source is marked, and the default push path never silently
  installs it.
- Rewrites are grounded in the saved quote, so a rewrite cannot wander outside
  the source or outside the fact the card already tested.
- Outside knowledge presented as if it came from the lecture is a defect, even
  when the fact is true.

### III. Anki Owns the Schedule

We never implement spaced repetition, and we never write scheduling state.

- We **read** `reps`, `lapses`, `interval`, `ease`, `due` and act on them.
- We never duplicate Anki's review UI, browser or scheduler. Study surfaces in
  this app are practice and validation, not the schedule.
- Card state that Anki already owns is mirrored at most, never authoritative.

### IV. Local First, One Student

The app is a local tool bound to `127.0.0.1`, with no accounts and no telemetry.

- Data lives under `%LOCALAPPDATA%\AnkiScribe`; the API key never leaves the
  machine and never appears in a log, a bundle or an export.
- No new outbound network destination is added except the one LLM endpoint the
  user configured.
- Logs contain counts, names and errors — never card text or page text.

### V. No Build Step, No Casual Dependencies

The browser loads plain scripts in dependency order; there is no bundler, and
there will not be one.

- Standard library first. A new runtime dependency requires a written
  justification in the plan and must install from PyPI with no build step and no
  incompatible licence.
- Client code stays dependency-free; no framework, no CDN.
- Public functions are typed; module boundaries are explicit.

### VI. Tests Are the Contract

A feature is not done because it works on one file; it is done when the suite
proves it.

- New behaviour ships with a test that fails before it and passes after.
- AnkiConnect, OCR and the LLM are mocked; the suite never touches the network.
- The full suite must be green at the end of every task, not just at the end of
  the feature.

### VII. Reversible by Default

The student's work is never destroyed by an action they did not intend.

- Destructive UI has undo. Deletions in the collection are **supersessions**:
  tag and suspend, then add the replacement.
- A rewrite keeps the previous version (`was`), so it can be compared and
  reverted.
- Data files are additive and tolerant: a reader must survive a record written
  by an older version.

### VIII. Small Modules, Predictable Failures

One concern per module; no god objects; no hidden global state.

- Errors are typed and actionable (`LLMError`, `AnkiError`) and say what the user
  can do next.
- Quality rules live in **one** place and are shared, never re-implemented per
  caller.
- A pure function that decides something about a card is testable without a
  browser, a model or Anki.

## Constraints

- **Platform**: Windows 10/11, Python 3.11–3.12, no frontend build step.
- **Performance**: a 1,000-card batch stays interactive; per-card server work is
  O(n) and fast enough to run on every push.
- **Compatibility**: on-disk records (`drafts.json`, `sent.json`, document
  metadata) may gain fields; they may not lose them or change meaning without a
  migration path.
- **Security**: loopback-only binding, host header validation, no remote triggers
  for local dialogs.

## Development Workflow

1. A feature begins as `spec.md` (what and why, technology-agnostic), then
   `plan.md` (how), then `tasks.md` (order of work).
2. Each plan carries a **Constitution Check**; any violation is recorded under
   Complexity Tracking with its justification.
3. Implement task by task, keeping the suite green.
4. User-facing changes update `README.md`; shipped work updates `FEATURES.md`.
5. Behaviour that touches card correctness gets a test in the same change.

## Governance

- This constitution supersedes convenience and momentum.
- Amendments: edit this file, bump the version (semver), and record the change
  in the history below. A plan written before an amendment is re-checked against
  the new text.
- Principle II (evidence) and Principle V (no casual dependencies) are hard
  gates: a plan that violates either is rejected, not justified.
- Complexity must be justified in writing, in the plan, at the time it is
  introduced.

**Version**: 1.0.0 | **Ratified**: 2026-11-21 | **Last Amended**: 2026-11-21

## History

- **1.0.0** (2026-11-21) — Ratified at the start of the learning-upgrade
  programme, before feature 001.
