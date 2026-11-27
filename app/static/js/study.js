"use strict";

/* Study sheet: in-app reveal, plus PDF and HTML export of the ticked cards */

const CLOZE_PATTERN = /\{\{c\d+::([\s\S]*?)\}\}/g;
const STUDY_REVIEWS_KEY = "ankiScribeCardReviews";
const STUDY_SESSIONS_KEY = "ankiScribeStudySessions";
const STUDY_SESSION_LIMIT = 30;

const studyServer = {
  loaded: false,
  reviews: {},
  sessions: [],
  stats: null,
};

async function syncStudyFromServer() {
  try {
    const data = await api("/api/study");
    studyServer.loaded = true;
    const rawReviews =
      data && typeof data.reviews === "object" ? data.reviews : {};
    const reviews = {};
    for (const [key, record] of Object.entries(rawReviews)) {
      if (!record || typeof record !== "object") continue;
      reviews[key] = {
        ...record,
        due: Number(record.due) < 1e12 ? Number(record.due) * 1000 : record.due,
        last: Number(record.last) < 1e12 ? Number(record.last) * 1000 : record.last,
      };
    }
    studyServer.reviews = reviews;
    studyServer.sessions = Array.isArray(data?.sessions)
      ? data.sessions.map((session) => ({
          ...session,
          at: Number(session.at) < 1e12 ? Number(session.at) * 1000 : session.at,
        }))
      : [];
    studyServer.stats = data?.stats || null;
  } catch {
    studyServer.loaded = false;
  }
  return studyServer.loaded;
}

function currentStudyReviews() {
  return studyServer.loaded ? studyServer.reviews : loadStudyReviews();
}

const studyState = {
  items: [],
  index: 0,
  startedAt: 0,
  cardStartedAt: 0,
  grades: [],
  accuracy: 0,
  streak: 0,
  bestStreak: 0,
  timer: null,
  revealed: false,
  summarySaved: false,
};

function readStudyJson(key, fallback) {
  try {
    const value = JSON.parse(localStorage.getItem(key) || "null");
    return value && typeof value === "object" ? value : fallback;
  } catch {
    return fallback;
  }
}

function loadStudyReviews() {
  const raw = readStudyJson(STUDY_REVIEWS_KEY, {});
  return raw && typeof raw === "object" ? raw : {};
}

function saveStudyReviews(reviews) {
  try {
    const keys = Object.keys(reviews);
    if (keys.length > 5000) {
      const kept = keys
        .sort((a, b) => (reviews[b].last || 0) - (reviews[a].last || 0))
        .slice(0, 5000);
      const trimmed = {};
      for (const key of kept) trimmed[key] = reviews[key];
      reviews = trimmed;
    }
    localStorage.setItem(STUDY_REVIEWS_KEY, JSON.stringify(reviews));
  } catch {
    // Storage is optional; the session still works without it.
  }
}

function loadStudySessions() {
  const raw = readStudyJson(STUDY_SESSIONS_KEY, []);
  return Array.isArray(raw) ? raw.slice(-200) : [];
}

function saveStudySessions(sessions) {
  try {
    localStorage.setItem(STUDY_SESSIONS_KEY, JSON.stringify(sessions.slice(-200)));
  } catch {
    // Storage is optional.
  }
}

