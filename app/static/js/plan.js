"use strict";

/* Study plan: an exam date, an amount to learn and daily time, scheduled with
   FSRS-6 (see app/fsrs.py). */

const PLAN_PREF_KEY = "ankiScribePlan";

function planClozeItems(card) {
  const text = String(card.text || card.question || "");
  const numbers = new Set();
  for (const match of text.matchAll(/\{\{c(\d+)::/g)) numbers.add(match[1]);
  return numbers.size || 1;
}

/* A study item is one thing FSRS would schedule: a Q&A card, a figure card,
   each distinct cloze deletion, or an answer the student hid by hand. */
function planItemBreakdown() {
  const seen = new Set();
  const items = { basic: 0, cloze: 0, figure: 0, manual: 0, total: 0 };
  for (const card of sourceCards()) {
    const uid = String(card.uid || card.id || "");
    if (!uid || seen.has(uid)) continue;
    seen.add(uid);
    if (card.selected === false) continue;
    if (card.mode === "figure") {
      items.figure += 1;
    } else if (card.mode === "cloze") {
      items.cloze += planClozeItems(card);
    } else {
      items.basic += 1;
    }
  }
  const manualIds = new Set(
    (state.answers.manual || []).map((mask) => String(mask.id))
  );
  items.manual = manualIds.size;
  items.total = items.basic + items.cloze + items.figure + items.manual;
  return items;
}

function planAvailableItems() {
  if (state.plan.scopeIds.length) return planScopeItems().total;
  return planItemBreakdown().total;
}

function planScopeItems() {
  const items = { basic: 0, cloze: 0, figure: 0, manual: 0, total: 0 };
  const sources = state.plan.sources || [];
  for (const source of sources) {
    items.basic += Number(source.basic) || 0;
    items.cloze += Number(source.cloze) || 0;
    items.figure += Number(source.figure) || 0;
    items.manual += Number(source.manual) || 0;
  }
  const currentId = state.activeLibraryFileId || state.doc?.libraryFileId || "";
  const covered =
    currentId && sources.some((source) => String(source.fileId) === String(currentId));
  if (state.doc && (!state.plan.scopeIds.length || covered)) {
    const current = planItemBreakdown();
    items.basic += current.basic;
    items.cloze += current.cloze;
    items.figure += current.figure;
    items.manual += current.manual;
  }
  items.total = items.basic + items.cloze + items.figure + items.manual;
  return items;
}

function planBreakdownText(items, sourceCount = 0) {
  const parts = [];
  if (items.basic) parts.push(`${items.basic} Q&A`);
  if (items.cloze) parts.push(`${items.cloze} cloze`);
  if (items.figure) parts.push(`${items.figure} figure${items.figure === 1 ? "" : "s"}`);
  if (items.manual) parts.push(`${items.manual} hidden`);
  const files = sourceCount > 1 ? ` across ${sourceCount} files` : "";
  return `${items.total} study item${items.total === 1 ? "" : "s"}${files}${
    parts.length ? `: ${parts.join(" + ")}` : ""
  }`;
}

function planFallbackSources(fileIds) {
  const files = Array.isArray(state.library.files) ? state.library.files : [];
  const rows = [];
  for (const id of fileIds) {
    const file = files.find((item) => String(item.id) === String(id));
    if (!file) continue;
    const count =
      (Number(file.draftCount) || 0) + (Number(file.sentCount) || 0);
    rows.push({
      fileId: file.id,
      name: file.name,
      basic: count,
      cloze: 0,
      figure: 0,
      manual: 0,
      total: count,
      approximate: true,
    });
  }
  return rows;
}

function planCountCards(cards) {
  const seen = new Set();
  const items = { basic: 0, cloze: 0, figure: 0, manual: 0, total: 0 };
  for (const card of cards) {
    if (!card || card.selected === false) continue;
    const uid = String(card.uid || card.id || "");
    if (uid) {
      if (seen.has(uid)) continue;
      seen.add(uid);
    }
    if (card.mode === "figure") items.figure += 1;
    else if (card.mode === "cloze") items.cloze += planClozeItems(card);
    else items.basic += 1;
  }
  items.total = items.basic + items.cloze + items.figure + items.manual;
  return items;
}

async function planDirectSources(fileIds) {
  const files = Array.isArray(state.library.files) ? state.library.files : [];
  const rows = [];
  for (const id of fileIds) {
    const file = files.find((item) => String(item.id) === String(id));
    if (!file) continue;
    const path = encodeURIComponent(file.path);
    const [drafts, sent, masks] = await Promise.all([
      api(`/api/drafts?path=${path}`).catch(() => ({ cards: [] })),
      api(`/api/sent?path=${path}`).catch(() => ({ cards: [] })),
      api(`/api/masks?path=${path}`).catch(() => ({ masks: [] })),
    ]);
    const items = planCountCards([
      ...(Array.isArray(drafts.cards) ? drafts.cards : []),
      ...(Array.isArray(sent.cards) ? sent.cards : []),
    ]);
    items.manual = Array.isArray(masks.masks) ? masks.masks.length : 0;
    items.total = items.basic + items.cloze + items.figure + items.manual;
    rows.push({
      fileId: file.id,
      name: file.name,
      ...items,
    });
  }
  return rows;
}

function updatePlanAvailability() {
  if (!els.planCards) return;
  const items = planScopeItems();
  const available = items.total;
  els.planCards.max = String(Math.min(available, 10000));
  if (Number(els.planCards.value) > available) {
    els.planCards.value = String(available);
  }
  const sourceCount = state.plan.scopeIds.length || 0;
  els.planCardsHint.textContent =
    planBreakdownText(items, sourceCount) +
    (state.plan.approximate ? " \u00b7 approximate" : "");
}

function planLocalIso(day) {
  const year = day.getFullYear();
  const month = String(day.getMonth() + 1).padStart(2, "0");
  const date = String(day.getDate()).padStart(2, "0");
  return `${year}-${month}-${date}`;
}

function planDateFromIso(value) {
  return new Date(`${value}T00:00:00`);
}

function planToday() {
  const now = new Date();
  return new Date(now.getFullYear(), now.getMonth(), now.getDate());
}

function planDefaultDeadline() {
  const day = planToday();
  day.setDate(day.getDate() + 7);
  return planLocalIso(day);
}

function formatPlanDate(value) {
  const date = planDateFromIso(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleDateString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
  });
}

function formatPlanMinutes(value) {
  const minutes = Number(value) || 0;
  if (minutes >= 90) {
    return `${(minutes / 60).toFixed(1)} h`;
  }
  return `${Math.max(0, Math.round(minutes))} min`;
}

function planRatingLabel(value) {
  if (String(value) === "2") return "Hard";
  if (String(value) === "4") return "Easy";
  return "Good";
}

function planClock(value, fallback) {
  const match = /^(\d{1,2}):(\d{2})$/.exec(String(value || ""));
  if (!match) return fallback;
  const minutes = Number(match[1]) * 60 + Number(match[2]);
  return Number.isFinite(minutes) && minutes >= 0 && minutes <= 1439
    ? minutes
    : fallback;
}

function formatPlanClock(minutes) {
  const value = ((Math.round(minutes) % 1440) + 1440) % 1440;
  return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(
    value % 60
  ).padStart(2, "0")}`;
}

function updatePlanWindow() {
  if (!els.planStart || !els.planEnd) return 60;
  const start = planClock(els.planStart.value, 8 * 60);
  const end = planClock(els.planEnd.value, 22 * 60);
  const minutes = end - start;
  if (minutes < 5) {
    if (els.planWindowHint) els.planWindowHint.textContent = "End must be after start";
    if (els.planMinutes) els.planMinutes.value = "0";
    return 0;
  }
  if (els.planMinutes) els.planMinutes.value = String(minutes);
  if (els.planWindowHint) {
    els.planWindowHint.textContent = `${formatPlanMinutes(minutes)} per day \u00b7 ${formatPlanClock(
      start
    )}\u2013${formatPlanClock(end)}`;
  }
  return minutes;
}

function planBufferLimit() {
  const deadline = els.planDeadline.value
    ? planDateFromIso(els.planDeadline.value)
    : planDateFromIso(planDefaultDeadline());
  if (Number.isNaN(deadline.getTime())) return 60;
  return Math.max(
    0,
    Math.min(60, Math.round((deadline.getTime() - planToday().getTime()) / 86400000) - 1)
  );
}

function clampPlanBuffer() {
  if (!els.planBuffer) return;
  const limit = planBufferLimit();
  els.planBuffer.max = String(limit);
  if (Number(els.planBuffer.value) > limit) {
    els.planBuffer.value = String(limit);
  }
}

function loadPlanPrefs() {
  try {
    const raw = localStorage.getItem(PLAN_PREF_KEY);
    const parsed = raw ? JSON.parse(raw) : null;
    return parsed && typeof parsed === "object" ? parsed : {};
  } catch {
    return {};
  }
}

function savePlanPrefs(payload) {
  try {
    localStorage.setItem(
      PLAN_PREF_KEY,
      JSON.stringify({
        deadline: payload.deadline,
        minutes: payload.minutes,
        start_time: payload.start_time,
        end_time: payload.end_time,
        buffer_days: payload.buffer_days,
        retention: payload.retention,
        rating: payload.rating,
        weekdays: payload.weekdays,
        new_seconds: payload.new_seconds,
        review_seconds: payload.review_seconds,
        session_minutes: payload.session_minutes,
        break_minutes: payload.break_minutes,
      })
    );
  } catch {
    // A private-mode browser may refuse storage; the plan still works.
  }
}

async function openPlanDialog(options = {}) {
  const fileIds = Array.isArray(options?.fileIds) ? options.fileIds : [];
  state.plan.scopeIds = fileIds;
  state.plan.sources = [];
  state.plan.approximate = false;
  state.plan.history = null;
  if (fileIds.length) {
    try {
      const data = await api("/api/plan/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_ids: fileIds }),
      });
      state.plan.sources = Array.isArray(data.files) ? data.files : [];
    } catch (error) {
      // A server started before the multi-file endpoint existed returns 404.
      // The older drafts/sent/masks endpoints still exist, so count exactly
      // from those before falling back to coarse library counts.
      try {
        state.plan.sources = await planDirectSources(fileIds);
        state.plan.approximate = false;
        toast(
          "The running server is older; counts were read directly from drafts and history. Restart Anki Scribe when convenient.",
          "info",
          9000
        );
      } catch (fallbackError) {
        state.plan.sources = planFallbackSources(fileIds);
        state.plan.approximate = true;
        toast(
          "The running server is older; using approximate card counts. Restart Anki Scribe for exact cloze and hidden-answer counts.",
          "info",
          10000
        );
      }
    }
  }
  if (fileIds.length) {
    try {
      state.plan.history = await api("/api/anki/review-history", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_ids: fileIds }),
      });
    } catch {
      state.plan.history = null;
    }
  }
  if (!state.doc && !fileIds.length) {
    toast("Open a file first.", "info", 3000);
    return;
  }
  const available = planAvailableItems();
  if (!available) {
    toast(
      "Generate cards or hide an answer first \u2014 the plan schedules study items, not pages.",
      "info",
      6000
    );
    return;
  }
  const prefs = loadPlanPrefs();
  const deadline = prefs.deadline && prefs.deadline > planLocalIso(planToday())
    ? prefs.deadline
    : planDefaultDeadline();
  els.planDeadline.min = planLocalIso(new Date(planToday().getTime() + 86400000));
  els.planDeadline.value = deadline;
  els.planCards.max = String(Math.min(available, 10000));
  const preferredCards = Number(prefs.cards);
  els.planCards.value = String(
    Number.isFinite(preferredCards) && preferredCards > 0
      ? Math.min(preferredCards, available)
      : available
  );
  els.planStart.value = prefs.start_time || "08:00";
  els.planEnd.value = prefs.end_time || "22:00";
  updatePlanWindow();
  updatePlanAvailability();
  els.planSubtitle.textContent = fileIds.length
    ? `FSRS-6 schedule across ${fileIds.length} selected file${fileIds.length === 1 ? "" : "s"}; Q&A cards, every cloze deletion and hand-hidden answers count as items.`
    : "FSRS-6 schedule for Q&A cards, every cloze deletion and the answers you hid by hand. It assumes they are new.";
  els.planBuffer.value = String(
    Math.min(
      Number.isFinite(Number(prefs.buffer_days)) ? Number(prefs.buffer_days) : 2,
      Math.max(
        0,
        Math.round(
          (planDateFromIso(deadline).getTime() - planToday().getTime()) / 86400000
        ) - 1
      ),
      60
    )
  );
  clampPlanBuffer();
  els.planRetention.value = String(
    Math.round((Number(prefs.retention) || 0.9) * 100)
  );
  els.planRetentionValue.textContent = `${els.planRetention.value}%`;
  els.planRating.value = String(prefs.rating || 3);
  els.planNewSeconds.value = String(prefs.new_seconds || 60);
  els.planReviewSeconds.value = String(prefs.review_seconds || 15);
  els.planSession.value = String(prefs.session_minutes || 50);
  els.planBreak.value = String(
    Number.isFinite(Number(prefs.break_minutes)) ? prefs.break_minutes : 10
  );
  const weekdays = Array.isArray(prefs.weekdays) ? prefs.weekdays : [0, 1, 2, 3, 4, 5, 6];
  document.querySelectorAll("[data-weekday]").forEach((box) => {
    box.checked = weekdays.includes(Number(box.dataset.weekday));
  });
  if (!document.querySelector("[data-weekday]:checked")) {
    document.querySelectorAll("[data-weekday]").forEach((box) => {
      box.checked = true;
    });
  }
  els.planResult.hidden = true;
  els.planResult.replaceChildren();
  els.planCopy.hidden = true;
  if (els.planIcs) els.planIcs.hidden = true;
  els.planRun.disabled = false;
  els.planRun.textContent = "Make schedule";
  state.plan.result = null;
  state.plan.payload = null;
  updatePlanNote(available);
  if (typeof els.planDialog.showModal === "function") {
    els.planDialog.showModal();
    els.planCards.focus();
  }
}

function updatePlanNote(available) {
  if (!els.planNote) return;
  const sent = state.sent && Array.isArray(state.sent.cards) ? state.sent.cards.length : 0;
  const items = planScopeItems();
  const sourceCount = state.plan.scopeIds.length || 0;
  const breakdown = planBreakdownText(items, sourceCount);
  const sourceText = sourceCount
    ? ` ${sourceCount} selected file${sourceCount === 1 ? "" : "s"}; `
    : " ";
  const history = state.plan.history?.totals;
  const historyText =
    history && history.cards
      ? `Anki history: ${history.learned} reviewed, ${history.lapsed} with lapses, ${history.leeches} leech${history.leeches === 1 ? "" : "es"}; this planner still treats the items as new. `
      : "";
  els.planNote.textContent =
    `${breakdown}.${sourceText}` +
    historyText +
    (sent && !sourceCount
      ? `${sent} cards are already in Anki; the plan treats every item as new because it cannot read Anki's review history. `
      : "") +
    (state.plan.approximate
      ? "These are approximate card counts from the library; restart the app for exact cloze and hidden-answer counts. "
      : "") +
    "Each cloze deletion counts once, answers you hid by hand count as items, and every item is treated as new. Card creation and reading time are the per-card estimate below.";
}

