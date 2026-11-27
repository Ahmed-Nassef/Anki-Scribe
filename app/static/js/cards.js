"use strict";

/* Card generation, rendering and editing */

function setMode(mode) {
  state.mode = mode;
  els.modeToggle.querySelectorAll("button[data-mode]").forEach((button) => {
    button.classList.toggle("is-active", button.dataset.mode === mode);
  });
}

function cancelGenerate() {
  if (!state.generating || !state.generateController) return;
  els.generateCancel.disabled = true;
  state.generateController.abort();
}

async function generateCards() {
  if (state.generating || state.auto.running) return;
  if (state.drafts.loading) {
    toast("Restoring draft cards\u2026 try again in a moment.");
    return;
  }
  const text = els.selectionText.value.trim();
  if (text.length < MIN_CHARS) {
    toast("Select a little more text first.");
    return;
  }
  if (text.length > MAX_CHARS) {
    toast(`That selection is too long. Select fewer than ${MAX_CHARS.toLocaleString()} characters.`, "error");
    return;
  }
  if (!state.settings.has_key) {
    toast("Add your DeepSeek API key first.", "error");
    openSettings();
    return;
  }

  // Everything about the source is captured before the request goes out. If the
  // student opens another file while this is in flight, the cards must be
  // discarded rather than attributed to the new document.
  const docId = state.doc ? state.doc.id : "";
  const mode = state.mode;
  const count = els.cardCount.value ? Number(els.cardCount.value) : null;
  const sourceLabel = state.selection.label;
  const selectionLocation = (state.selection.location || []).slice();
  const selectionQuote = text.replace(/\s+/g, " ").slice(0, 260);
  const sourceTitle = sourceTitleForDoc();
  const selectionChapter = chapterForLocation(selectionLocation);
  const chapterPath =
    selectionChapter && Array.isArray(selectionChapter.path) ? selectionChapter.path : [];

  const controller = new AbortController();
  state.generateController = controller;
  state.generating = true;
  els.generateBtn.disabled = true;
  els.generateBtn.classList.add("is-busy");
  els.generateLabel.textContent = "Writing cards\u2026";
  els.generateCancel.hidden = false;
  els.generateCancel.disabled = false;
  updateAutoButton();

  try {
    const data = await api("/api/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        text,
        mode,
        count,
        filename: state.doc ? state.doc.filename : null,
        page: sourceLabel || null,
        strict: Boolean(state.strict),
        style: state.style,
      }),
    });

    if (!state.doc || state.doc.id !== docId) {
      toast(
        "Another file was opened while these cards were being written, so they were discarded.",
        "error",
        9000
      );
      return;
    }

    const deckPath = [sourceTitle, ...chapterPath].filter(Boolean);
    let sourceTemplate;
    if (state.doc && state.doc.kind === "transcript") {
      const segmentIndices = Array.from(
        new Set(
          selectionLocation
            .map((entry) => Number(entry.segment))
            .filter((index) => Number.isInteger(index) && index >= 0)
        )
      ).sort((a, b) => a - b);
      sourceTemplate = {
        kind: "transcript",
        label: sourceLabel || "Transcript",
        file: state.doc.filename,
        location: selectionLocation,
        segments: segmentIndices.length
          ? [segmentIndices[0] + 1, segmentIndices[segmentIndices.length - 1] + 1]
          : [],
        quote: selectionQuote,
        sourceTitle,
        chapterPath,
        chapterTitle: selectionChapter ? selectionChapter.title : "",
        deckPath,
      };
    } else {
      const selectionPages = selectionLocation.length
        ? [
            Math.min(...selectionLocation.map((entry) => entry.page)),
            Math.max(...selectionLocation.map((entry) => entry.page)),
          ]
        : [];
      sourceTemplate = {
        kind: "selection",
        label: sourceLabel || "Selection",
        file: state.doc ? state.doc.filename : "",
        location: selectionLocation,
        pages: selectionPages,
        quote: selectionQuote,
        sourceTitle,
        chapterPath,
        chapterTitle: selectionChapter ? selectionChapter.title : "",
        deckPath,
      };
    }
    const cards = (data.cards || []).map((card) => ({
      ...card,
      uid: uid(),
      mode,
      selected: true,
      source: {
        ...sourceTemplate,
        evidence: card.evidence || "",
        quote: card.evidence || selectionQuote,
      },
    }));

    if (!cards.length) {
      toast("No testable facts found in that selection. Try a longer passage.", "error");
      return;
    }

    state.cards.push(...cards);
    renderCards();
    toast(
      `Draft ${cards.length} card${cards.length === 1 ? "" : "s"} \u2014 review, then send to Anki.`,
      "success"
    );
    requestAnimationFrame(() => {
      scrollPanelTo(els.cardsBlock);
    });
  } catch (error) {
    if (error.name === "AbortError") {
      toast("Generation stopped.", "info", 4000);
    } else {
      toast(error.message, "error", 9000);
      if (/api key|settings|401/i.test(error.message)) openSettings();
    }
  } finally {
    state.generateController = null;
    state.generating = false;
    els.generateBtn.classList.remove("is-busy");
    els.generateLabel.textContent = "Generate cards";
    els.generateCancel.hidden = true;
    els.generateCancel.disabled = false;
    updateSelectionUi();
    updateAutoButton();
    refreshCoverage({ quiet: true });
    refreshAiBalance({ quiet: true });
  }
}

