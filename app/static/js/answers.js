"use strict";

/* Hide card answers on the PDF page itself.
 *
 * The server returns page-relative rectangles for the answer text of every
 * card (and for text the student selected by hand). This module overlays them
 * on the page image. Clicking a blank reveals it; the rest of the slide —
 * title, table, bullet list — is untouched.
 */

const ANSWER_PREF_KEY = "ankiScribeHideAnswers";

function resetAnswers() {
  if (state.answers.refreshTimer) clearTimeout(state.answers.refreshTimer);
  if (state.answers.saveTimer) {
    clearTimeout(state.answers.saveTimer);
    state.answers.saveTimer = null;
    // A manual hide made in the last few hundred milliseconds still belongs to
    // the document that is about to close; write it before the path changes.
    saveManualMasks();
  }
  const preferred =
    typeof localStorage !== "undefined" &&
    localStorage.getItem(ANSWER_PREF_KEY) === "1";
  state.answers = {
    active: preferred,
    loading: false,
    request: 0,
    manualRequest: 0,
    masks: [],
    manual: [],
    aiMasks: [],
    aiLoading: false,
    path: "",
    revealed: new Set(),
    signature: "",
    refreshTimer: null,
    saveTimer: null,
    warningAt: 0,
    emptyNotified: false,
  };
  clearAnswerLayers();
}

function prepareAnswersForDocument(doc) {
  if (!doc || doc.kind === "transcript") {
    state.answers.active = false;
    clearAnswerLayers();
    updateAnswerToolbar();
    return;
  }
  state.answers.active =
    typeof localStorage !== "undefined" &&
    localStorage.getItem(ANSWER_PREF_KEY) === "1";
  els.pages.classList.toggle("is-hiding-answers", state.answers.active);
  updateAnswerToolbar();
  loadManualMasks(doc);
  if (state.answers.active) scheduleAnswerRefresh(0);
}

/* ------------------------------------------------------------------ */
/* toolbar                                                            */
/* ------------------------------------------------------------------ */

function answerMaskCount() {
  return (
    state.answers.masks.length +
    state.answers.aiMasks.length +
    state.answers.manual.length
  );
}

function revealedAnswerCount() {
  let count = 0;
  for (const mask of state.answers.masks) {
    if (state.answers.revealed.has(String(mask.id))) count += 1;
  }
  for (const mask of state.answers.aiMasks) {
    if (state.answers.revealed.has(String(mask.id))) count += 1;
  }
  for (const mask of state.answers.manual) {
    if (state.answers.revealed.has(String(mask.id))) count += 1;
  }
  return count;
}

function updateAnswerToolbar() {
  if (!els.hideAnswersBtn) return;
  const available = Boolean(state.doc) && state.doc.kind !== "transcript";
  const active = Boolean(state.answers.active) && available;
  const count = answerMaskCount();
  const revealed = revealedAnswerCount();

  els.hideAnswersBtn.hidden = !available;
  els.hideAnswersBtn.setAttribute("aria-pressed", active ? "true" : "false");
  els.hideAnswersBtn.classList.toggle("is-active", active);
  els.hideAnswersBtn.title = active
    ? "Show the page normally; answers stay hidden until you turn this back on"
    : "Hide the answers your cards point at on the page; click a blank to reveal it";
  els.hideAnswersLabel.textContent = state.answers.loading
    ? "Finding answers\u2026"
    : active
      ? "Answers hidden"
      : "Hide answers";
  els.hideAnswersCount.textContent = String(count);
  els.hideAnswersCount.hidden = !(active && count > 0);
  els.revealAnswersBtn.hidden = !active || count === 0;
  els.revealAnswersBtn.textContent =
    count > 0 && revealed >= count ? "Hide all" : "Reveal all";
  els.revealAnswersBtn.title =
    count > 0 && revealed >= count
      ? "Hide every answer again"
      : "Reveal every hidden answer on the pages";
  els.clearMasksBtn.hidden = state.answers.manual.length === 0;
  if (els.aiAnswersBtn) {
    const gaps = answerGapCount();
    els.aiAnswersBtn.hidden = !active || gaps === 0;
    els.aiAnswersBtn.disabled =
      Boolean(state.answers.aiLoading) || Boolean(state.answers.loading);
    els.aiAnswersLabel.textContent = state.answers.aiLoading
      ? "AI finding\u2026"
      : `AI fill ${gaps}`;
    els.aiAnswersBtn.title =
      "Use DeepSeek to find exact answers the local matcher missed; " +
      "it sends the page text to DeepSeek";
  }
  if (els.toolbarHint) {
    els.toolbarHint.textContent = active
      ? "Click a blank to reveal it \u00b7 click it again to hide \u00b7 R reveal all \u00b7 H hide all"
      : "Drag over the page to select text \u00b7 click Select page for a whole slide";
  }
  els.pages.classList.toggle("is-hiding-answers", active);
  if (els.answerLegend) els.answerLegend.hidden = !(active && count > 0);
  updateHideSelectionButton();
  if (typeof updateStudyHud === "function") updateStudyHud();
}