function closePlanDialog() {
  state.plan.scopeIds = [];
  state.plan.sources = [];
  state.plan.approximate = false;
  state.plan.history = null;
  if (els.planDialog && els.planDialog.open) els.planDialog.close();
}

function collectPlanPayload() {
  const weekdays = Array.from(document.querySelectorAll("[data-weekday]:checked"))
    .map((box) => Number(box.dataset.weekday))
    .filter((day) => Number.isInteger(day) && day >= 0 && day <= 6);
  if (!weekdays.length) {
    throw new Error("Choose at least one study day.");
  }
  const start = planLocalIso(planToday());
  const deadline = els.planDeadline.value;
  if (!deadline || deadline <= start) {
    throw new Error("Pick an exam date after today.");
  }
  const cards = Number(els.planCards.value);
  const available = planAvailableItems();
  if (!Number.isInteger(cards) || cards < 1) {
    throw new Error("Enter how many cards you need to learn.");
  }
  if (cards > available) {
    throw new Error(`This selection only has ${available} selected items.`);
  }
  const minutes = updatePlanWindow();
  if (!Number.isFinite(minutes) || minutes < 5) {
    throw new Error("Set an end time later than the start time.");
  }
  const startTime = els.planStart.value || "08:00";
  const endTime = els.planEnd.value || "22:00";
  const buffer = Number(els.planBuffer.value);
  if (!Number.isFinite(buffer) || buffer < 0) {
    throw new Error("The review buffer cannot be negative.");
  }
  const retention = Number(els.planRetention.value) / 100;
  const rating = Number(els.planRating.value);
  const newSeconds = Number(els.planNewSeconds.value);
  const reviewSeconds = Number(els.planReviewSeconds.value);
  const sessionMinutes = Number(els.planSession.value);
  const breakMinutes = Number(els.planBreak.value);
  if (!Number.isFinite(newSeconds) || newSeconds < 5) {
    throw new Error("Seconds per new card must be at least 5.");
  }
  if (!Number.isFinite(reviewSeconds) || reviewSeconds < 3) {
    throw new Error("Seconds per review must be at least 3.");
  }
  if (!Number.isFinite(sessionMinutes) || sessionMinutes < 10) {
    throw new Error("A study session must be at least 10 minutes.");
  }
  if (!Number.isFinite(breakMinutes) || breakMinutes < 0) {
    throw new Error("The break cannot be negative.");
  }
  return {
    start,
    deadline,
    cards,
    minutes: Math.round(minutes),
    start_time: startTime,
    end_time: endTime,
    weekdays,
    buffer_days: Math.round(buffer),
    retention,
    rating,
    new_seconds: Math.round(newSeconds),
    review_seconds: Math.round(reviewSeconds),
    session_minutes: Math.round(sessionMinutes),
    break_minutes: Math.round(breakMinutes),
  };
}

