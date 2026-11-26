# Implementation Plan: Card Quality Gate

**Branch**: `001-card-quality-gate` | **Date**: 2026-11-21 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `/specs/001-card-quality-gate/spec.md`

## Summary

Add one server-side module that decides, for every card, **what type of knowledge
it tests** and **what is wrong with it**. Generation returns both; a push refuses
cards with a blocking defect unless the student explicitly overrides. The
generation prompt is rewritten to state the same rules, so most defects are never
produced. The browser only displays what the server decided — it never
re-implements a rule.

The change is additive: no new dependency, no new endpoint that must exist for the
app to work, and old cards without a type remain valid.

## Technical Context

**Language/Version**: Python 3.12 (project supports 3.11–3.12), plain browser JS (ES2020), no build step

**Primary Dependencies**: FastAPI + Pydantic v2 (existing), httpx (existing) — **no new dependency**

**Storage**: none added. Card types live on the in-memory/`drafts.json` card objects (already persisted verbatim) and are copied into the sent ledger additively. Faults are **derived**, never stored, so they cannot go stale.

**Testing**: pytest + `fastapi.testclient.TestClient`; LLM, OCR and AnkiConnect are mocked (existing patterns in `tests/test_llm.py`, `tests/test_api.py`)

**Target Platform**: Windows 10/11, local web app on `127.0.0.1`

**Project Type**: single web app — FastAPI backend + plain-script frontend

**Performance Goals**: evaluate 1,000 cards in < 250 ms; the guard runs on every push

**Constraints**: no new runtime dependency; no network call added; no frontend build step; rule set must have exactly one implementation (Constitution VIII)

**Scale/Scope**: one student, decks of 50–2,000 cards per source, batches up to ~2,000

## Constitution Check

*GATE: evaluated before design, re-checked after Phase 1.*

| Principle | Gate | Result |
| --- | --- | --- |
| I. Learning over volume | Does the feature reduce weak cards rather than add cards? | PASS — it blocks weak cards and reports the type mix that exposes definition-only decks |
| II. Evidence or nothing | Are cards still grounded in a verbatim quote? | PASS — evidence verification is untouched; the new `empty_side` rule complements it; the gate never accepts a card whose quote is missing without marking it |
| III. Anki owns the schedule | Any scheduling logic? | PASS — no scheduling state is read or written |
| IV. Local first | New network destination or telemetry? | PASS — none |
| V. No build step / deps | New dependency or bundler? | PASS — stdlib only; client stays dependency-free |
| VI. Tests are contract | Tests for each rule, guard, and compatibility? | PASS — planned in `tasks.md`; fixtures per rule plus guard/API tests |
| VII. Reversible | Does it destroy work? | PASS — the gate blocks before writing; override is available; nothing is deleted |
| VIII. Small modules | Is any rule implemented twice? | PASS — one module; JS renders only what the server sends |

No violations. Complexity Tracking is therefore empty.

## Project Structure

### Documentation (this feature)

```text
specs/001-card-quality-gate/
├── plan.md              # this file
├── research.md          # Phase 0 decisions
├── data-model.md        # Phase 1 entities and shapes
├── contracts/           # Phase 1 API contract deltas
│   └── quality-gate.md
├── quickstart.md        # Phase 1 manual verification
└── tasks.md             # Phase 2 task list
```

### Source Code (repository root)

```text
app/
├── cards_quality.py     # NEW — the only place quality rules live
├── llm.py               # prompts (SYSTEM_BASIC/CLOZE v2), parse_cards attaches type + faults
├── main.py              # push/preflight guard, error contract
├── anki.py              # unchanged note building (+ additive type tag is deferred to 002)
└── static/js/
    ├── cards.js         # type badge + fault chips + mix summary
    ├── triage.js        # show faults instead of only risk score (display only)
    └── deck.js          # surface the guard's refusal with the card list

tests/
├── test_cards_quality.py   # NEW — rule fixtures, policy, interference, performance
├── test_llm.py             # extend — type parsing, backward compatibility
└── test_api.py             # extend — push guard, override, preflight parity
```

**Structure Decision**: single project. `app/cards_quality.py` is a pure module
(no FastAPI, no httpx, no disk) so it can be imported by `llm.py`, `main.py` and
the tests without a cycle. It deliberately does not import `llm` — `llm` imports
it, not the other way round.

## Phase 0 — Research

See [research.md](./research.md). Decisions in brief:

1. Rules live server-side only; the browser renders.
2. Faults are derived on demand; only `type` is stored.
3. Severity is a three-level policy table in one constant.
4. `answer_leak` uses a high-precision head-term rule, not an LLM entailment check
   (which belongs to a later feature because it costs a model call).
5. Interference mirrors the existing `risk.js` bucketed Jaccard, ported to Python.
6. The guard runs in `main.py` before any Anki call, and returns 400 with a
   structured payload; `allow_blocked` is the explicit override.
7. Old cards without a type are read as `definition`.

## Phase 1 — Design

- Entities and shapes: [data-model.md](./data-model.md)
- API deltas: [contracts/quality-gate.md](./contracts/quality-gate.md)
- Manual verification: [quickstart.md](./quickstart.md)

### Implementation outline

1. **`app/cards_quality.py`**
   - `TYPES` vocabulary, `DEFAULT_TYPE`.
   - `Fault` dataclass; `BLOCKING`, `WARNING` severity constants.
   - `POLICY` constants (max deletions, max deletion words, overlap ratio,
     minimum question words).
   - `card_type(card)` — normalise, fall back.
   - `evaluate_card(card)` — per-card rules.
   - `evaluate_batch(cards)` — per-card plus interference pairs.
   - `blocking(cards)` — the subset that must stop a push.
2. **`llm.py`** — prompt v2 adds the type vocabulary and the rules; `parse_cards`
   keeps `type` and attaches `faults` from `evaluate_batch`.
3. **`main.py`** — `PushBody.allow_blocked`; a `_refuse_blocked()` helper used by
   both `anki_push` and `anki_preflight`; 400 with `detail={"blocked": [...]}`.
4. **`cards.js` / `deck.js`** — badge, chips, mix line; push refusal shows the
   blocked cards and offers the override path.
5. **Tests** — fixtures per rule, clean fixtures must stay clean, guard tests,
   compatibility tests, performance test.

## Phase 2 — Tasks

Generated by `/speckit.tasks` into [tasks.md](./tasks.md).

## Complexity Tracking

> No Constitution Check violations. Nothing to justify.