/* ------------------------------------------------------------------ */
/* whole-file generation                                              */
/* ------------------------------------------------------------------ */

function cardKey(card) {
  const base = card.mode === "cloze" ? card.text : card.question;
  return String(base || "").toLowerCase().replace(/\s+/g, " ").trim();
}

function addGeneratedCards(cards, mode, sourceMeta) {
  const existing = new Set(state.cards.map(cardKey));
  const fresh = [];
  for (const raw of cards || []) {
    const card = {
      ...raw,
      uid: uid(),
      mode,
      selected: true,
      source: {
        ...(sourceMeta || {}),
        evidence: raw.evidence || "",
        quote: raw.evidence || (sourceMeta && sourceMeta.quote) || "",
      },
    };
    const key = cardKey(card);
    if (!key || existing.has(key)) continue;
    existing.add(key);
    fresh.push(card);
  }
  if (fresh.length) state.cards.push(...fresh);
  return fresh.length;
}

function setModeControlsDisabled(disabled) {
  els.modeToggle.querySelectorAll("button[data-mode]").forEach((button) => {
    button.disabled = disabled;
  });
  els.cardCount.disabled = disabled;
  els.clearCards.disabled = disabled;
}

/* ------------------------------------------------------------------ */
/* the review list                                                    */
/* ------------------------------------------------------------------ */

/* A thousand cards is a normal whole-book run, and a thousand full cards is
   ~70,000 DOM nodes: enough to put a browser tab in the hundreds of megabytes,
   and every re-render used to build them all again. The list therefore keeps
   one cheap slot per card and builds the card itself only when it comes near
   the viewport; far cards are recycled back to a slot. */
const CARD_BUILD_MARGIN = "900px 0px";
const MAX_BUILT_CARDS = 80;
const DEFAULT_CARD_HEIGHT = 168;

let cardObserver = null;
let cardRisk = null;
const builtSlots = new Map();
const visibleSlots = new Set();

function observeCardSlots() {
  if (!cardObserver) {
    cardObserver = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          const slot = entry.target;
          const uid = slot.dataset.slotUid;
          if (entry.isIntersecting) {
            visibleSlots.add(uid);
            buildCardSlot(slot);
          } else {
            visibleSlots.delete(uid);
          }
        }
        pruneBuiltCards();
      },
      { root: els.panelScroll, rootMargin: CARD_BUILD_MARGIN }
    );
  }
  cardObserver.disconnect();
  els.cardsList.querySelectorAll(".card-slot").forEach((slot) => {
    cardObserver.observe(slot);
  });
}

function cardSlotFor(uid) {
  return els.cardsList.querySelector(`.card-slot[data-slot-uid="${uid}"]`);
}

function buildCardSlot(slot) {
  if (!slot || slot.dataset.built === "1") {
    return slot ? slot.querySelector(".card") : null;
  }
  const uid = slot.dataset.slotUid;
  const card = state.cards.find((item) => item.uid === uid);
  if (!card) return null;
  slot.replaceChildren(buildCard(card, cardRisk));
  slot.dataset.built = "1";
  slot.style.minHeight = "";
  builtSlots.delete(uid);
  builtSlots.set(uid, slot);
  state.cardHeights[uid] = Math.max(60, slot.offsetHeight);
  return slot.querySelector(".card");
}

/* Keep the number of fully built cards bounded. Anything far from the
   viewport goes back to an empty slot at its remembered height. */