function studyItemGrade(item, rating, seconds) {
  const reviews = currentStudyReviews();
  const key = studyCardKey(item.card);
  if (!key) return reviews;
  const now = Date.now();
  const previous = reviews[key] || {};
  const ease = Math.min(3.0, Math.max(1.3, Number(previous.ease) || 2.5));
  const interval = Math.max(0, Number(previous.interval) || 0);
  let nextInterval = interval;
  let nextEase = ease;
  let due = now + 10 * 60 * 1000;
  if (rating === 1) {
    nextInterval = 0;
    nextEase = Math.max(1.3, ease - 0.2);
  } else if (rating === 2) {
    nextInterval = interval ? Math.max(1, Math.round(interval * 1.2)) : 1;
    nextEase = Math.max(1.3, ease - 0.15);
    due = now + nextInterval * 86400000;
  } else if (rating === 3) {
    nextInterval = interval ? Math.max(1, Math.round(interval * ease)) : 1;
    due = now + nextInterval * 86400000;
  } else {
    nextInterval = interval ? Math.max(4, Math.round(interval * ease * 1.4)) : 4;
    nextEase = Math.min(3.0, ease + 0.15);
    due = now + nextInterval * 86400000;
  }
  reviews[key] = {
    uid: String(item.card.uid || ""),
    question: String(item.card.question || item.card.text || "").slice(0, 500),
    mode: item.card.mode || "basic",
    ease: Number(nextEase.toFixed(2)),
    interval: nextInterval,
    due,
    last: now,
    reps: (Number(previous.reps) || 0) + 1,
    lapses: (Number(previous.lapses) || 0) + (rating === 1 ? 1 : 0),
    lastRating: rating,
    seconds: Math.max(0, Math.round(seconds)),
  };
  saveStudyReviews(reviews);
  if (studyServer.loaded) {
    api("/api/study/review", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        uid: key,
        question: String(item.card.question || item.card.text || "").slice(0, 500),
        mode: item.card.mode || "basic",
        rating,
        seconds: Math.max(0, Math.round(seconds)),
      }),
    })
      .then((data) => {
        if (data && data.review) {
          const review = { ...data.review };
          review.due = Number(review.due) < 1e12 ? Number(review.due) * 1000 : review.due;
          review.last = Number(review.last) < 1e12 ? Number(review.last) * 1000 : review.last;
          studyServer.reviews[key] = review;
        }
      })
      .catch(() => {
        // The local record above is the fallback.
      });
  }
  return reviews;
}


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
  const seen = new Set();
  for (const card of sourceCards()) {
    if (card.selected === false) continue;
    const uid = String(card.uid || card.id || "");
    if (uid) {
      if (seen.has(uid)) continue;
      seen.add(uid);
    }
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
  for (const card of sourceCards()) if (card.selected !== false) count += 1;
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
  if (els.studyStatsBtn) els.studyStatsBtn.hidden = !state.doc;
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

function studyCardKey(card) {
  return String(card?.uid || card?.id || "");
}

function studyItems() {
  const items = [];
  for (const [, group] of studyGroups()) items.push(...group);
  const reviews = currentStudyReviews();
  const now = Date.now();
  const rank = (item) => {
    const record = reviews[studyCardKey(item.card)];
    if (!record) return 1;
    return Number(record.due) <= now ? 0 : 2;
  };
  items.sort((left, right) => {
    const difference = rank(left) - rank(right);
    if (difference) return difference;
    const leftDue = Number(reviews[studyCardKey(left.card)]?.due) || 0;
    const rightDue = Number(reviews[studyCardKey(right.card)]?.due) || 0;
    return leftDue - rightDue;
  });
  return items;
}

async function openStudy() {
  await syncStudyFromServer();
  const items = studyItems();
  if (!items.length) {
    toast("Tick at least one card first.");
    return;
  }
  studyState.items = items;
  studyState.index = 0;
  studyState.startedAt = Date.now();
  studyState.cardStartedAt = Date.now();
  studyState.grades = [];
  studyState.accuracy = 0;
  studyState.streak = 0;
  studyState.bestStreak = 0;
  studyState.revealed = false;
  studyState.summarySaved = false;
  els.studyTitle.textContent = studyTitle();
  els.studyDialog.classList.remove("is-summary");
  if (els.studySummary) {
    els.studySummary.hidden = true;
    els.studySummary.replaceChildren();
  }
  if (!els.studyDialog.open) els.studyDialog.showModal();
  startStudyTimer();
  renderStudy();
  els.studyReveal.focus();
}

function closeStudy() {
  stopStudyTimer();
  savePartialStudySession();
  if (els.studyDialog.open) els.studyDialog.close();
}

function startStudyTimer() {
  stopStudyTimer();
  updateStudyLive();
  studyState.timer = setInterval(updateStudyLive, 1000);
}

function stopStudyTimer() {
  if (studyState.timer) clearInterval(studyState.timer);
  studyState.timer = null;
}

function studyElapsedSeconds() {
  return Math.max(0, Math.round((Date.now() - studyState.startedAt) / 1000));
}

function formatStudyDuration(seconds) {
  const value = Math.max(0, Math.round(seconds));
  const minutes = Math.floor(value / 60);
  return `${minutes}:${String(value % 60).padStart(2, "0")}`;
}

function studyCorrectCount() {
  return studyState.grades.filter((entry) => entry.rating >= 3).length;
}

function updateStudyLive() {
  if (!els.studyDialog?.open) return;
  if (els.studyLiveTime) {
    els.studyLiveTime.textContent = formatStudyDuration(studyElapsedSeconds());
  }
  if (els.studyLiveAccuracy) {
    const total = studyState.grades.length;
    els.studyLiveAccuracy.textContent = total
      ? `${Math.round((studyCorrectCount() / total) * 100)}%`
      : "\u2014";
  }
  if (els.studyLiveStreak) {
    els.studyLiveStreak.textContent = `${studyState.streak} streak`;
  }
}

function saveStudySession() {
  if (studyState.summarySaved || !studyState.grades.length) return;
  studyState.summarySaved = true;
  const sessions = loadStudySessions();
  sessions.push({
    at: Date.now(),
    total: studyState.grades.length,
    correct: studyCorrectCount(),
    seconds: studyElapsedSeconds(),
    streak: studyState.bestStreak,
    grades: {
      again: studyState.grades.filter((entry) => entry.rating === 1).length,
      hard: studyState.grades.filter((entry) => entry.rating === 2).length,
      good: studyState.grades.filter((entry) => entry.rating === 3).length,
      easy: studyState.grades.filter((entry) => entry.rating === 4).length,
    },
  });
  saveStudySessions(sessions);
  if (studyServer.loaded) {
    api("/api/study/session", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(sessions[sessions.length - 1]),
    })
      .then((data) => {
        if (data && data.session) {
          const session = { ...data.session };
          session.at =
            Number(session.at) < 1e12 ? Number(session.at) * 1000 : session.at;
          studyServer.sessions = [...studyServer.sessions, session].slice(-200);
        }
      })
      .catch(() => {
        // Local history remains available.
      });
  }
}