function planChip(label, value) {
  const chip = document.createElement("span");
  chip.className = "plan-chip";
  const strong = document.createElement("strong");
  strong.textContent = value;
  const text = document.createElement("span");
  text.textContent = label;
  chip.append(strong, text);
  return chip;
}

function planText(tag, className, value) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  node.textContent = value;
  return node;
}

function planShortFile(name) {
  const stem = String(name || "File").replace(/\.[^.]+$/, "");
  return stem.length > 18 ? `${stem.slice(0, 17)}\u2026` : stem;
}

function allocatePlanFiles(result) {
  const sources = state.plan.sources || [];
  if (sources.length < 2 || !result || !Array.isArray(result.days)) return null;
  const remaining = new Map(
    sources.map((source) => [
      String(source.fileId),
      Math.max(0, Number(source.total) || 0),
    ])
  );
  const totals = new Map(sources.map((source) => [String(source.fileId), 0]));
  for (const row of result.days) {
    let left = Math.max(0, Number(row.new) || 0);
    const parts = [];
    for (const source of sources) {
      if (left <= 0) break;
      const key = String(source.fileId);
      const take = Math.min(left, remaining.get(key) || 0);
      if (!take) continue;
      remaining.set(key, (remaining.get(key) || 0) - take);
      totals.set(key, (totals.get(key) || 0) + take);
      parts.push({ fileId: key, name: source.name, count: take });
      left -= take;
    }
    row.filePlan = parts;
  }
  return { sources, totals, remaining };
}