function updateHideSelectionButton() {
  if (!els.hideSelectionBtn) return;
  const available = Boolean(state.doc) && state.doc.kind !== "transcript";
  let inside = false;
  const selection = window.getSelection();
  if (selection && !selection.isCollapsed && selection.rangeCount) {
    const anchor = selection.anchorNode;
    const focus = selection.focusNode;
    inside = Boolean(
      anchor &&
        focus &&
        els.pages.contains(anchor) &&
        els.pages.contains(focus) &&
        String(selection).trim()
    );
  }
  const panelSelection = Boolean(
    state.selection &&
      state.selection.text &&
      Array.isArray(state.selection.location) &&
      state.selection.location.some(
        (entry) => entry && Number.isInteger(Number(entry.page))
      )
  );
  els.hideSelectionBtn.hidden = !available || !(inside || panelSelection);
}

/* ------------------------------------------------------------------ */
/* automatic masks from cards                                         */
/* ------------------------------------------------------------------ */

function answerSourcePages(source) {
  if (!source || typeof source !== "object") return [];
  if (Array.isArray(source.pages) && source.pages.length) {
    const pages = source.pages
      .slice(0, 2)
      .map((page) => Number(page))
      .filter((page) => Number.isInteger(page) && page >= 0);
    if (pages.length) return pages;
  }
  if (Array.isArray(source.location)) {
    const pages = source.location
      .map((entry) => Number(entry && entry.page))
      .filter((page) => Number.isInteger(page) && page >= 0);
    if (pages.length) return [Math.min(...pages), Math.max(...pages)];
  }
  return [];
}

function answerCardsPayload() {
  const seen = new Set();
  const cards = [];
  for (const card of sourceCards()) {
    if (!card || typeof card !== "object") continue;
    const uid = String(card.uid || card.id || "");
    if (!uid || seen.has(uid)) continue;
    seen.add(uid);
    if (card.mode === "figure") continue;
    // The review tick is the student's "study this one" decision; an unticked
    // card should not punch a hole in the page. Sent cards have no tick and
    // have already been accepted, so they stay in.
    if (card.selected === false) continue;
    const source = card.source && typeof card.source === "object" ? card.source : {};
    const pages = answerSourcePages(source);
    if (!pages.length) continue;
    const clozeText = card.mode === "cloze" ? String(card.text || card.question || "") : "";
    cards.push({
      uid,
      mode: card.mode === "cloze" ? "cloze" : "basic",
      type: String(card.type || "").slice(0, 40),
      text: clozeText.slice(0, 8000),
      question: String(card.question || "").slice(0, 8000),
      answer: String(card.answer || "").slice(0, 8000),
      source: {
        pages,
        quote: String(source.quote || card.evidence || "").slice(0, 4000),
        evidence: String(source.evidence || card.evidence || "").slice(0, 4000),
      },
    });
    if (cards.length >= 2000) break;
  }
  return cards;
}

function answerGapCards() {
  const masked = new Set();
  for (const mask of state.answers.masks) {
    for (const uid of mask.uids || []) masked.add(String(uid));
  }
  for (const mask of state.answers.aiMasks) {
    for (const uid of mask.uids || []) masked.add(String(uid));
  }
  return answerCardsPayload().filter((card) => !masked.has(String(card.uid)));
}

function answerGapCount() {
  return answerGapCards().length;
}

