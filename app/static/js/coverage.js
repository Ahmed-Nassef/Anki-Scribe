"use strict";

/* File and transcript coverage */

function cardSourceUnits(card) {
  const units = new Set();
  const source = card.source;
  if (!source || typeof source !== "object") return units;
  const isTranscript = source.kind === "transcript";
  if (isTranscript) {
    const count = state.transcript.segments.length;
    if (Array.isArray(source.location)) {
      source.location.forEach((entry) => {
        const index = Number(entry && entry.segment);
        if (Number.isInteger(index) && index >= 0 && index < count) {
          units.add(index + 1);
        }
      });
    }
    if (Array.isArray(source.segments) && source.segments.length >= 2) {
      const start = Math.min(Number(source.segments[0]), Number(source.segments[1]));
      const end = Math.max(Number(source.segments[0]), Number(source.segments[1]));
      if (Number.isInteger(start) && Number.isInteger(end)) {
        for (let unit = Math.max(1, start); unit <= Math.min(count, end); unit += 1) {
          units.add(unit);
        }
      }
    }
    return units;
  }

  const pageCount = state.doc ? state.doc.pageCount : 0;
  if (Array.isArray(source.location)) {
    source.location.forEach((entry) => {
      const index = Number(entry && entry.page);
      if (Number.isInteger(index) && index >= 0 && index < pageCount) {
        units.add(index + 1);
      }
    });
  }
  if (Array.isArray(source.pages) && source.pages.length >= 2) {
    const start = Math.min(Number(source.pages[0]), Number(source.pages[1]));
    const end = Math.max(Number(source.pages[0]), Number(source.pages[1]));
    if (Number.isInteger(start) && Number.isInteger(end)) {
      for (let page = Math.max(0, start); page <= Math.min(pageCount - 1, end); page += 1) {
        units.add(page + 1);
      }
    }
  }
  return units;
}

function coverageCheckReason(page) {
  const imageArea =
    page.imageArea != null ? Number(page.imageArea) : page.images > 0 ? 0.2 : 0;
  if (page.needsOcr) return "Scanned page \u2014 text may be incomplete";
  if (page.chars === 0 && imageArea > 0.05) return "No text found \u2014 check the image";
  if (page.chars === 0) return "No text found";
  if (imageArea > 0.18 && page.chars < 300) {
    return "Mostly image \u2014 check figures and labels";
  }
  if (imageArea > 0.18) return "Contains an image \u2014 check labels";
  if (imageArea > 0.05 && page.chars < 120) {
    return "Image with little text \u2014 check this page";
  }
  if (page.chars < 80) return "Very little text \u2014 check this page";
  return "";
}

function coverageModel() {
  const data = state.coverage.data;
  if (!data || !state.doc || !Array.isArray(data.pages)) return null;

  const content = data.pages.filter(
    (page) =>
      page.chars > 0 ||
      (page.imageArea != null ? Number(page.imageArea) : 0) > 0.05
  );
  const contentNumbers = new Set(content.map((page) => page.page));
  const covered = new Set();
  const cards = sourceCards();
  cards.forEach((card) => {
    cardSourceUnits(card).forEach((page) => {
      if (contentNumbers.has(page)) covered.add(page);
    });
  });

  const totalChars = Number(data.textCharacters) || 0;
  const coveredChars = content
    .filter((page) => covered.has(page.page))
    .reduce((sum, page) => sum + (Number(page.chars) || 0), 0);
  const textPercent = totalChars > 0 ? (coveredChars / totalChars) * 100 : 0;
  const pagePercent = content.length ? (covered.size / content.length) * 100 : 0;
  const percent = totalChars > 0 ? textPercent : pagePercent;
  const isTranscript = data.kind === "transcript";
  const hasChunkCards = cards.some(
    (card) => card.source && card.source.kind === "chunk"
  );
  const flagged = isTranscript
    ? []
    : content
        .map((page) => ({ ...page, reason: coverageCheckReason(page) }))
        .filter((page) => page.reason);

  return {
    data,
    content,
    covered,
    totalChars,
    coveredChars,
    percent,
    pagePercent,
    textPercent,
    flagged,
    isTranscript,
    hasChunkCards,
    title: hasChunkCards ? "Page coverage" : totalChars > 0 ? "Text coverage" : "Page coverage",
  };
}

function renderCoverage() {
  const model = coverageModel();
  if (!model) {
    els.coverageBlock.hidden = true;
    return;
  }

  const percent = Math.max(0, Math.min(100, Math.round(model.percent)));
  els.coverageBlock.hidden = false;
  els.coverageBlock.classList.toggle("is-low", percent < 60);
  els.coverageBlock.title = model.hasChunkCards
    ? "Pages with at least one whole-file card. Whole-file cards are planned by " +
      "page range, so use the teal source highlights to inspect exact facts and gaps."
    : model.isTranscript
      ? "Share of transcript text in segments that have at least one card. " +
        "Segment-level estimate, not a sentence-by-sentence check."
      : "Share of extracted text on pages with at least one card. " +
        "Page-level estimate; image pages may contain figures or labels that text extraction cannot read.";
  els.coverageTitle.textContent = model.title;
  els.coveragePercent.textContent = `${percent}%`;
  els.coveragePages.textContent = model.isTranscript
    ? `${model.covered.size} of ${model.content.length} segments`
    : `${model.covered.size} of ${model.content.length} content pages`;
  els.coverageBar.style.width = `${percent}%`;

  const draftCount = state.cards.length;
  const sentCount = state.sent.cards.length;
  if (!draftCount && !sentCount) {
    els.coverageNote.textContent = "No cards yet \u2014 generate to start covering this file.";
  } else if (model.data.textPages === 0) {
    els.coverageNote.textContent = model.isTranscript
      ? "No readable transcript text found."
      : "No readable text found \u2014 check the images.";
  } else if (!draftCount) {
    els.coverageNote.textContent =
      `${sentCount} card${sentCount === 1 ? "" : "s"} already in Anki.`;
  } else {
    els.coverageNote.textContent = model.isTranscript
      ? `${model.data.textPages} of ${model.content.length} segments have text.`
      : `${model.data.textPages} of ${model.content.length} pages have readable text.`;
  }
  if (draftCount || sentCount) {
    els.coverageNote.textContent += " Teal-highlighted text has a card.";
    if (model.hasChunkCards) {
      els.coverageNote.textContent += " Whole-file cards are page-level.";
    }
  }

  const count = model.flagged.length;
  els.coverageCheckBtn.hidden = count === 0;
  els.coverageCheckBtn.textContent =
    `${count} page${count === 1 ? "" : "s"} to check`;
}