function renderPlanTable(result, payload, showFiles = false) {
  const wrap = document.createElement("div");
  wrap.className = "plan-table-wrap";
  const table = document.createElement("table");
  table.className = "plan-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  const headers = ["Date", "New", "Reviews", "Time", "Learned"];
  if (showFiles) headers.splice(2, 0, "Files");
  for (const label of headers) {
    headRow.appendChild(planText("th", "", label));
  }
  thead.appendChild(headRow);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const row of result.days) {
    const tr = document.createElement("tr");
    tr.className = "plan-day";
    if (row.over) tr.classList.add("is-over");
    if (!row.new && !row.reviews) tr.classList.add("is-empty");
    tr.appendChild(planText("td", "plan-date", formatPlanDate(row.date)));
    tr.appendChild(planText("td", "plan-num", row.new ? `+${row.new}` : "\u2014"));
    if (showFiles) {
      const parts = Array.isArray(row.filePlan) ? row.filePlan : [];
      tr.appendChild(
        planText(
          "td",
          "plan-files",
          parts.length
            ? parts
                .map((part) => `${planShortFile(part.name)} ${part.count}`)
                .join(" \u00b7 ")
            : "\u2014"
        )
      );
    }
    tr.appendChild(planText("td", "plan-num", row.reviews ? String(row.reviews) : "\u2014"));
    tr.appendChild(planText("td", "plan-time", formatPlanMinutes(row.minutes)));
    tr.appendChild(planText("td", "plan-num", String(row.learned)));
    tbody.appendChild(tr);
  }
  const examRow = document.createElement("tr");
  examRow.className = "plan-exam";
  const examCell = planText(
    "td",
    "",
    `Exam \u00b7 ${formatPlanDate(payload.deadline)}`
  );
  examCell.colSpan = showFiles ? 6 : 5;
  examRow.appendChild(examCell);
  tbody.appendChild(examRow);
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
}

