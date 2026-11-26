# Phase 0 — Research: Card Quality Gate

Decisions taken before design, with the alternative that was rejected. Time
constraint on all of them: this is a local single-user app, and every rule here
runs on every generation and every push.

## R1. Where do the rules live?

**Decision**: one pure Python module, `app/cards_quality.py`, imported by the
generation path and the push path.

**Why**: the same rule must hold before review and at push time; two copies drift.
The browser cannot be authoritative because the client can be stale or edited.

**Rejected**: duplicating the rules in `risk.js` (the app already does this for
ranking — and the duplicated thresholds are already inconsistent with nothing).
Also rejected: a `/api/cards/quality` round-trip per keystroke, which would make
the review list chatty for no benefit.

**Consequence**: the badge in the review list reflects the last server answer. If
the student edits a question so it now leaks the answer, the chip does not update
until the next generation — but the **push** re-evaluates and refuses. That is the
correct trade: cheap UI, authoritative gate.

## R2. Do we store faults?

**Decision**: no. Faults are derived on every evaluation. `type` **is** stored on
the card, because it is a decision by the writer that later features (tags, mix
report, prompt A/B) need, and because it must survive a reload.

**Why**: a stored fault goes stale the moment a card is edited; a stored type does
not, because editing a question does not change what kind of fact it tests.

**Consequence**: `sent.json` entries gain no faults; they gain `type` additively
(the ledger stores the card as sent). Old records without `type` read as
`definition`.

## R3. Severity model

**Decision**: three levels — `blocking`, `warning`, `info` — and only `blocking`
stops a push.

**Why**: a two-level model forces a bad choice for "question is short but not
necessarily wrong". A four-level model invites argument about levels instead of
about cards. Blocking is reserved for faults that make a card *unanswerable* or
*self-defeating*, which is a property we can defend.

**Blocking**: `answer_leak`, `open_ended`, `cloze_overloaded`, `empty_side`.
**Warning**: `list_answer`, `vague_question`, `bare_number`, `untagged`,
`interference_pair`.

## R4. How to detect an answer that leaks its question, without a model

**Decision**: three high-precision local signals, all reported as `answer_leak`:

1. **Yes/no answer** — the answer begins `yes`/`no`/`true`/`false`, so the
   question was answerable with one bit.
2. **Containment** — every content token of the answer (at least two of them)
   already appears in the question: the answer is composed from the question.
3. **Restatement** — for a question with at least three content tokens, at least
   80% of them appear in the answer: the answer is the question reordered.

**Why**: a head-term echo was the obvious first choice and it is wrong. A
definition card ("What is preload?" → "Preload is the ventricular stretch at
end-diastole") necessarily names its own term, so that rule would block the
most common legitimate card. The three signals above never fire on it, and
they still catch the cards that test nothing: the yes/no question, the answer
built out of the question's own words, and the answer that repeats the premise.
Spec scenario US2-1 was amended to match this narrower, defensible rule.

**Rejected**: an LLM entailment pass (a real solution, but it costs a model call
per batch and belongs to feature 003, "blind answer check"), and a token-overlap
ratio alone, which flags every legitimate question that names its subject.

## R5. Interference detection

**Decision**: port the existing bucketed-Jaccard approach from `risk.js` to
Python: tokenise fronts, index each card under its two rarest tokens, compare
within buckets, flag pairs at Jaccard ≥ 0.8.

**Why**: O(n) buckets with a hard comparison cap keeps a 2,000-card batch cheap,
and it already works well enough to be worth keeping. Reusing the same idea means
the same cards get flagged in both places.

**Rejected**: pairwise comparison (O(n²) at 2,000 cards), and embeddings (a new
dependency, and overkill for "these two fronts are nearly the same string").

## R6. Where does the guard run?

**Decision**: in `main.py`, at the top of `anki_push` and `anki_preflight`, before
`anki.build_notes` and therefore before any AnkiConnect call.

**Why**: `anki.py` is a transport client; policy does not belong in it. Running
before `build_notes` also means a blocked push cannot upload media or create a
deck, so a refusal leaves no trace in the collection.

**Consequence**: one `allow_blocked: bool = False` field on `PushBody`, and a 400
whose `detail` is a structured object rather than a string, so the client can
render the cards.

## R7. Backward compatibility

**Decision**: every new field is optional on the way in and defaulted on the way
out. `parse_cards` accepts a reply with no `type` and no faults. `PushBody`
without `allow_blocked` behaves exactly as today *except* for blocking cards,
which is the intended change.

**Why**: `drafts.json` from earlier versions must load; a custom OpenAI-compatible
endpoint must still work even if it ignores the new schema; and the study-sheet
export must not change shape.

## R8. Performance

**Decision**: single pass per card for per-card rules, plus the bucketed
interference pass. Target under 250 ms for 1,000 cards, asserted in a test with a
generous ceiling so it does not flake on a slow machine.

**Why**: the guard runs on every push, and pushes are already the slowest
operation (AnkiConnect round-trips). Adding a visible delay there would teach the
student to use the override blindly.