async function fillAnswerGapsWithAI() {
  if (!state.doc || state.doc.kind === "transcript" || !state.answers.active) return;
  const gaps = answerGapCards();
  if (!gaps.length) {
    toast("Every card already has a hidden answer.", "info", 3500);
    return;
  }
  const batch = gaps.slice(0, 80);
  const doc = state.doc;
  state.answers.aiLoading = true;
  updateAnswerToolbar();
  try {
    const data = await api(
      `/api/documents/${encodeURIComponent(doc.id)}/ai-answer-masks`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cards: batch }),
      }
    );
    if (!state.doc || state.doc.id !== doc.id) return;
    const byId = new Map(
      state.answers.aiMasks.map((mask) => [String(mask.id), mask])
    );
    for (const mask of data.masks || []) {
      if (mask && mask.id) byId.set(String(mask.id), mask);
    }
    state.answers.aiMasks = [...byId.values()];
    pruneRevealedAnswers();
    renderAllAnswerLayers();
    updateAnswerToolbar();
    const added = Array.isArray(data.masks) ? data.masks.length : 0;
    if (added) {
      toast(
        `AI hid ${added} more answer${added === 1 ? "" : "s"}.`,
        "success",
        4500
      );
    } else {
      toast(
        "AI found no additional exact quotes. Those answers may be paraphrased on the page.",
        "info",
        6000
      );
    }
    if (gaps.length > batch.length) {
      toast(
        `Filled the first ${batch.length} gaps; click AI fill again for the rest.`,
        "info",
        5500
      );
    }
  } catch (error) {
    toast(`AI couldn't find answers: ${error.message}`, "error", 8000);
  } finally {
    state.answers.aiLoading = false;
    updateAnswerToolbar();
  }
}

function scheduleAnswerRefresh(delay = 450) {
  if (!state.answers.active || !state.doc || state.doc.kind === "transcript") return;
  if (state.answers.refreshTimer) clearTimeout(state.answers.refreshTimer);
  state.answers.refreshTimer = setTimeout(() => {
    state.answers.refreshTimer = null;
    refreshAnswerMasks();
  }, delay);
}

async function refreshAnswerMasks() {
  const doc = state.doc;
  if (!doc || doc.kind === "transcript" || !state.answers.active) return;
  const cards = answerCardsPayload();
  const signature = JSON.stringify(cards);
  if (!cards.length) {
    if (signature !== state.answers.signature) state.answers.aiMasks = [];
    state.answers.masks = [];
    state.answers.signature = signature;
    state.answers.loading = false;
    pruneRevealedAnswers();
    renderAllAnswerLayers();
    updateAnswerToolbar();
    if (!state.answers.manual.length && !state.answers.emptyNotified) {
      state.answers.emptyNotified = true;
      toast(
        "No card answers to hide yet. Generate cards, or select text and press Hide selection.",
        "info",
        6000
      );
    }
    return;
  }
  if (signature === state.answers.signature && !state.answers.loading) {
    renderAllAnswerLayers();
    updateAnswerToolbar();
    return;
  }

  const request = state.answers.request + 1;
  state.answers.request = request;
  if (signature !== state.answers.signature) state.answers.aiMasks = [];
  state.answers.loading = true;
  updateAnswerToolbar();
  try {
    const data = await api(
      `/api/documents/${encodeURIComponent(doc.id)}/answer-masks`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cards }),
      }
    );
    if (
      !state.doc ||
      state.doc.id !== doc.id ||
      state.answers.request !== request ||
      !state.answers.active
    ) {
      return;
    }
    state.answers.masks = Array.isArray(data.masks)
      ? data.masks.filter(
          (mask) =>
            mask &&
            Number.isInteger(Number(mask.page)) &&
            Array.isArray(mask.boxes)
        )
      : [];
    state.answers.signature = signature;
    state.answers.emptyNotified = false;
    pruneRevealedAnswers();
    renderAllAnswerLayers();
    if (!state.answers.masks.length && !state.answers.manual.length) {
      toast(
        "No card answers found on these pages yet. Select the text you want to hide instead.",
        "info",
        6500
      );
    }
  } catch (error) {
    if (state.doc && state.doc.id === doc.id && state.answers.request === request) {
      toast(`Couldn't find the answers on the page: ${error.message}`, "error", 8000);
    }
  } finally {
    if (state.answers.request === request) {
      state.answers.loading = false;
      updateAnswerToolbar();
    }
  }
}

function pruneRevealedAnswers() {
  const ids = new Set();
  for (const mask of state.answers.masks) ids.add(mask.id);
  for (const mask of state.answers.aiMasks) ids.add(mask.id);
  for (const mask of state.answers.manual) ids.add(mask.id);
  state.answers.revealed = new Set(
    [...state.answers.revealed].filter((id) => ids.has(id))
  );
}

