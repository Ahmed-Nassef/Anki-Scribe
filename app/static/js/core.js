"use strict";

/* Shared state, DOM references and helpers */

const MIN_CHARS = 30;
const MAX_CHARS = 16000;
const ZOOM_MIN = 0.5;
const ZOOM_MAX = 2.5;

const $ = (id) => document.getElementById(id);

const state = {
  settings: {
    has_key: false,
    key_hint: "",
    base_url: "https://api.deepseek.com",
    model: "deepseek-chat",
    anki_url: "http://127.0.0.1:8765",
    default_deck: "Anki Scribe",
    default_tags: "anki-scribe",
  },
  anki: { connected: false, decks: [], message: "" },
  aiBalance: { loading: false, data: null, error: "" },
  coverage: { loading: false, data: null, error: "", request: 0 },
  deckSelection: "",
  deckMode:
    typeof localStorage !== "undefined" &&
    localStorage.getItem("ankiScribeDeckMode") === "exact"
      ? "exact"
      : "parent",
  strict:
    typeof localStorage !== "undefined" &&
    localStorage.getItem("ankiScribeStrict") === "1",
  style:
    (typeof localStorage !== "undefined" &&
      localStorage.getItem("ankiScribeStyle")) ||
    "balanced",
  library: { groups: [], files: [], lastOpenedFileId: null },
  librarySelection: new Set(),
  batch: { running: false, cancelled: false, index: 0, total: 0, results: [] },
  activeLibraryFileId: null,
  dragFileId: null,
  doc: null,
  transcript: { segments: [] },
  chapterPlan: null,
  drafts: {
    path: "",
    ready: false,
    loading: false,
    request: 0,
    saveTimer: null,
  },
  sent: { path: "", cards: [], ready: false, request: 0 },
  undo: { stack: [], redo: [] },
  pendingPush: null,
  triage: { queue: [], index: 0, accepted: 0, rejected: 0, revealed: false, rewriting: false },
  objectives: { items: [], loading: false, request: 0, busy: false },
  models: new Map(),
  selection: { text: "", label: "", location: [] },
  answers: {
    active:
      typeof localStorage !== "undefined" &&
      localStorage.getItem("ankiScribeHideAnswers") === "1",
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
  },
  plan: { request: 0, result: null, payload: null, scopeIds: [], sources: [], approximate: false },
  ocr: { docId: "", timer: null, request: 0, started: false, lastDone: 0, status: null },
  figureMode: false,
  imageCrop: null,
  imageTarget: null,
  mode: "basic",
  cards: [],
  /* Cards are built lazily: the list holds one slot per card, and the full
     markup is created only near the viewport. `cardHeights` keeps the measured
     height of a slot so placeholders do not jump when you scroll back. */
  cardHeights: {},
  zoom: 1,
  activePage: 0,
  generating: false,
  generateController: null,
  pushing: false,
  uploading: false,
  savingChapters: false,
  auto: {
    running: false,
    cancelled: false,
    controller: null,
    cards: 0,
    total: 0,
    hideTimer: null,
  },
  loadObserver: null,
  spyObserver: null,
  imageObserver: null,
};

const els = {};

/* ------------------------------------------------------------------ */
/* helpers                                                            */
/* ------------------------------------------------------------------ */

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const type = response.headers.get("content-type") || "";
  let data = null;
  if (type.includes("application/json")) {
    data = await response.json().catch(() => null);
  }
  if (!response.ok) {
    let message = data && data.detail ? data.detail : `Request failed (HTTP ${response.status}).`;
    let detail = null;
    if (Array.isArray(message)) {
      message = message.map((entry) => entry.msg || String(entry)).join("; ");
    } else if (message && typeof message === "object") {
      /* A structured refusal (the quality gate) carries a message plus the
         cards that caused it; keep both, so the caller can render the list. */
      detail = message;
      message = message.message || `Request failed (HTTP ${response.status}).`;
    }
    const error = new Error(String(message));
    if (detail) error.detail = detail;
    throw error;
  }
  return data;
}

function uid() {
  if (typeof crypto !== "undefined" && crypto.randomUUID) return crypto.randomUUID();
  return `c${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
}

function debounce(fn, ms) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

function isTypingTarget(node) {
  if (!node || !node.tagName) return false;
  const tag = node.tagName.toLowerCase();
  if (tag === "textarea" || tag === "select") return true;
  if (tag === "input") {
    const type = String(node.type || "text").toLowerCase();
    return !["checkbox", "radio", "button", "submit", "file", "range"].includes(type);
  }
  return Boolean(node.isContentEditable);
}

function splitTags(value) {
  return String(value || "")
    .split(/[,\n]+/)
    .map((tag) => tag.trim())
    .filter(Boolean);
}

/* Every card that belongs to the open source: drafts plus what is already in
   Anki. Coverage and the source map are derived from this, so a push makes
   text *more* covered, never less. */
function sourceCards() {
  const sent = state.sent.cards || [];
  if (!sent.length) return state.cards;
  return state.cards.concat(sent);
}

function toastHost() {
  const dialogs = Array.from(document.querySelectorAll("dialog[open]"));
  const dialog = dialogs[dialogs.length - 1];
  if (dialog) {
    if (els.toasts.parentElement !== dialog) dialog.appendChild(els.toasts);
    return els.toasts;
  }
  if (els.toasts.parentElement !== document.body) {
    document.body.appendChild(els.toasts);
  }
  return els.toasts;
}

function toast(message, kind = "info", ms = 5000, action = null) {
  const node = document.createElement("div");
  node.className = `toast ${kind}`;

  const icon = document.createElement("span");
  icon.className = "toast-icon";
  icon.textContent = kind === "error" ? "!" : kind === "success" ? "\u2713" : "i";

  const text = document.createElement("p");
  text.textContent = message;

  const close = document.createElement("button");
  close.type = "button";
  close.className = "toast-close";
  close.setAttribute("aria-label", "Dismiss");
  close.textContent = "\u00d7";

  const remove = () => node.remove();
  close.addEventListener("click", remove);
  node.append(icon, text);

  if (action && action.label && typeof action.run === "function") {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "toast-action";
    button.textContent = action.label;
    button.addEventListener("click", () => {
      remove();
      action.run();
    });
    node.appendChild(button);
  }

  node.appendChild(close);
  const host = toastHost();
  host.appendChild(node);
  while (host.children.length > 4) {
    host.firstElementChild.remove();
  }
  setTimeout(remove, ms);
}
