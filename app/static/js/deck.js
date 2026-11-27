"use strict";

/* Deck location, hierarchy and Anki push */

function sanitizeDeckPart(value) {
  return String(value || "")
    .replace(/::/g, " - ")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80);
}

function sourceTitleForDoc() {
  const planTitle = state.chapterPlan && state.chapterPlan.sourceTitle;
  const filename = state.doc ? state.doc.filename : "";
  const stem = filename.replace(/\.[^.]+$/, "").replace(/[_-]+/g, " ");
  return sanitizeDeckPart(planTitle || stem || "Untitled");
}

function baseDeckParts() {
  const raw =
    els.deckInput.value.trim() ||
    state.settings.default_deck ||
    "Anki Scribe";
  return raw
    .split("::")
    .map(sanitizeDeckPart)
    .filter(Boolean);
}

function cardDeckParts(card) {
  const source = card.source && typeof card.source === "object" ? card.source : {};
  let relative =
    Array.isArray(source.deckPath) && source.deckPath.length
      ? source.deckPath.map(sanitizeDeckPart).filter(Boolean)
      : [sourceTitleForDoc()];
  const base = baseDeckParts();
  if (state.deckMode === "exact") {
    return base.length ? base : ["Anki Scribe"];
  }
  const baseKey = base.join("::").toLowerCase();
  const relativeKey = relative.join("::").toLowerCase();
  if (baseKey && relativeKey && (baseKey === relativeKey || baseKey.endsWith(`::${relativeKey}`))) {
    relative = [];
  }
  while (
    relative.length &&
    base.length &&
    base[base.length - 1].toLowerCase() === relative[0].toLowerCase()
  ) {
    relative = relative.slice(1);
  }
  const parts = [...base, ...relative].filter(Boolean);
  while (parts.length > 1 && parts.join("::").length > 200) {
    parts.pop();
  }
  if (parts.join("::").length > 200) {
    parts[parts.length - 1] = parts[parts.length - 1].slice(0, 200 - (parts[0].length + 2));
  }
  return parts;
}

function cardDeckName(card) {
  return cardDeckParts(card).join("::");
}

function updateDeckModeLabel() {
  const exact = state.deckMode === "exact";
  els.deckFieldLabel.textContent = exact ? "Deck location" : "Parent deck";
  els.deckInput.title = exact
    ? "Cards go directly to this deck; no source/chapter subdecks are added."
    : "Parent deck. The source title and each chapter become subdecks under it.";
}

function updateCardDeckLabels() {
  document.querySelectorAll(".card").forEach((article) => {
    const card = state.cards.find((item) => item.uid === article.dataset.uid);
    if (!card) return;
    const label = article.querySelector(".card-deck");
    if (!label) return;
    const deck = cardDeckName(card);
    label.textContent = deck;
    label.title = `Anki deck: ${deck}`;
  });
}

function chapterForLocation(location) {
  const chapters = state.chapterPlan && Array.isArray(state.chapterPlan.chapters)
    ? state.chapterPlan.chapters
    : [];
  if (!chapters.length || !Array.isArray(location)) return null;
  for (const entry of location) {
    if (Number.isInteger(entry.segment)) {
      const segment = entry.segment + 1;
      const chapter = chapters.find(
        (item) =>
          item.startSegment != null &&
          item.endSegment != null &&
          segment >= item.startSegment &&
          segment <= item.endSegment
      );
      if (chapter) return chapter;
    }
    if (Number.isInteger(entry.page)) {
      const page = entry.page + 1;
      const chapter = chapters.find(
        (item) =>
          item.startPage != null &&
          item.endPage != null &&
          page >= item.startPage &&
          page <= item.endPage
      );
      if (chapter) return chapter;
    }
  }
  return null;
}