/* ------------------------------------------------------------------ */
/* manual masks                                                       */
/* ------------------------------------------------------------------ */

async function loadManualMasks(doc) {
  const path = sourcePathForDraft(doc);
  if (!path) return;
  state.answers.path = path;
  state.answers.manual = [];
  const request = state.answers.manualRequest + 1;
  state.answers.manualRequest = request;
  try {
    const data = await api(`/api/masks?path=${encodeURIComponent(path)}`);
    if (
      !state.doc ||
      state.doc.id !== doc.id ||
      state.answers.manualRequest !== request
    ) {
      return;
    }
    state.answers.manual = Array.isArray(data.masks)
      ? data.masks.filter(
          (mask) =>
            mask &&
            typeof mask.id === "string" &&
            Array.isArray(mask.boxes) &&
            mask.boxes.length
        )
      : [];
    renderAllAnswerLayers();
    updateAnswerToolbar();
    if (typeof updatePlanAvailability === "function") updatePlanAvailability();
    if (typeof updateSheetActions === "function") updateSheetActions();
  } catch (error) {
    console.warn("Couldn't load hidden text", error);
  }
}

function scheduleManualMaskSave() {
  if (state.answers.saveTimer) clearTimeout(state.answers.saveTimer);
  state.answers.saveTimer = setTimeout(() => {
    state.answers.saveTimer = null;
    saveManualMasks();
  }, 350);
}

async function saveManualMasks({ beacon = false } = {}) {
  if (!state.answers.path || !state.doc) return;
  const body = JSON.stringify({
    path: state.answers.path,
    masks: state.answers.manual,
  });
  if (
    beacon &&
    body.length < 60_000 &&
    typeof navigator !== "undefined" &&
    navigator.sendBeacon
  ) {
    const blob = new Blob([body], { type: "application/json" });
    if (navigator.sendBeacon("/api/masks", blob)) return;
  }
  try {
    await api("/api/masks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body,
    });
  } catch (error) {
    const now = Date.now();
    if (now - state.answers.warningAt > 30_000) {
      state.answers.warningAt = now;
      toast(`Couldn't save the hidden text: ${error.message}`, "error", 8000);
    }
  }
}

function flushManualMasks({ beacon = false } = {}) {
  if (state.answers.saveTimer) {
    clearTimeout(state.answers.saveTimer);
    state.answers.saveTimer = null;
  }
  if (state.answers.path) saveManualMasks({ beacon });
}

function mergeClientBoxes(boxes) {
  const cleaned = [];
  for (const box of boxes) {
    let merged = false;
    for (const existing of cleaned) {
      if (existing.page !== box.page) continue;
      const left = Math.max(existing.x, box.x);
      const top = Math.max(existing.y, box.y);
      const right = Math.min(existing.x + existing.w, box.x + box.w);
      const bottom = Math.min(existing.y + existing.h, box.y + box.h);
      if (right <= left || bottom <= top) continue;
      const intersection = (right - left) * (bottom - top);
      const smaller = Math.min(existing.w * existing.h, box.w * box.h);
      if (intersection / Math.max(1e-9, smaller) < 0.55) continue;
      const x0 = Math.min(existing.x, box.x);
      const y0 = Math.min(existing.y, box.y);
      const x1 = Math.max(existing.x + existing.w, box.x + box.w);
      const y1 = Math.max(existing.y + existing.h, box.y + box.h);
      existing.x = x0;
      existing.y = y0;
      existing.w = x1 - x0;
      existing.h = y1 - y0;
      merged = true;
      break;
    }
    if (!merged) cleaned.push({ ...box });
  }
  if (cleaned.length > 120) cleaned.length = 120;
  return cleaned;
}