function savePartialStudySession() {
  if (studyState.grades.length) saveStudySession();
}

function renderStudy() {
  const items = studyState.items;
  const index = clamp(studyState.index, 0, Math.max(0, items.length - 1));
  studyState.index = index;
  const item = items[index];
  if (!item) return;
  const total = items.length;
  studyState.cardStartedAt = Date.now();
  studyState.revealed = false;

  els.studyCounter.textContent = `${index + 1} / ${total}`;
  els.studySection.textContent = item.chapter || "Cards";
  els.studyBar.style.width = `${((index + 1) / total) * 100}%`;
  els.studyPrev.disabled = index === 0;
  els.studyNext.disabled = index === total - 1;
  els.studyBody.scrollTop = 0;

  fillStudyQuestion(item.card);
  hideStudyAnswer();
  updateStudyLive();
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
  studyState.revealed = false;
  els.studyAnswer.hidden = true;
  if (els.studyGrades) els.studyGrades.hidden = true;
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
  studyState.revealed = true;
  els.studyAnswerText.textContent =
    item.answer || "No answer was recorded for this card.";
  els.studyDetail.textContent = item.detail || "";
  els.studyDetail.hidden = !item.detail;
  els.studyAnswer.hidden = false;
  if (els.studyGrades) els.studyGrades.hidden = false;
  els.studyAnswer.classList.remove("is-fresh");
  void els.studyAnswer.offsetWidth;
  els.studyAnswer.classList.add("is-fresh");
  els.studyRevealLabel.textContent = "Hide answer";
  els.studyReveal.setAttribute("aria-expanded", "true");
  els.studyAnswer.scrollIntoView({ block: "nearest", behavior: "smooth" });
  updateStudyLive();
}

