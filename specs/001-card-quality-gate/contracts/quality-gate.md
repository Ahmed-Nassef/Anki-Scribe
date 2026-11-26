# API Contract — Card Quality Gate

Only deltas are described. Existing request fields and response keys are
unchanged.

## 1. `POST /api/generate`

**Request**: unchanged.

**Response**: `cards[]` entries gain two keys.

```json
{
  "cards": [
    {
      "question": "How does metoprolol differ from carvedilol in HFrEF?",
      "answer": "Metoprolol blocks β1 and reduces mortality; carvedilol also blocks α1.",
      "extra": "...", "tags": ["cardiology"], "evidence": "...", "verified": true,
      "type": "compare",
      "faults": []
    }
  ],
  "mode": "basic", "model": "deepseek-chat", "unverified": 0,
  "strict": false, "style": "balanced"
}
```

- `type` — one of the six values; always present.
- `mode` — `basic` or `cloze`; always present, so the card is self-describing.
- `faults` — array, possibly empty; always present.
- All existing keys keep their meaning. A client that ignores the new keys behaves
  exactly as before.

## 2. `POST /api/generate/one`

**Response**: `card` gains the same two keys.

```json
{"card": {"question": "...", "answer": "...", "type": "definition", "faults": []},
 "mode": "basic", "nudge": "improve", "model": "deepseek-chat"}
```

## 3. `POST /api/anki/preflight`

**Request**: unchanged, plus optional override.

```json
{"deck": "Anki Scribe::Cardiology", "cards": [ ... ], "tags": "extra",
 "source_path": "...", "filename": "...", "allow_blocked": false}
```

**Refusal** (when a blocking fault exists and `allow_blocked` is false):

```
HTTP/1.1 400 Bad Request
```

```json
{"detail": {
  "error": "blocked_cards",
  "message": "3 cards have a blocking quality fault.",
  "blocked": [
    {"uid": "c1", "question": "Does metoprolol reduce mortality in heart failure?",
     "faults": [{"code": "answer_leak", "label": "the answer is already in the question",
                 "severity": "blocking", "detail": "yes/no answer"}]}
  ]
}}
```

- `blocked` is capped at 50 entries; `message` always carries the true count.
- When no blocking fault exists, the existing response shape is returned
  unchanged, including duplicates/`canAddNotes` results.

## 4. `POST /api/anki/push`

Identical request and refusal contract. On refusal **nothing is written**: no
deck creation, no media upload, no `addNotes`.

On success the response is unchanged; each ledger entry gains `type`
additively, which later features use to compare review outcomes per card type.

## Invariants

1. A fault's `code` is stable across releases; labels may change.
2. `faults` order is deterministic: blocking first, then by code, then by detail.
3. The guard runs before any AnkiConnect call, so a refusal is side-effect free.
4. `allow_blocked: true` is the only way past a blocking fault; warnings never
   need one.
5. The server never trusts client-sent `type` or `faults` for the decision — it
   recomputes faults from the submitted question/answer/text.