function renderPlanFiles(allocation) {
  if (!allocation) return document.createDocumentFragment();
  const box = document.createElement("div");
  box.className = "plan-file-summary";
  const head = document.createElement("strong");
  head.textContent = "Plan by file";
  box.appendChild(head);
  for (const source of allocation.sources) {
    const key = String(source.fileId);
    const planned = allocation.totals.get(key) || 0;
    const left = allocation.remaining.get(key) || 0;
    const row = document.createElement("div");
    row.className = "plan-file-row";
    row.append(
      planText("span", "plan-file-name", planShortFile(source.name)),
      planText(
        "span",
        "plan-file-count",
        `${planned} planned${left ? ` \u00b7 ${left} beyond this plan` : ""}`
      )
    );
    box.appendChild(row);
  }
  return box;
}

function planDaySessions(day, payload) {
  const start = planClock(payload.start_time, 8 * 60);
  const end = planClock(payload.end_time, 22 * 60);
  const sessionMinutes = Math.max(
    10,
    Math.min(180, Number(payload.session_minutes) || 50)
  );
  const breakMinutes = Math.max(0, Math.min(60, Number(payload.break_minutes) || 0));
  let reviewLeft = Number(day.reviews) || 0;
  let newLeft = Number(day.new) || 0;
  let cursor = start;
  const sessions = [];
  while (cursor < end && (reviewLeft || newLeft)) {
    const sessionEnd = Math.min(cursor + sessionMinutes, end);
    let seconds = (sessionEnd - cursor) * 60;
    const reviews = Math.min(
      reviewLeft,
      Math.floor(seconds / Math.max(3, Number(payload.review_seconds) || 15))
    );
    seconds -= reviews * Math.max(3, Number(payload.review_seconds) || 15);
    const news = Math.min(
      newLeft,
      Math.floor(seconds / Math.max(5, Number(payload.new_seconds) || 60))
    );
    reviewLeft -= reviews;
    newLeft -= news;
    if (reviews || news) {
      sessions.push({
        start: cursor,
        end: sessionEnd,
        new: news,
        reviews,
        break: false,
      });
    }
    cursor = sessionEnd;
    if (cursor < end && breakMinutes > 0 && (reviewLeft || newLeft)) {
      const breakEnd = Math.min(cursor + breakMinutes, end);
      sessions.push({
        start: cursor,
        end: breakEnd,
        new: 0,
        reviews: 0,
        break: true,
      });
      cursor = breakEnd;
    }
  }
  return { sessions, remaining: reviewLeft + newLeft };
}

