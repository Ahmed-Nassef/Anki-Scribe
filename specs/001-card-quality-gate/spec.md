# Feature Specification: Card Quality Gate

**Feature Branch**: `001-card-quality-gate`

**Created**: 2026-11-21

**Status**: Draft

**Input**: User description: "Server-side card quality checks, a card type taxonomy, and a push guard so a defective card cannot reach Anki"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Every card says what kind of card it is (Priority: P1)

A student generates cards from a chapter. Each card is labelled with the kind of
knowledge it tests, and the review list summarises the mix, so the student can
see at a glance that this chapter is all definitions and no discrimination.

**Why this priority**: The generator currently optimises for "one testable
fact", which collapses to definition cards. Without a visible type there is no
way to notice the bias, let alone ask for a different card.

**Independent Test**: Generate from a chapter; every card shows exactly one type
label and the list shows a per-type count. No other feature depends on it.

**Acceptance Scenarios**:

1. **Given** generation returns cards, **When** they are displayed, **Then** each
   card carries exactly one type from the fixed vocabulary.
2. **Given** a card whose type is missing or unrecognised, **When** it is
   displayed, **Then** it is shown as a definition card and no error is raised.
3. **Given** a batch with more than one type, **When** the list renders, **Then**
   a summary shows how many cards there are of each type.

---

### User Story 2 - Defects are named, not merely ranked (Priority: P1)

Each card states why it is suspect — the answer leaks the question, the question
is open-ended, the cloze is overloaded — so the student can fix or drop it
instead of reading an unexplained risk score.

**Why this priority**: Triage today sorts by an aggregate score and explains it
in a sentence. The student still has to work out what is wrong; and a defect
that is only "ranked" is still pushable.

**Independent Test**: A fixture set of hand-written defective cards produces
exactly the expected fault labels, and clean cards produce none.

**Acceptance Scenarios**:

1. **Given** a card whose answer is already contained in its question, merely
   restates the question, or is a bare yes/no, **Then** it is flagged
   `answer_leak` with blocking severity. (A definition question that names
   its own term is not a leak; see research R4.)
2. **Given** a card that asks the reader to explain, describe, discuss or list,
   **Then** it is flagged `open_ended` with blocking severity.
3. **Given** a cloze card with more than three deletions, or any deletion longer
   than eight words, **Then** it is flagged `cloze_overloaded` as blocking.
4. **Given** a card with a list answer, a too-short question, a bare number, or
   no tags, **Then** it is warned but not blocked.
5. **Given** two cards submitted together whose fronts overlap heavily,
   **Then** both are flagged as interfering with each other.

---

### User Story 3 - A defective card cannot reach Anki by accident (Priority: P1)

A batch that contains a blocking defect does not go to Anki. The student is told
which cards are wrong and why, and can either fix them or explicitly override.

**Why this priority**: This is the whole point of the feature. A vague, leaking
or unanswerable card that enters the collection is a permanent cost: it is
studied for months before anyone notices it was never a real question.

**Independent Test**: Push a batch containing one blocking card; the request is
refused, nothing is written, and the response names the card and the defect. The
same batch with an explicit override succeeds.

**Acceptance Scenarios**:

1. **Given** a batch with one blocking defect, **When** the student pushes,
   **Then** nothing is written to Anki and the response names every blocking card
   and its faults.
2. **Given** the same batch and an explicit "send anyway", **Then** the batch is
   written normally.
3. **Given** a batch with warnings only, **Then** the push proceeds and the
   warnings are still reported.
4. **Given** a duplicate preflight for that batch, **Then** the same policy
   applies.

---

### User Story 4 - The writer is told the rules (Priority: P2)

Generation itself is instructed in terms of the same rules, so most defects are
never produced in the first place: a type is chosen deliberately, questions are
closed, answers do not restate their own question, and a cloze hides one term.

**Why this priority**: Repairing defects is expensive attention; prevention is
free. Without this story the gate becomes a nuisance that blocks work.

**Independent Test**: The generation instructions contain every rule the gate
enforces, and a model reply that omits the new fields still produces usable
cards.

**Acceptance Scenarios**:

1. **Given** a generation request, **Then** the instructions name the type
   vocabulary and require exactly one type per card.
2. **Given** a generation request, **Then** the instructions forbid open-ended
   question openings, answers that reuse the question's distinctive term, list
   answers, and more than one cloze deletion by default.
