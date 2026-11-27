"use strict";

/* Chapter-aware whole-file generation */

function showAutoPanel(status, detail, fraction) {
  clearTimeout(state.auto.hideTimer);
  state.auto.hideTimer = null;
  const batch = state.auto.batch;
  els.autoPanel.hidden = false;
  els.autoSpinner.hidden = false;
  els.autoStatus.classList.remove("error");
  els.autoStatus.textContent = batch
    ? `File ${batch.index}/${batch.total} \u00b7 ${status}`
    : status;
  els.autoDetail.textContent = detail || "";
  els.autoCancel.hidden = false;
  els.autoCancel.disabled = false;
  els.autoCancel.textContent = "Stop";
  if (fraction === null || fraction === undefined) {
    els.autoBar.classList.add("indeterminate");
    els.autoBar.style.width = "100%";
  } else {
    els.autoBar.classList.remove("indeterminate");
    els.autoBar.style.width = `${Math.round(fraction * 100)}%`;
  }
}

function finishAuto(status, detail, kind = "info") {
  els.autoSpinner.hidden = true;
  const batch = state.auto.batch;
  els.autoStatus.textContent = batch
    ? `File ${batch.index}/${batch.total} \u00b7 ${status}`
    : status;
  els.autoStatus.classList.toggle("error", kind === "error");
  els.autoDetail.textContent = detail || "";
  els.autoBar.classList.remove("indeterminate");
  if (kind !== "error") els.autoBar.style.width = "100%";
  els.autoCancel.hidden = false;
  els.autoCancel.disabled = false;
  els.autoCancel.textContent = "Hide";
  clearTimeout(state.auto.hideTimer);
  state.auto.hideTimer = setTimeout(
    () => {
      if (!state.auto.running) hideAutoPanel();
    },
    kind === "error" ? 9000 : 5000
  );
}

function hideAutoPanel() {
  clearTimeout(state.auto.hideTimer);
  state.auto.hideTimer = null;
  els.autoPanel.hidden = true;
  els.autoPanel.classList.remove("is-error");
  els.autoBar.classList.remove("indeterminate");
  els.autoBar.style.width = "0%";
}

function cancelAutoGenerate() {
  if (state.batch.running) state.batch.cancelled = true;
  if (state.batch.running && state.batch.jobId) {
    els.autoCancel.disabled = true;
    els.autoStatus.textContent = "Stopping batch\u2026";
    return;
  }
  if (!state.auto.running) {
    hideAutoPanel();
    return;
  }
  state.auto.cancelled = true;
  if (state.auto.controller) state.auto.controller.abort();
  els.autoCancel.disabled = true;
  els.autoStatus.textContent = "Stopping\u2026";
}

function localChapterPlan(doc) {
  const isTranscript = doc.kind === "transcript";
  const units = isTranscript ? doc.segmentCount || 0 : doc.pageCount || 0;
  return {
    kind: doc.kind,
    unit: isTranscript ? "segments" : "pages",
    strategy: "fallback",
    sourceTitle: sourceTitleForDoc(),
    chapters: [
      {
        id: "0",
        title: "Full file",
        path: [],
        startPage: isTranscript ? null : 1,
        endPage: isTranscript ? null : doc.pageCount,
        startSegment: isTranscript ? 1 : null,
        endSegment: isTranscript ? doc.segmentCount : null,
        characters: 0,
        estimatedSections: Math.max(1, Math.ceil(units / 4)),
      },
    ],
    chapterCount: 1,
    estimatedSections: Math.max(1, Math.ceil(units / 4)),
  };
}

