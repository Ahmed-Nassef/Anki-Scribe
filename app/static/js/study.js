"use strict";

/* Study sheet: in-app reveal, plus PDF and HTML export of the ticked cards */

const CLOZE_PATTERN = /\{\{c\d+::([\s\S]*?)\}\}/g;

const studyState = { items: [], index: 0 };

/* ------------------------------------------------------------------ */
/* card text                                                          */
/* ------------------------------------------------------------------ */

function clozeParts(text) {
  const value = String(text || "");
  const parts = [];
  let last = 0;
  let match;
  CLOZE_PATTERN.lastIndex = 0;
  while ((match = CLOZE_PATTERN.exec(value))) {
    if (match.index > last) {
      parts.push({ type: "text", text: value.slice(last, match.index) });
    }
    const body = match[1];
    const split = body.split("::");
    parts.push({
      type: "blank",
      term: split[0],
      hint: split.slice(1).join("::").trim(),
    });
    last = match.index + match[0].length;
  }
  if (last < value.length) {
    parts.push({ type: "text", text: value.slice(last) });
  }
  return parts;
}

function clozeQuestion(text) {
  return clozeParts(text)
    .map((part) =>
      part.type === "text" ? part.text : part.hint ? `[${part.hint}]` : "[ \u2026 ]"
    )
    .join("");
}

function clozeAnswer(text) {
  return clozeParts(text)
    .map((part) => (part.type === "text" ? part.text : part.term))
    .join("");
}

function studyText(card) {
  if (card.mode === "cloze") {
    const parts = clozeParts(card.text);
    const hasBlank = parts.some((part) => part.type === "blank");
    return {
      question: hasBlank
        ? clozeQuestion(card.text)
        : String(card.text || "").trim(),
      answer: hasBlank ? clozeAnswer(card.text) : "",
      detail: String(card.extra || "").trim(),
    };
  }
  return {
    question: String(card.question || "").trim(),
    answer: String(card.answer || "").trim(),
    detail: String(card.extra || "").trim(),
  };
}

function studyGroups() {
  const groups = new Map();
  for (const card of state.cards) {
    if (!card.selected) continue;
    const source =
      card.source && typeof card.source === "object" ? card.source : {};
    const title = String(source.chapterTitle || "").trim();
    if (!groups.has(title)) groups.set(title, []);
    groups.get(title).push({
      card,
      chapter: title,
      ...studyText(card),
    });
  }
  return groups;
}

function selectedStudyCards() {
  let count = 0;
  for (const card of state.cards) if (card.selected) count += 1;
  return count;
}

function studyTitle() {
  if (!state.doc) return "Study sheet";
  return sourceTitleForDoc();
}

function studyDeck() {
  return (
    (els.deckInput && els.deckInput.value.trim()) ||
    state.settings.default_deck ||
    ""
  );
}

function studyPayload() {
  const groups = studyGroups();
  const mixed = groups.size > 1;
  const sections = [];
  for (const [title, items] of groups) {
    if (!items.length) continue;
    sections.push({
      title: title || (mixed ? "Other cards" : ""),
      cards: items.map((item) => ({
        kind: item.card.mode === "cloze" ? "cloze" : "basic",
        question: item.question || "Untitled card",
        answer: item.answer,
        detail: item.detail,
      })),
    });
  }
  return {
    title: studyTitle(),
    source: state.doc ? state.doc.filename : "",
    deck: studyDeck(),
    generated: new Date().toLocaleDateString(undefined, {
      day: "numeric",
      month: "short",
      year: "numeric",
    }),
    sections,
  };
}

/* ------------------------------------------------------------------ */
/* panel actions                                                      */
/* ------------------------------------------------------------------ */

function updateSheetActions() {
  if (!els.sheetRow) return;
  const count = selectedStudyCards();
  const total = state.cards.length;
  // Triage works on every draft, ticked or not, so the row outlives the ticks.
  els.sheetRow.hidden = total === 0;
  els.studyBtn.disabled = count === 0;
  els.exportPdfBtn.disabled = count === 0;
  els.exportHtmlBtn.disabled = count === 0;
  if (els.triageBtn) {
    els.triageBtn.disabled = total === 0;
    els.triageBtn.textContent = total ? `Triage ${total}` : "Triage";
    els.triageBtn.title = total
      ? "One card at a time: keep, fix or reject"
      : "Generate some cards first";
  }
  if (els.sheetHint) {
    els.sheetHint.textContent = count
      ? `${count} ticked card${count === 1 ? "" : "s"}`
      : total
        ? "nothing ticked"
        : "";
  }
  if (els.planBtn) {
    const available =
      typeof planAvailableItems === "function" ? planAvailableItems() : 0;
    els.planBtn.hidden = !state.doc;
    els.planBtn.disabled = available === 0;
    els.planBtn.title = available
      ? `Build a day-by-day schedule from ${available} study items`
      : "Generate cards or hide an answer first";
  }
  if (els.leechesBtn) els.leechesBtn.hidden = !state.doc;
}

/* ------------------------------------------------------------------ */
/* export                                                             */
/* ------------------------------------------------------------------ */

