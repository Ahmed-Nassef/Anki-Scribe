# Quickstart — Card Quality Gate

## Automated

```bat
cd C:\Users\mahmo\Desktop\projects\anki-scribe
.venv\Scripts\python.exe -m pytest -q
```

New coverage:

```bat
.venv\Scripts\python.exe -m pytest -q tests\test_cards_quality.py
```

## Manual, in the app

1. Start the app: `.venv\Scripts\python.exe run.py` (Anki does not need to run).
2. Open a lecture and select a paragraph; click **Generate cards**.
3. In Review, every card now shows a type word (`mechanism`, `compare`, …) and,
   where relevant, a fault chip such as **answer repeats the question**.
4. The review header shows the mix, e.g.
   `12 cards · 7 definition · 3 mechanism · 2 compare`.
5. Introduce a defect on purpose: edit a question to `Does metoprolol reduce
   mortality in heart failure?` and its answer to `Yes, it does.` The card is
   not re-checked until push — that is expected (see research R1).
6. Click **Send to Anki** with that card selected. Nothing is sent; a dialog
   names the card and the fault, and offers **Send anyway**.
7. Confirm Anki received nothing (no new deck, no notes).
8. Click **Send anyway**; the batch is written exactly as before.

## Manual, via the API

```bat
curl -s -X POST http://127.0.0.1:8777/api/anki/push ^
  -H "Content-Type: application/json" ^
  -d "{\"deck\":\"Test\",\"cards\":[{\"uid\":\"a\",\"mode\":\"basic\",\"question\":\"What does metoprolol do?\",\"answer\":\"Metoprolol is a beta blocker.\",\"tags\":[\"x\"]}]}"
```

Expect `400` with `detail.error = "blocked_cards"`. Add `"allow_blocked": true`
and the same request proceeds (Anki must be running, or it fails with the usual
AnkiConnect error instead).

## What "done" looks like

- Every generated card has a type and a fault list.
- A card that leaks its answer cannot reach Anki without an explicit override.
- Clean cards are not blocked, and old drafts still load and push.
- The full suite is green, including the 268 pre-existing tests.

## Verification, 2026-11-21

- `pytest`: 334 tests green, including 44 rule tests, 7 guard/API tests and
  15 generation tests added by this feature.
- `node --check` on every patched script: clean.
- Live run on port 8823 against the real Anki build:
  - `GET /` serves the override button.
  - A leaking card: `400` with `{"error":"blocked_cards","message":"1 card has a
    blocking quality fault."}` and the card listed — while Anki was running, so
    the refusal demonstrably happened before any AnkiConnect call.
  - A clean card: `200`, note created, which is how we proved the gate is not
    what stops valid cards. That test note and the empty deck it created were
    deleted afterwards, and the deck count is back to 117.
