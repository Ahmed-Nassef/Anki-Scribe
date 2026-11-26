"use strict";

/* Triage: one card at a time, with its source beside it and the answer hidden.
   This is the screen the product actually needs — generation is cheap, deciding
   what to keep is the work. Every decision reuses setCardSelected, so the whole
   pass is undoable one card at a time. */

function triageOrder() {
  const risk = computeRisk();
  // Highest local risk first: the cards most likely to be wrong are the ones
  // worth a student's first minute.
  return state.cards
    .filter((card) => card && card.uid)
    .slice()
    .sort((a, b) => {
      const right = (risk.get(b.uid) || { score: 0 }).score;
      const left = (risk.get(a.uid) || { score: 0 }).score;
      return right - left;
    });
}

function openTriage(options = {}) {
  if (!state.cards.length) {
    toast("Generate some cards first.");
    return;
  }
  let queue = triageOrder();
  if (options.onlyRisky) {
    const risk = computeRisk();
    queue = queue.filter((card) => (risk.get(card.uid) || { score: 0 }).score > 0);
    if (!queue.length) {
      toast("Nothing is flagged. Every card quotes its source.", "success");
      return;
    }
  }
  state.triage = {
    queue: queue.map((card) => card.uid),
    index: 0,
    accepted: 0,
    rejected: 0,
    revealed: false,
    rewriting: false,
  };
  renderTriage();
  if (!els.triageDialog.open) els.triageDialog.showModal();
  els.triageReveal.focus();
}

function closeTriage() {
  if (els.triageDialog.open) els.triageDialog.close();
}

function triageCard() {
  const uid = state.triage.queue[state.triage.index];
  if (!uid) return null;
  return state.cards.find((card) => card.uid === uid) || null;
}

function triageMetaText(card) {
  const parts = [card.mode === "cloze" ? "Cloze" : "Q & A"];
  const deck = cardDeckName(card);
  if (deck) parts.push(deck);
  if (Array.isArray(card.tags) && card.tags.length) parts.push(card.tags.join(", "));
  const blocking = blockingFaults(card);
  const faults = cardFaults(card);
  if (blocking.length) {
    parts.push(`blocked: ${blocking[0].label}`);
  } else if (faults.length) {
    parts.push(`check: ${faults[0].label}`);
  }
  const risk = riskFor(card.uid);
  if (risk.score > 0) parts.push(`flagged: ${risk.reasons[0].label}`);
  return parts.join(" \u00b7 ");
}

function setTriageRevealLabel() {
  els.triageReveal.replaceChildren();
  const label = document.createElement("span");
  label.textContent = state.triage.revealed ? "Hide answer" : "Show answer";
  const kbd = document.createElement("kbd");
  kbd.textContent = "Space";
  const gap = document.createTextNode(" ");
  if (state.triage.revealed) els.triageReveal.append(kbd, gap, label);
  else els.triageReveal.append(label, gap, kbd);
  els.triageReveal.setAttribute("aria-expanded", String(state.triage.revealed));
  els.triageReveal.classList.toggle("is-revealed", state.triage.revealed);
}

function setTriageRewriteBusy(busy) {
  if (!els.triageRewrite) return;
  els.triageRewrite.classList.toggle("is-busy", busy);
  els.triageRewrite.querySelectorAll("button").forEach((button) => {
    button.disabled = busy;
  });
  const label = els.triageRewrite.querySelector(".triage-rewrite-label");
  if (label) label.textContent = busy ? "Rewriting\u2026" : "Rewrite";
}

function applyRewrittenCard(card, data) {
  const next = data.card || {};
  if (data.mode === "cloze") {
    card.mode = "cloze";
    card.text = next.text || "";
    card.question = "";
    card.answer = "";
  } else {
    card.mode = "basic";
    card.question = next.question || card.question || "";
    card.answer = next.answer || card.answer || "";
    card.text = "";
  }
  if (next.extra !== undefined) card.extra = next.extra;
  if (next.evidence) card.evidence = next.evidence;
  card.verified = next.verified;
}

/* Rewrite the card on screen from the quote it was built on. The quote is
   already verbatim from the source, so the rewrite cannot drift outside it. */
async function regenerateTriageCard(nudge) {
  const card = triageCard();
  if (!card || state.triage.rewriting) return;
  const source = card.source && typeof card.source === "object" ? card.source : {};
  const excerpt = String(card.evidence || source.evidence || "").trim();
  if (excerpt.length < MIN_CHARS) {
    toast("This card has no saved quote to rewrite from.", "error", 7000);
    return;
  }

  const docId = state.doc ? state.doc.id : "";
  const before = snapshotCard(card);
  state.triage.rewriting = true;
  setTriageRewriteBusy(true);
  try {
    const data = await api("/api/generate/one", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        text: excerpt,
        mode: card.mode,
        nudge,
        question: card.question || "",
        answer: card.answer || "",
        cloze_text: card.mode === "cloze" ? card.text || "" : "",
        filename: state.doc ? state.doc.filename : null,
        style: state.style,
      }),
    });
    if (!state.doc || state.doc.id !== docId) return;
    applyRewrittenCard(card, data);
    pushUndo({ type: "replace", uid: card.uid, before, after: snapshotCard(card) });
    state.triage.revealed = true;
    updateCardsMeta();
    renderTriage();
  } catch (error) {
    toast(error.message, "error", 8000);
  } finally {
    state.triage.rewriting = false;
    setTriageRewriteBusy(false);
  }
}