function pruneBuiltCards() {
  if (builtSlots.size <= MAX_BUILT_CARDS) return;
  for (const [uid, slot] of Array.from(builtSlots.entries())) {
    if (builtSlots.size <= MAX_BUILT_CARDS) break;
    if (visibleSlots.has(uid)) continue;
    if (slot.contains(document.activeElement)) continue;
    state.cardHeights[uid] = Math.max(60, slot.offsetHeight);
    slot.replaceChildren();
    slot.dataset.built = "0";
    slot.style.minHeight = `${state.cardHeights[uid] || DEFAULT_CARD_HEIGHT}px`;
    builtSlots.delete(uid);
  }
}

function renderCards() {
  els.cardsList.replaceChildren();
  if (cardObserver) cardObserver.disconnect();
  cardRisk = computeRisk();
  builtSlots.clear();
  visibleSlots.clear();

  const visibleCards = state.blockedOnly
    ? state.cards.filter((card) => blockingFaults(card).length)
    : state.cards;
  if (!state.cards.length || !visibleCards.length) {
    const empty = document.createElement("div");
    empty.className = "cards-empty";
    empty.textContent = state.blockedOnly
      ? "No blocked cards left in this file."
      : "Generated cards land here. Edit anything before it goes to Anki.";
    els.cardsList.appendChild(empty);
  } else {
    const fragment = document.createDocumentFragment();
    visibleCards.forEach((card) => {
      const slot = document.createElement("div");
      slot.className = "card-slot";
      slot.dataset.slotUid = card.uid;
      if (!card.selected) slot.classList.add("is-unselected");
      slot.style.minHeight = `${state.cardHeights[card.uid] || DEFAULT_CARD_HEIGHT}px`;
      fragment.appendChild(slot);
    });
    els.cardsList.appendChild(fragment);
    observeCardSlots();
  }

  updateCardsMeta();
  els.clearCards.hidden = state.cards.length === 0;
  updatePushLabel();
  updatePushDestination();
  renderCoverage();
  renderObjectives();
  applyDraftHighlights();
  scheduleDraftSave();
  if (typeof scheduleAnswerRefresh === "function") scheduleAnswerRefresh();
}

function figureUrl(figure, side) {
  const name = side ? figure[side] : figure.masked || figure.revealed;
  if (!figure.docId || !name) return "";
  return `/api/documents/${encodeURIComponent(figure.docId)}/figures/${encodeURIComponent(name)}`;
}

/* ------------------------------------------------------------------ */
/* pictures attached to a card                                        */
/* ------------------------------------------------------------------ */

function cardImageUrl(image) {
  if (!image || !image.docId || !image.name) return "";
  return `/api/documents/${encodeURIComponent(image.docId)}/images/${encodeURIComponent(image.name)}`;
}

function buildCardImage(card) {
  const figure = document.createElement("figure");
  figure.className = "card-image";

  const img = document.createElement("img");
  img.loading = "lazy";
  img.alt = "Picture attached to this card";
  img.src = cardImageUrl(card.image);

  const bar = document.createElement("figcaption");
  bar.className = "card-image-bar";

  const toggle = document.createElement("label");
  toggle.className = "checkline";
  const box = document.createElement("input");
  box.type = "checkbox";
  box.checked = (card.image.side || "front") !== "back";
  box.dataset.action = "image-side";
  box.setAttribute("aria-label", "Show this picture on the front of the card");
  const label = document.createElement("span");
  label.textContent = "Show on front";
  toggle.append(box, label);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "text-btn danger";
  remove.dataset.action = "image-remove";
  remove.textContent = "Remove picture";

  const replace = document.createElement("button");
  replace.type = "button";
  replace.className = "text-btn";
  replace.dataset.action = "image-add";
  replace.textContent = "Replace";
  replace.title = "Use a different picture on this card";

  const actions = document.createElement("span");
  actions.className = "card-image-actions";
  actions.append(replace, remove);

  bar.append(toggle, actions);
  figure.append(img, bar);
  return figure;
}

function buildImageRow(card) {
  const row = document.createElement("div");
  row.className = "card-image-row";
  row.dataset.uid = card.uid;
  const add = document.createElement("button");
  add.type = "button";
  add.className = "text-btn card-image-add";
  add.dataset.action = "image-add";
  add.textContent = "Add picture";
  add.title = "Attach a picture to this card";
  row.appendChild(add);
  return row;
}

