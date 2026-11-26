"use strict";

/* Document viewers, pages, transcripts and selection */

function loadDocument(doc) {
  flushDrafts({ beacon: true });
  resetDrafts();
  resetSent();
  resetUndo();
  resetObjectives();
  resetAnswers();
  state.doc = doc;
  state.activeLibraryFileId = doc.libraryFileId || null;
  state.models.clear();
  state.cards = [];
  state.cardHeights = {};
  state.chapterPlan = null;
  state.imageCrop = null;
  state.imageTarget = null;
  state.figureMode = false;
  els.pages.classList.remove("is-figure-mode");
  if (els.figureBtn) els.figureBtn.classList.remove("is-active");
  state.coverage = { loading: false, data: null, error: "", request: 0 };
  state.activePage = 0;
  state.zoom = 1;
  clearSourceHighlights();
  clearSelection();

  if (state.loadObserver) state.loadObserver.disconnect();
  if (state.spyObserver) state.spyObserver.disconnect();
  if (state.imageObserver) state.imageObserver.disconnect();

  els.emptyState.hidden = true;
  els.stageToolbar.hidden = false;
  els.docBar.hidden = false;
  els.docName.textContent = doc.filename;
  els.docName.title = doc.filename;
  document.title = `${doc.filename} \u2014 Anki Scribe`;

  els.pages.replaceChildren();

  if (doc.kind === "transcript") {
    state.transcript = { segments: doc.segments || [] };
    els.stageToolbar.hidden = true;
    els.pagePill.parentElement.hidden = true;
    els.pages.classList.add("is-transcript");
    els.autoBadge.textContent = "transcript";
    els.splitBadge.textContent = "per chapter";
    els.autoDocBtn.title = "Generate cards from the whole transcript, section by section";
    els.splitDocBtn.title = "Write one Markdown file per chapter (timestamped sections)";
    renderTranscript(doc);
    renderCards();
    hideAutoPanel();
    updateAutoButton();
    if (els.libraryDialog.open) renderLibrary();
    els.scroller.scrollTop = 0;
    refreshCoverage({ quiet: true });
    loadDraftsForDocument(doc);
    loadSentForDocument(doc);
    loadObjectives(doc);
    prepareAnswersForDocument(doc);
    if (typeof prepareOcrForDocument === "function") prepareOcrForDocument(doc);
    return;
  }

  state.transcript = { segments: [] };
  els.pages.classList.remove("is-transcript");
  els.pagePill.parentElement.hidden = false;
  const isBook = doc.format === "epub";
  els.autoBadge.textContent = isBook ? "chapters" : "text + tables";
  els.splitBadge.textContent = ".md + manifest";
  els.autoDocBtn.title = isBook
    ? "Generate cards one chapter at a time, straight from the book's contents"
    : "Read every page and table, then generate cards section by section";
  els.splitDocBtn.title = isBook
    ? "Write one Markdown file per chapter, with a manifest of the book"
    : "Write one Markdown file per chapter, ready to feed a model";
  buildPageElements(doc);
  applyPageWidth();
  setActivePage(0);
  renderCards();
  hideAutoPanel();
  updateAutoButton();
  if (els.libraryDialog.open) renderLibrary();
  els.scroller.scrollTop = 0;

  const first = state.models.get(0);
  if (first) loadPage(first);
  refreshCoverage({ quiet: true });
  loadDraftsForDocument(doc);
  loadSentForDocument(doc);
  loadObjectives(doc);
  prepareAnswersForDocument(doc);
  if (typeof prepareOcrForDocument === "function") prepareOcrForDocument(doc);
}