async function checkAnki({ quiet = false } = {}) {
  els.ankiStatus.classList.remove("ok", "off");
  els.ankiStatus.classList.add("checking");
  els.ankiLabel.textContent = "Anki";
  try {
    const data = await api("/api/anki/status");
    if (data.connected) {
      state.anki = data;
      els.ankiStatus.classList.remove("checking", "off");
      els.ankiStatus.classList.add("ok");
      els.ankiLabel.textContent = "Anki connected";
      els.ankiStatus.title = `AnkiConnect v${data.version} \u00b7 ${data.decks.length} decks`;
      fillDecks(data.decks || []);
      if (state.cards.length) {
        updatePushDestination();
      } else {
        setPushStatus("Choose a deck; generated cards will go there.");
      }
      if (!quiet) toast(`Anki connected \u2014 ${data.decks.length} decks found.`, "success");
    } else {
      setAnkiOff(data.message);
      if (!quiet) toast(data.message, "error", 9000);
    }
  } catch (error) {
    setAnkiOff(error.message);
    if (!quiet) toast(error.message, "error", 9000);
  } finally {
    els.ankiStatus.classList.remove("checking");
  }
}

function setAnkiOff(message) {
  const cachedDecks = Array.isArray(state.anki.decks) ? state.anki.decks : [];
  state.anki = { connected: false, decks: cachedDecks, message: message || "" };
  els.ankiStatus.classList.remove("ok", "checking");
  els.ankiStatus.classList.add("off");
  els.ankiLabel.textContent = "Anki offline";
  els.ankiStatus.title = message || "AnkiConnect isn't reachable.";
  setPushStatus("Open Anki with the AnkiConnect add-on, then send.", "error");
  updateDeckActions();
  if (els.deckDialog.open) renderDeckList();
}

function fillDecks(decks) {
  const list = Array.isArray(decks) ? decks.slice() : [];
  state.anki.decks = list;
  els.deckOptions.replaceChildren();
  list.forEach((deck) => {
    const option = document.createElement("option");
    option.value = deck;
    els.deckOptions.appendChild(option);
  });
  if (!els.deckInput.value.trim()) {
    els.deckInput.value =
      state.settings.default_deck || list[0] || "Anki Scribe";
  }
  updateDeckActions();
  if (els.deckDialog.open) {
    if (!list.includes(state.deckSelection)) {
      state.deckSelection = list[0] || "";
    }
    renderDeckList();
  }
}

function updateDeckActions() {
  const current = els.deckInput.value.trim();
  const exists = Boolean(current) && state.anki.decks.includes(current);
  const connected = state.anki.connected;
  els.renameDeckBtn.disabled = !connected || !exists;
  els.renameDeckBtn.title = !connected
    ? "Open Anki to rename a deck"
    : exists
      ? `Rename \u201c${current}\u201d in Anki`
      : "Rename is available for decks that already exist in Anki";
  els.newSubdeckBtn.disabled = !connected;
  els.newSubdeckBtn.title = connected
    ? "Create a subdeck"
    : "Open Anki to create a subdeck";
}

function openDeckDialog(focusSubdeck = false) {
  if (!els.deckDialog.open) {
    const current = els.deckInput.value.trim();
    const decks = state.anki.decks || [];
    state.deckSelection = current || decks[0] || "";
    els.deckSearch.value = "";
    els.deckPathInput.value = state.deckSelection;
    els.deckExact.checked = state.deckMode === "exact";
    els.subdeckName.value = "";
    renderDeckList();
    els.deckDialog.showModal();
  }
  updateDeckSelectionUi();
  setTimeout(() => {
    (focusSubdeck ? els.subdeckName : els.deckSearch).focus();
  }, 40);
}

