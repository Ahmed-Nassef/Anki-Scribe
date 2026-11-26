---

description: "Task list for the Card Quality Gate feature"
---

# Tasks: Card Quality Gate

**Input**: Design documents from `/specs/001-card-quality-gate/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/quality-gate.md

**Tests**: Included — Constitution VI requires a failing test before behaviour.

**Organization**: Grouped by user story so each can be verified on its own.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1 = types, US2 = named faults, US3 = push guard, US4 = writer rules

## Path Conventions

Single project: `app/`, `tests/`, `app/static/js/` at repository root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: The module and its test file exist, with the vocabulary fixed before anything depends on it.

- [x] T001 Create `app/cards_quality.py` with the type vocabulary, `DEFAULT_TYPE`, policy constants, `Fault` dataclass and severity constants in `app/cards_quality.py`
- [x] T002 [P] Create `tests/test_cards_quality.py` with fixture builders (basic card, cloze card, clean card) in `tests/test_cards_quality.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The pure rule engine. Every story consumes it.

**⚠️ CRITICAL**: No story work can begin until this phase is complete.

- [x] T003 [P] Implement `card_type()` normalisation with unknown/missing → `definition` in `app/cards_quality.py`
- [x] T004 Implement `evaluate_card()` for per-card rules: `empty_side`, `open_ended`, `answer_leak`, `cloze_overloaded`, `list_answer`, `vague_question`, `bare_number`, `untagged` in `app/cards_quality.py`
- [x] T005 Implement `evaluate_batch()` adding `interference_pair` via bucketed Jaccard (caps from policy) in `app/cards_quality.py`
- [x] T006 Implement deterministic ordering (blocking first, then code, then detail) and a `blocking()` selector in `app/cards_quality.py`
- [x] T007 Write the rule tests: one fixture per code that must fire, plus clean fixtures that must stay empty in `tests/test_cards_quality.py`

**Checkpoint**: `pytest tests/test_cards_quality.py` green for the engine alone.

---

## Phase 3: User Story 1 — Every card says what kind of card it is (P1) 🎯 MVP

**Goal**: Cards carry a type end to end, and the review list shows the mix.

**Independent Test**: Generate from a chapter, see a type word on each card and a per-type count in the header.

- [x] T008 [P] [US1] Keep `type` in `parse_cards()` for both modes, defaulting missing/unknown to `definition`, in `app/llm.py`
- [x] T009 [P] [US1] Add the type vocabulary and "exactly one type" rule to `SYSTEM_BASIC` and `SYSTEM_CLOZE` in `app/llm.py`
- [x] T010 [US1] Render a type badge per card and a mix summary line in `app/static/js/cards.js`
- [x] T011 [US1] Extend `tests/test_llm.py` for type parsing and for a reply that omits `type`

**Checkpoint**: US1 works with no notion of faults at all.

---

## Phase 4: User Story 2 — Defects are named (P1)

**Goal**: Every card arrives with its faults, and the UI shows them.

**Independent Test**: Generate cards from a passage engineered to produce a leak; the card shows the fault chip while a clean card shows none.

- [x] T012 [US2] Attach `faults` from `evaluate_batch()` in `parse_cards()` for both modes in `app/llm.py`
- [x] T013 [US2] Render fault chips with severity styling next to the type badge in `app/static/js/cards.js`
- [x] T014 [US2] Show the fault label in triage instead of only the risk sentence in `app/static/js/triage.js`
- [x] T015 [US2] Add generation-level tests for faults in `tests/test_generation_quality.py`

**Checkpoint**: US1 and US2 both work; push is still unguarded.

---

## Phase 5: User Story 3 — A defective card cannot reach Anki by accident (P1)

**Goal**: The push and preflight refuse blocking cards, side-effect free, with an explicit override.

**Independent Test**: POST a batch with one leaking card; 400, nothing written; `allow_blocked: true` succeeds.

- [x] T016 [US3] Add `allow_blocked` to `PushBody` and a `_refuse_blocked()` helper building the 400 payload in `app/main.py`
- [x] T017 [US3] Call the guard at the top of `anki_push()` and `anki_preflight()`, before any AnkiConnect call, in `app/main.py`
- [x] T018 [US3] Surface the refusal in the push flow with the blocked card list and an explicit **Send anyway** in `app/static/js/deck.js`
- [x] T019 [US3] API tests: refusal writes nothing, override succeeds, preflight parity, warnings do not block, in `tests/test_quality_gate_api.py`

**Checkpoint**: All three P1 stories are independently demonstrable.

---

## Phase 6: User Story 4 — The writer is told the rules (P2)

**Goal**: The prompt states every rule the gate enforces, and the cloze contradiction is removed.

**Independent Test**: The prompt text contains each rule; a reply without the new fields still parses.

- [x] T020 [US4] Rewrite `SYSTEM_BASIC` / `SYSTEM_CLOZE` to state the rules: closed questions, no answer echo, no lists in answers, one deletion by default, type per card in `app/llm.py`
- [x] T021 [US4] Align the regenerate prompt so a rewrite cannot reintroduce a blocked defect in `app/llm.py`
- [x] T022 [US4] Tests: prompt contains each rule; a legacy reply (no type, no faults) still yields cards in `tests/test_generation_quality.py`

---

## Phase 7: Polish & Cross-Cutting Concerns

- [x] T023 Performance test: `evaluate_batch()` on 1,000 cards under 250 ms in `tests/test_cards_quality.py`
- [x] T024 Document the gate and the type vocabulary in `README.md` and mark the ticket shipped in `FEATURES.md`
- [x] T025 Run `quickstart.md` by hand and the full suite; record results in `specs/001-card-quality-gate/quickstart.md` notes

---

## Dependencies & Execution Order

### Phase Dependencies

- Setup (Phase 1) → Foundational (Phase 2): blocks everything
- US1 (Phase 3) and US2 (Phase 4) share `cards.js` and `llm.py`; run US1 then US2
- US3 (Phase 5) depends only on Phase 2 (not on US1/US2)
- US4 (Phase 6) depends on Phase 2 for the vocabulary, and can run before the UI work
- Polish (Phase 7) last

### Within Each Story

- Tests before implementation (Constitution VI)
- Engine before callers; callers before UI
- Full suite green at each checkpoint

### Parallel Opportunities

- T008/T009 and T012 are all in `llm.py` — sequential to avoid conflicting edits
- T010 and T013 are both in `cards.js` — sequential
- T019 (API tests) can be written while T016/T017 are implemented

---

## Implementation Strategy

### MVP First

1. Phase 1 + 2 → the engine, tested alone
2. Phase 3 (US1) → types visible, safe to ship
3. Phase 5 (US3) → the actual guarantee
4. STOP and validate against `quickstart.md`

### Incremental Delivery

1. Engine + US1 → cards carry a type (lowest risk, no behaviour change)
2. US2 → faults visible, still advisory
3. US3 → faults enforced
4. US4 + polish → prevention and documentation

---

## Notes

- `[P]` tasks touch different files.
- Faults are never persisted (research R2); types are.
- One implementation of every rule (Constitution VIII) — the browser renders only.