function formatTranscriptTime(seconds) {
  const total = Math.max(0, Math.round(Number(seconds) || 0));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (hours) return `${hours}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function renderTranscript(doc) {
  const segments = doc.segments || [];
  const wrap = document.createElement("div");
  wrap.className = "transcript";

  const head = document.createElement("div");
  head.className = "transcript-head";
  const badge = document.createElement("span");
  badge.className = "transcript-badge";
  badge.textContent = "Transcript";
  const meta = document.createElement("span");
  meta.className = "transcript-meta";
  const firstStart = segments.length ? Number(segments[0].start) || 0 : 0;
  meta.textContent = doc.hasTimestamps
    ? `${formatTranscriptTime(firstStart)}\u2013${formatTranscriptTime(doc.duration)} \u00b7 ${segments.length} segments`
    : `${segments.length} segments`;
  head.append(badge, meta);
  wrap.appendChild(head);

  const hint = document.createElement("p");
  hint.className = "transcript-hint";
  hint.textContent = doc.hasTimestamps
    ? "Drag over the transcript to select text, or click a timestamp to select that whole segment."
    : "Drag over the transcript to select text, or click the paragraph marker to select that whole segment.";
  wrap.appendChild(hint);

  if (!segments.length) {
    const empty = document.createElement("div");
    empty.className = "transcript-empty";
    empty.textContent = "No readable transcript text was found.";
    wrap.appendChild(empty);
    els.pages.appendChild(wrap);
    return;
  }

  const list = document.createElement("div");
  list.className = "transcript-cues";
  segments.forEach((segment, index) => {
    const cue = document.createElement("article");
    cue.className = "cue";
    cue.dataset.segment = String(index);
    cue.dataset.label = segment.label || `Segment ${index + 1}`;

    const time = document.createElement("button");
    time.type = "button";
    time.className = "cue-time";
    time.dataset.action = "select-cue";
    time.title = `Select ${segment.label || `segment ${index + 1}`}`;
    time.setAttribute(
      "aria-label",
      `Select ${segment.label || `segment ${index + 1}`}`
    );
    time.textContent = segment.startLabel || "\u00b6";

    const text = document.createElement("p");
    text.className = "cue-text";
    text.textContent = segment.text || "";

    cue.append(time, text);
    list.appendChild(cue);
  });
  wrap.appendChild(list);
  els.pages.appendChild(wrap);
}

function buildPageElements(doc) {
  const fragment = document.createDocumentFragment();

  doc.pages.forEach((page) => {
    const pageEl = document.createElement("div");
    pageEl.className = "page";
    pageEl.dataset.page = String(page.index);
    pageEl.style.setProperty("--ratio", `${page.width} / ${page.height}`);

    pageEl.innerHTML = `
      <div class="page-skeleton"><span class="spinner"></span></div>
      <img alt="Page ${page.index + 1}" draggable="false" decoding="async">
      <div class="text-layer"></div>
      <button type="button" class="page-chip">Select page</button>
      <div class="page-status" hidden></div>
    `;

    const model = {
      index: page.index,
      width: page.width,
      height: page.height,
      needsOcr: page.needsOcr,
      el: pageEl,
      lines: null,
      linesError: false,
      loading: false,
    };
    state.models.set(page.index, model);
    fragment.appendChild(pageEl);
  });

  els.pages.appendChild(fragment);

  state.loadObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        const model = state.models.get(Number(entry.target.dataset.page));
        if (model) loadPage(model);
        state.loadObserver.unobserve(entry.target);
      });
    },
    { root: els.scroller, rootMargin: "700px 0px" }
  );

  state.spyObserver = new IntersectionObserver(
    (entries) => {
      let best = null;
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        if (!best || entry.intersectionRatio > best.intersectionRatio) best = entry;
      });
      if (best) setActivePage(Number(best.target.dataset.page));
    },
    { root: els.scroller, threshold: [0.05, 0.25, 0.5, 0.75] }
  );

  state.imageObserver = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        const model = state.models.get(Number(entry.target.dataset.page));
        if (!model) return;
        if (entry.isIntersecting) {
          ensurePageImage(model);
        } else if (Number(entry.target.dataset.page) !== state.activePage) {
          releasePageImage(model);
        }
      });
    },
    { root: els.scroller, rootMargin: "900px 0px" }
  );

  state.models.forEach((model) => {
    state.loadObserver.observe(model.el);
    state.spyObserver.observe(model.el);
    state.imageObserver.observe(model.el);
  });
}

async function loadPage(model) {
  if (!model || model.loading || !state.doc) return;
  model.loading = true;
  const docId = state.doc.id;
  const pageEl = model.el;

  ensurePageImage(model);

  try {
    if (pageEl.dataset.linesLoaded === "1") return;
    if (model.needsOcr) {
      showPageStatus(model, "Reading text with OCR\u2026");
    }

    const data = await api(`/api/documents/${docId}/pages/${model.index}/lines`);
    if (!state.doc || state.doc.id !== docId) return;
    pageEl.dataset.linesLoaded = "1";
    model.lines = data.lines || [];
    model.linesError = false;
    renderTextLayer(model, model.lines, data.width || model.width, data.height || model.height);
    applyDraftHighlightsForPage(model);
    hidePageStatus(model);

    if (!model.lines.length) {
      showPageStatus(model, "No selectable text on this page. Try a sharper image.", "warn");
    } else if (data.ocr) {
      const badge = document.createElement("span");
      badge.className = "ocr-badge";
      badge.textContent = "OCR";
      badge.title = "Text was read from the image with OCR.";
      pageEl.appendChild(badge);
    }
  } catch (error) {
    model.linesError = true;
    showPageStatus(model, "Couldn't read the text on this page.", "error");
    console.warn(error);
  } finally {
    model.loading = false;
  }
}

/* A rendered page is about 8 MB decoded. A book is hundreds of pages, so the
   viewer keeps images only around the viewport and lets the rest go: the page
   box keeps its aspect ratio, so nothing moves when the picture comes back. */
function ensurePageImage(model) {
  if (!model || !state.doc) return;
  const img = model.el.querySelector("img");
  if (!img || img.getAttribute("src")) return;
  img.addEventListener("load", () => model.el.classList.add("has-image"), {
    once: true,
  });
  img.addEventListener(
    "error",
    () => showPageStatus(model, "Couldn't render this page.", "error"),
    { once: true }
  );
  img.src = `/api/documents/${state.doc.id}/pages/${model.index}/image`;
}

function releasePageImage(model) {
  const img = model && model.el ? model.el.querySelector("img") : null;
  if (!img || !img.getAttribute("src")) return;
  img.removeAttribute("src");
  img.removeAttribute("srcset");
  model.el.classList.remove("has-image");
}

function renderTextLayer(model, lines, width, height) {
  const layer = model.el.querySelector(".text-layer");
  const fragment = document.createDocumentFragment();

  lines.forEach((line, lineIndex) => {
    if (!line || !line.text) return;
    const x0 = clamp(line.x0, 0, width);
    const y0 = clamp(line.y0, 0, height);
    const x1 = clamp(line.x1, 0, width);
    const y1 = clamp(line.y1, 0, height);
    if (x1 - x0 < 1 || y1 - y0 < 1) return;

    const span = document.createElement("span");
    span.className = "line";
    span.textContent = line.text;
    span.dataset.text = line.text;
    span.dataset.lineIndex = String(lineIndex);
    span.style.left = `${((x0 / width) * 100).toFixed(3)}%`;
    span.style.top = `${((y0 / height) * 100).toFixed(3)}%`;
    span.style.width = `${(((x1 - x0) / width) * 100).toFixed(3)}%`;
    span.style.height = `${(((y1 - y0) / height) * 100).toFixed(3)}%`;
    span.style.fontSize = `${((((y1 - y0) / width) * 100) * 0.92).toFixed(3)}cqw`;
    fragment.appendChild(span);
  });

  layer.replaceChildren(fragment);
}

function showPageStatus(model, text, kind = "") {
  const node = model.el.querySelector(".page-status");
  if (!node) return;
  node.textContent = text;
  node.className = `page-status${kind ? ` ${kind}` : ""}`;
  node.hidden = false;
}

function hidePageStatus(model) {
  const node = model.el.querySelector(".page-status");
  if (node) node.hidden = true;
}

function applyPageWidth() {
  if (!state.doc) return;
  const available = Math.max(280, els.scroller.clientWidth - 64);
  const base = Math.min(available, 980);
  const width = Math.max(240, Math.round(base * state.zoom));
  els.pages.style.setProperty("--page-width", `${width}px`);
  els.zoomLabel.textContent = `${Math.round(state.zoom * 100)}%`;
}

function setZoom(value) {
  state.zoom = clamp(Math.round(value * 10) / 10, ZOOM_MIN, ZOOM_MAX);
  applyPageWidth();
}

function goToPage(index) {
  const model = state.models.get(index);
  if (!model) return;
  scrollViewerTo(model.el);
}

function scrollViewerTo(element) {
  const top =
    element.getBoundingClientRect().top -
    els.scroller.getBoundingClientRect().top +
    els.scroller.scrollTop -
    8;
  els.scroller.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
}

function scrollPanelTo(element) {
  const top =
    element.getBoundingClientRect().top -
    els.panelScroll.getBoundingClientRect().top +
    els.panelScroll.scrollTop -
    8;
  els.panelScroll.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
}

function setActivePage(index) {
  if (!state.doc) return;
  const count = state.doc.pageCount;
  if (index < 0 || index >= count) return;
  state.activePage = index;
  els.pagePill.textContent = `${index + 1} / ${count}`;
  els.prevPage.disabled = index <= 0;
  els.nextPage.disabled = index >= count - 1;
}

/* ------------------------------------------------------------------ */
/* figure cards                                                       */
/* ------------------------------------------------------------------ */

let figureDrag = null;

function setFigureMode(on) {
  state.figureMode = Boolean(on);
  if (state.figureMode) state.imageCrop = null;
  if (els.figureBtn) els.figureBtn.classList.toggle("is-active", state.figureMode);
  if (els.pages) {
    els.pages.classList.toggle(
      "is-figure-mode",
      state.figureMode || Boolean(state.imageCrop)
    );
  }
  if (state.figureMode) {
    toast("Drag a box over a figure or a label to make an image card.", "info", 4500);
  }
}

/* Attaching a picture to an existing card uses the same drag as the figure
   tool, but cuts a plain crop and puts it on the card instead of making one. */
function startImageCrop(uid) {
  if (!state.doc) return;
  if (state.doc.kind !== "pdf") {
    toast(
      "Cropping needs a PDF page. Use Upload a file for this source instead.",
      "error",
      6500
    );
    return;
  }
  state.figureMode = false;
  if (els.figureBtn) els.figureBtn.classList.remove("is-active");
  state.imageCrop = { uid };
  els.pages.classList.add("is-figure-mode");
  toast("Drag a box over the picture for this card. Esc cancels.", "info", 5000);
}

function cancelImageCrop() {
  if (!state.imageCrop) return;
  state.imageCrop = null;
  if (!state.figureMode) els.pages.classList.remove("is-figure-mode");
  toast("Picture cancelled.", "info", 2500);
}

function figurePoint(event, drag) {
  return {
    x: clamp((event.clientX - drag.rect.left) * drag.scaleX, 0, drag.model.width),
    y: clamp((event.clientY - drag.rect.top) * drag.scaleY, 0, drag.model.height),
  };
}

function paintFigureBox(drag, current) {
  const x0 = Math.min(drag.start.x, current.x);
  const y0 = Math.min(drag.start.y, current.y);
  const x1 = Math.max(drag.start.x, current.x);
  const y1 = Math.max(drag.start.y, current.y);
  drag.box.style.left = `${(x0 / drag.model.width) * 100}%`;
  drag.box.style.top = `${(y0 / drag.model.height) * 100}%`;
  drag.box.style.width = `${((x1 - x0) / drag.model.width) * 100}%`;
  drag.box.style.height = `${((y1 - y0) / drag.model.height) * 100}%`;
  drag.area = { x0: Math.round(x0), y0: Math.round(y0), x1: Math.round(x1), y1: Math.round(y1) };
}

function moveFigureDrag(event) {
  if (!figureDrag) return;
  event.preventDefault();
  paintFigureBox(figureDrag, figurePoint(event, figureDrag));
}

function endFigureDrag(event) {
  if (!figureDrag) return;
  const drag = figureDrag;
  figureDrag = null;
  window.removeEventListener("mousemove", moveFigureDrag);
  window.removeEventListener("mouseup", endFigureDrag);
  drag.box.remove();

  paintFigureBox(drag, figurePoint(event, drag));
  const area = drag.area;
  if (!area || area.x1 - area.x0 < 12 || area.y1 - area.y0 < 12) {
    toast("That box was too small \u2014 drag a bigger one.", "info", 4000);
    return;
  }
  if (state.imageCrop) {
    const uid = state.imageCrop.uid;
    state.imageCrop = null;
    if (!state.figureMode) els.pages.classList.remove("is-figure-mode");
    attachImageCrop(drag.model, area, uid);
    return;
  }
  createFigureCard(drag.model, area);
}

function beginFigureDrag(event) {
  if (
    (!state.figureMode && !state.imageCrop) ||
    event.button !== 0 ||
    figureDrag
  ) {
    return;
  }
  const pageEl = event.target.closest(".page");
  if (!pageEl) return;
  const model = state.models.get(Number(pageEl.dataset.page));
  if (!model) return;
  event.preventDefault();
  event.stopPropagation();

  const rect = pageEl.getBoundingClientRect();
  if (!rect.width || !rect.height) return;
  const box = document.createElement("div");
  box.className = "figure-box";
  pageEl.appendChild(box);

  figureDrag = {
    pageEl,
    model,
    rect,
    scaleX: model.width / rect.width,
    scaleY: model.height / rect.height,
    start: { x: 0, y: 0 },
    box,
    area: null,
  };
  figureDrag.start = figurePoint(event, figureDrag);
  paintFigureBox(figureDrag, figureDrag.start);
  window.addEventListener("mousemove", moveFigureDrag);
  window.addEventListener("mouseup", endFigureDrag);
}

async function createFigureCard(model, area) {
  const doc = state.doc;
  if (!doc) return;
  const docId = doc.id;
  try {
    const data = await api(`/api/documents/${encodeURIComponent(docId)}/figures`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page: model.index, ...area }),
    });
    if (!state.doc || state.doc.id !== docId) {
      toast("Another file was opened, so that figure was discarded.", "error", 8000);
      return;
    }
    const sourceTitle = sourceTitleForDoc();
    const suggested = String(data.suggested || "").trim();
    const card = {
      uid: uid(),
      mode: "figure",
      selected: true,
      question: "What is covered in this figure?",
      answer: suggested,
      extra: "",
      tags: [],
      evidence: suggested,
      verified: true,
      figure: {
        docId,
        masked: data.masked,
        revealed: data.revealed,
        page: model.index,
      },
      source: {
        kind: "figure",
        label: data.label || `Page ${model.index + 1}`,
        file: doc.filename,
        location: [],
        pages: [model.index, model.index],
        quote: "",
        sourceTitle,
        chapterPath: [],
        chapterTitle: "",
        deckPath: [sourceTitle],
      },
    };
    state.cards.push(card);
    renderCards();
    toast(
      suggested
        ? `Figure card added \u2014 we read \u201c${suggested}\u201d in that box. Check the answer.`
        : "Figure card added. Type the answer before sending.",
      "success",
      8000
    );
    requestAnimationFrame(() => scrollPanelTo(els.cardsBlock));
  } catch (error) {
    toast(error.message, "error", 8000);
  }
}

/* The plain version of the figure tool: one crop, put on a card that exists. */
async function attachImageCrop(model, area, uid) {
  const doc = state.doc;
  if (!doc || !uid) return;
  const docId = doc.id;
  try {
    const data = await api(`/api/documents/${encodeURIComponent(docId)}/images/crop`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ page: model.index, ...area }),
    });
    if (!state.doc || state.doc.id !== docId) {
      toast("Another file was opened, so that picture was discarded.", "error", 8000);
      return;
    }
    setCardImage(uid, { docId, name: data.name, side: "front" });
    toast("Picture added to the card.", "success", 4000);
  } catch (error) {
    toast(error.message, "error", 8000);
  }
}

/* ------------------------------------------------------------------ */
/* selection                                                          */
/* ------------------------------------------------------------------ */

function captureDocSelection() {
  if (!state.doc) return;
  if (state.doc.kind === "transcript") {
    captureTranscriptSelection();
    return;
  }
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount) return;
  const anchor = selection.anchorNode;
  const focus = selection.focusNode;
  if (!anchor || !focus) return;
  if (!els.pages.contains(anchor) || !els.pages.contains(focus)) return;

  const ranges = [];
  for (let i = 0; i < selection.rangeCount; i += 1) ranges.push(selection.getRangeAt(i));

  const picked = [];
  els.pages.querySelectorAll(".page").forEach((pageEl) => {
    const spans = Array.from(pageEl.querySelectorAll(".line"));
    if (!spans.length) return;
    const hit = spans.filter((span) =>
      ranges.some((range) => {
        try {
          return range.intersectsNode(span);
        } catch {
          return false;
        }
      })
    );
    if (hit.length) {
      picked.push({
        index: Number(pageEl.dataset.page),
        lines: hit.map((span) => span.dataset.text || span.textContent || ""),
        indices: hit.map((span) => Number(span.dataset.lineIndex)),
      });
    }
  });

  if (!picked.length) return;

  const text = normalizeSelection(picked.map((page) => page.lines.join("\n")).join("\n\n"));
  if (text.length < 2) return;

  const first = Math.min(...picked.map((page) => page.index));
  const last = Math.max(...picked.map((page) => page.index));
  const label = first === last ? `Page ${first + 1}` : `Pages ${first + 1}\u2013${last + 1}`;
  const location = picked
    .filter((page) => page.indices.length)
    .map((page) => ({ page: page.index, indices: page.indices }));
  setSelection(text, label, location);
}

function normalizeSelection(text) {
  return text
    .replace(/\u00ad/g, "")
    .replace(/-\n(?=[a-z])/g, "")
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function transcriptRangeLabel(indices) {
  const segments = state.transcript.segments;
  if (!indices.length || !segments.length) return "Transcript";
  const first = segments[Math.min(...indices)];
  const last = segments[Math.max(...indices)];
  if (!first || !last) return "Transcript";
  if (first.startLabel && last.endLabel) {
    return `${first.startLabel}\u2013${last.endLabel}`;
  }
  return first === last
    ? first.label || `Segment ${indices[0] + 1}`
    : `Segments ${Math.min(...indices) + 1}\u2013${Math.max(...indices) + 1}`;
}

function captureTranscriptSelection() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed || !selection.rangeCount) return;
  const anchor = selection.anchorNode;
  const focus = selection.focusNode;
  if (!anchor || !focus) return;
  if (!els.pages.contains(anchor) || !els.pages.contains(focus)) return;

  const ranges = [];
  for (let i = 0; i < selection.rangeCount; i += 1) ranges.push(selection.getRangeAt(i));
  const cues = Array.from(els.pages.querySelectorAll(".cue"));
  const hit = cues.filter((cue) =>
    ranges.some((range) => {
      try {
        return range.intersectsNode(cue);
      } catch {
        return false;
      }
    })
  );
  if (!hit.length) return;

  const indices = hit.map((cue) => Number(cue.dataset.segment));
  const text = normalizeSelection(
    hit
      .map((cue) => {
        const node = cue.querySelector(".cue-text");
        return node ? node.textContent || "" : "";
      })
      .join("\n")
  );
  if (text.length < 2) return;

  setSelection(
    text,
    transcriptRangeLabel(indices),
    indices.map((segment) => ({ segment }))
  );
}

function selectTranscriptSegment(index) {
  const segment = state.transcript.segments[index];
  if (!segment) return;
  clearNativeSelection();
  setSelection(
    segment.text || "",
    segment.label || `Segment ${index + 1}`,
    [{ segment: index }]
  );
}

function setSelection(text, label, location = []) {
  state.selection = { text, label, location };
  els.selectionText.value = text;
  els.selectionMeta.textContent = label;
  els.clearSelection.hidden = !text;
  updateSelectionUi();
  if (typeof updateHideSelectionButton === "function") updateHideSelectionButton();
}

function clearSelection() {
  clearNativeSelection();
  state.selection = { text: "", label: "", location: [] };
  els.selectionText.value = "";
  els.selectionMeta.textContent = "Drag across text in the document";
  els.clearSelection.hidden = true;
  updateSelectionUi();
  if (typeof updateHideSelectionButton === "function") updateHideSelectionButton();
}

function clearNativeSelection() {
  const selection = window.getSelection();
  if (selection) selection.removeAllRanges();
}

function updateSelectionUi() {
  const text = els.selectionText.value;
  const count = text.trim().length;
  els.charCount.textContent = `${count.toLocaleString()} chars`;

  const over = count > MAX_CHARS;
  els.charCount.parentElement.classList.toggle("over", over);
  els.charLimit.textContent = over ? `limit ${MAX_CHARS.toLocaleString()}` : "";

  els.generateBtn.disabled =
    count < MIN_CHARS || over || state.generating || state.auto.running;
}

function updateAutoButton() {
  els.autoDocBtn.disabled = !state.doc || state.auto.running || state.generating;
  els.splitDocBtn.disabled =
    !state.doc ||
    state.auto.running ||
    state.generating ||
    state.uploading ||
    state.savingChapters;
}

function selectWholePage(model) {
  if (!model.lines || !model.lines.length) {
    if (model.linesError) {
      toast(
        "Couldn't read the text on this page. Try reopening the file, or select the text by hand.",
        "error",
        8000
      );
    } else if (model.needsOcr || model.loading) {
      toast("Still reading this page \u2014 try again in a moment.");
    } else {
      toast("There is no selectable text on this page.");
    }
    return;
  }
  const text = normalizeSelection(model.lines.map((line) => line.text).join("\n"));
  if (!text) {
    toast("There is no selectable text on this page.");
    return;
  }
  // Drop the old native range first, otherwise the debounced selectionchange
  // handler would overwrite this whole-page selection with it.
  clearNativeSelection();
  setSelection(text, `Page ${model.index + 1}`, [
    { page: model.index, indices: model.lines.map((_, index) => index) },
  ]);
}