function renderDeckList() {
  const query = els.deckSearch.value.trim().toLowerCase();
  const decks = (state.anki.decks || []).filter((deck) =>
    deck.toLowerCase().includes(query)
  );
  els.deckList.replaceChildren();

  if (!decks.length) {
    const empty = document.createElement("div");
    empty.className = "deck-empty";
    empty.textContent = state.anki.connected
      ? query
        ? "No decks match that search."
        : "No decks yet. Create your first deck by typing a name in the Deck field."
      : "Open Anki and click refresh to load your decks.";
    els.deckList.appendChild(empty);
    updateDeckSelectionUi();
    renderDeckChildren();
    return;
  }

  const fragment = document.createDocumentFragment();
  decks.forEach((deck) => {
    const parts = deck.split("::");
    const name = parts[parts.length - 1];
    const parent = parts.slice(0, -1).join("::");
    const depth = parts.length - 1;
    const item = document.createElement("button");
    item.type = "button";
    item.className = `deck-item${deck === state.deckSelection ? " is-selected" : ""}`;
    item.dataset.deck = deck;
    item.title = deck;
    item.setAttribute("role", "option");
    item.setAttribute("aria-selected", deck === state.deckSelection ? "true" : "false");
    item.style.paddingLeft = `${8 + depth * 16}px`;
    item.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" aria-hidden="true">
        <path d="M3.5 6.5h6l2 2h9v10h-17z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
      </svg>
      <span class="deck-item-name"></span>
    `;
    item.querySelector(".deck-item-name").textContent = name;
    if (parent) {
      const parentEl = document.createElement("span");
      parentEl.className = "deck-item-path";
      parentEl.textContent = parent;
      item.appendChild(parentEl);
    }
    fragment.appendChild(item);
  });
  els.deckList.appendChild(fragment);
  updateDeckSelectionUi();
  renderDeckChildren();
}

function renderDeckChildren() {
  const selected = state.deckSelection;
  const decks = state.anki.decks || [];
  const prefix = selected ? `${selected}::` : "";
  const children = decks
    .filter(
      (deck) =>
        prefix &&
        deck.startsWith(prefix) &&
        !deck.slice(prefix.length).includes("::")
    )
    .sort((a, b) => a.localeCompare(b));

  if (!children.length) {
    els.deckChildField.hidden = true;
    els.deckChildSelect.replaceChildren();
    return;
  }

  els.deckChildField.hidden = false;
  const current = els.deckChildSelect.value;
  els.deckChildSelect.replaceChildren();
  const none = document.createElement("option");
  none.value = "";
  none.textContent = "\u2014 none \u2014";
  els.deckChildSelect.appendChild(none);
  children.forEach((deck) => {
    const option = document.createElement("option");
    option.value = deck;
    option.textContent = deck.slice(prefix.length);
    els.deckChildSelect.appendChild(option);
  });
  if (children.includes(current)) els.deckChildSelect.value = current;
}

function updateDeckSelectionUi() {
  const selected = state.deckSelection;
  const exists = (state.anki.decks || []).includes(selected);
  if (selected) {
    const label = document.createElement("strong");
    label.textContent = selected;
    els.deckSelectedLabel.replaceChildren(
      document.createTextNode("Selected: "),
      label,
      document.createTextNode(exists ? "" : " (new deck)")
    );
  } else {
    els.deckSelectedLabel.textContent = "No deck selected";
  }
  els.useDeckBtn.disabled = !selected;
  const child = els.subdeckName.value.trim();
  const canCreate = Boolean(state.anki.connected && selected && exists);
  els.createSubdeckBtn.disabled = !canCreate;
  els.createSubdeckBtn.title = canCreate ? "" : "Select an existing deck and open Anki first";
  els.subdeckPathPreview.textContent = selected
    ? `${selected}::${child || "\u2026"}`
    : "\u2026";
  els.deckModeHint.textContent = els.deckExact.checked
    ? "Cards will go directly to this deck; no source/chapter subdecks will be added."
    : "Cards will be placed under this location, with source and chapter subdecks added.";
}

function updateSubdeckPreview() {
  updateDeckSelectionUi();
}

function useSelectedDeck() {
  if (!state.deckSelection) return;
  state.deckMode = els.deckExact.checked ? "exact" : "parent";
  try {
    localStorage.setItem("ankiScribeDeckMode", state.deckMode);
  } catch {
    // localStorage can be unavailable in locked-down browsers
  }
  els.deckInput.value = state.deckSelection;
  els.deckDialog.close();
  updateDeckModeLabel();
  updateDeckActions();
  updateCardDeckLabels();
  if (state.anki.connected) {
    updatePushDestination();
    if (!state.cards.length) {
      setPushStatus(`Ready \u2014 cards go to \u201c${state.deckSelection}\u201d.`);
    }
  }
}

async function createSubdeck() {
  if (!state.anki.connected) {
    toast("Open Anki to create a subdeck.", "error");
    return;
  }
  const parent = state.deckSelection;
  const name = els.subdeckName.value.trim();
  if (!parent) {
    toast("Select the deck to nest the new subdeck under.");
    return;
  }
  if (!name) {
    els.subdeckName.focus();
    toast("Give the subdeck a name.");
    return;
  }
  els.createSubdeckBtn.disabled = true;
  try {
    const data = await api("/api/anki/decks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ parent, name }),
    });
    fillDecks(data.decks || []);
    state.deckSelection = data.name;
    els.deckInput.value = data.name;
    els.deckDialog.close();
    updateDeckActions();
    toast(`Created \u201c${data.name}\u201d. New cards will go there.`, "success", 6000);
  } catch (error) {
    toast(error.message, "error", 9000);
  } finally {
    els.createSubdeckBtn.disabled = false;
    updateDeckSelectionUi();
  }
}

async function renameCurrentDeck() {
  const oldName = els.deckInput.value.trim();
  if (!state.anki.connected) {
    toast("Open Anki to rename a deck.", "error");
    return;
  }
  if (!state.anki.decks.includes(oldName)) {
    toast("That deck doesn't exist in Anki yet. Send a card to create it first.");
    return;
  }
  const proposed = window.prompt(
    `Rename \u201c${oldName}\u201d in Anki?\n\nExisting cards in this deck move with it.`,
    oldName
  );
  if (proposed === null) return;
  const newName = proposed.trim();
  if (!newName || newName === oldName) return;
  const confirmed = window.confirm(
    `Rename \u201c${oldName}\u201d to \u201c${newName}\u201d?\n\nThis changes your Anki collection.`
  );
  if (!confirmed) return;
  els.renameDeckBtn.disabled = true;
  try {
    const data = await api("/api/anki/decks/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ old: oldName, new: newName }),
    });
    state.anki.decks = data.decks || [];
    fillDecks(state.anki.decks);
    els.deckInput.value = data.name;
    state.deckSelection = data.name;
    updateDeckActions();
    toast(`Renamed to \u201c${data.name}\u201d.`, "success", 6000);
  } catch (error) {
    toast(error.message, "error", 9000);
  } finally {
    updateDeckActions();
  }
}

function setPushStatus(message, kind = "") {
  els.pushStatus.textContent = message;
  els.pushStatus.className = `push-status${kind ? ` ${kind}` : ""}`;
}

function updatePushDestination() {
  if (!state.anki.connected || !state.cards.length) return;
  if (state.deckMode === "exact") {
    setPushStatus(
      `Ready \u2014 cards go directly to \u201c${baseDeckParts().join("::")}\u201d.`
    );
    return;
  }
  const decks = new Set(state.cards.map((card) => cardDeckName(card)));
  if (decks.size > 1) {
    setPushStatus(
      `Ready \u2014 ${decks.size} chapter decks under \u201c${baseDeckParts().join("::")}\u201d.`
    );
  } else {
    setPushStatus(`Ready \u2014 cards go to \u201c${[...decks][0]}\u201d.`);
  }
}

/* ------------------------------------------------------------------ */
/* push                                                               */
/* ------------------------------------------------------------------ */

/* Only the source fields the ledger keeps, so a selection of forty lines does
   not turn into forty kilobytes of coordinates in the payload. */
const PUSH_SOURCE_KEYS = [
  "kind",
  "label",
  "file",
  "pages",
  "segments",
  "location",
  "quote",
  "evidence",
  "chapterPath",
  "chapterTitle",
  "deckPath",
  "sourceTitle",
];

function publicSource(source) {
  const out = {};
  PUSH_SOURCE_KEYS.forEach((key) => {
    if (source[key] !== undefined && source[key] !== null) out[key] = source[key];
  });
  return out;
}

function pushPayload(card) {
  const source = card.source && typeof card.source === "object" ? card.source : null;
  return {
    mode: card.mode,
    question: card.question || "",
    answer: card.answer || "",
    text: card.text || "",
    extra: card.extra || "",
    tags: card.tags || [],
    uid: card.uid || "",
    type: card.type || "",
    evidence: card.evidence || (source && source.evidence) || "",
    sourceLabel: (source && (source.file || source.sourceTitle)) || "",
    sourcePage: (source && source.label) || "",
    source: source ? publicSource(source) : null,
    figure: card.figure && typeof card.figure === "object" ? card.figure : null,
    image: card.image && typeof card.image === "object" ? card.image : null,
  };
}

function buildPushGroups(selected, baseDeck) {
  const groups = new Map();
  for (const card of selected) {
    const deck = cardDeckName(card) || baseDeck;
    if (!groups.has(deck)) groups.set(deck, []);
    groups.get(deck).push(card);
  }
  return groups;
}

/* Ask Anki which notes it would actually accept. Best effort: on a collection
   whose AnkiConnect predates canAddNotes we simply skip the confirmation. */
async function preflightPush(groups) {
  const results = new Map();
  let total = 0;
  let addable = 0;
  for (const [deck, cards] of groups) {
    const data = await api("/api/anki/preflight", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        deck,
        tags: els.extraTags.value.trim(),
        cards: cards.map(pushPayload),
      }),
    });
    const flags = Array.isArray(data.results) ? data.results : cards.map(() => true);
    results.set(deck, flags);
    total += Number(data.total) || cards.length;
    addable += Number(data.addable);
  }
  return { results, total, addable, duplicates: Math.max(0, total - addable) };
}

function closePushDialog() {
  if (els.pushDialog && els.pushDialog.open) els.pushDialog.close();
}

function cancelPendingPush() {
  state.pendingPush = null;
  closePushDialog();
  updatePushLabel();
}

function renderPushDialog(preflight) {
  els.pushSendNew.hidden = false;
  els.pushSendAll.hidden = false;
  if (els.pushSendAnyway) els.pushSendAnyway.hidden = true;
  els.pushDialogSummary.textContent =
    `${preflight.total} selected \u00b7 ${preflight.addable} new \u00b7 ` +
    `${preflight.duplicates} already in Anki`;
  els.pushDialogDetail.replaceChildren();
  state.pendingPush.groups.forEach((cards, deck) => {
    const flags = preflight.results.get(deck) || [];
    const fresh = flags.filter((value) => value !== false).length;
    const row = document.createElement("li");
    const name = document.createElement("span");
    name.className = "push-deck";
    name.textContent = deck;
    const count = document.createElement("span");
    count.className = "push-count";
    count.textContent =
      cards.length === fresh
        ? `${cards.length} new`
        : `${fresh} new \u00b7 ${cards.length - fresh} existing`;
    row.append(name, count);
    els.pushDialogDetail.appendChild(row);
  });
  els.pushSendNew.textContent = `Send ${preflight.addable} new`;
  els.pushSendNew.disabled = preflight.addable === 0;
  els.pushSendAll.textContent = `Send all ${preflight.total}`;
}


function isBlockedError(error) {
  return Boolean(
    error && error.detail && error.detail.error === "blocked_cards" && Array.isArray(error.detail.blocked)
  );
}

/* The gate refused a batch. Show exactly which cards and why, and keep the
   override explicit: sending a card you cannot answer is a decision, not an
   accident (constitution VII). */
function openBlockedDialog(detail, groups) {
  state.pendingPush = { groups, blocked: detail };
  els.pushDialogSummary.textContent =
    `${detail.message} Fix them, or send anyway.`;
  els.pushDialogDetail.replaceChildren();
  (detail.blocked || []).forEach((entry) => {
    const row = document.createElement("li");
    const name = document.createElement("span");
    name.className = "push-deck";
    name.textContent = entry.question || "(no question)";
    const why = document.createElement("span");
    why.className = "push-count";
    why.textContent = (entry.faults || []).map((fault) => fault.label).join(" \u00b7 ");
    row.append(name, why);
    if (entry.uid) {
      const open = document.createElement("button");
      open.type = "button";
      open.className = "text-btn";
      open.textContent = "Open";
      open.title = "Close this dialog and open the blocked card for editing";
      open.addEventListener("click", () => {
        closePushDialog();
        state.pendingPush = null;
        focusCard(entry.uid);
      });
      row.appendChild(open);
    }
    els.pushDialogDetail.appendChild(row);
  });
  els.pushSendNew.hidden = true;
  els.pushSendAll.hidden = true;
  if (els.pushSendAnyway) els.pushSendAnyway.hidden = false;
  if (!els.pushDialog.open) els.pushDialog.showModal();
}

function sendBlockedAnyway() {
  const pending = state.pendingPush;
  closePushDialog();
  state.pendingPush = null;
  if (!pending || !pending.groups) return;
  sendPushGroups(pending.groups, { allowBlocked: true });
}

function openPushDialog(preflight) {
  renderPushDialog(preflight);
  if (!els.pushDialog.open) els.pushDialog.showModal();
}

/* Send either everything or only the notes Anki said it would add. */
function confirmPush(sendAll) {
  const pending = state.pendingPush;
  closePushDialog();
  state.pendingPush = null;
  if (!pending) return;
  let groups = pending.groups;
  if (!sendAll) {
    groups = new Map();
    pending.groups.forEach((cards, deck) => {
      const flags = pending.preflight.results.get(deck) || [];
      const kept = cards.filter((_, index) => flags[index] !== false);
      if (kept.length) groups.set(deck, kept);
    });
  }
  sendPushGroups(groups);
}

function mergeLedger(ledger) {
  if (!ledger || !Array.isArray(ledger.cards) || !ledger.cards.length) return;
  const byId = new Map(state.sent.cards.map((card) => [card.id, card]));
  ledger.cards.forEach((card) => {
    if (card && card.id) byId.set(card.id, card);
  });
  state.sent = {
    path: ledger.path || state.sent.path,
    cards: Array.from(byId.values()),
    ready: true,
    request: state.sent.request,
  };
}

async function sendPushGroups(groups, options = {}) {
  if (state.pushing) return;
  let total = 0;
  groups.forEach((cards) => {
    total += cards.length;
  });
  if (!total) {
    toast("Nothing new to send.", "info");
    return;
  }

  const baseDeck = els.deckInput.value.trim();
  const sourcePath = state.drafts.path || state.sent.path || sourcePathForDraft(state.doc);

  state.pushing = true;
  els.pushBtn.classList.add("is-busy");
  els.pushBtn.disabled = true;
  els.pushLabel.textContent = "Sending\u2026";

  const jobs = [];
  groups.forEach((cards, deck) => {
    for (let index = 0; index < cards.length; index += 100) {
      jobs.push({ deck, cards: cards.slice(index, index + 100) });
    }
  });

  let created = 0;
  let duplicates = 0;
  let sentNow = 0;
  const decksUsed = new Set();
  try {
    for (let index = 0; index < jobs.length; index += 1) {
      const job = jobs[index];
      if (jobs.length > 1) {
        els.pushLabel.textContent = `Sending ${index + 1}/${jobs.length}\u2026`;
      }
      const result = await api("/api/anki/push", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          deck: job.deck,
          tags: els.extraTags.value.trim(),
          source_path: sourcePath,
          filename: state.doc ? state.doc.filename : "",
          cards: job.cards.map(pushPayload),
          allow_blocked: Boolean(options && options.allowBlocked),
        }),
      });
      created += result.created || 0;
      duplicates += result.duplicates || 0;
      sentNow += job.cards.length;
      decksUsed.add(job.deck);
      mergeLedger(result.ledger);
      if (result.ledger && result.ledger.warning) {
        toast(result.ledger.warning, "error", 9000);
      }
      const pushedIds = new Set(job.cards.map((card) => card.uid));
      state.cards = state.cards.filter((card) => !pushedIds.has(card.uid));
      renderCards();
      setPushStatus(
        `Sent ${sentNow}/${total} across ${decksUsed.size} deck` +
          `${decksUsed.size === 1 ? "" : "s"}\u2026`
      );
    }

    if (created === 0 && duplicates > 0) {
      toast(
        `All ${duplicates} card${duplicates === 1 ? " is" : "s are"} already in their decks.`,
        "success",
        6000
      );
    } else {
      const parts = [
        decksUsed.size === 1
          ? `Added ${created} card${created === 1 ? "" : "s"} to \u201c${[...decksUsed][0]}\u201d`
          : `Added ${created} card${created === 1 ? "" : "s"} across ${decksUsed.size} decks under \u201c${baseDeck}\u201d`,
      ];
      if (duplicates) parts.push(`${duplicates} already there`);
      toast(`${parts.join(" \u00b7 ")}.`, "success", 7000);
    }

    if (state.sent.cards.length) {
      setPushStatus(
        `${state.sent.cards.length} card${state.sent.cards.length === 1 ? "" : "s"} sent from this file. ` +
          "Coverage keeps them.",
        "ok"
      );
    }
  } catch (error) {
    toast(error.message, "error", 9000);
    setPushStatus(error.message, "error");
    if (/Couldn't reach Anki/i.test(error.message)) {
      setAnkiOff(error.message);
    }
  } finally {
    state.pushing = false;
    els.pushBtn.classList.remove("is-busy");
    updatePushLabel();
  }
}

async function pushToAnki() {
  if (state.pushing) return;
  if (state.auto.running) {
    toast("Wait for the chapter generation to finish.");
    return;
  }
  const selected = state.cards.filter((card) => card.selected);
  if (!selected.length) {
    toast("Select at least one card.");
    return;
  }
  const baseDeck = els.deckInput.value.trim();
  if (!baseDeck) {
    toast("Pick a parent deck first.", "error");
    els.deckInput.focus();
    return;
  }
  for (const card of selected) {
    if (card.mode === "cloze" && !/\{\{c\d+::.+?\}\}/.test(card.text || "")) {
      toast("A cloze card is missing its {{c1::\u2026}} deletion. Fix it before sending.", "error");
      return;
    }
    if (card.mode === "basic" && (!(card.question || "").trim() || !(card.answer || "").trim())) {
      toast("A card is missing its question or answer.", "error");
      return;
    }
  }

  const groups = buildPushGroups(selected, baseDeck);
  els.pushLabel.textContent = "Checking Anki\u2026";
  els.pushBtn.disabled = true;
  try {
    const preflight = await preflightPush(groups);
    if (preflight.duplicates > 0) {
      state.pendingPush = { groups, preflight };
      openPushDialog(preflight);
      return;
    }
  } catch (error) {
    if (isBlockedError(error)) {
      openBlockedDialog(error.detail, groups);
      return;
    }
    // Preflight is a courtesy, not a requirement.
    console.warn("Preflight unavailable", error);
  } finally {
    updatePushLabel();
  }
  sendPushGroups(groups);
}
