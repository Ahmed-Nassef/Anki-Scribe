"use strict";

/* Draft-card persistence and automatic source highlighting. */

let lastDraftSaveWarning = 0;

function sourcePathForDraft(doc = state.doc) {
  // EPUB and PPTX pages live in a cache that is rebuilt under a new id, so the
  // drafts must be keyed to the file the user actually opened.
  if (doc && doc.originPath) return doc.originPath;
  if (doc && doc.sourcePath) return doc.sourcePath;
  const file = state.library.files.find(
    (item) => item.id === state.activeLibraryFileId
  );
  return file ? file.path : doc ? doc.id : "";
}

function resetDrafts() {
  if (state.drafts.saveTimer) clearTimeout(state.drafts.saveTimer);
  state.drafts = {
    path: "",
    ready: false,
    loading: false,
    request: 0,
    saveTimer: null,
  };
}

async function loadDraftsForDocument(doc) {
  const path = sourcePathForDraft(doc);
  if (!path) return;
  const request = state.drafts.request + 1;
  state.drafts = {
    path,
    ready: false,
    loading: true,
    request,
    saveTimer: null,
  };
  try {
    const data = await api(`/api/drafts?path=${encodeURIComponent(path)}`);
    if (
      !state.doc ||
      state.doc.id !== doc.id ||
      state.drafts.request !== request
    ) {
      return;
    }
    const cards = Array.isArray(data.cards)
      ? data.cards
          .filter((card) => card && typeof card === "object")
          .map((card) => ({
            ...card,
            uid: card.uid || uid(),
            selected: card.selected !== false,
            mode: card.mode === "cloze" ? "cloze" : "basic",
          }))
      : [];
    state.cards = cards;
    state.drafts.ready = true;
    state.drafts.loading = false;
    renderCards();
    applyDraftHighlights();
    if (cards.length) {
      toast(
        `Restored ${cards.length} draft card${cards.length === 1 ? "" : "s"}.`,
        "info",
        3500
      );
    }
  } catch (error) {
    if (
      !state.doc ||
      state.doc.id !== doc.id ||
      state.drafts.request !== request
    ) {
      return;
    }
    state.drafts.ready = true;
    state.drafts.loading = false;
    toast(`Couldn't restore draft cards: ${error.message}`, "error", 7000);
  }
}

function resetSent() {
  state.sent = { path: "", cards: [], ready: false, request: 0 };
}

/* Load what has already been sent to Anki for this source. Drafts and the
   ledger together are the source of truth for coverage and highlighting. */
async function loadSentForDocument(doc) {
  const path = sourcePathForDraft(doc);
  if (!path) return;
  const request = state.sent.request + 1;
  state.sent = { path, cards: state.sent.cards, ready: false, request };
  try {
    const data = await api(`/api/sent?path=${encodeURIComponent(path)}`);
    if (!state.doc || state.doc.id !== doc.id || state.sent.request !== request) {
      return;
    }
    state.sent = {
      path,
      cards: Array.isArray(data.cards) ? data.cards : [],
      ready: true,
      request,
    };
  } catch (error) {
    if (!state.doc || state.doc.id !== doc.id || state.sent.request !== request) {
      return;
    }
    state.sent = { path, cards: [], ready: true, request };
    console.warn("Couldn't load sent history", error);
  }
  renderCards();
  applyDraftHighlights();
}

function scheduleDraftSave() {
  if (!state.drafts.ready || !state.drafts.path || !state.doc) return;
  if (state.drafts.saveTimer) clearTimeout(state.drafts.saveTimer);
  state.drafts.saveTimer = setTimeout(() => {
    state.drafts.saveTimer = null;
    saveDraftsNow();
  }, 450);
}

/* The Fetch spec rejects a request whose keepalive body is over 64 KiB, so
   keepalive is only for the small unload flush. A normal save can be megabytes. */
const KEEPALIVE_LIMIT = 60_000;

async function saveDraftsNow({ beacon = false } = {}) {
  if (!state.drafts.ready || !state.drafts.path || !state.doc) return;
  const body = JSON.stringify({
    path: state.drafts.path,
    filename: state.doc.filename,
    cards: state.cards,
  });
  const canKeepAlive = beacon && body.length <= KEEPALIVE_LIMIT;

  if (canKeepAlive && typeof navigator !== "undefined" && navigator.sendBeacon) {
    const blob = new Blob([body], { type: "application/json" });
    if (navigator.sendBeacon("/api/drafts", blob)) return;
  }

  const options = {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
  };
  if (canKeepAlive) options.keepalive = true;

  try {
    await api("/api/drafts", options);
  } catch (error) {
    console.warn("Couldn't save draft cards", error, `${body.length} bytes`);
    // A silent autosave failure is how work disappears. Say it once, and not
    // once per keystroke.
    const now = Date.now();
    if (now - lastDraftSaveWarning > 30000) {
      lastDraftSaveWarning = now;
      toast(
        `Couldn't save your drafts: ${error.message}. Keep this tab open.`,
        "error",
        9000
      );
    }
  }
}

function flushDrafts({ beacon = false } = {}) {
  if (state.drafts.saveTimer) {
    clearTimeout(state.drafts.saveTimer);
    state.drafts.saveTimer = null;
  }
  if (state.drafts.ready && state.drafts.path) {
    saveDraftsNow({ beacon });
  }
}