function studyFileBase() {
  const base = String(studyTitle() || "study sheet")
    .replace(/[\\/:*?"<>|\u0000-\u001f]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return (base || "study sheet").slice(0, 80);
}

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

async function exportStudy(format) {
  const payload = studyPayload();
  if (!payload.sections.length) {
    toast("Tick at least one card first.");
    return;
  }
  const button = format === "pdf" ? els.exportPdfBtn : els.exportHtmlBtn;
  if (!button) return;
  const label = button.textContent;
  button.disabled = true;
  button.textContent = "Saving\u2026";
  try {
    const response = await fetch(`/api/study/${format}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) {
      let message = `Couldn't build the study sheet (HTTP ${response.status}).`;
      const data = await response.json().catch(() => null);
      if (data && data.detail) {
        message =
          typeof data.detail === "string"
            ? data.detail
            : data.detail.map((entry) => entry.msg || String(entry)).join("; ");
      }
      throw new Error(message);
    }
    const blob = await response.blob();
    const name = `${studyFileBase()} - study sheet.${format}`;
    downloadBlob(blob, name);
    toast(
      format === "pdf"
        ? `Saved \u201c${name}\u201d \u2014 click a question to jump to its answer.`
        : `Saved \u201c${name}\u201d \u2014 answers open on click, on any device.`,
      "success",
      8000
    );
  } catch (error) {
    toast(error.message || "Couldn't build the study sheet.", "error", 9000);
  } finally {
    button.textContent = label;
    button.disabled = false;
    updateSheetActions();
  }
}

/* ------------------------------------------------------------------ */
/* study view                                                         */
/* ------------------------------------------------------------------ */

function studyItems() {
  const items = [];
  for (const [, group] of studyGroups()) items.push(...group);
  return items;
}

function openStudy() {
  const items = studyItems();
  if (!items.length) {
    toast("Tick at least one card first.");
    return;
  }
  studyState.items = items;
  studyState.index = 0;
  els.studyTitle.textContent = studyTitle();
  els.studyDialog.showModal();
  renderStudy();
  els.studyReveal.focus();
}

function closeStudy() {
  if (els.studyDialog.open) els.studyDialog.close();
}

function renderStudy() {
  const items = studyState.items;
  const index = clamp(studyState.index, 0, Math.max(0, items.length - 1));
  studyState.index = index;
  const item = items[index];
  if (!item) return;
  const total = items.length;

  els.studyCounter.textContent = `${index + 1} / ${total}`;
  els.studySection.textContent = item.chapter || "Cards";
  els.studyBar.style.width = `${((index + 1) / total) * 100}%`;
  els.studyPrev.disabled = index === 0;
  els.studyNext.disabled = index === total - 1;
  els.studyBody.scrollTop = 0;

  fillStudyQuestion(item.card);
  hideStudyAnswer();
}

function fillStudyQuestion(card) {
  const host = els.studyQuestion;
  host.replaceChildren();
  if (card.mode === "cloze") {
    const parts = clozeParts(card.text);
    if (!parts.some((part) => part.type === "blank")) {
      host.textContent = String(card.text || "");
      return;
    }
    for (const part of parts) {
      if (part.type === "text") {
        host.appendChild(document.createTextNode(part.text));
      } else {
        const blank = document.createElement("span");
        blank.className = "study-blank";
        blank.textContent = part.hint || "\u2026";
        host.appendChild(blank);
      }
    }
    return;
  }
  host.textContent = String(card.question || "");
}

function hideStudyAnswer() {
  const item = studyState.items[studyState.index];
  els.studyAnswer.hidden = true;
  els.studyRevealLabel.textContent = "Show answer";
  els.studyReveal.setAttribute("aria-expanded", "false");
  if (els.studyRevealHint) {
    els.studyRevealHint.textContent = "Space";
  }
  if (item) {
    els.studyAnswerText.textContent = "";
    els.studyDetail.textContent = "";
    els.studyDetail.hidden = true;
  }
}

function showStudyAnswer() {
  const item = studyState.items[studyState.index];
  if (!item) return;
  els.studyAnswerText.textContent =
    item.answer || "No answer was recorded for this card.";
  els.studyDetail.textContent = item.detail || "";
  els.studyDetail.hidden = !item.detail;
  els.studyAnswer.hidden = false;
  els.studyAnswer.classList.remove("is-fresh");
  void els.studyAnswer.offsetWidth;
  els.studyAnswer.classList.add("is-fresh");
  els.studyRevealLabel.textContent = "Hide answer";
  els.studyReveal.setAttribute("aria-expanded", "true");
  els.studyAnswer.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function toggleStudyAnswer() {
  if (els.studyAnswer.hidden) {
    showStudyAnswer();
  } else {
    hideStudyAnswer();
  }
}

function moveStudy(delta) {
  const next = clamp(studyState.index + delta, 0, studyState.items.length - 1);
  if (next === studyState.index) return;
  studyState.index = next;
  renderStudy();
}

function handleStudyKey(event) {
  if (!els.studyDialog.open) return;
  if (event.key === " ") {
    // Space always reveals: a focused Next/Previous button must not eat it.
    event.preventDefault();
    toggleStudyAnswer();
    return;
  }
  if (event.key === "Enter") {
    // Enter still activates whichever button has focus.
    if (event.target.closest("button")) return;
    event.preventDefault();
    toggleStudyAnswer();
    return;
  }
  if (event.key === "ArrowRight" || event.key.toLowerCase() === "j") {
    event.preventDefault();
    moveStudy(1);
    return;
  }
  if (event.key === "ArrowLeft" || event.key.toLowerCase() === "k") {
    event.preventDefault();
    moveStudy(-1);
  }
}
