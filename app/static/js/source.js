"use strict";

/* Source lookup and highlighting */

function clearSourceHighlights() {
  document.querySelectorAll(".line.is-source-highlight").forEach((span) => {
    span.classList.remove("is-source-highlight");
  });
  document.querySelectorAll(".page.is-source-target").forEach((pageEl) => {
    pageEl.classList.remove("is-source-target");
  });
  document.querySelectorAll(".cue.is-source-highlight").forEach((cue) => {
    cue.classList.remove("is-source-highlight");
  });
}

function normalizeSourceText(value) {
  return String(value || "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

async function ensurePageLines(model) {
  if (!model) return null;
  if (model.lines !== null) return model.lines;
  loadPage(model);
  const started = Date.now();
  while (
    model.lines === null &&
    !model.linesError &&
    Date.now() - started < 20000
  ) {
    await new Promise((resolve) => setTimeout(resolve, 80));
  }
  return model.lines;
}

function searchEvidenceInLines(lines, evidence) {
  const target = normalizeSourceText(evidence);
  if (!target) return null;
  const normalized = lines.map((line) => normalizeSourceText(line.text));
  const words = target.split(" ").filter(Boolean);

  // Start from the line that actually contains the opening words, so we don't
  // include an unrelated heading that happens to sit just before the quote.
  const anchor = words.slice(0, 6).join(" ");
  if (anchor) {
    for (let start = 0; start < normalized.length; start += 1) {
      if (!normalized[start].includes(anchor)) continue;
      let combined = "";
      for (let end = start; end < normalized.length && end < start + 12; end += 1) {
        combined = `${combined} ${normalized[end]}`.trim();
        if (combined.includes(target)) return { start, end };
        if (combined.length > target.length + 180) break;
      }
    }
  }

  for (let start = 0; start < normalized.length; start += 1) {
    let combined = "";
    for (let end = start; end < normalized.length && end < start + 12; end += 1) {
      combined = `${combined} ${normalized[end]}`.trim();
      if (combined.includes(target)) return { start, end };
      if (combined.length > target.length + 180) break;
    }
  }

  if (words.length) {
    const startWords = words.slice(0, 6).join(" ");
    for (let index = 0; index < normalized.length; index += 1) {
      if (normalized[index].includes(startWords)) return { start: index, end: index };
    }
  }
  return null;
}

async function findCardEvidence(source) {
  const evidence = source.evidence || "";
  if (!evidence || !Array.isArray(source.pages) || source.pages.length < 2) {
    return null;
  }
  const pageCount = state.doc ? state.doc.pageCount : 0;
  const start = clamp(Math.min(...source.pages), 0, Math.max(0, pageCount - 1));
  const end = clamp(Math.max(...source.pages), 0, Math.max(0, pageCount - 1));
  for (let page = start; page <= end; page += 1) {
    const model = state.models.get(page);
    if (!model) continue;
    const lines = await ensurePageLines(model);
    if (!lines || !lines.length) continue;
    const found = searchEvidenceInLines(lines, evidence);
    if (found) return { page, ...found };
  }
  return null;
}

function highlightPageLines(pageIndex, startIndex, endIndex) {
  const model = state.models.get(pageIndex);
  if (!model) return null;
  const spans = Array.from(model.el.querySelectorAll(".line"));
  const byIndex = new Map(
    spans.map((span) => [Number(span.dataset.lineIndex), span])
  );
  let first = null;
  for (let index = startIndex; index <= endIndex; index += 1) {
    const span = byIndex.get(index);
    if (span) {
      span.classList.add("is-source-highlight");
      if (!first) first = span;
    }
  }
  model.el.classList.add("is-source-target");
  return first;
}

async function highlightLocation(location) {
  let first = null;
  for (const entry of location || []) {
    const model = state.models.get(entry.page);
    if (!model) continue;
    await ensurePageLines(model);
    const indices = entry.indices || [];
    if (!indices.length) continue;
    const span = highlightPageLines(
      entry.page,
      Math.min(...indices),
      Math.max(...indices)
    );
    if (!first && span) first = span;
  }
  return first;
}

function scrollToSource(target) {
  if (!target) return;
  const top =
    target.getBoundingClientRect().top -
    els.scroller.getBoundingClientRect().top +
    els.scroller.scrollTop -
    els.scroller.clientHeight * 0.32;
  els.scroller.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
}

function transcriptSourceLabel(start, end) {
  const segments = state.transcript.segments;
  const first = segments[start];
  const last = segments[end];
  if (!first || !last) return "Transcript";
  if (first.startLabel && last.endLabel) {
    return `${first.startLabel}\u2013${last.endLabel}`;
  }
  return start === end
    ? first.label || `Segment ${start + 1}`
    : `Segments ${start + 1}\u2013${end + 1}`;
}

function highlightTranscriptSegments(start, end) {
  const segments = state.transcript.segments;
  let first = null;
  for (let index = Math.max(0, start); index <= Math.min(segments.length - 1, end); index += 1) {
    const cue = els.pages.querySelector(`.cue[data-segment="${index}"]`);
    if (!cue) continue;
    cue.classList.add("is-source-highlight");
    if (!first) first = cue;
  }
  return first;
}

function locateTranscriptSource(source, cardEl) {
  const segments = state.transcript.segments;
  if (!segments.length) return null;

  let start = null;
  let end = null;
  if (source.evidence) {
    const found = searchEvidenceInLines(segments, source.evidence);
    if (found) {
      start = found.start;
      end = found.end;
    }
  }
  if (start === null && Array.isArray(source.location)) {
    const indices = source.location
      .map((entry) => Number(entry && entry.segment))
      .filter((index) => Number.isInteger(index) && index >= 0 && index < segments.length);
    if (indices.length) {
      start = Math.min(...indices);
      end = Math.max(...indices);
    }
  }
  if (start === null && Array.isArray(source.segments) && source.segments.length >= 2) {
    start = Math.max(0, Number(source.segments[0]) - 1);
    end = Math.min(segments.length - 1, Number(source.segments[1]) - 1);
  }
  if (start === null || end === null || end < start) return null;

  const first = highlightTranscriptSegments(start, end);
  if (!first) return null;
  source.segments = [start + 1, end + 1];
  source.label = transcriptSourceLabel(start, end);
  const labelEl = cardEl ? cardEl.querySelector(".card-locate-label") : null;
  if (labelEl) labelEl.textContent = source.label;
  scrollToSource(first);
  return first;
}

async function locateCardSource(card, cardEl) {
  const source =
    card.source && typeof card.source === "object" ? card.source : null;
  if (!source) {
    toast("No source location was saved for this card.", "error");
    return;
  }

  clearSourceHighlights();

  if (source.kind === "transcript") {
    const target = locateTranscriptSource(source, cardEl);
    if (!target) {
      toast("Couldn't find the saved segment in this transcript.", "error", 6000);
    }
    return;
  }

  let target = null;

  if (source.evidence) {
    const found = await findCardEvidence(source);
    if (found) {
      target = highlightPageLines(found.page, found.start, found.end);
      source.pages = [found.page, found.page];
      source.label = `Page ${found.page + 1}`;
      const labelEl = cardEl ? cardEl.querySelector(".card-locate-label") : null;
      if (labelEl) labelEl.textContent = source.label;
    }
  }

  if (!target && Array.isArray(source.location) && source.location.length) {
    target = await highlightLocation(source.location);
  }

  if (!target && Array.isArray(source.pages) && source.pages.length) {
    const pageIndex = source.pages[0];
    const model = state.models.get(pageIndex);
    if (model) {
      await ensurePageLines(model);
      model.el.classList.add("is-source-target");
      target = model.el;
    }
  }

  if (!target) {
    toast("Couldn't find the saved source location in this document.", "error", 6000);
    return;
  }

  scrollToSource(target);
}