function toggleStudyAnswer() {
  if (studyState.revealed) {
    hideStudyAnswer();
  } else {
    showStudyAnswer();
  }
}

function gradeStudy(rating) {
  if (!studyState.revealed) {
    showStudyAnswer();
    return;
  }
  const item = studyState.items[studyState.index];
  if (!item) return;
  const seconds = Math.max(0, (Date.now() - studyState.cardStartedAt) / 1000);
  studyItemGrade(item, rating, seconds);
  studyState.grades.push({ rating, seconds });
  studyState.streak = rating >= 3 ? studyState.streak + 1 : 0;
  studyState.bestStreak = Math.max(studyState.bestStreak, studyState.streak);
  const total = studyState.grades.length;
  studyState.accuracy = studyCorrectCount() / Math.max(1, total);
  updateStudyLive();
  if (studyState.index >= studyState.items.length - 1) {
    showStudySummary();
    return;
  }
  studyState.index += 1;
  renderStudy();
}

function moveStudy(delta) {
  const next = clamp(studyState.index + delta, 0, studyState.items.length - 1);
  if (next === studyState.index) return;
  studyState.index = next;
  renderStudy();
}

function studyMetric(label, value) {
  const box = document.createElement("div");
  box.className = "study-stat";
  const strong = document.createElement("strong");
  strong.textContent = String(value);
  const text = document.createElement("span");
  text.textContent = label;
  box.append(strong, text);
  return box;
}

function showStudySummary() {
  if (!els.studySummary) return;
  saveStudySession();
  stopStudyTimer();
  const total = studyState.grades.length;
  const correct = studyCorrectCount();
  const again = studyState.grades.filter((entry) => entry.rating === 1).length;
  const hard = studyState.grades.filter((entry) => entry.rating === 2).length;
  const good = studyState.grades.filter((entry) => entry.rating === 3).length;
  const easy = studyState.grades.filter((entry) => entry.rating === 4).length;
  const avg = total
    ? studyState.grades.reduce((sum, entry) => sum + entry.seconds, 0) / total
    : 0;
  els.studyDialog.classList.add("is-summary");
  const box = els.studySummary;
  box.replaceChildren();
  const head = document.createElement("div");
  head.className = "study-summary-head";
  const title = document.createElement("h3");
  title.textContent = "Session complete";
  const detail = document.createElement("p");
  detail.textContent =
    `${total} card${total === 1 ? "" : "s"} reviewed \u00b7 ` +
    `${Math.round((correct / Math.max(1, total)) * 100)}% recalled \u00b7 ` +
    `${Math.round(avg)}s average`;
  head.append(title, detail);
  box.appendChild(head);
  const stats = document.createElement("div");
  stats.className = "study-summary-stats";
  stats.append(
    studyMetric("Again", again),
    studyMetric("Hard", hard),
    studyMetric("Good", good),
    studyMetric("Easy", easy),
    studyMetric("Best streak", studyState.bestStreak),
    studyMetric("Session time", formatStudyDuration(studyElapsedSeconds()))
  );
  box.appendChild(stats);
  const actions = document.createElement("div");
  actions.className = "study-summary-actions";
  const againButton = document.createElement("button");
  againButton.type = "button";
  againButton.className = "btn primary";
  againButton.textContent = "Study again";
  againButton.addEventListener("click", openStudy);
  const statsButton = document.createElement("button");
  statsButton.type = "button";
  statsButton.className = "btn";
  statsButton.textContent = "Lifetime stats";
  statsButton.addEventListener("click", openStudyStats);
  const closeButton = document.createElement("button");
  closeButton.type = "button";
  closeButton.className = "btn";
  closeButton.textContent = "Close";
  closeButton.addEventListener("click", closeStudy);
  actions.append(againButton, statsButton, closeButton);
  box.appendChild(actions);
  box.hidden = false;
}

