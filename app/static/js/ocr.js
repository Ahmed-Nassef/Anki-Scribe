"use strict";

/* Automatic OCR for scanned PDFs.
 *
 * The server starts OCR when a scanned file is uploaded/opened; this module
 * polls progress, then reloads the visible page text layers that were waiting
 * for OCR. No button is required for the normal path. */

function resetOcrWatch() {
  if (state.ocr.timer) clearTimeout(state.ocr.timer);
  state.ocr = {
    docId: "",
    timer: null,
    request: 0,
    started: false,
    lastDone: 0,
    status: null,
    refreshed: false,
  };
  hideOcrBanner();
}

function prepareOcrForDocument(doc) {
  resetOcrWatch();
  if (!doc || doc.kind === "transcript") return;
  state.ocr.docId = doc.id;
  const request = state.ocr.request + 1;
  state.ocr.request = request;
  pollOcrDocument(doc.id, request);
}

function hideOcrBanner() {
  if (els.ocrBanner) els.ocrBanner.hidden = true;
}

function updateOcrBanner(status) {
  if (!els.ocrBanner) return;
  const pending = Number(status.pending) || 0;
  const running = Boolean(status.running);
  const total = Number(status.total) || 0;
  const done = Number(status.done) || 0;
  const show = Boolean(status) && (running || pending > 0);
  els.ocrBanner.hidden = !show;
  if (!show) return;
  els.ocrSpinner.hidden = !running;
  els.ocrBannerTitle.textContent = status.error
    ? "OCR stopped"
    : running
      ? "Reading scanned pages\u2026"
      : "Scanned pages need OCR";
  const percent = total ? Math.round((100 * done) / total) : 0;
  els.ocrBannerDetail.textContent =
    `${done} / ${total} page${total === 1 ? "" : "s"} \u00b7 ${percent}%` +
    (status.error ? ` \u00b7 ${status.error}` : "");
  els.ocrBannerBar.style.width = `${percent}%`;
  els.ocrRetry.hidden = running || pending === 0;
  els.ocrCancel.hidden = !running;
}

async function pollOcrDocument(docId, request) {
  if (!state.doc || state.doc.id !== docId || state.ocr.request !== request) {
    return;
  }
  try {
    let status = await api(`/api/documents/${encodeURIComponent(docId)}/ocr`);
    if (!state.doc || state.doc.id !== docId || state.ocr.request !== request) {
      return;
    }
    if (
      status.pending > 0 &&
      !status.running &&
      !status.error &&
      !state.ocr.started
    ) {
      state.ocr.started = true;
      status = await api(`/api/documents/${encodeURIComponent(docId)}/ocr`, {
        method: "POST",
      });
      if (!state.doc || state.doc.id !== docId || state.ocr.request !== request) {
        return;
      }
    }
    state.ocr.status = status;
    updateOcrBanner(status);
    if (status.running || status.pending > 0) {
      state.ocr.timer = setTimeout(
        () => pollOcrDocument(docId, request),
        900
      );
      return;
    }
    finishOcr(status);
  } catch (error) {
    if (!state.doc || state.doc.id !== docId || state.ocr.request !== request) {
      return;
    }
    updateOcrBanner({
      running: false,
      pending: 1,
      total: 1,
      done: 0,
      error: error.message,
      percent: 0,
    });
  }
}

function finishOcr(status) {
  const total = Number(status.total) || 0;
  const done = Number(status.done) || 0;
  hideOcrBanner();
  if (total > 0 && done >= total && state.ocr.lastDone !== done) {
    state.ocr.lastDone = done;
    toast(
      `OCR finished \u2014 ${done} scanned page${done === 1 ? "" : "s"} are now searchable.`,
      "success",
      5000
    );
  }
  refreshOcrPages();
  if (typeof refreshCoverage === "function") refreshCoverage({ quiet: true });
}

function refreshOcrPages() {
  if (state.ocr.refreshed) return;
  state.ocr.refreshed = true;
  state.models.forEach((model) => {
    if (!model || !model.el) return;
    const loaded = model.el.classList.contains("has-image");
    const empty = !Array.isArray(model.lines) || model.lines.length === 0;
    if (!loaded || !empty || model.loading) return;
    model.lines = null;
    loadPage(model);
  });
}

async function retryOcr() {
  const doc = state.doc;
  if (!doc || doc.kind === "transcript") return;
  try {
    state.ocr.started = true;
    const status = await api(
      `/api/documents/${encodeURIComponent(doc.id)}/ocr`,
      { method: "POST" }
    );
    state.ocr.status = status;
    state.ocr.refreshed = false;
    updateOcrBanner(status);
    const request = state.ocr.request + 1;
    state.ocr.request = request;
    pollOcrDocument(doc.id, request);
  } catch (error) {
    toast(`Couldn't start OCR: ${error.message}`, "error", 7000);
  }
}

async function cancelOcr() {
  const doc = state.doc;
  if (!doc || doc.kind === "transcript") return;
  try {
    const status = await api(
      `/api/documents/${encodeURIComponent(doc.id)}/ocr/cancel`,
      { method: "POST" }
    );
    updateOcrBanner(status);
  } catch (error) {
    toast(`Couldn't stop OCR: ${error.message}`, "error", 7000);
  }
}

function bindOcrEvents() {
  if (els.ocrRetry) els.ocrRetry.addEventListener("click", retryOcr);
  if (els.ocrCancel) els.ocrCancel.addEventListener("click", cancelOcr);
}
