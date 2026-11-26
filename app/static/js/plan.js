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

function updatePlanAvailability() {
  if (!els.planCards) return;
  const items = planScopeItems();
  const available = items.total;
  els.planCards.max = String(Math.min(available, 10000));
  if (Number(els.planCards.value) > available) {
    els.planCards.value = String(available);
  }
  const sourceCount = state.plan.scopeIds.length || 0;
  els.planCardsHint.textContent = planBreakdownText(items, sourceCount);
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
  if (fileIds.length) {
    try {
      const data = await api("/api/plan/sources", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ file_ids: fileIds }),
      });
      state.plan.sources = Array.isArray(data.files) ? data.files : [];
    } catch (error) {
      toast(`Couldn't count the selected files: ${error.message}`, "error", 7000);
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
  els.planNote.textContent =
    `${breakdown}.${sourceText}` +
    (sent && !sourceCount
      ? `${sent} cards are already in Anki; the plan treats every item as new because it cannot read Anki's review history. `
      : "") +
    "Each cloze deletion counts once, answers you hid by hand count as items, and every item is treated as new. Card creation and reading time are the per-card estimate below.";
}

function closePlanDialog() {
  state.plan.scopeIds = [];
  state.plan.sources = [];
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
  if (!Number.isFinite(newSeconds) || newSeconds < 5) {
    throw new Error("Seconds per new card must be at least 5.");
  }
  if (!Number.isFinite(reviewSeconds) || reviewSeconds < 3) {
    throw new Error("Seconds per review must be at least 3.");
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

function renderPlanTable(result, payload) {
  const wrap = document.createElement("div");
  wrap.className = "plan-table-wrap";
  const table = document.createElement("table");
  table.className = "plan-table";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const label of ["Date", "New", "Reviews", "Time", "Learned"]) {
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
  examCell.colSpan = 5;
  examRow.appendChild(examCell);
  tbody.appendChild(examRow);
  table.appendChild(tbody);
  wrap.appendChild(table);
  return wrap;
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
    let reviewLeft = Number(day.reviews) || 0;
    let newLeft = Number(day.new) || 0;
    let cursor = start;
    let rendered = 0;
    while (cursor < end && (reviewLeft || newLeft)) {
      const bucketEnd = Math.min(cursor + 60, end);
      let seconds = (bucketEnd - cursor) * 60;
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
        const row = document.createElement("div");
        row.className = "plan-hour";
        const range = planText(
          "span",
          "plan-hour-range",
          `${formatPlanClock(cursor)}\u2013${formatPlanClock(bucketEnd)}`
        );
        const counts = [];
        if (news) counts.push(`${news} new`);
        if (reviews) counts.push(`${reviews} review${reviews === 1 ? "" : "s"}`);
        row.append(range, planText("span", "plan-hour-work", counts.join(" \u00b7 ")));
        list.appendChild(row);
        rendered += news + reviews;
      }
      cursor = bucketEnd;
    }
    if (!rendered) {
      list.appendChild(
        planText("p", "plan-hours-empty", "No items fit in this study window.")
      );
    }
    if (reviewLeft || newLeft) {
      const left = reviewLeft + newLeft;
      list.appendChild(
        planText(
          "p",
          "plan-hours-empty",
          `${left} item${left === 1 ? "" : "s"} do not fit in this window; add time or move the deadline.`
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

  target.appendChild(renderPlanTable(result, payload));
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
    "| Date | New | Reviews | Time | Learned |",
    "| --- | ---: | ---: | ---: | ---: |",
  ];
  for (const row of result.days) {
    lines.push(
      `| ${formatPlanDate(row.date)} | ${row.new} | ${row.reviews} | ${formatPlanMinutes(row.minutes)} | ${row.learned} |`
    );
  }
  if (result.warnings && result.warnings.length) {
    lines.push("", "## Notes", "");
    for (const warning of result.warnings) lines.push(`- ${warning}`);
  }
  return lines.join("\n");
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