function renderPlanHours(result, payload) {
  const days = (result.days || []).filter((day) => day.new || day.reviews);
  if (!days.length) return document.createDocumentFragment();
  const start = planClock(payload.start_time, 8 * 60);
  const end = planClock(payload.end_time, 22 * 60);
  if (end - start < 5) return document.createDocumentFragment();

  const details = document.createElement("details");
  details.className = "plan-hours";
  details.open = days.length === 1;
  const summary = document.createElement("summary");
  summary.textContent = `Hour-by-hour \u00b7 ${formatPlanClock(start)}\u2013${formatPlanClock(end)}`;
  details.appendChild(summary);

  const select = document.createElement("select");
  select.className = "plan-hours-day";
  select.setAttribute("aria-label", "Day to show hour by hour");
  for (const day of days) {
    const option = document.createElement("option");
    option.value = day.date;
    option.textContent = formatPlanDate(day.date);
    select.appendChild(option);
  }
  details.appendChild(select);

  const list = document.createElement("div");
  list.className = "plan-hours-list";
  details.appendChild(list);

  function draw() {
    list.replaceChildren();
    const day = days.find((item) => item.date === select.value) || days[0];
    if (Array.isArray(day.filePlan) && day.filePlan.length) {
      const filesLine = document.createElement("p");
      filesLine.className = "plan-hours-files";
      filesLine.textContent =
        "New: " +
        day.filePlan
          .map((part) => `${planShortFile(part.name)} ${part.count}`)
          .join(" \u00b7 ");
      list.appendChild(filesLine);
    }
    let rendered = 0;
    const plan = planDaySessions(day, payload);
    for (const session of plan.sessions) {
      const row = document.createElement("div");
      row.className = session.break ? "plan-hour is-break" : "plan-hour";
      const range = planText(
        "span",
        "plan-hour-range",
        `${formatPlanClock(session.start)}\u2013${formatPlanClock(session.end)}`
      );
      if (session.break) {
        row.append(range, planText("span", "plan-hour-work", "Break"));
      } else {
        const counts = [];
        if (session.new) counts.push(`${session.new} new`);
        if (session.reviews) {
          counts.push(
            `${session.reviews} review${session.reviews === 1 ? "" : "s"}`
          );
        }
        row.append(range, planText("span", "plan-hour-work", counts.join(" \u00b7 ")));
        rendered += session.new + session.reviews;
      }
      list.appendChild(row);
    }
    if (!rendered) {
      list.appendChild(
        planText("p", "plan-hours-empty", "No items fit in this study window.")
      );
    }
    if (plan.remaining) {
      list.appendChild(
        planText(
          "p",
          "plan-hours-empty",
          `${plan.remaining} item${plan.remaining === 1 ? "" : "s"} do not fit in this window; add time or move the deadline.`
        )
      );
    }
  }

  select.addEventListener("change", draw);
  draw();
  return details;
}

function renderPlan(result, payload) {
  const target = els.planResult;
  target.replaceChildren();
  target.hidden = false;
  const summary = result.summary || {};
  const valid = Boolean(result.feasible);

  const verdict = document.createElement("div");
  verdict.className = `plan-verdict ${valid ? "is-ok" : "is-bad"}`;
  const headline = planText(
    "strong",
    "",
    valid
      ? "This fits your time"
      : result.reason === "buffer"
        ? "The review buffer leaves no new-card days"
        : "Not enough time at this pace"
  );
  const detail = planText(
    "span",
    "",
    valid
      ? `Peak ${formatPlanMinutes(summary.peakMinutes)}/day \u00b7 ${summary.studyDays} study day${summary.studyDays === 1 ? "" : "s"}`
      : `Needs about ${formatPlanMinutes(summary.minimumMinutes)} on the heaviest day`
  );
  verdict.append(headline, detail);
  target.appendChild(verdict);

  const chips = document.createElement("div");
  chips.className = "plan-chips";
  chips.append(
    planChip("items", String(summary.cards)),
    planChip("study days", String(summary.studyDays)),
    planChip("total time", formatPlanMinutes(summary.totalMinutes)),
    planChip("peak/day", formatPlanMinutes(summary.peakMinutes))
  );
  target.appendChild(chips);

  const body = document.createElement("p");
  body.className = "plan-summary";
  if (valid) {
    body.textContent =
      `Learn ${summary.cards} study items by ${formatPlanDate(payload.deadline)}. ` +
      `Last new item: ${summary.lastNew ? formatPlanDate(summary.lastNew) : "\u2014"}; ` +
      `first review: ${summary.firstReview ? formatPlanDate(summary.firstReview) : "\u2014"}. ` +
      `${summary.reviewedBeforeExam} items get a second review before the exam.`;
  } else if (result.reason === "buffer") {
    body.textContent =
      `With a ${summary.bufferDays}-day review buffer there is no day left for new cards. ` +
      "Shorten the buffer or move the exam date.";
  } else {
    body.textContent =
      `At ${summary.minutesPerDay} minutes/day you can learn about ` +
      `${summary.suggestedCards} study items by ${formatPlanDate(payload.deadline)}. ` +
      "Add time, reduce the items, or extend the deadline.";
  }
  target.appendChild(body);

  if (Array.isArray(result.warnings) && result.warnings.length) {
    const warnings = document.createElement("ul");
    warnings.className = "plan-warnings";
    for (const warning of result.warnings) {
      warnings.appendChild(planText("li", "", warning));
    }
    target.appendChild(warnings);
  }

  const fileAllocation = allocatePlanFiles(result);
  target.appendChild(renderPlanTable(result, payload, Boolean(fileAllocation)));
  target.appendChild(renderPlanFiles(fileAllocation));
  target.appendChild(renderPlanHours(result, payload));

  const foot = document.createElement("p");
  foot.className = "plan-foot";
  foot.textContent =
    `FSRS-6 \u00b7 ${Math.round(Number(summary.retention) * 100)}% desired retention \u00b7 ` +
    `${planRatingLabel(summary.rating)} recall \u00b7 no extra intraday reviews \u00b7 hourly blocks show how the day's workload fits your study window`;
  target.appendChild(foot);

  state.plan.result = result;
  state.plan.payload = payload;
  els.planCopy.hidden = false;
  if (els.planIcs) els.planIcs.hidden = false;
}