3. **Given** a model reply that omits type, **Then** the cards are still accepted
   and treated as definitions.
4. **Given** a model reply that omits the new fields entirely, **Then** the JSON
   contract for existing callers is unchanged.

---

### Edge Cases

- Cards created before this feature (no type, no faults) must keep working and
  must not appear defective merely for being old.
- Figure cards and cards with an attached picture may have an empty text side;
  text-based rules must be skipped rather than triggered.
- Non-English sources: only English imperative openings count as open-ended, and
  only at the start of the question, so a legitimate foreign-language question
  is not blocked.
- A cloze card with two deletions is a warning, not a block, because the two
  terms are sometimes one indivisible list.
- A card whose evidence is already missing must not be blocked twice for the
  same reason; the existing evidence check owns that fault.
- Very long questions and answers are evaluated as they will be shown
  (truncated), so a fault is never raised against text the student cannot see.
- A batch of one card cannot produce an interference fault.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The system MUST classify every generated card into exactly one type
  from a fixed vocabulary: definition, mechanism, compare, application,
  enumeration, number.
- **FR-002**: The system MUST attach zero or more quality faults to every card,
  each with a stable code, a human-readable label, and a severity of blocking,
  warning or info.
- **FR-003**: The system MUST treat at least these as blocking: an answer that
  leaks its question, an open-ended question, an overloaded cloze deletion, and a
  card missing a side that its mode requires.
- **FR-004**: The system MUST treat at least these as warnings: a list answer, a
  question too short to stand alone, a bare number with no unit, an untagged
  card, and two cards that interfere with each other.
- **FR-005**: Generation MUST return the type and faults for both question/answer
  and cloze cards.
- **FR-006**: A push MUST be refused when the submitted batch contains a blocking
  fault, unless the caller explicitly overrides, and MUST write nothing in that
  case.
- **FR-007**: A duplicate preflight MUST apply the same quality policy as a push.
- **FR-008**: Quality MUST be recomputed from the cards as submitted, so a
  student's edits are honoured and a stale client cannot smuggle a defect
  through.
- **FR-009**: Existing card behaviour MUST be preserved: evidence verification,
  strict mode, duplicate handling, note types and their fallbacks.
- **FR-010**: The quality rules MUST have a single implementation, shared by
  generation and push, and MUST NOT be re-implemented in the browser.
- **FR-011**: The review interface MUST show each card's type and its faults, with
  blocking faults visually distinct from warnings.
- **FR-012**: The feature MUST NOT add a runtime dependency, a network call, or a
  build step.
- **FR-013**: A rule MUST NOT fire when the information it needs is absent (for
  example a text rule against a card with no text side).

### Key Entities

- **Card**: one item under review. It has an identity, a mode (question/answer or
  cloze), a type, its question and answer or its cloze text, an evidence quote
  from the source, a verified flag, and the faults found in it.
- **Fault**: one reason a card is suspect. It has a code (stable, machine
  readable), a label (short, human), a severity, and optionally a detail that
  locates the problem.
- **Quality Policy**: the thresholds the rules use — deletion count, deletion
  length, front overlap ratio, minimum question length. Defined once, so the
  gate and the writer cannot disagree.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: 100% of cards returned by generation carry a type and a fault list.
- **SC-002**: 0 blocking cards can be pushed without an explicit override.
- **SC-003**: Quality evaluation of a 1,000-card batch completes in under 250 ms
  on the development machine, so it can run on every push.
- **SC-004**: A fixture set of at least 12 known-defect cards is classified with
  exactly the expected fault codes, and at least 6 clean fixtures produce no
  faults — measured as a test, not an assertion.
- **SC-005**: The JSON contract for generation remains backward compatible: a
  client that ignores the new fields behaves exactly as before.

## Assumptions

- The student remains the final authority: the gate prevents accidents, it does
  not overrule a deliberate choice.
- Existing on-disk records without the new fields remain valid and are not
  rewritten by this feature.
- Open-ended detection is English-only in this iteration; other languages are
  explicitly out of scope.
- Interference detection is scoped to cards submitted together (a batch), not to
  the whole collection; collection-wide interference belongs to a later feature
  that can read the collection.
- The vocabulary is closed; adding a type is a specification change, not a
  configuration value.
