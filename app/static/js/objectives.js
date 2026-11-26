"use strict";

/* Learning-objective coverage.

   The objectives are detected server-side from the document. Coverage is
   estimated here against drafts plus cards already in Anki, so it costs
   nothing, works offline, and never leaves the machine. The estimate is a
   token-recall check, deliberately forgiving: it should not nag about an
   objective that is covered. */

function resetObjectives() {
  state.objectives = { items: [], loading: false, request: 0, busy: false };
  renderObjectives();
}

async function loadObjectives(doc) {
  const request = (state.objectives.request || 0) + 1;
  state.objectives = {
    items: state.objectives.items,
    loading: true,
    request,
    busy: false,
  };
  try {
    const data = await api(`/api/documents/${encodeURIComponent(doc.id)}/objectives`);
    if (!state.doc || state.doc.id !== doc.id || state.objectives.request !== request) {
      return;
    }
    state.objectives = {
      items: Array.isArray(data.objectives) ? data.objectives : [],
      loading: false,
      request,
      busy: false,
    };
  } catch (error) {
    if (!state.doc || state.doc.id !== doc.id || state.objectives.request !== request) {
      return;
    }
    state.objectives = { items: [], loading: false, request, busy: false };
    console.warn("Couldn't load objectives", error);
  }
  renderObjectives();
}

function objectiveTokens(text) {
  return String(text || "")
    .toLowerCase()
    .replace(/[^a-z0-9\s]+/g, " ")
    .split(/\s+/)
    .filter((token) => token.length > 3 && !RISK_STOPWORDS.has(token));
}

/* One pass over every card, so the panel stays cheap on a large batch. */
function objectiveBag() {
  const bag = new Set();
  sourceCards().forEach((card) => {
    const source = card.source && typeof card.source === "object" ? card.source : {};
    const text = [
      card.question,
      card.answer,
      card.text,
      card.evidence,
      source.evidence,
      source.quote,
    ]
      .filter(Boolean)
      .join(" ");
    objectiveTokens(text).forEach((token) => bag.add(token));
  });
  return bag;
}

function objectiveCovered(objective, bag) {
  const tokens = objectiveTokens(objective.text);
  if (!tokens.length || !bag.size) return false;
  const present = tokens.filter((token) => bag.has(token)).length;
  return present / tokens.length >= 0.5;
}

function renderObjectives() {
  if (!els.objectivesPanel) return;
  const items = state.objectives.items || [];
  const visible = Boolean(state.doc) && (items.length > 0 || state.objectives.loading);
  els.objectivesPanel.hidden = !visible;
  if (!visible) return;

  const bag = objectiveBag();
  let covered = 0;
  els.objectivesList.replaceChildren();

  items.forEach((objective, index) => {
    const isCovered = objectiveCovered(objective, bag);
    if (isCovered) covered += 1;

    const item = document.createElement("li");
    item.className = `objective${isCovered ? " is-covered" : ""}`;

    const mark = document.createElement("span");
    mark.className = "objective-mark";
    mark.setAttribute("aria-hidden", "true");
    mark.textContent = isCovered ? "\u2713" : "\u2717";

    const text = document.createElement("span");
    text.className = "objective-text";
    text.textContent = objective.text;

    item.append(mark, text);

    if (!isCovered) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "text-btn";
      button.dataset.objective = String(index);
      button.textContent = "generate";
      button.disabled = Boolean(state.objectives.busy);
      button.title = `Write cards for this objective from ${objective.label}`;
      item.appendChild(button);
    }

    els.objectivesList.appendChild(item);
  });

  els.objectivesScore.textContent = items.length ? `${covered} / ${items.length}` : "";
  if (state.objectives.loading && !items.length) {
    els.objectivesMeta.textContent = "Looking for objectives\u2026";
  } else if (items.length) {
    const where = items[0].label || "";
    els.objectivesMeta.textContent =
      covered === items.length
        ? `All covered${where ? ` \u00b7 from ${where}` : ""}`
        : `estimated from your cards${where ? ` \u00b7 from ${where}` : ""}`;
  } else {
    els.objectivesMeta.textContent = "";
  }
}

async function generateForObjective(index) {
  const objective = state.objectives.items[index];
  const doc = state.doc;
  if (!objective || !doc || state.objectives.busy || state.generating || state.auto.running) {
    return;
  }
  if (!state.settings.has_key) {
    toast("Add your DeepSeek API key first.", "error");
    openSettings();
    return;
  }

  const params = new URLSearchParams({ max_chars: "6000" });
  if (doc.kind === "transcript") {
    params.set("start_segment", String(objective.unit + 1));
    params.set("end_segment", String(objective.unit + 1));
  } else {
    params.set("start_page", String(objective.unit + 1));
    params.set("end_page", String(objective.unit + 1));
  }

  const target = els.objectivesList.querySelector(`[data-objective="${index}"]`);
  if (target) {
    target.disabled = true;
    target.textContent = "writing\u2026";
  }
  state.objectives.busy = true;
  const sourceTitle = sourceTitleForDoc();

  try {
    const extract = await api(
      `/api/documents/${encodeURIComponent(doc.id)}/extract?${params.toString()}`
    );
    if (!state.doc || state.doc.id !== doc.id) return;

    let added = 0;
    for (const chunk of extract.chunks || []) {
      const data = await api("/api/generate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: chunk.text,
          mode: state.mode,
          count: null,
          filename: doc.filename,
          page: chunk.label,
          strict: Boolean(state.strict),
          style: state.style,
        }),
      }).catch((error) => {
        toast(error.message, "error", 8000);
        return null;
      });
      if (!data) continue;
      const template =
        doc.kind === "transcript"
          ? {
              kind: "transcript",
              label: chunk.label,
              file: doc.filename,
              location: [],
              segments: Array.isArray(chunk.segments) ? chunk.segments : [],
              quote: "",
              sourceTitle,
              chapterPath: [],
              chapterTitle: "",
              deckPath: [sourceTitle],
            }
          : {
              kind: "chunk",
              label: chunk.label,
              file: doc.filename,
              location: [],
              pages:
                Array.isArray(chunk.pages) && chunk.pages.length >= 2
                  ? [chunk.pages[0] - 1, chunk.pages[1] - 1]
                  : [],
              quote: "",
              sourceTitle,
              chapterPath: [],
              chapterTitle: "",
              deckPath: [sourceTitle],
            };
      added += addGeneratedCards(data.cards || [], state.mode, template);
    }

    renderCards();
    toast(
      added
        ? `${added} card${added === 1 ? "" : "s"} added for that objective.`
        : "No new cards for that objective \u2014 it may already be covered.",
      added ? "success" : "info",
      6000
    );
  } catch (error) {
    toast(error.message, "error", 8000);
  } finally {
    state.objectives.busy = false;
    renderObjectives();
    refreshCoverage({ quiet: true });
    refreshAiBalance({ quiet: true });
  }
}