function renderPlanError(message) {
  const target = els.planResult;
  target.replaceChildren();
  target.hidden = false;
  const box = document.createElement("div");
  box.className = "plan-verdict is-bad";
  box.append(
    planText("strong", "", "Couldn't build the plan"),
    planText("span", "", message)
  );
  target.appendChild(box);
  els.planCopy.hidden = true;
  if (els.planIcs) els.planIcs.hidden = true;
}

async function runPlan() {
  let payload;
  try {
    payload = collectPlanPayload();
  } catch (error) {
    toast(error.message, "info", 5000);
    return;
  }
  const request = state.plan.request + 1;
  state.plan.request = request;
  els.planRun.disabled = true;
  els.planRun.textContent = "Building\u2026";
  try {
    const result = await api("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!els.planDialog.open || state.plan.request !== request) return;
    renderPlan(result, payload);
    savePlanPrefs({ ...payload, cards: payload.cards });
  } catch (error) {
    if (els.planDialog.open && state.plan.request === request) {
      renderPlanError(error.message);
    }
  } finally {
    els.planRun.disabled = false;
    els.planRun.textContent = "Make schedule";
  }
}

function markdownPlan() {
  const result = state.plan.result;
  const payload = state.plan.payload;
  if (!result || !payload) return "";
  const summary = result.summary;
  const lines = [
    `# Study plan \u2014 exam ${formatPlanDate(payload.deadline)}`,
    "",
    `- Study items: ${summary.cards}`,
    `- Study window: ${payload.start_time || "08:00"}\u2013${payload.end_time || "22:00"}`,
    `- Study days: ${summary.studyDays} (${payload.weekdays.map((day) => ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day]).join(", ")})`,
    `- Time per day: ${summary.minutesPerDay} min`,
    ...(state.plan.scopeIds.length
      ? [`- Files: ${state.plan.scopeIds.length} selected`]
      : []),
    `- Peak day: ${formatPlanMinutes(summary.peakMinutes)}`,
    `- Total time: ${formatPlanMinutes(summary.totalMinutes)}`,
    `- FSRS-6 desired retention: ${Math.round(Number(summary.retention) * 100)}%`,
    `- Expected recall: ${planRatingLabel(summary.rating)}`,
    "",
  ];
  const showFiles = result.days.some(
    (row) => Array.isArray(row.filePlan) && row.filePlan.length
  );
  lines.push(
    showFiles
      ? "| Date | New | Files | Reviews | Time | Learned |"
      : "| Date | New | Reviews | Time | Learned |",
    showFiles
      ? "| --- | ---: | --- | ---: | ---: | ---: |"
      : "| --- | ---: | ---: | ---: | ---: |"
  );
  for (const row of result.days) {
    const files = showFiles
      ? ` | ${
          (row.filePlan || [])
            .map((part) => `${planShortFile(part.name)} ${part.count}`)
            .join(", ") || "\u2014"
        }`
      : "";
    lines.push(
      `| ${formatPlanDate(row.date)} | ${row.new}${files} | ${row.reviews} | ${formatPlanMinutes(row.minutes)} | ${row.learned} |`
    );
  }
  if (result.warnings && result.warnings.length) {
    lines.push("", "## Notes", "");
    for (const warning of result.warnings) lines.push(`- ${warning}`);
  }
  return lines.join("\n");
}

function planIcsStamp(date, minutes) {
  const day = planDateFromIso(date);
  if (Number.isNaN(day.getTime())) return "";
  const local = new Date(
    day.getFullYear(),
    day.getMonth(),
    day.getDate(),
    Math.floor(minutes / 60),
    minutes % 60
  );
  const pad = (value) => String(value).padStart(2, "0");
  return (
    `${local.getFullYear()}${pad(local.getMonth() + 1)}${pad(local.getDate())}` +
    `T${pad(local.getHours())}${pad(local.getMinutes())}00`
  );
}

function icsEscape(value) {
  return String(value || "")
    .replace(/\\/g, "\\\\")
    .replace(/\n/g, "\\n")
    .replace(/,/g, "\\,")
    .replace(/;/g, "\\;");
}

function buildPlanIcs() {
  const result = state.plan.result;
  const payload = state.plan.payload;
  if (!result || !payload) return "";
  const lines = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//Anki Scribe//Study Plan//EN",
    "CALSCALE:GREGORIAN",
    `X-WR-CALNAME:${icsEscape("Study plan \u00b7 " + (state.doc?.filename || "Anki Scribe"))}`,
  ];
  const stamp = new Date()
    .toISOString()
    .replace(/[-:]/g, "")
    .replace(/\.\d{3}Z$/, "Z");
  let event = 0;
  for (const day of result.days || []) {
    const sessions = planDaySessions(day, payload).sessions.filter(
      (session) => !session.break
    );
    for (const session of sessions) {
      event += 1;
      const files = (day.filePlan || [])
        .map((part) => `${planShortFile(part.name)} ${part.count}`)
        .join(", ");
      const summary =
        `Study ${session.new} new` +
        (session.reviews ? ` + ${session.reviews} reviews` : "");
      lines.push(
        "BEGIN:VEVENT",
        `UID:anki-scribe-${day.date}-${event}@localhost`,
        `DTSTAMP:${stamp}`,
        `DTSTART:${planIcsStamp(day.date, session.start)}`,
        `DTEND:${planIcsStamp(day.date, session.end)}`,
        `SUMMARY:${icsEscape(summary)}`,
        `DESCRIPTION:${icsEscape(files ? `Files: ${files}` : "Anki Scribe study plan")}`,
        "BEGIN:VALARM",
        "TRIGGER:-PT10M",
        "ACTION:DISPLAY",
        `DESCRIPTION:${icsEscape("Study session starts in 10 minutes")}`,
        "END:VALARM",
        "END:VEVENT"
      );
    }
  }
  lines.push("END:VCALENDAR");
  return lines.join("\r\n");
}