function addManualMaskFromSelection() {
  const selection = window.getSelection();
  let text = "";
  const boxes = [];
  const anchor = selection ? selection.anchorNode : null;
  const focus = selection ? selection.focusNode : null;
  const nativeInside = Boolean(
    selection &&
      !selection.isCollapsed &&
      selection.rangeCount &&
      anchor &&
      focus &&
      els.pages.contains(anchor) &&
      els.pages.contains(focus)
  );

  if (nativeInside) {
    text = String(selection)
      .replace(/\s+/g, " ")
      .trim()
      .slice(0, 500);
    const pageEls = Array.from(els.pages.querySelectorAll(".page"));
    for (const pageEl of pageEls) {
      const pageRect = pageEl.getBoundingClientRect();
      if (!pageRect.width || !pageRect.height) continue;
      const pageIndex = Number(pageEl.dataset.page);
      if (!Number.isInteger(pageIndex)) continue;
      for (let index = 0; index < selection.rangeCount; index += 1) {
        const rects = selection.getRangeAt(index).getClientRects();
        for (const rect of rects) {
          const left = Math.max(rect.left, pageRect.left);
          const top = Math.max(rect.top, pageRect.top);
          const right = Math.min(rect.right, pageRect.right);
          const bottom = Math.min(rect.bottom, pageRect.bottom);
          if (right - left < 2 || bottom - top < 2) continue;
          const pad = 1.5;
          const x = clamp((left - pageRect.left - pad) / pageRect.width, 0, 1);
          const y = clamp((top - pageRect.top - pad) / pageRect.height, 0, 1);
          const x1 = clamp((right - pageRect.left + pad) / pageRect.width, 0, 1);
          const y1 = clamp((bottom - pageRect.top + pad) / pageRect.height, 0, 1);
          if (x1 - x <= 0 || y1 - y <= 0) continue;
          boxes.push({
            page: pageIndex,
            x: Math.round(x * 10000) / 10000,
            y: Math.round(y * 10000) / 10000,
            w: Math.round((x1 - x) * 10000) / 10000,
            h: Math.round((y1 - y) * 10000) / 10000,
          });
        }
      }
    }
  } else if (
    state.selection &&
    state.selection.text &&
    Array.isArray(state.selection.location)
  ) {
    // "Select page" clears the native range on purpose, so fall back to the
    // line numbers the app already recorded for the selection panel.
    text = String(state.selection.text).replace(/\s+/g, " ").trim().slice(0, 500);
    for (const entry of state.selection.location) {
      const pageIndex = Number(entry && entry.page);
      const indices = Array.isArray(entry && entry.indices) ? entry.indices : [];
      const model = state.models.get(pageIndex);
      if (!model || !Array.isArray(model.lines) || !model.width || !model.height) {
        continue;
      }
      for (const rawIndex of indices) {
        const line = model.lines[Number(rawIndex)];
        if (!line) continue;
        const pad = 1.5;
        const x = clamp((Number(line.x0) - pad) / model.width, 0, 1);
        const y = clamp((Number(line.y0) - pad) / model.height, 0, 1);
        const x1 = clamp((Number(line.x1) + pad) / model.width, 0, 1);
        const y1 = clamp((Number(line.y1) + pad) / model.height, 0, 1);
        if (x1 - x <= 0 || y1 - y <= 0) continue;
        boxes.push({
          page: pageIndex,
          x: Math.round(x * 10000) / 10000,
          y: Math.round(y * 10000) / 10000,
          w: Math.round((x1 - x) * 10000) / 10000,
          h: Math.round((y1 - y) * 10000) / 10000,
        });
      }
    }
  }

  if (!text) {
    toast("Select the answer text on the page first.", "info", 4500);
    return;
  }
  if (!boxes.length) {
    toast("Couldn't measure that selection. Try selecting it again.", "error", 5000);
    return;
  }
  const mask = {
    id: `manual-${uid()}`,
    text,
    boxes: mergeClientBoxes(boxes),
    createdAt: Date.now(),
  };
  state.answers.manual.push(mask);
  if (!state.answers.active) {
    setHideAnswers(true, { persist: true });
  } else {
    renderAllAnswerLayers();
  }
  scheduleManualMaskSave();
  updateAnswerToolbar();
  if (typeof updatePlanAvailability === "function") updatePlanAvailability();
  if (typeof updateSheetActions === "function") updateSheetActions();
  clearSelection();
  toast(`Hid the selected text. Click it to reveal.`, "success", 3500);
}

function clearManualMasks() {
  if (!state.answers.manual.length) return;
  if (!window.confirm("Remove the text you hid by hand on this file?")) return;
  const removed = new Set(state.answers.manual.map((mask) => mask.id));
  state.answers.manual = [];
  state.answers.revealed = new Set(
    [...state.answers.revealed].filter((id) => !removed.has(id))
  );
  if (state.answers.path) {
    api(`/api/masks?path=${encodeURIComponent(state.answers.path)}`, {
      method: "DELETE",
    }).catch((error) => {
      toast(`Couldn't remove the hidden text: ${error.message}`, "error", 7000);
    });
  }
  renderAllAnswerLayers();
  updateAnswerToolbar();
  if (typeof updatePlanAvailability === "function") updatePlanAvailability();
  if (typeof updateSheetActions === "function") updateSheetActions();
  toast("Removed the text you hid by hand.", "info", 3000);
}