function studyStreakDays(sessions) {
  const days = [
    ...new Set(
      sessions
        .map((session) => new Date(session.at))
        .filter((date) => !Number.isNaN(date.getTime()))
        .map((date) => new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime())
    ),
  ].sort((a, b) => b - a);
  if (!days.length) return 0;
  const today = new Date();
  const todayStart = new Date(
    today.getFullYear(),
    today.getMonth(),
    today.getDate()
  ).getTime();
  let cursor = days[0];
  if (cursor !== todayStart && cursor !== todayStart - 86400000) return 0;
  let streak = 0;
  for (const day of days) {
    if (day === cursor) {
      streak += 1;
      cursor -= 86400000;
    } else if (day < cursor) {
      break;
    }
  }
  return streak;
}

async function openStudyStats() {
  if (!els.studyStatsDialog) return;
  if (els.studyDialog?.open) closeStudy();
  await syncStudyFromServer();
  const sessions = studyServer.loaded ? studyServer.sessions : loadStudySessions();
  const reviews = currentStudyReviews();
  const total = sessions.reduce((sum, session) => sum + (Number(session.total) || 0), 0);
  const correct = sessions.reduce(
    (sum, session) => sum + (Number(session.correct) || 0),
    0
  );
  const seconds = sessions.reduce(
    (sum, session) => sum + (Number(session.seconds) || 0),
    0
  );
  const days = new Set(
    sessions.map((session) =>
      new Date(Number(session.at) || 0).toDateString()
    )
  ).size;
  const due = Object.values(reviews).filter(
    (record) => Number(record.due) <= Date.now()
  ).length;
  const known = new Set(
    sourceCards()
      .filter((card) => card.selected !== false && (card.uid || card.id))
      .map((card) => String(card.uid || card.id))
  );
  const newCards = [...known].filter((uid) => !reviews[uid]).length;
  const body = els.studyStatsBody;
  if (!body) return;
  body.replaceChildren();
  const grid = document.createElement("div");
  grid.className = "study-summary-stats";
  grid.append(
    studyMetric("Sessions", sessions.length),
    studyMetric("Cards reviewed", total),
    studyMetric("Days studied", days),
    studyMetric("Current streak", `${studyStreakDays(sessions)}d`),
    studyMetric(
      "Retention",
      total ? `${Math.round((correct / total) * 100)}%` : "\u2014"
    ),
    studyMetric(
      "Average",
      total ? `${Math.round(seconds / total)}s` : "\u2014"
    ),
    studyMetric("Due now", due),
    studyMetric("New cards", newCards)
  );
  body.appendChild(grid);
  if (!sessions.length) {
    const empty = document.createElement("p");
    empty.className = "study-stats-empty";
    empty.textContent =
      "No sessions yet. Open Study cards, reveal an answer and grade it Again / Hard / Good / Easy.";
    body.appendChild(empty);
  } else {
    const recent = document.createElement("div");
    recent.className = "study-recent";
    const title = document.createElement("strong");
    title.textContent = "Recent sessions";
    recent.appendChild(title);
    for (const session of sessions.slice(-8).reverse()) {
      const row = document.createElement("div");
      row.className = "study-recent-row";
      const date = new Date(Number(session.at) || 0);
      const label = document.createElement("span");
      label.textContent = date.toLocaleDateString(undefined, {
        month: "short",
        day: "numeric",
        hour: "2-digit",
        minute: "2-digit",
      });
      const score = document.createElement("span");
      score.textContent =
        `${session.correct || 0}/${session.total || 0} recalled \u00b7 ` +
        `${formatStudyDuration(session.seconds || 0)}`;
      row.append(label, score);
      recent.appendChild(row);
    }
    body.appendChild(recent);
  }
  els.studyStatsDialog.showModal();
}

function closeStudyStats() {
  if (els.studyStatsDialog?.open) els.studyStatsDialog.close();
}

function handleStudyKey(event) {
  if (!els.studyDialog.open) return;
  if (els.studyDialog.classList.contains("is-summary")) {
    if (event.key === "Escape") {
      event.preventDefault();
      closeStudy();
    }
    return;
  }
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
  if (event.key >= "1" && event.key <= "4" && studyState.revealed) {
    event.preventDefault();
    gradeStudy(Number(event.key));
    return;
  }
  if (event.key === "Escape") {
    event.preventDefault();
    closeStudy();
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