async function startAutoGenerate(options = {}) {
  const batch = options.batch || null;
  if (!state.doc) {
    toast("Open a file first.");
    return;
  }
  if (state.auto.running || state.generating) return;
  if (state.uploading) {
    toast("Wait for the file to finish loading.");
    return;
  }
  if (state.drafts.loading) {
    toast("Restoring draft cards\u2026 try again in a moment.");
    return;
  }
  if (!state.settings.has_key) {
    toast("Add your DeepSeek API key first.", "error");
    openSettings();
    return;
  }

  const doc = state.doc;
  const mode = state.mode;
  const controller = new AbortController();
  state.auto = {
    running: true,
    cancelled: false,
    controller,
    cards: 0,
    total: 0,
    hideTimer: null,
    batch,
    error: "",
  };
  setModeControlsDisabled(true);
  updateSelectionUi();
  updateAutoButton();
  updatePushLabel();
  showAutoPanel(
    "Planning chapters\u2026",
    "Looking for chapter and section boundaries."
  );

  try {
    showAutoPanel(
      "Planning chapters\u2026",
      "Looking for chapter and section boundaries."
    );
    let plan = state.chapterPlan;
    if (!plan) {
      try {
        plan = await api(
          `/api/documents/${encodeURIComponent(doc.id)}/chapters`,
          { signal: controller.signal }
        );
      } catch (error) {
        if (error.name === "AbortError") throw error;
        plan = localChapterPlan(doc);
        toast(
          `Couldn't plan chapters (${error.message}). Using one pass.`,
          "error",
          8000
        );
      }
    }
    if (!plan || !Array.isArray(plan.chapters) || !plan.chapters.length) {
      plan = localChapterPlan(doc);
    }
    state.chapterPlan = plan;
    if (plan.warning) toast(plan.warning, "info", 9000);

    const chapters = plan.chapters;
    const sourceTitle = plan.sourceTitle || sourceTitleForDoc();
    const estimatedSections = Math.max(
      chapters.length,
      Number(plan.estimatedSections) || chapters.length
    );
    const baseDeck =
      els.deckInput.value.trim() ||
      state.settings.default_deck ||
      "Anki Scribe";
    if (chapters.length > 1 || estimatedSections > 1) {
      const titlePreview = chapters
        .slice(0, 8)
        .map((chapter) => `\u2022 ${chapter.title}`)
        .join("\n");
      const more = chapters.length > 8 ? `\n\u2022 \u2026 ${chapters.length - 8} more` : "";
      const destination =
        state.deckMode === "exact"
          ? baseDeck
          : `${baseDeck}::${sourceTitle}`;
      const destinationLine =
        state.deckMode === "exact"
          ? `Cards will go directly to \u201c${destination}\u201d.`
          : `Cards will be organized under \u201c${destination}\u201d.`;
      if (!state.auto.batch) {
        const proceed = window.confirm(
          `Found ${chapters.length} chapter${chapters.length === 1 ? "" : "s"} \u00b7 ` +
            `${estimatedSections} section${estimatedSections === 1 ? "" : "s"}.\n\n` +
            `${titlePreview}${more}\n\n` +
            `${destinationLine}\n\n` +
            "Generate chapter by chapter?"
        );
        if (!proceed) {
          finishAuto("Cancelled", "No cards were generated.", "info");
          return;
        }
      }
    }

    state.auto.total = estimatedSections;
    let sectionNumber = 0;
    let processedChunks = 0;
    let failedSections = 0;

    for (let chapterIndex = 0; chapterIndex < chapters.length; chapterIndex += 1) {
      if (state.auto.cancelled) break;
      const chapter = chapters[chapterIndex];
      const sectionChars = doc.kind === "transcript" ? "6000" : "3500";
      const params = new URLSearchParams({ max_chars: sectionChars });
      if (doc.kind === "transcript") {
        if (chapter.startSegment != null) {
          params.set("start_segment", String(chapter.startSegment));
        }
        if (chapter.endSegment != null) {
          params.set("end_segment", String(chapter.endSegment));
        }
      } else {
        if (chapter.startPage != null) {
          params.set("start_page", String(chapter.startPage));
        }
        if (chapter.endPage != null) {
          params.set("end_page", String(chapter.endPage));
        }
      }

      showAutoPanel(
        `Reading chapter ${chapterIndex + 1} of ${chapters.length}\u2026`,
        chapter.title || "Chapter",
        state.auto.total ? sectionNumber / state.auto.total : 0
      );
      const extract = await api(
        `/api/documents/${encodeURIComponent(doc.id)}/extract?${params.toString()}`,
        { signal: controller.signal }
      );
      if (state.auto.cancelled) break;
      if (extract.truncated) {
        toast(
          `\u201c${chapter.title || "A chapter"}\u201d is very large \u2014 only the first ` +
            `${extract.chunks.length} sections were processed.`,
          "error",
          8000
        );
      }
      if (!extract.chunks || !extract.chunks.length) continue;

      for (let index = 0; index < extract.chunks.length; index += 1) {
        if (state.auto.cancelled) break;
        if (!state.doc || state.doc.id !== doc.id) {
          toast("The file changed, so the rest of this run was stopped.", "error", 9000);
          state.auto.cancelled = true;
          break;
        }
        const chunk = extract.chunks[index];
        sectionNumber += 1;
        processedChunks += 1;
        state.auto.total = Math.max(state.auto.total, sectionNumber);
        showAutoPanel(
          `Chapter ${chapterIndex + 1}/${chapters.length} \u00b7 ` +
            `section ${index + 1}/${extract.chunks.length}`,
          `${chapter.title || "Chapter"} \u00b7 ${chunk.label} \u00b7 ` +
            `${state.auto.cards} card${state.auto.cards === 1 ? "" : "s"} so far`,
          state.auto.total
            ? Math.min(1, (sectionNumber - 1) / state.auto.total)
            : 0
        );

        const data = await api("/api/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          signal: controller.signal,
          body: JSON.stringify({
            text: chunk.text,
            mode,
            count: null,
            filename: doc.filename,
            page: chunk.label,
            whole_file: true,
            strict: Boolean(state.strict),
            style: state.style,
          }),
        }).catch((error) => {
          if (error.name === "AbortError" || state.auto.cancelled) throw error;
          if (
            /api key|insufficient balance|rate-limit|401|402|429/i.test(
              error.message
            )
          ) {
            throw error;
          }
          failedSections += 1;
          toast(
            `Skipped ${chunk.label}: ${error.message} You can run the file again to retry it.`,
            "error",
            8000
          );
          return null;
        });
        if (!data) continue;
        if (state.auto.cancelled) break;

        const chunkPages = Array.isArray(chunk.pages) && chunk.pages.length >= 2
          ? [chunk.pages[0] - 1, chunk.pages[1] - 1]
          : [];
        const chapterPath = Array.isArray(chapter.path) ? chapter.path : [];
        const deckPath = [sourceTitle, ...chapterPath].filter(Boolean);
        const sourceTemplate =
          doc.kind === "transcript"
            ? {
                kind: "transcript",
                label: chunk.label,
                file: doc.filename,
                location: [],
                segments: Array.isArray(chunk.segments) ? chunk.segments : [],
                quote: "",
                sourceTitle,
                chapterPath,
                chapterTitle: chapter.title || "",
                deckPath,
              }
            : {
                kind: "chunk",
                label: chunk.label,
                file: doc.filename,
                location: [],
                pages: chunkPages,
                quote: "",
                sourceTitle,
                chapterPath,
                chapterTitle: chapter.title || "",
                deckPath,
              };
        const added = addGeneratedCards(data.cards || [], mode, sourceTemplate);
        state.auto.cards += added;
        if (added) renderCards();

        showAutoPanel(
          `Chapter ${chapterIndex + 1}/${chapters.length} \u00b7 ` +
            `section ${index + 1}/${extract.chunks.length}`,
          `${chapter.title || "Chapter"} \u00b7 ${chunk.label} \u00b7 ` +
            `${state.auto.cards} card${state.auto.cards === 1 ? "" : "s"} so far`,
          state.auto.total
            ? Math.min(1, sectionNumber / state.auto.total)
            : 0
        );
      }
    }

    if (!processedChunks) {
      toast(
        doc.kind === "transcript"
          ? "No readable transcript text was found."
          : "No readable text or tables found in this file.",
        "error"
      );
      finishAuto(
        "Nothing to generate",
        doc.kind === "transcript"
          ? "No readable transcript text was found."
          : "No selectable text or tables were found in the file.",
        "error"
      );
      return;
    }

    if (state.auto.cancelled) {
      finishAuto(
        `Stopped \u00b7 ${state.auto.cards} cards kept`,
        "Review them below, or run the whole file again.",
        "info"
      );
      if (state.auto.cards) {
        toast(`Stopped after ${state.auto.cards} cards.`, "info");
      }
    } else if (failedSections && failedSections === processedChunks) {
      finishAuto(
        "Generation failed",
        "No section produced cards. Check the DeepSeek error and try again.",
        "error"
      );
    } else {
      const scope =
        chapters.length > 1
          ? ` across ${chapters.length} chapters`
          : "";
      const failedNote = failedSections
        ? ` ${failedSections} section${failedSections === 1 ? "" : "s"} failed; run the file again to retry.`
        : " Review the teal highlights for lines without a card.";
      finishAuto(
        `Finished \u00b7 ${state.auto.cards} cards`,
        `Review, edit, then send to Anki.${failedNote}`,
        failedSections ? "info" : "success"
      );
      toast(
        `Generated ${state.auto.cards} card${state.auto.cards === 1 ? "" : "s"}${scope}.${failedNote}`,
        failedSections ? "info" : "success",
        7000
      );
      if (state.auto.cards) {
        requestAnimationFrame(() => scrollPanelTo(els.cardsBlock));
      }
    }
  } catch (error) {
    if (error.name === "AbortError" || state.auto.cancelled) {
      finishAuto(
        `Stopped \u00b7 ${state.auto.cards} cards kept`,
        "Review them below, or run the whole file again.",
        "info"
      );
    } else {
      toast(error.message, "error", 9000);
      state.auto.error = error.message;
      finishAuto("Chapter generation stopped", error.message, "error");
      if (/api key|settings|401/i.test(error.message)) openSettings();
    }
  } finally {
    state.auto.running = false;
    state.auto.controller = null;
    setModeControlsDisabled(false);
    updateSelectionUi();
    updateAutoButton();
    updatePushLabel();
    els.autoCancel.disabled = false;
    refreshCoverage({ quiet: true }).then(() => {
      if (state.auto.cards) notifyCoverageAfterAuto();
    });
    refreshAiBalance({ quiet: true });
  }
}