/* ------------------------------------------------------------------ */
/* rendering                                                          */
/* ------------------------------------------------------------------ */

function answerLayerForPage(model) {
  if (!model || !model.el) return null;
  let layer = model.el.querySelector(".answer-layer");
  if (!layer) {
    layer = document.createElement("div");
    layer.className = "answer-layer";
    layer.setAttribute("role", "group");
    layer.setAttribute("aria-label", "Hidden answers on this page");
    model.el.appendChild(layer);
  }
  return layer;
}

const ANSWER_CATEGORY_LABELS = {
  date: "date",
  dose: "dose",
  number: "number",
  procedure: "procedure",
  definition: "definition",
  mechanism: "mechanism",
  compare: "comparison",
  list: "list",
  application: "application",
  fact: "fact",
  manual: "hand-hidden",
  mixed: "mixed",
};

function answerCategoryLabel(category) {
  return ANSWER_CATEGORY_LABELS[category] || "answer";
}

function answerGroupsForPage(pageIndex) {
  const groups = [];
  for (const mask of state.answers.masks) {
    if (Number(mask.page) !== pageIndex) continue;
    groups.push({
      id: String(mask.id),
      category: String(mask.category || "fact"),
      boxes: (mask.boxes || []).map((box) => ({ ...box, page: pageIndex })),
    });
  }
  for (const mask of state.answers.aiMasks) {
    if (Number(mask.page) !== pageIndex) continue;
    groups.push({
      id: String(mask.id),
      category: String(mask.category || "fact"),
      boxes: (mask.boxes || []).map((box) => ({ ...box, page: pageIndex })),
    });
  }
  for (const mask of state.answers.manual) {
    const boxes = (mask.boxes || [])
      .map((box) => ({ ...box, page: Number(box.page) }))
      .filter((box) => box.page === pageIndex);
    if (boxes.length) groups.push({ id: String(mask.id), category: "manual", boxes });
  }
  return groups;
}

function renderAnswerLayer(model) {
  const layer = answerLayerForPage(model);
  if (!layer) return;
  layer.replaceChildren();
  if (!state.answers.active) return;
  const groups = answerGroupsForPage(model.index);
  if (!groups.length) return;
  const fragment = document.createDocumentFragment();
  for (const group of groups) {
    const revealed = state.answers.revealed.has(group.id);
    const label = answerCategoryLabel(group.category);
    for (const box of group.boxes) {
      if (!box || !Number.isFinite(Number(box.x))) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = `answer-mask kind-${group.category}`;
      button.dataset.maskId = group.id;
      button.dataset.category = group.category;
      button.setAttribute("aria-label", `Hidden ${label} answer \u2014 click to reveal`);
      button.setAttribute("aria-expanded", revealed ? "true" : "false");
      button.title = `Hidden ${label} answer \u2014 click to reveal`;
      button.style.left = `${clamp(Number(box.x) * 100, 0, 100)}%`;
      button.style.top = `${clamp(Number(box.y) * 100, 0, 100)}%`;
      button.style.width = `${clamp(Number(box.w) * 100, 0.15, 100)}%`;
      button.style.height = `${clamp(Number(box.h) * 100, 0.15, 100)}%`;
      button.classList.toggle("is-revealed", revealed);
      button.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        revealAnswerMask(group.id);
      });
      fragment.appendChild(button);
    }
  }
  layer.appendChild(fragment);
}

function renderAllAnswerLayers() {
  state.models.forEach((model) => renderAnswerLayer(model));
}

function clearAnswerLayers() {
  if (!els.pages) return;
  els.pages.querySelectorAll(".answer-layer").forEach((layer) => {
    layer.replaceChildren();
  });
}

function updateAnswerMaskButtons() {
  const buttons = els.pages ? Array.from(els.pages.querySelectorAll(".answer-mask")) : [];
  for (const button of buttons) {
    const revealed = state.answers.revealed.has(button.dataset.maskId);
    button.classList.toggle("is-revealed", revealed);
    button.setAttribute("aria-expanded", revealed ? "true" : "false");
  }
}