function downloadPlanIcs() {
  const text = buildPlanIcs();
  if (!text) return;
  const blob = new Blob([text], { type: "text/calendar;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = "anki-scribe-study-plan.ics";
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast("Calendar file downloaded. Import it into your calendar app.", "success", 5000);
}

async function copyPlan() {
  const text = markdownPlan();
  if (!text) return;
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(text);
    } else {
      const area = document.createElement("textarea");
      area.value = text;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    toast("Plan copied as Markdown.", "success", 3000);
  } catch (error) {
    toast(`Couldn't copy the plan: ${error.message}`, "error", 5000);
  }
}

function bindPlanEvents() {
  if (els.planBtn) els.planBtn.addEventListener("click", openPlanDialog);
  if (els.closePlan) els.closePlan.addEventListener("click", closePlanDialog);
  if (els.planCancel) els.planCancel.addEventListener("click", closePlanDialog);
  if (els.planRun) els.planRun.addEventListener("click", runPlan);
  if (els.planCopy) els.planCopy.addEventListener("click", copyPlan);
  if (els.planIcs) els.planIcs.addEventListener("click", downloadPlanIcs);
  if (els.planForm) {
    els.planForm.addEventListener("submit", (event) => {
      event.preventDefault();
      runPlan();
    });
  }
  if (els.planRetention) {
    els.planRetention.addEventListener("input", () => {
      els.planRetentionValue.textContent = `${els.planRetention.value}%`;
    });
  }
  for (const input of [els.planStart, els.planEnd]) {
    if (!input) continue;
    input.addEventListener("change", () => {
      updatePlanWindow();
      updatePlanAvailability();
    });
  }
  if (els.planDeadline) {
    els.planDeadline.addEventListener("change", () => {
      clampPlanBuffer();
      updatePlanAvailability();
    });
  }
  if (els.planAllDay) {
    els.planAllDay.addEventListener("click", () => {
      els.planStart.value = "00:00";
      els.planEnd.value = "23:59";
      updatePlanWindow();
      updatePlanAvailability();
    });
  }
}