function openImageMenu(cardEl) {
  let row = cardEl.querySelector(".card-image-row");
  if (!row) {
    // A card that already has a picture shows its bar instead of the add row.
    row = document.createElement("div");
    row.className = "card-image-row";
    const figure = cardEl.querySelector(".card-image");
    if (figure) figure.after(row);
    else cardEl.appendChild(row);
  }
  const crop = document.createElement("button");
  crop.type = "button";
  crop.className = "btn tiny";
  crop.dataset.action = "image-crop";
  crop.textContent = "Crop from this page";

  const upload = document.createElement("button");
  upload.type = "button";
  upload.className = "btn tiny";
  upload.dataset.action = "image-upload";
  upload.textContent = "Upload a file";

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "text-btn";
  cancel.dataset.action = "image-menu-cancel";
  cancel.textContent = "Cancel";

  row.replaceChildren(crop, upload, cancel);
}

function setCardImage(uid, image) {
  const card = state.cards.find((item) => item.uid === uid);
  if (!card) return false;
  card.image = image;
  renderCards();
  scheduleDraftSave();
  requestAnimationFrame(() => focusCard(uid));
  return true;
}

function removeCardImage(uid) {
  const card = state.cards.find((item) => item.uid === uid);
  if (!card || !card.image) return;
  delete card.image;
  renderCards();
  scheduleDraftSave();
  toast("Picture removed from the card.", "info", 3000);
}

function setCardImageSide(uid, side) {
  const card = state.cards.find((item) => item.uid === uid);
  if (!card || !card.image) return;
  card.image.side = side === "back" ? "back" : "front";
  scheduleDraftSave();
}

function chooseCardImageFile(uid) {
  if (!els.imageFileInput) {
    toast("This browser cannot open a file picker here.", "error", 6000);
    return;
  }
  state.imageTarget = uid;
  els.imageFileInput.value = "";
  els.imageFileInput.click();
}

async function uploadCardImage(file) {
  const uid = state.imageTarget;
  state.imageTarget = null;
  if (!file || !uid || !state.doc) return;
  const docId = state.doc.id;
  const form = new FormData();
  form.append("file", file);
  try {
    const data = await api(`/api/documents/${encodeURIComponent(docId)}/images`, {
      method: "POST",
      body: form,
    });
    if (!state.doc || state.doc.id !== docId) {
      toast("Another file was opened, so that picture was discarded.", "error", 8000);
      return;
    }
    setCardImage(uid, { docId, name: data.name, side: "front" });
    toast("Picture added to the card.", "success", 4000);
  } catch (error) {
    toast(error.message, "error", 9000);
  }
}

function toggleBlockedFilter() {
  const blocked = state.cards.filter((card) => blockingFaults(card).length);
  if (!blocked.length) {
    state.blockedOnly = false;
    renderCards();
    toast("No blocked cards. The quality gate is clear.", "success", 3500);
    return;
  }
  state.blockedOnly = !state.blockedOnly;
  renderCards();
  if (state.blockedOnly) {
    focusCard(blocked[0].uid);
    toast(
      `Showing ${blocked.length} blocked card${blocked.length === 1 ? "" : "s"} only. Fix each red card, then click Blocked again to show all.`,
      "info",
      8000
    );
  }
}

let blockedCursor = -1;

function focusNextBlocked() {
  const blocked = state.cards.filter((card) => blockingFaults(card).length);
  if (!blocked.length) {
    toast("No blocked cards. The quality gate is clear.", "success", 3500);
    return;
  }
  blockedCursor = (blockedCursor + 1) % blocked.length;
  const card = blocked[blockedCursor];
  focusCard(card.uid);
  const labels = blockingFaults(card)
    .map((fault) => fault.label)
    .join(" \u00b7 ");
  toast(
    `Blocked card ${blockedCursor + 1} of ${blocked.length}: ${labels}. Edit it here, then send again.`,
    "info",
    7500
  );
}

/* Bring one card into view in the review panel and flash it, so a click on the
   highlighted source text lands somewhere unmistakable. The card is built on
   demand: the list may only hold a slot for it. */
function focusCard(uid) {
  const slot = cardSlotFor(uid);
  if (!slot) {
    toast(
      "That card is not in the list any more \u2014 it may have been sent or removed.",
      "info",
      5000
    );
    return;
  }
  const cardEl = buildCardSlot(slot) || slot;
  scrollPanelTo(slot);
  els.cardsList.querySelectorAll(".card.is-flash").forEach((node) => {
    node.classList.remove("is-flash");
  });
  void cardEl.offsetWidth;
  cardEl.classList.add("is-flash");
  setTimeout(() => cardEl.classList.remove("is-flash"), 1600);
}