function answerGroupById(id) {
  for (const mask of state.answers.masks) {
    if (String(mask.id) === id) {
      return {
        id,
        page: Number(mask.page),
        category: String(mask.category || "fact"),
        uids: Array.isArray(mask.uids) ? mask.uids.map(String) : [],
        boxes: (mask.boxes || []).map((box) => ({
          ...box,
          page: Number(mask.page),
        })),
      };
    }
  }
  for (const mask of state.answers.aiMasks) {
    if (String(mask.id) === id) {
      return {
        id,
        page: Number(mask.page),
        category: String(mask.category || "fact"),
        uids: Array.isArray(mask.uids) ? mask.uids.map(String) : [],
        boxes: (mask.boxes || []).map((box) => ({
          ...box,
          page: Number(mask.page),
        })),
      };
    }
  }
  for (const mask of state.answers.manual) {
    if (String(mask.id) === id) {
      return {
        id,
        category: "manual",
        uids: [],
        boxes: (mask.boxes || []).map((box) => ({
          ...box,
          page: Number(box.page),
        })),
      };
    }
  }
  return null;
}

function boxesOverlap(first, second) {
  if (Number(first.page) !== Number(second.page)) return false;
  const left = Math.max(first.x, second.x);
  const top = Math.max(first.y, second.y);
  const right = Math.min(first.x + first.w, second.x + second.w);
  const bottom = Math.min(first.y + first.h, second.y + second.h);
  if (right <= left || bottom <= top) return false;
  const intersection = (right - left) * (bottom - top);
  const smaller = Math.min(first.w * first.h, second.w * second.h);
  return intersection / Math.max(1e-9, smaller) >= 0.18;
}

function revealAnswerMask(id) {
  const target = answerGroupById(id);
  if (!target) return;
  const ids = new Set([id]);
  const targetUids = new Set(target.uids || []);
  for (const mask of state.answers.masks) {
    if (String(mask.id) === id) continue;
    // Every blank from the same card is one answer; clicking one should
    // reveal the whole fact, not half a sentence.
    if (
      targetUids.size &&
      Array.isArray(mask.uids) &&
      mask.uids.some((uid) => targetUids.has(String(uid)))
    ) {
      ids.add(String(mask.id));
      continue;
    }
    const boxes = (mask.boxes || []).map((box) => ({
      ...box,
      page: Number(mask.page),
    }));
    if (
      target.boxes.some((mine) =>
        boxes.some((other) => boxesOverlap(mine, other))
      )
    ) {
      ids.add(String(mask.id));
    }
  }
  for (const mask of state.answers.manual) {
    if (String(mask.id) === id) continue;
    const boxes = (mask.boxes || []).map((box) => ({
      ...box,
      page: Number(box.page),
    }));
    if (
      target.boxes.some((mine) =>
        boxes.some((other) => boxesOverlap(mine, other))
      )
    ) {
      ids.add(String(mask.id));
    }
  }
  for (const mask of state.answers.aiMasks) {
    if (String(mask.id) === id) continue;
    if (
      targetUids.size &&
      Array.isArray(mask.uids) &&
      mask.uids.some((uid) => targetUids.has(String(uid)))
    ) {
      ids.add(String(mask.id));
      continue;
    }
    const boxes = (mask.boxes || []).map((box) => ({
      ...box,
      page: Number(mask.page),
    }));
    if (
      target.boxes.some((mine) =>
        boxes.some((other) => boxesOverlap(mine, other))
      )
    ) {
      ids.add(String(mask.id));
    }
  }
  for (const maskId of ids) state.answers.revealed.add(maskId);
  updateAnswerMaskButtons();
  updateAnswerToolbar();
}

function revealAllAnswerMasks() {
  for (const mask of state.answers.masks) state.answers.revealed.add(String(mask.id));
  for (const mask of state.answers.aiMasks) state.answers.revealed.add(String(mask.id));
  for (const mask of state.answers.manual) state.answers.revealed.add(String(mask.id));
  updateAnswerMaskButtons();
  updateAnswerToolbar();
}

function hideAllAnswerMasks() {
  state.answers.revealed.clear();
  updateAnswerMaskButtons();
  updateAnswerToolbar();
}

function toggleAllAnswerMasks() {
  const total = answerMaskCount();
  if (total && revealedAnswerCount() >= total) {
    hideAllAnswerMasks();
  } else {
    revealAllAnswerMasks();
  }
}

/* ------------------------------------------------------------------ */
/* controls                                                           */
/* ------------------------------------------------------------------ */