function clearDraftHighlights() {
  document.querySelectorAll(".line.is-draft-source").forEach((span) => {
    span.classList.remove("is-draft-source");
  });
  document.querySelectorAll(".page.has-draft-source").forEach((pageEl) => {
    pageEl.classList.remove("has-draft-source");
  });
  document.querySelectorAll(".cue.is-draft-source").forEach((cue) => {
    cue.classList.remove("is-draft-source");
  });
  document.querySelectorAll("[data-card-uids]").forEach((node) => {
    delete node.dataset.cardUids;
    delete node.dataset.cardCycle;
  });
}

/* A highlighted line can belong to more than one card. Remembering the owners
   is what lets a click on the teal text jump back to the card that quoted it. */
function addCardOwner(node, uid) {
  if (!node || !uid) return;
  const owners = (node.dataset.cardUids || "").split(" ").filter(Boolean);
  if (!owners.includes(uid)) owners.push(uid);
  node.dataset.cardUids = owners.join(" ");
}

function sourceHasPage(source, pageIndex) {
  if (!source || typeof source !== "object") return false;
  if (Array.isArray(source.location)) {
    if (source.location.some((entry) => Number(entry && entry.page) === pageIndex)) {
      return true;
    }
  }
  if (Array.isArray(source.pages) && source.pages.length >= 2) {
    const start = Math.min(Number(source.pages[0]), Number(source.pages[1]));
    const end = Math.max(Number(source.pages[0]), Number(source.pages[1]));
    return pageIndex >= start && pageIndex <= end;
  }
  return false;
}

function markDraftLines(model, start, end, owner) {
  const spans = Array.from(model.el.querySelectorAll(".line"));
  const byIndex = new Map(
    spans.map((span) => [Number(span.dataset.lineIndex), span])
  );
  let marked = false;
  for (let index = start; index <= end; index += 1) {
    const span = byIndex.get(index);
    if (span) {
      span.classList.add("is-draft-source");
      addCardOwner(span, owner);
      marked = true;
    }
  }
  return marked;
}

function applyDraftHighlightsForPage(model) {
  const pageEl = model.el;
  pageEl.querySelectorAll(".line.is-draft-source").forEach((span) => {
    span.classList.remove("is-draft-source");
  });
  pageEl.querySelectorAll(".line[data-card-uids]").forEach((span) => {
    delete span.dataset.cardUids;
    delete span.dataset.cardCycle;
  });
  pageEl.classList.remove("has-draft-source");
  const cards = sourceCards();
  if (!cards.length) return;

  let pageUsed = false;
  for (const card of cards) {
    const source = card.source;
    if (!source || typeof source !== "object") continue;
    if (!sourceHasPage(source, model.index)) continue;
    pageUsed = true;

    let marked = false;
    if (Array.isArray(source.location)) {
      const indices = source.location
        .filter((entry) => Number(entry && entry.page) === model.index)
        .flatMap((entry) => (Array.isArray(entry.indices) ? entry.indices : []))
        .map(Number)
        .filter((index) => Number.isInteger(index) && index >= 0);
      if (indices.length) {
        marked = markDraftLines(
          model,
          Math.min(...indices),
          Math.max(...indices),
          card.uid
        );
      }
    }
    if (!marked && source.evidence && Array.isArray(model.lines)) {
      const found = searchEvidenceInLines(model.lines, source.evidence);
      if (found) marked = markDraftLines(model, found.start, found.end, card.uid);
    }
  }
  if (pageUsed) pageEl.classList.add("has-draft-source");
}

function applyTranscriptDraftHighlights() {
  const cues = Array.from(els.pages.querySelectorAll(".cue"));
  cues.forEach((cue) => {
    cue.classList.remove("is-draft-source");
    delete cue.dataset.cardUids;
    delete cue.dataset.cardCycle;
  });
  const cards = sourceCards();
  if (!cards.length || !state.transcript.segments.length) return;
  const segments = state.transcript.segments;

  for (const card of cards) {
    const source = card.source;
    if (!source || typeof source !== "object") continue;
    let indices = [];
    if (Array.isArray(source.location)) {
      indices = source.location
        .map((entry) => Number(entry && entry.segment))
        .filter((index) => Number.isInteger(index) && index >= 0);
    }
    if (!indices.length && Array.isArray(source.segments) && source.segments.length >= 2) {
      const start = Math.max(0, Number(source.segments[0]) - 1);
      const end = Math.min(segments.length - 1, Number(source.segments[1]) - 1);
      for (let index = start; index <= end; index += 1) indices.push(index);
    }
    if (!indices.length && source.evidence) {
      const found = searchEvidenceInLines(segments, source.evidence);
      if (found) {
        for (let index = found.start; index <= found.end; index += 1) {
          indices.push(index);
        }
      }
    }
    indices.forEach((index) => {
      const cue = cues.find((node) => Number(node.dataset.segment) === index);
      if (cue) {
        cue.classList.add("is-draft-source");
        addCardOwner(cue, card.uid);
      }
    });
  }
}

function applyDraftHighlights() {
  clearDraftHighlights();
  if (!state.doc) return;
  if (state.doc.kind === "transcript") {
    applyTranscriptDraftHighlights();
    return;
  }
  state.models.forEach((model) => applyDraftHighlightsForPage(model));
}