function jumpToCardFromLine(node) {
  const uids = (node.dataset.cardUids || "").split(" ").filter(Boolean);
  if (!uids.length) {
    toast("No card is recorded for that line yet.", "info", 3500);
    return;
  }
  const next = Number(node.dataset.cardCycle || 0);
  node.dataset.cardCycle = String(next + 1);
  focusCard(uids[next % uids.length]);
  if (uids.length > 1) {
    toast(
      `${uids.length} cards come from this line \u2014 click again for the next one.`,
      "info",
      3500
    );
  }
}

const TYPE_LABELS = {
  definition: "definition",
  mechanism: "mechanism",
  compare: "compare",
  application: "application",
  enumeration: "list",
  number: "number",
};
const TYPE_ORDER = ["definition", "mechanism", "compare", "application", "enumeration", "number"];

function cardTypeOf(card) {
  const value = String((card && card.type) || "").toLowerCase();
  return Object.prototype.hasOwnProperty.call(TYPE_LABELS, value) ? value : "definition";
}

function fallbackCardFaults(card) {
  const faults = [];
  const mode = card && card.mode === "cloze" ? "cloze" : "basic";
  const question = String(card?.question || "").trim();
  const answer = String(card?.answer || "").trim();
  const text = String(card?.text || "").trim();
  if (mode === "cloze") {
    if (!text) {
      faults.push({ code: "empty_side", label: "a required side is empty", severity: "blocking" });
    }
    if (text.match(/\{\{c\d+::/g)) {
      const deletions = [...text.matchAll(/\{\{c\d+::([\s\S]*?)(?:::[^}]*)?\}\}/g)].map(
        (match) => match[1]
      );
      if (deletions.length > 3) {
        faults.push({ code: "cloze_overloaded", label: "too many deletions, or one deletion too long", severity: "blocking" });
      } else if (
        deletions.some((deletion) => deletion.trim().split(/\s+/).filter(Boolean).length > 8)
      ) {
        faults.push({ code: "cloze_overloaded", label: "too many deletions, or one deletion too long", severity: "blocking" });
      }
    }
    return faults;
  }
  if (!question) {
    faults.push({ code: "empty_side", label: "a required side is empty", severity: "blocking" });
  }
  if (!answer && !card?.image) {
    faults.push({ code: "empty_side", label: "a required side is empty", severity: "blocking" });
  }
  if (question && /^(explain|describe|discuss|list|outline|summari[sz]e|compare and contrast)\b/i.test(question)) {
    faults.push({ code: "open_ended", label: "it asks for an essay, not a recallable fact", severity: "blocking" });
  }
  if (question && answer && /^(yes|no|true|false)\b/i.test(answer)) {
    faults.push({ code: "answer_leak", label: "the answer is already in the question", severity: "blocking" });
  }
  return faults;
}

function cardFaults(card) {
  if (Array.isArray(card?.faults)) {
    return card.faults.filter((fault) => fault && fault.code);
  }
  return fallbackCardFaults(card);
}

function blockingFaults(card) {
  return cardFaults(card).filter((fault) => fault.severity === "blocking");
}

/* The mix is the whole point of the type field: a deck that is 90% definition
   is a deck that will feel easy and fail the exam. */
function typeMixSummary(cards) {
  const counts = new Map();
  (cards || []).forEach((card) => {
    const key = cardTypeOf(card);
    counts.set(key, (counts.get(key) || 0) + 1);
  });
  return TYPE_ORDER.filter((key) => counts.has(key))
    .map((key) => `${counts.get(key)} ${TYPE_LABELS[key]}`)
    .join(" \u00b7 ");
}

function buildCard(card, risk) {
  const article = document.createElement("article");
  const blocked = blockingFaults(card).length > 0;
  article.className = `card${card.selected ? "" : " is-unselected"}${blocked ? " is-blocked" : ""}`;
  article.dataset.uid = card.uid;

  const sourceMeta =
    card.source && typeof card.source === "object"
      ? card.source
      : { label: String(card.source || "") };

  const top = document.createElement("div");
  top.className = "card-top";

  const tick = document.createElement("label");
  tick.className = "tick";
  const checkbox = document.createElement("input");
  checkbox.type = "checkbox";
  checkbox.checked = Boolean(card.selected);
  checkbox.dataset.action = "select";
  checkbox.setAttribute("aria-label", "Include this card");
  const tickBox = document.createElement("span");
  tick.append(checkbox, tickBox);

  const badge = document.createElement("span");
  badge.className = `badge${card.mode === "cloze" ? " cloze" : ""}`;
  badge.textContent =
    card.mode === "cloze" ? "Cloze" : card.mode === "figure" ? "Figure" : "Q & A";

  const riskEntry = risk && typeof risk.get === "function" ? risk.get(card.uid) : null;
  if (riskEntry && riskEntry.score > 0) {
    badge.title = `Why this card is flagged: ${riskEntry.reasons
      .map((reason) => reason.label)
      .join(" \u00b7 ")}`;
  }

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "card-remove";
  remove.dataset.action = "remove";
  remove.title = "Remove card";
  remove.setAttribute("aria-label", "Remove card");
  remove.textContent = "\u00d7";

  top.append(tick, badge);

  const typeBadge = document.createElement("span");
  typeBadge.className = `badge type type-${cardTypeOf(card)}`;
  typeBadge.textContent = TYPE_LABELS[cardTypeOf(card)];
  typeBadge.title = "What this card tests";
  top.appendChild(typeBadge);

  if (card.verified === false) {
    const flag = document.createElement("span");
    flag.className = "badge check";
    flag.textContent = "check";
    flag.title =
      "The quote saved with this card was not found in the source. Verify it before sending.";
    top.appendChild(flag);
  }

  cardFaults(card).forEach((fault) => {
    const chip = document.createElement("span");
    const blocking = fault.severity === "blocking";
    chip.className = `badge fault${blocking ? " blocking" : ""}`;
    chip.textContent = blocking ? "blocked" : "warn";
    chip.title = fault.detail ? `${fault.label} (${fault.detail})` : fault.label;
    chip.setAttribute("aria-label", `${chip.textContent}: ${fault.label}`);
    top.appendChild(chip);
  });

  top.appendChild(remove);

  const sourceRow = document.createElement("div");
  sourceRow.className = "card-source-row";

  const locate = document.createElement("button");
  locate.type = "button";
  locate.className = "card-locate";
  locate.dataset.action = "locate";
  locate.title = sourceMeta.file
    ? `Show this answer in ${sourceMeta.file}`
    : "Show this answer in the document";
  locate.setAttribute(
    "aria-label",
    `Show ${sourceMeta.label || "the source"} in the document`
  );
  locate.innerHTML = `
    <svg width="11" height="11" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="12" cy="12" r="6" stroke="currentColor" stroke-width="1.8"/>
      <path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/>
    </svg>
    <span class="card-locate-label"></span>
  `;
  locate.querySelector(".card-locate-label").textContent = sourceMeta.label || "Source";
  const canLocate =
    (Array.isArray(sourceMeta.location) && sourceMeta.location.length > 0) ||
    (Array.isArray(sourceMeta.pages) && sourceMeta.pages.length > 0) ||
    (Array.isArray(sourceMeta.segments) && sourceMeta.segments.length > 0);
  locate.disabled = !canLocate;
  if (!canLocate) locate.title = "No source location was saved for this card";
  sourceRow.appendChild(locate);

  const quoteText = String(sourceMeta.quote || sourceMeta.evidence || "").trim();
  if (quoteText) {
    const quote = document.createElement("span");
    quote.className = "card-quote";
    quote.textContent = `\u201c${quoteText}\u201d`;
    quote.title = quoteText;
    sourceRow.appendChild(quote);
  }

  const body = document.createElement("div");

  if (card.image && card.image.name) {
    body.appendChild(buildCardImage(card));
  } else if (card.mode !== "figure") {
    body.appendChild(buildImageRow(card));
  }

  if (card.mode === "figure" && card.figure) {
    const figure = document.createElement("figure");
    figure.className = "card-figure";
    const img = document.createElement("img");
    img.loading = "lazy";
    img.alt = "The masked figure this card asks about";
    img.src = figureUrl(card.figure);
    figure.appendChild(img);
    body.appendChild(figure);
  }

  if (card.mode === "cloze") {
    body.appendChild(makeField("Cloze text", "textarea", "text", card.text, 3));
    const hint = document.createElement("div");
    hint.className = "cloze-hint";
    hint.textContent = "Keep the {{c1::\u2026}} syntax \u2014 Anki hides the deletion.";
    body.appendChild(hint);
  } else {
    body.appendChild(makeField("Question", "textarea", "question", card.question, 2));
    body.appendChild(makeField("Answer", "textarea", "answer", card.answer, 2));
  }

  const details = document.createElement("details");
  details.className = "extra";
  const summary = document.createElement("summary");
  summary.textContent = "Extra context";
  details.appendChild(summary);
  details.appendChild(makeField("", "textarea", "extra", card.extra, 2));

  body.appendChild(details);
  body.appendChild(makeField("Tags", "input", "tags", (card.tags || []).join(", "), 0));

  const deckLine = document.createElement("div");
  deckLine.className = "card-deck";
  deckLine.textContent = cardDeckName(card);
  deckLine.title = `Anki deck: ${deckLine.textContent}`;

  article.append(top, sourceRow, deckLine, body);
  return article;
}

function makeField(label, tag, name, value, rows) {
  const wrapper = document.createElement("label");
  wrapper.className = "field";
  if (label) {
    const text = document.createElement("span");
    text.textContent = label;
    wrapper.appendChild(text);
  }
  const input = document.createElement(tag === "textarea" ? "textarea" : "input");
  input.dataset.field = name;
  if (tag === "textarea") {
    input.rows = rows || 2;
    input.value = value || "";
    input.spellcheck = false;
  } else {
    input.type = "text";
    input.value = value || "";
    input.spellcheck = false;
  }
  if (!label) input.setAttribute("aria-label", "Extra context");
  wrapper.appendChild(input);
  return wrapper;
}

function updateCardsMeta() {
  const total = state.cards.length;
  const selected = state.cards.filter((card) => card.selected).length;
  const unverified = state.cards.filter((card) => card.verified === false).length;
  const sent = state.sent.cards.length;
  if (!total) {
    els.cardsMeta.textContent = sent
      ? `${sent} card${sent === 1 ? "" : "s"} already in Anki`
      : "No cards yet";
  } else {
    const mix = typeMixSummary(state.cards);
    const blocked = state.cards.filter((card) => blockingFaults(card).length).length;
    els.cardsMeta.textContent =
      `${total} draft${total === 1 ? "" : "s"} \u00b7 ${selected} selected` +
      (unverified ? ` \u00b7 ${unverified} to check` : "") +
      (blocked ? ` \u00b7 ${blocked} blocked` : "") +
      (state.blockedOnly ? " \u00b7 showing blocked" : "") +
      (sent ? ` \u00b7 ${sent} sent` : "") +
      (mix ? ` \u00b7 ${mix}` : "");
  }
  updateRiskButton(total);
  updateBlockedButton();
  updateSheetActions();
  updateUndoButton();
  refreshSentHistoryButton();
}

function updateBlockedButton() {
  if (!els.blockedBtn) return;
  const count = state.cards.filter((card) => blockingFaults(card).length).length;
  if (count === 0 && state.blockedOnly) {
    state.blockedOnly = false;
    renderCards();
    return;
  }
  els.blockedBtn.hidden = count === 0;
  els.blockedBtn.textContent = state.blockedOnly
    ? `Show all (${count})`
    : `Blocked ${count}`;
  els.blockedBtn.classList.toggle("is-active", state.blockedOnly);
  els.blockedBtn.setAttribute("aria-pressed", state.blockedOnly ? "true" : "false");
  els.blockedBtn.title = state.blockedOnly
    ? "Show the full review list again"
    : `Show only the ${count} card${count === 1 ? "" : "s"} the quality gate would block`;
  if (els.pushBlockedBtn) els.pushBlockedBtn.hidden = count === 0;
}

function updateRiskButton(total) {
  if (!els.riskBtn) return;
  const risky = total ? riskyCards().length : 0;
  els.riskBtn.hidden = risky === 0;
  if (risky) {
    els.riskBtn.textContent = `${risky} to check`;
    els.riskBtn.title =
      `${risky} card${risky === 1 ? "" : "s"} flagged by the local checks ` +
      "(unverified quote, vague question, long deletion, duplicate or untagged)";
  }
}

function updatePushLabel() {
  const selected = state.cards.filter((card) => card.selected).length;
  if (!state.pushing) {
    els.pushLabel.textContent = selected
      ? `Send ${selected} card${selected === 1 ? "" : "s"} to Anki`
      : "Send to Anki";
  }
  els.pushBtn.disabled = selected === 0 || state.pushing || state.auto.running;
}

/* ------------------------------------------------------------------ */
/* undo                                                               */
/* ------------------------------------------------------------------ */

/* Deletion is the app's main verb and it used to be final. Every mutation
   that removes or hides work records an inverse here; the last 20 survive
   until the next document. */
const UNDO_LIMIT = 20;

function pushUndo(entry) {
  state.undo.stack.push(entry);
  if (state.undo.stack.length > UNDO_LIMIT) state.undo.stack.shift();
  state.undo.redo = [];
  updateUndoButton();
}

function resetUndo() {
  state.undo = { stack: [], redo: [] };
  updateUndoButton();
}

function updateUndoButton() {
  if (!els.undoBtn) return;
  const depth = state.undo.stack.length;
  els.undoBtn.disabled = depth === 0;
  els.undoBtn.title = depth
    ? `Undo the last change (${state.undo.stack[depth - 1].type})`
    : "Nothing to undo";
}

function undoLast() {
  const entry = state.undo.stack.pop();
  if (!entry) return;
  if (entry.type === "remove") {
    const index = Math.max(0, Math.min(entry.index, state.cards.length));
    state.cards.splice(index, 0, entry.card);
  } else if (entry.type === "clear") {
    state.cards = entry.cards.concat(state.cards);
  } else if (entry.type === "select") {
    const card = state.cards.find((item) => item.uid === entry.uid);
    if (card) card.selected = entry.before;
  } else if (entry.type === "replace") {
    const card = state.cards.find((item) => item.uid === entry.uid);
    if (card) Object.assign(card, entry.before);
  }
  state.undo.redo.push(entry);
  renderCards();
  toast("Undone.", "info", 2500);
}

function redoLast() {
  const entry = state.undo.redo.pop();
  if (!entry) return;
  if (entry.type === "remove") {
    const index = state.cards.findIndex((item) => item.uid === entry.card.uid);
    if (index !== -1) state.cards.splice(index, 1);
  } else if (entry.type === "clear") {
    state.cards = [];
  } else if (entry.type === "select") {
    const card = state.cards.find((item) => item.uid === entry.uid);
    if (card) card.selected = entry.after;
  } else if (entry.type === "replace") {
    const card = state.cards.find((item) => item.uid === entry.uid);
    if (card) Object.assign(card, entry.after);
  }
  state.undo.stack.push(entry);
  updateUndoButton();
  renderCards();
}

function snapshotCard(card) {
  return {
    mode: card.mode,
    question: card.question || "",
    answer: card.answer || "",
    text: card.text || "",
    extra: card.extra || "",
    evidence: card.evidence || "",
    verified: card.verified,
  };
}

function removeCard(uid) {
  const index = state.cards.findIndex((card) => card.uid === uid);
  if (index === -1) return;
  const card = state.cards[index];
  state.cards.splice(index, 1);
  pushUndo({ type: "remove", index, card });
  renderCards();
  toast("Card removed.", "info", 6000, { label: "Undo", run: undoLast });
}

function clearAllCards() {
  if (!state.cards.length) return;
  const cards = state.cards.slice();
  state.cards = [];
  pushUndo({ type: "clear", cards });
  renderCards();
  toast(
    `${cards.length} draft${cards.length === 1 ? "" : "s"} cleared. Cards already in Anki are kept.`,
    "info",
    6500,
    { label: "Undo", run: undoLast }
  );
}

function setCardSelected(uid, selected) {
  const card = state.cards.find((item) => item.uid === uid);
  if (!card || card.selected === selected) return;
  pushUndo({ type: "select", uid, before: card.selected, after: selected });
  card.selected = selected;
  if (typeof scheduleAnswerRefresh === "function") scheduleAnswerRefresh();
}

/* ------------------------------------------------------------------ */
/* sent history                                                       */
/* ------------------------------------------------------------------ */

let clearHistoryArmed = false;
let clearHistoryTimer = null;

function refreshSentHistoryButton() {
  if (!els.clearHistory) return;
  const count = state.sent.cards.length;
  els.clearHistory.hidden = count === 0;
  if (!clearHistoryArmed) {
    els.clearHistory.textContent = "Clear history";
    els.clearHistory.title =
      `${count} card${count === 1 ? "" : "s"} recorded as sent. Clearing forgets them here, not in Anki.`;
  }
}

function clearSentHistory() {
  if (!state.sent.cards.length || !state.sent.path) return;
  if (!clearHistoryArmed) {
    clearHistoryArmed = true;
    els.clearHistory.textContent = "Really clear?";
    clearTimeout(clearHistoryTimer);
    clearHistoryTimer = setTimeout(() => {
      clearHistoryArmed = false;
      refreshSentHistoryButton();
    }, 4000);
    return;
  }
  clearTimeout(clearHistoryTimer);
  clearHistoryArmed = false;
  const path = state.sent.path;
  api(`/api/sent?path=${encodeURIComponent(path)}`, { method: "DELETE" })
    .then(() => {
      state.sent.cards = [];
      renderCards();
      applyDraftHighlights();
      toast("Sent history cleared for this file.", "success");
    })
    .catch((error) => toast(error.message, "error", 8000));
}