async function refreshCoverage({ quiet = true } = {}) {
  if (!state.doc) {
    state.coverage = { loading: false, data: null, error: "", request: 0 };
    renderCoverage();
    return;
  }
  const docId = state.doc.id;
  const request = (state.coverage.request || 0) + 1;
  state.coverage = {
    loading: true,
    data: state.coverage.data,
    error: "",
    request,
  };
  renderCoverage();
  try {
    const data = await api(`/api/documents/${docId}/coverage`);
    if (
      !state.doc ||
      state.doc.id !== docId ||
      state.coverage.request !== request
    ) {
      return;
    }
    state.coverage = { loading: false, data, error: "", request };
    renderCoverage();
  } catch (error) {
    if (
      !state.doc ||
      state.doc.id !== docId ||
      state.coverage.request !== request
    ) {
      return;
    }
    state.coverage = { loading: false, data: null, error: error.message, request };
    renderCoverage();
    if (!quiet) toast(error.message, "error", 7000);
  }
}

function openCoverageDialog() {
  const model = coverageModel();
  if (!model) return;
  renderCoverageDialog(model);
  if (!els.coverageDialog.open) els.coverageDialog.showModal();
}

function renderCoverageDialog(model) {
  const percent = Math.max(0, Math.min(100, Math.round(model.percent)));
  els.coverageDialogSummary.textContent =
    `${percent}% ${model.title.toLowerCase()} \u00b7 ${model.flagged.length} page` +
    `${model.flagged.length === 1 ? "" : "s"} worth checking.`;
  els.coverageSummary.replaceChildren();

  const summary = document.createElement("p");
  summary.textContent =
    `${model.covered.size} of ${model.content.length} content pages have at least one card. ` +
    `${model.data.textPages} of ${model.content.length} pages have readable text. ` +
    `${model.data.imagePages} page${model.data.imagePages === 1 ? "" : "s"} contain images.`;
  els.coverageSummary.appendChild(summary);

  els.coveragePageList.replaceChildren();
  if (!model.flagged.length) {
    const empty = document.createElement("div");
    empty.className = "coverage-empty";
    empty.textContent = "No image or low-text pages were detected.";
    els.coveragePageList.appendChild(empty);
    return;
  }

  model.flagged.forEach((page) => {
    const row = document.createElement("div");
    row.className = "coverage-page-row";
    const number = document.createElement("span");
    number.className = "coverage-page-num";
    number.textContent = `Page ${page.page}`;
    const reason = document.createElement("span");
    reason.className = "coverage-page-reason";
    reason.textContent = page.reason;
    const open = document.createElement("button");
    open.type = "button";
    open.className = "text-btn coverage-page-open";
    open.dataset.page = String(page.page);
    open.textContent = "Show page";
    row.append(number, reason, open);
    els.coveragePageList.appendChild(row);
  });
}

function showCoveragePage(pageNumber) {
  const index = Number(pageNumber) - 1;
  if (state.doc && state.doc.kind === "transcript") {
    const cue = els.pages.querySelector(`.cue[data-segment="${index}"]`);
    if (!cue) return;
    document.querySelectorAll(".cue.is-coverage-target").forEach((node) => {
      node.classList.remove("is-coverage-target");
    });
    cue.classList.add("is-coverage-target");
    els.coverageDialog.close();
    scrollViewerTo(cue);
    return;
  }
  const model = state.models.get(index);
  if (!model) return;
  document.querySelectorAll(".page.is-coverage-target").forEach((pageEl) => {
    pageEl.classList.remove("is-coverage-target");
  });
  model.el.classList.add("is-coverage-target");
  els.coverageDialog.close();
  goToPage(index);
  setActivePage(index);
}

function notifyCoverageAfterAuto() {
  const model = coverageModel();
  if (!model) return;
  if (model.isTranscript) {
    const uncovered = Math.max(0, model.content.length - model.covered.size);
    if (!uncovered) return;
    toast(
      `Coverage ${Math.round(model.percent)}% \u00b7 ${uncovered} segment` +
        `${uncovered === 1 ? "" : "s"} have no cards yet.`,
      "info",
      9000
    );
    return;
  }
  if (!model.flagged.length) return;
  const count = model.flagged.length;
  toast(
    `Coverage ${Math.round(model.percent)}% \u00b7 ${count} page` +
      `${count === 1 ? "" : "s"} may have images or little text \u2014 check them.`,
    "info",
    9000
  );
}