function renderTriage() {
  const queue = state.triage.queue;
  // A card can disappear while the pass is open; skip anything that vanished.
  while (state.triage.index < queue.length && !triageCard()) {
    state.triage.index += 1;
  }
  if (state.triage.index >= queue.length) {
    finishTriage();
    return;
  }

  const card = triageCard();
  if (!card) {
    finishTriage();
    return;
  }

  const total = queue.length;
  const position = state.triage.index + 1;
  els.triageCounter.textContent = `${position} / ${total}`;
  els.triageBar.style.width = `${Math.round((position / total) * 100)}%`;

  const source = card.source && typeof card.source === "object" ? card.source : {};
  els.triageSourceLabel.textContent = source.label || source.file || "Source";
  const quote = String(card.evidence || source.evidence || source.quote || "").trim();
  els.triageQuote.textContent = quote ? `\u201c${quote}\u201d` : "No quote was saved for this card.";
  els.triageQuote.classList.toggle("is-empty", !quote);

  const text = studyText(card);
  els.triageQuestion.textContent = text.question;
  els.triageAnswer.textContent = text.answer;
  els.triageDetail.textContent = text.detail;
  els.triageDetail.hidden = !text.detail;
  els.triageAnswerWrap.hidden = !state.triage.revealed;
  els.triageMeta.textContent = triageMetaText(card);
  setTriageRevealLabel();
  const clozeButton = els.triageRewrite.querySelector('[data-nudge="cloze"]');
  if (clozeButton) clozeButton.hidden = card.mode === "cloze";
  setTriageRewriteBusy(Boolean(state.triage.rewriting));
}

function toggleTriageAnswer() {
  state.triage.revealed = !state.triage.revealed;
  els.triageAnswerWrap.hidden = !state.triage.revealed;
  setTriageRevealLabel();
}

function triageMove(delta) {
  state.triage.index = clamp(
    state.triage.index + delta,
    0,
    state.triage.queue.length
  );
  state.triage.revealed = false;
  if (state.triage.index >= state.triage.queue.length) {
    finishTriage();
    return;
  }
  renderTriage();
}

function triageDecide(keep) {
  const card = triageCard();
  if (!card) {
    triageMove(1);
    return;
  }
  setCardSelected(card.uid, keep);
  if (keep) state.triage.accepted += 1;
  else state.triage.rejected += 1;
  updateCardsMeta();
  updatePushLabel();
  triageMove(1);
}

function finishTriage() {
  const { accepted, rejected } = state.triage;
  closeTriage();
  renderCards();
  if (accepted || rejected) {
    toast(
      `Triage done \u2014 ${accepted} kept, ${rejected} rejected.`,
      "success",
      6000
    );
  }
}

function triageLocateSource() {
  const card = triageCard();
  if (!card) return;
  closeTriage();
  locateCardSource(card, null);
}

function triageBulk(keep) {
  const queue = state.triage.queue;
  for (let index = state.triage.index; index < queue.length; index += 1) {
    const card = state.cards.find((item) => item.uid === queue[index]);
    if (!card) continue;
    const matches = keep ? card.verified !== false : card.verified === false;
    if (!matches) continue;
    setCardSelected(card.uid, keep);
    if (keep) state.triage.accepted += 1;
    else state.triage.rejected += 1;
  }
  state.triage.index = queue.length;
  updateCardsMeta();
  updatePushLabel();
  finishTriage();
}

function handleTriageKey(event) {
  if (!els.triageDialog.open) return;
  if (event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
  const key = event.key;
  if (key === " " || key === "Spacebar") {
    event.preventDefault();
    toggleTriageAnswer();
    return;
  }
  const lower = key.toLowerCase();
  if (lower === "a" && event.shiftKey) {
    event.preventDefault();
    triageBulk(true);
    return;
  }
  if (lower === "x" && event.shiftKey) {
    event.preventDefault();
    triageBulk(false);
    return;
  }
  if (lower === "a") {
    event.preventDefault();
    triageDecide(true);
    return;
  }
  if (lower === "x") {
    event.preventDefault();
    triageDecide(false);
    return;
  }
  if (lower === "r") {
    event.preventDefault();
    regenerateTriageCard("improve");
    return;
  }
  if (lower === "u") {
    event.preventDefault();
    undoLast();
    renderTriage();
    return;
  }
  if (lower === "j" || key === "ArrowRight" || key === "ArrowDown") {
    event.preventDefault();
    triageMove(1);
    return;
  }
  if (lower === "k" || key === "ArrowLeft" || key === "ArrowUp") {
    event.preventDefault();
    triageMove(-1);
  }
}