let answerPointer = null;

function pointInsideBox(box, x, y) {
  const pad = 0.004;
  return (
    x >= Number(box.x) - pad &&
    x <= Number(box.x) + Number(box.w) + pad &&
    y >= Number(box.y) - pad &&
    y <= Number(box.y) + Number(box.h) + pad
  );
}

/* The revealed mask has pointer-events:none so text can be selected, but a
   plain click must still toggle it back. A capture-phase click on the page
   finds the revealed rectangle under the pointer, and a drag is ignored. */
function toggleRevealedAtPointer(event) {
  const pointer = answerPointer;
  answerPointer = null;
  if (!pointer || pointer.moved || !state.answers.active) return;
  const target = event.target;
  if (!(target instanceof Element)) return;
  if (target.closest(".page-chip")) return;
  const maskButton = target.closest(".answer-mask");
  if (maskButton && !maskButton.classList.contains("is-revealed")) return;
  const selection = window.getSelection();
  if (selection && String(selection).trim()) return;
  const pageEl = target.closest(".page");
  if (!pageEl) return;
  const pageRect = pageEl.getBoundingClientRect();
  if (!pageRect.width || !pageRect.height) return;
  const x = (event.clientX - pageRect.left) / pageRect.width;
  const y = (event.clientY - pageRect.top) / pageRect.height;
  const groups = answerGroupsForPage(Number(pageEl.dataset.page));
  const ids = groups
    .filter((group) => state.answers.revealed.has(group.id))
    .filter((group) => group.boxes.some((box) => pointInsideBox(box, x, y)))
    .map((group) => group.id);
  if (!ids.length) return;
  for (const id of ids) state.answers.revealed.delete(id);
  updateAnswerMaskButtons();
  updateAnswerToolbar();
  event.preventDefault();
  event.stopPropagation();
}

function trackAnswerPointer(event) {
  if (!answerPointer || event.buttons === 0) return;
  if (
    Math.abs(event.clientX - answerPointer.x) > 6 ||
    Math.abs(event.clientY - answerPointer.y) > 6
  ) {
    answerPointer.moved = true;
  }
}

function beginAnswerPointer(event) {
  if (!state.answers.active || event.button !== 0) {
    answerPointer = null;
    return;
  }
  answerPointer = {
    x: event.clientX,
    y: event.clientY,
    moved: false,
  };
}

function setHideAnswers(on, { persist = true } = {}) {
  const available = Boolean(state.doc) && state.doc.kind !== "transcript";
  state.answers.active = Boolean(on) && available;
  if (persist && typeof localStorage !== "undefined") {
    localStorage.setItem(
      ANSWER_PREF_KEY,
      state.answers.active ? "1" : "0"
    );
  }
  if (!state.answers.active) {
    state.answers.revealed.clear();
    clearAnswerLayers();
    updateAnswerToolbar();
    return;
  }
  state.answers.emptyNotified = false;
  renderAllAnswerLayers();
  updateAnswerToolbar();
  scheduleAnswerRefresh(0);
}

function bindAnswerEvents() {
  if (els.pages) {
    els.pages.addEventListener("pointerdown", beginAnswerPointer, true);
    els.pages.addEventListener("click", toggleRevealedAtPointer, true);
  }
  window.addEventListener("pointermove", trackAnswerPointer, true);
  if (els.hideAnswersBtn) {
    els.hideAnswersBtn.addEventListener("click", () => {
      setHideAnswers(!state.answers.active);
    });
  }
  if (els.hideSelectionBtn) {
    // Clicking a button normally collapses the page selection before the
    // click fires, which would make "Hide selection" see an empty range.
    els.hideSelectionBtn.addEventListener("mousedown", (event) => {
      event.preventDefault();
    });
    els.hideSelectionBtn.addEventListener("click", addManualMaskFromSelection);
  }
  if (els.aiAnswersBtn) {
    els.aiAnswersBtn.addEventListener("click", fillAnswerGapsWithAI);
  }
  if (els.revealAnswersBtn) {
    els.revealAnswersBtn.addEventListener("click", toggleAllAnswerMasks);
  }
  if (els.clearMasksBtn) {
    els.clearMasksBtn.addEventListener("click", clearManualMasks);
  }
  document.addEventListener(
    "selectionchange",
    debounce(updateHideSelectionButton, 120)
  );
  window.addEventListener("beforeunload", () => flushManualMasks({ beacon: true }));
}