/* ------------------------------------------------------------------ */
/* chapters on disk                                                   */
/* ------------------------------------------------------------------ */

async function openFolder(path) {
  try {
    await api("/api/reveal", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path }),
    });
  } catch (error) {
    toast(error.message, "error", 7000);
  }
}

/* Write the same split the model gets — one file per chapter — to disk, so a
   book can also be fed to an LLM outside Anki Scribe. */
async function saveChapters() {
  if (!state.doc || state.savingChapters) return;
  if (state.auto.running || state.generating) {
    toast("Wait for the current run to finish first.", "error");
    return;
  }
  const docId = state.doc.id;
  state.savingChapters = true;
  const original = els.splitLabel.textContent;
  els.splitLabel.textContent = "Writing chapters\u2026";
  updateAutoButton();
  try {
    const data = await api(`/api/documents/${encodeURIComponent(docId)}/split`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    });
    if (data.plan) state.chapterPlan = data.plan;
    const count = Number(data.chapterCount) || 0;
    toast(
      `${count} chapter${count === 1 ? "" : "s"} saved to ${data.folder}`,
      "success",
      12000,
      { label: "Open folder", run: () => openFolder(data.folder) }
    );
  } catch (error) {
    toast(error.message, "error", 9000);
  } finally {
    state.savingChapters = false;
    els.splitLabel.textContent = original;
    updateAutoButton();
  }
}

/* ------------------------------------------------------------------ */
/* cards                                                              */
/* ------------------------------------------------------------------ */
