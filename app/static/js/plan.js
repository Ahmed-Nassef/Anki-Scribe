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
  return planItemBreakdown().total;
}

function planBreakdownText(items) {
  const parts = [];
  if (items.basic) parts.push(`${items.basic} Q&A`);
  if (items.cloze) parts.push(`${items.cloze} cloze`);
  if (items.figure) parts.push(`${items.figure} figure${items.figure === 1 ? "" : "s"}`);
  if (items.manual) parts.push(`${items.manual} hidden`);
  return `${items.total} study item${items.total === 1 ? "" : "s"}${
    parts.length ? `: ${parts.join(" + ")}` : ""
  }`;
}

function updatePlanAvailability() {
  if (!els.planCards) return;
  const items = planItemBreakdown();
  const available = items.total;
  els.planCards.max = String(Math.min(available, 10000));
  if (Number(els.planCards.value) > available) {
    els.planCards.value = String(available);
  }
  els.planCardsHint.textContent = planBreakdownText(items);
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

function openPlanDialog() {
  if (!state.doc) {
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
  updatePlanAvailability();
  els.planSubtitle.textContent =
    "FSRS-6 schedule for Q&A cards, every cloze deletion and the answers you hid by hand. It assumes they are new.";
  els.planMinutes.value = String(prefs.minutes || 60);
  els.planBuffer.value = String(
    Number.isFinite(Number(prefs.buffer_days)) ? prefs.buffer_days : 2
  );
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
  const items = planItemBreakdown();
  const breakdown = planBreakdownText(items);
  els.planNote.textContent = sent
    ? `${breakdown}. ${sent} cards are already in Anki; the plan treats every item as new because it cannot read Anki's review history. Each cloze deletion counts once, and answers you hid by hand count as items.`
    : `${breakdown}. Each cloze deletion counts once, answers you hid by hand count as items, and every item is treated as new. Card creation and reading time are the per-card estimate below.`;
}

function closePlanDialog() {
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
    throw new Error(`This file only has ${available} selected cards.`);
  }
  const minutes = Number(els.planMinutes.value);
  if (!Number.isFinite(minutes) || minutes < 5) {
    throw new Error("Give the plan at least 5 minutes per day.");
  }
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

  const foot = document.createElement("p");
  foot.className = "plan-foot";
  foot.textContent =
    `FSRS-6 \u00b7 ${Math.round(Number(summary.retention) * 100)}% desired retention \u00b7 ` +
    `${planRatingLabel(summary.rating)} recall \u00b7 no intraday learning steps \u00b7 no lapses simulated`;
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
    `- Study days: ${summary.studyDays} (${payload.weekdays.map((day) => ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"][day]).join(", ")})`,
    `- Time per day: ${summary.minutesPerDay} min`,
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
}
