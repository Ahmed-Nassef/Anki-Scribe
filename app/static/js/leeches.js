"use strict";

/* Anki review history: surface real lapses and the leeches they produce.
 *
 * The sent ledger keeps the Anki note id for every pushed card. This module
 * joins those ids to AnkiConnect's notesInfo/cardsInfo and shows cards with
 * four or more lapses, plus a compact history summary used by the plan. */

function leechFileIds() {
  const ids = [];
  if (state.activeLibraryFileId) ids.push(state.activeLibraryFileId);
  else if (state.doc?.libraryFileId) ids.push(state.doc.libraryFileId);
  if (!ids.length && state.librarySelection?.size) {
    ids.push(...state.librarySelection);
  }
  return [...new Set(ids)];
}

function renderLeeches(data) {
  if (!els.leechesList) return;
  els.leechesList.replaceChildren();
  const totals = data.totals || {};
  if (els.leechesSummary) {
    els.leechesSummary.textContent =
      `${totals.cards || 0} cards in Anki \u00b7 ${totals.learned || 0} reviewed \u00b7 ` +
      `${totals.lapsed || 0} with a lapse \u00b7 ${totals.leeches || 0} leech${totals.leeches === 1 ? "" : "es"}`;
  }
  const leeches = Array.isArray(data.leeches) ? data.leeches : [];
  if (!leeches.length) {
    const empty = document.createElement("p");
    empty.className = "leeches-empty";
    empty.textContent =
      "No leeches yet. A leech is a card with four or more lapses; review a few more cards in Anki and check again.";
    els.leechesList.appendChild(empty);
    return;
  }
  for (const leech of leeches) {
    const item = document.createElement("article");
    item.className = "leech-item";
    const head = document.createElement("div");
    head.className = "leech-head";
    const title = document.createElement("strong");
    title.textContent = leech.front || "Untitled card";
    const count = document.createElement("span");
    count.className = "leech-count";
    count.textContent = `${leech.lapses} lapses \u00b7 ${leech.reps} reviews`;
    head.append(title, count);
    item.appendChild(head);
    if (leech.back) {
      const back = document.createElement("p");
      back.className = "leech-back";
      back.textContent = leech.back;
      item.appendChild(back);
    }
    const meta = document.createElement("div");
    meta.className = "leech-meta";
    meta.textContent = [leech.deck, leech.interval ? `${leech.interval}d interval` : ""]
      .filter(Boolean)
      .join(" \u00b7 ");
    item.appendChild(meta);
    const source = leech.source || {};
    if (source.label || source.file) {
      const origin = document.createElement("div");
      origin.className = "leech-source";
      origin.textContent = `Source: ${source.file || ""}${source.label ? ` \u00b7 ${source.label}` : ""}`;
      item.appendChild(origin);
    }
    if (
      state.doc &&
      source.file === state.doc.filename &&
      Array.isArray(source.pages) &&
      source.pages.length
    ) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "text-btn";
      button.textContent = "Show page";
      button.addEventListener("click", () => {
        closeLeeches();
        goToPage(Number(source.pages[0]) || 0);
      });
      item.appendChild(button);
    }
    els.leechesList.appendChild(item);
  }
}

async function openLeeches() {
  if (!els.leechesDialog) return;
  const fileIds = leechFileIds();
  if (!fileIds.length) {
    toast("Open a file from the Library first so its Anki notes can be matched.", "info", 5000);
    return;
  }
  if (els.leechesDialog.open) return;
  if (els.leechesList) {
    els.leechesList.replaceChildren(
      Object.assign(document.createElement("p"), {
        className: "leeches-empty",
        textContent: "Reading review history from Anki\u2026",
      })
    );
  }
  els.leechesDialog.showModal();
  try {
    const data = await api("/api/anki/review-history", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ file_ids: fileIds }),
    });
    renderLeeches(data);
  } catch (error) {
    if (els.leechesSummary) els.leechesSummary.textContent = "Couldn't read Anki history.";
    if (els.leechesList) {
      els.leechesList.replaceChildren(
        Object.assign(document.createElement("p"), {
          className: "leeches-empty",
          textContent: error.message,
        })
      );
    }
  }
}

function closeLeeches() {
  if (els.leechesDialog?.open) els.leechesDialog.close();
}

function bindLeechEvents() {
  if (els.leechesBtn) els.leechesBtn.addEventListener("click", openLeeches);
  if (els.closeLeeches) els.closeLeeches.addEventListener("click", closeLeeches);
  if (els.leechesClose) els.leechesClose.addEventListener("click", closeLeeches);
  if (els.leechesDialog) {
    els.leechesDialog.addEventListener("click", (event) => {
      if (event.target === els.leechesDialog) closeLeeches();
    });
  }
}
