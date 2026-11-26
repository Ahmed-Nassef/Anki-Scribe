# Data Model — Card Quality Gate

Everything here is additive to the existing card dictionary. No existing field
changes meaning.

## CardType

A closed vocabulary. Values are lower-case strings, stored as-is.

| Type | The card tests | Typical front |
| --- | --- | --- |
| `definition` | what a term means or what it is | "What is preload?" |
| `mechanism` | why something happens, or what it causes | "Why does a β1 blocker lower mortality in HFrEF?" |
| `compare` | discrimination between two confusable things | "How does metoprolol differ from carvedilol in HFrEF?" |
| `application` | transferring the fact to a scenario | a two-line vignette |
| `enumeration` | completeness of a list | cloze over the list, context intact |
| `number` | a value with unit and condition | "At what dose does X start?" |

- `DEFAULT_TYPE = "definition"`.
- Unknown, missing or non-string values are normalised to `DEFAULT_TYPE` on read;
  this is not a fault, because it keeps old cards and permissive endpoints valid.
- The type is written by the generator and preserved through editing, drafts,
  push and the ledger. It is never inferred from the card text.

## Fault

```json
{"code": "answer_leak", "label": "the answer repeats the question", "severity": "blocking", "detail": "metoprolol"}
```

- `code` — stable identifier, English, snake_case. Callers match on this.
- `label` — short human sentence, shown to the student. May change wording.
- `severity` — `blocking` | `warning` | `info`.
- `detail` — optional string locating the problem (the offending token, the
  deletion length). Never contains page text.

Faults are returned in a deterministic order: blocking first, then by code, so the
UI and tests can compare lists directly.

## Card (delta)

```json
{
  "uid": "...", "mode": "basic",
  "question": "...", "answer": "...", "extra": "...", "tags": ["..."],
  "evidence": "...", "verified": true,
  "type": "mechanism",
  "faults": [{"code": "...", "label": "...", "severity": "...", "detail": "..."}]
}
```

- `type` — always present on cards returned by generation; may be absent on cards
  loaded from an older `drafts.json`.
- `faults` — always present in API responses (`[]` when clean). Not stored, not
  sent back by the client.

Cloze cards differ only in carrying `text` instead of `question`/`answer`.
- Generated cards also carry `mode`, so a rule can tell a cloze card from a
  question/answer card before the browser assigns one.

## Blocked report

The guard's payload, produced by `blocked_cards()`:

```json
{"count": 3,
 "cards": [{"uid": "c1", "question": "Does metoprolol reduce mortality?",
            "faults": [{"code": "answer_leak", "label": "...",
                         "severity": "blocking", "detail": "yes/no answer"}]}]}
```

`count` is the true number; `cards` is capped so one bad run cannot produce a
huge response.

## Quality policy

One constant table in `cards_quality.py`. Tests import it; nothing else may
hard-code a threshold.

| Constant | Value | Used by |
| --- | --- | --- |
| `MAX_CLOZE_DELETIONS` | 3 | `cloze_overloaded` |
| `MAX_DELETION_WORDS` | 8 | `cloze_overloaded` |
| `MIN_QUESTION_WORDS` | 5 | `vague_question` |
| `RESTATEMENT_RATIO` | 0.8 | `answer_leak` |
| `INTERFERENCE_JACCARD` | 0.8 | `interference_pair` |
| `MAX_INTERFERENCE_BUCKET` | 40 | interference cost cap |
| `MAX_INTERFERENCE_COMPARISONS` | 20 000 | interference cost cap |

## Rules

| Code | Severity | Condition | Applies to | Skipped when |
| --- | --- | --- | --- | --- |
| `empty_side` | blocking | Required side is blank after cleaning: `question` or `answer` for basic, `text` for cloze | both | never |
| `open_ended` | blocking | Question begins with an English imperative from the fixed list (explain, describe, discuss, list, outline, summarise, compare and contrast) or contains "which of the following" | basic | question is empty or non-English opening |
| `answer_leak` | blocking | Answer is a bare yes/no; or all of the answer's content tokens (≥ 2) appear in the question; or ≥ 80% of the question's content tokens (≥ 3) appear in the answer | basic | either side empty |
| `cloze_overloaded` | blocking | More than 3 deletions, or any single deletion longer than 8 words | cloze | no deletions found |
| `list_answer` | warning | Answer contains " and " plus at least two comma/semicolon separated items, or contains "such as"/"including" with ≥3 items | basic | answer shorter than 4 content tokens |
| `vague_question` | warning | Fewer than 5 words, or ends with "this?", "these?", "the text", "the excerpt", "the document" | basic | cloze |
| `bare_number` | warning | The answer is only a numeral (optionally with a currency symbol) and has no unit token | basic | answer has letters |
| `untagged` | warning | `tags` is missing or empty | both | never |
| `interference_pair` | warning | Two cards in the submitted batch have fronts with Jaccard ≥ 0.8 | both | batch smaller than 2 |

Rules are pure: same input, same output, no I/O, no clock, no random.

## Compatibility

| Input | Behaviour |
| --- | --- |
| Card with no `type` | read as `definition`; not a fault |
| Card with no `faults` | faults computed from scratch |
| Old `drafts.json` record | loads unchanged; new fields absent |
| Old `sent.json` record | loads unchanged; `type` absent |
| Model reply without `type` | cards accepted, typed `definition` |
| Model reply without new fields | accepted; contract unchanged for callers |
