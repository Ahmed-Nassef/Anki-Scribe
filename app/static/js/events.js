"use strict";

/* DOM event wiring */

/* ------------------------------------------------------------------ */
/* events                                                             */
/* ------------------------------------------------------------------ */

function bindEvents() {
  document.querySelectorAll("dialog").forEach((dialog) => {
    dialog.addEventListener("close", () => {
      if (els.toasts.parentElement !== dialog) return;
      const open = Array.from(document.querySelectorAll("dialog[open]")).pop();
      (open || document.body).appendChild(els.toasts);
    });
  });

  els.openBtn.addEventListener("click", openFilePicker);
  els.chooseBtn.addEventListener("click", openFilePicker);
  els.emptyLibraryBtn.addEventListener("click", openLibraryDialog);
  els.libraryBtn.addEventListener("click", openLibraryDialog);
  els.closeLibrary.addEventListener("click", () => els.libraryDialog.close());
  els.libraryClose.addEventListener("click", () => els.libraryDialog.close());
  els.libraryForm.addEventListener("submit", (event) => event.preventDefault());
  els.libraryDialog.addEventListener("click", (event) => {
    if (event.target === els.libraryDialog) els.libraryDialog.close();
  });
  els.librarySearch.addEventListener("input", renderLibrary);
  els.libraryAddBtn.addEventListener("click", () => addLibraryFiles(null));
  els.libraryNewGroupBtn.addEventListener("click", createLibraryGroup);
  els.librarySelectAllBtn.addEventListener("click", toggleLibrarySelection);
  els.libraryBatchBtn.addEventListener("click", runLibraryBatch);
  els.libraryPlanBtn.addEventListener("click", planSelectedLibraryFiles);
  els.libraryPathAdd.addEventListener("click", addLibraryPath);
  els.libraryPathInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      addLibraryPath();
    }
  });
  els.libraryGroups.addEventListener("click", handleLibraryClick);
  els.libraryGroups.addEventListener("change", handleLibraryChange);
  els.libraryGroups.addEventListener("dragstart", handleLibraryDragStart);
  els.libraryGroups.addEventListener("dragover", handleLibraryDragOver);
  els.libraryGroups.addEventListener("dragleave", handleLibraryDragLeave);
  els.libraryGroups.addEventListener("drop", handleLibraryDrop);
  els.libraryGroups.addEventListener("dragend", handleLibraryDragEnd);

  els.settingsBtn.addEventListener("click", openSettings);
  els.bannerSettings.addEventListener("click", openSettings);
  els.diagnosticsBtn.addEventListener("click", () => {
    const link = document.createElement("a");
    link.href = "/api/diagnostics/bundle";
    link.download = "anki-scribe-diagnostics.zip";
    document.body.appendChild(link);
    link.click();
    link.remove();
  });
  els.closeSettings.addEventListener("click", () => els.settingsDialog.close());
  els.cancelSettings.addEventListener("click", () => els.settingsDialog.close());
  els.settingsForm.addEventListener("submit", saveSettings);
  els.settingsDialog.addEventListener("click", (event) => {
    if (event.target === els.settingsDialog) els.settingsDialog.close();
  });

  els.ankiStatus.addEventListener("click", () => checkAnki({ quiet: false }));
  els.aiBalanceStatus.addEventListener("click", () => {
    if (!state.settings.has_key) {
      openSettings();
      return;
    }
    refreshAiBalance({ quiet: false, announce: true });
  });
  els.refreshBalanceBtn.addEventListener("click", () =>
    refreshAiBalance({ quiet: false })
  );
  els.refreshDecks.addEventListener("click", async () => {
    await checkAnki({ quiet: true });
    if (state.anki.connected) {
      toast(`Anki connected \u2014 ${state.anki.decks.length} decks found.`, "success");
    } else {
      toast(state.anki.message || "Anki isn't reachable.", "error", 8000);
    }
  });
  els.deckInput.addEventListener("input", () => {
    updateCardDeckLabels();
    if (state.anki.connected) {
      const deck = els.deckInput.value.trim() || state.settings.default_deck;
      const hasChapters = state.cards.some(
        (card) => card.source && Array.isArray(card.source.chapterPath) && card.source.chapterPath.length
      );
      setPushStatus(
        state.deckMode === "exact"
          ? `Ready \u2014 cards go directly to \u201c${deck}\u201d.`
          : hasChapters
            ? `Ready \u2014 chapter decks under \u201c${deck}\u201d.`
            : `Ready \u2014 cards go to \u201c${deck}\u201d.`
      );
    }
    updateDeckActions();
  });

  els.browseDecksBtn.addEventListener("click", () => openDeckDialog(false));
  els.newSubdeckBtn.addEventListener("click", () => openDeckDialog(true));
  els.renameDeckBtn.addEventListener("click", renameCurrentDeck);
  els.closeDecks.addEventListener("click", () => els.deckDialog.close());
  els.cancelDecks.addEventListener("click", () => els.deckDialog.close());
  els.useDeckBtn.addEventListener("click", useSelectedDeck);
  els.deckSearch.addEventListener("input", renderDeckList);
  els.deckList.addEventListener("click", (event) => {
    const item = event.target.closest(".deck-item");
    if (!item) return;
    state.deckSelection = item.dataset.deck || "";
    els.deckPathInput.value = state.deckSelection;
    renderDeckList();
  });
  els.deckList.addEventListener("dblclick", (event) => {
    const item = event.target.closest(".deck-item");
    if (!item) return;
    state.deckSelection = item.dataset.deck || "";
    els.deckPathInput.value = state.deckSelection;
    useSelectedDeck();
  });
  els.deckPathInput.addEventListener("input", () => {
    state.deckSelection = els.deckPathInput.value.trim();
    renderDeckList();
  });
  els.deckChildSelect.addEventListener("change", () => {
    if (!els.deckChildSelect.value) return;
    state.deckSelection = els.deckChildSelect.value;
    els.deckPathInput.value = state.deckSelection;
    renderDeckList();
  });
  els.deckExact.addEventListener("change", updateDeckSelectionUi);
  els.subdeckName.addEventListener("input", updateSubdeckPreview);
  els.createSubdeckBtn.addEventListener("click", createSubdeck);
  els.deckForm.addEventListener("submit", (event) => event.preventDefault());
  els.deckDialog.addEventListener("click", (event) => {
    if (event.target === els.deckDialog) els.deckDialog.close();
  });

  els.modeToggle.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-mode]");
    if (button) setMode(button.dataset.mode);
  });

  els.selectionText.addEventListener("input", () => {
    state.selection.text = els.selectionText.value;
    updateSelectionUi();
  });
  els.clearSelection.addEventListener("click", clearSelection);

  els.styleSelect.addEventListener("change", () => {
    state.style = els.styleSelect.value;
    try {
      localStorage.setItem("ankiScribeStyle", state.style);
    } catch {
      // localStorage can be unavailable in locked-down browsers
    }
  });

  els.generateBtn.addEventListener("click", generateCards);
  els.generateCancel.addEventListener("click", cancelGenerate);
  els.autoDocBtn.addEventListener("click", startAutoGenerate);
  els.splitDocBtn.addEventListener("click", saveChapters);
  els.autoCancel.addEventListener("click", cancelAutoGenerate);
  els.pushBtn.addEventListener("click", pushToAnki);

  els.strictToggle.addEventListener("change", () => {
    state.strict = Boolean(els.strictToggle.checked);
    try {
      localStorage.setItem("ankiScribeStrict", state.strict ? "1" : "0");
    } catch {
      // localStorage can be unavailable in locked-down browsers
    }
    toast(
      state.strict
        ? "Strict mode: cards without a quotable source line will be dropped."
        : "Strict mode off: every card is kept, and unverified ones wear a check badge.",
      "info",
      4500
    );
  });

  els.studyBtn.addEventListener("click", openStudy);
  els.exportPdfBtn.addEventListener("click", () => exportStudy("pdf"));
  els.exportHtmlBtn.addEventListener("click", () => exportStudy("html"));
  els.closeStudy.addEventListener("click", closeStudy);
  els.studyReveal.addEventListener("click", toggleStudyAnswer);
  els.studyPrev.addEventListener("click", () => moveStudy(-1));
  els.studyNext.addEventListener("click", () => moveStudy(1));
  for (const button of document.querySelectorAll("[data-study-grade]")) {
    button.addEventListener("click", () => {
      gradeStudy(Number(button.dataset.studyGrade));
    });
  }
  if (els.studyStatsBtn) {
    els.studyStatsBtn.addEventListener("click", openStudyStats);
  }
  if (els.closeStudyStats) {
    els.closeStudyStats.addEventListener("click", closeStudyStats);
  }
  if (els.studyStatsClose) {
    els.studyStatsClose.addEventListener("click", closeStudyStats);
  }
  if (els.studyStatsDialog) {
    els.studyStatsDialog.addEventListener("click", (event) => {
      if (event.target === els.studyStatsDialog) closeStudyStats();
    });
  }
  els.studyAnswer.addEventListener("click", () => {
    const selection = window.getSelection();
    if (selection && String(selection).length) return;
    hideStudyAnswer();
  });
  els.studyDialog.addEventListener("keydown", handleStudyKey);
  els.studyDialog.addEventListener("click", (event) => {
    if (event.target === els.studyDialog) closeStudy();
  });

  els.triageBtn.addEventListener("click", () => openTriage());
  els.riskBtn.addEventListener("click", () => openTriage({ onlyRisky: true }));
  if (els.blockedBtn) els.blockedBtn.addEventListener("click", toggleBlockedFilter);
  if (els.pushBlockedBtn) els.pushBlockedBtn.addEventListener("click", pushBlockedAnyway);
  els.closeTriage.addEventListener("click", closeTriage);
  els.triageReveal.addEventListener("click", toggleTriageAnswer);
  els.triageAccept.addEventListener("click", () => triageDecide(true));
  els.triageReject.addEventListener("click", () => triageDecide(false));
  els.triageLocate.addEventListener("click", triageLocateSource);
  els.triageRewrite.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-nudge]");
    if (!button || button.disabled) return;
    regenerateTriageCard(button.dataset.nudge);
  });
  els.triageDialog.addEventListener("keydown", handleTriageKey);
  els.triageDialog.addEventListener("click", (event) => {
    if (event.target === els.triageDialog) closeTriage();
  });

  els.clearCards.addEventListener("click", clearAllCards);
  els.clearHistory.addEventListener("click", clearSentHistory);
  els.undoBtn.addEventListener("click", undoLast);

  els.pushSendNew.addEventListener("click", () => confirmPush(false));
  els.pushSendAll.addEventListener("click", () => confirmPush(true));
  if (els.pushSendAnyway) {
    els.pushSendAnyway.addEventListener("click", sendBlockedAnyway);
  }
  els.pushCancel.addEventListener("click", cancelPendingPush);
  els.closePush.addEventListener("click", cancelPendingPush);
  els.pushDialog.addEventListener("click", (event) => {
    if (event.target === els.pushDialog) cancelPendingPush();
  });

  els.coverageCheckBtn.addEventListener("click", openCoverageDialog);
  els.objectivesList.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-objective]");
    if (!button || button.disabled) return;
    generateForObjective(Number(button.dataset.objective));
  });
  els.closeCoverage.addEventListener("click", () => els.coverageDialog.close());
  els.closeCoverageBtn.addEventListener("click", () => els.coverageDialog.close());
  els.coveragePageList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-page]");
    if (!button) return;
    showCoveragePage(Number(button.dataset.page));
  });

  els.cardsList.addEventListener("input", (event) => {
    const cardEl = event.target.closest(".card");
    if (!cardEl) return;
    const card = state.cards.find((item) => item.uid === cardEl.dataset.uid);
    if (!card) return;
    const field = event.target.dataset.field;
    if (!field) return;
    if (field === "tags") {
      card.tags = splitTags(event.target.value);
    } else {
      card[field] = event.target.value;
    }
    scheduleDraftSave();
    // The PDF study page derives its masks from the card text, so an edit has
    // to invalidate them even though the list itself does not need a redraw.
    if (typeof scheduleAnswerRefresh === "function") scheduleAnswerRefresh();
  });

  els.cardsList.addEventListener("change", (event) => {
    const action = event.target.dataset.action;
    if (action === "image-side") {
      const cardEl = event.target.closest(".card");
      if (!cardEl) return;
      setCardImageSide(cardEl.dataset.uid, event.target.checked ? "front" : "back");
      return;
    }
    if (action !== "select") return;
    const cardEl = event.target.closest(".card");
    if (!cardEl) return;
    setCardSelected(cardEl.dataset.uid, event.target.checked);
    cardEl.classList.toggle("is-unselected", !event.target.checked);
    const slot = cardEl.closest(".card-slot");
    if (slot) slot.classList.toggle("is-unselected", !event.target.checked);
    updateCardsMeta();
    updatePushLabel();
    scheduleDraftSave();
  });

  els.cardsList.addEventListener("click", (event) => {
    const locateButton = event.target.closest("button[data-action='locate']");
    if (locateButton) {
      const cardEl = locateButton.closest(".card");
      if (!cardEl) return;
      const card = state.cards.find((item) => item.uid === cardEl.dataset.uid);
      if (card) locateCardSource(card, cardEl);
      return;
    }
    const imageAdd = event.target.closest("button[data-action='image-add']");
    if (imageAdd) {
      const cardEl = imageAdd.closest(".card");
      if (cardEl) openImageMenu(cardEl);
      return;
    }
    const imageCrop = event.target.closest("button[data-action='image-crop']");
    if (imageCrop) {
      const cardEl = imageCrop.closest(".card");
      if (cardEl) startImageCrop(cardEl.dataset.uid);
      return;
    }
    const imageUpload = event.target.closest("button[data-action='image-upload']");
    if (imageUpload) {
      const cardEl = imageUpload.closest(".card");
      if (cardEl) chooseCardImageFile(cardEl.dataset.uid);
      return;
    }
    const imageRemove = event.target.closest("button[data-action='image-remove']");
    if (imageRemove) {
      const cardEl = imageRemove.closest(".card");
      if (cardEl) removeCardImage(cardEl.dataset.uid);
      return;
    }
    const imageMenuCancel = event.target.closest(
      "button[data-action='image-menu-cancel']"
    );
    if (imageMenuCancel) {
      renderCards();
      return;
    }
    const button = event.target.closest("button[data-action='remove']");
    if (!button) return;
    const cardEl = button.closest(".card");
    if (!cardEl) return;
    removeCard(cardEl.dataset.uid);
  });

  if (els.imageFileInput) {
    els.imageFileInput.addEventListener("change", () => {
      const file = els.imageFileInput.files && els.imageFileInput.files[0];
      uploadCardImage(file);
    });
  }

  let sourcePointer = null;
  els.pages.addEventListener("mousedown", (event) => {
    sourcePointer = { x: event.clientX, y: event.clientY };
  });

  els.pages.addEventListener("click", (event) => {
    const sourcePointerStart = sourcePointer;
    sourcePointer = null;

    const cueButton = event.target.closest("button[data-action='select-cue']");
    if (cueButton) {
      const cue = cueButton.closest(".cue");
      if (!cue) return;
      selectTranscriptSegment(Number(cue.dataset.segment));
      return;
    }
    const chip = event.target.closest(".page-chip");
    if (chip) {
      const pageEl = chip.closest(".page");
      if (!pageEl) return;
      const model = state.models.get(Number(pageEl.dataset.page));
      if (model) selectWholePage(model);
      return;
    }
    // Clicking the teal text jumps to the card that quoted it. A drag or a
    // text selection is not a click: selecting the source must keep working.
    const source = event.target.closest(
      ".line.is-draft-source, .cue.is-draft-source"
    );
    if (!source || !sourcePointerStart) return;
    const moved =
      Math.hypot(
        event.clientX - sourcePointerStart.x,
        event.clientY - sourcePointerStart.y
      ) > 4;
    const selection = window.getSelection();
    if (moved || (selection && String(selection).trim())) return;
    jumpToCardFromLine(source);
  });

  els.prevPage.addEventListener("click", () => goToPage(state.activePage - 1));
  els.nextPage.addEventListener("click", () => goToPage(state.activePage + 1));

  els.zoomOut.addEventListener("click", () => setZoom(state.zoom - 0.1));
  els.zoomIn.addEventListener("click", () => setZoom(state.zoom + 0.1));
  els.fitBtn.addEventListener("click", () => setZoom(1));
  els.figureBtn.addEventListener("click", () => setFigureMode(!state.figureMode));
  els.pages.addEventListener("mousedown", beginFigureDrag);

  document.addEventListener("selectionchange", debounce(captureDocSelection, 180));

  document.addEventListener("keydown", (event) => {
    const typing = isTypingTarget(event.target);
    // Any open modal owns the keyboard: a shortcut must not fire behind it.
    if (document.querySelector("dialog[open]")) return;
    if (event.key === "Escape" && state.imageCrop) {
      event.preventDefault();
      cancelImageCrop();
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
      if (!els.generateBtn.disabled && !state.generating) {
        event.preventDefault();
        generateCards();
      }
      return;
    }
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z" && !typing) {
      event.preventDefault();
      if (event.shiftKey) redoLast();
      else undoLast();
      return;
    }
    if (
      state.answers.active &&
      !typing &&
      !event.ctrlKey &&
      !event.metaKey &&
      !event.altKey
    ) {
      const key = event.key.toLowerCase();
      if (key === "r") {
        event.preventDefault();
        revealAllAnswerMasks();
      } else if (key === "h") {
        event.preventDefault();
        hideAllAnswerMasks();
      }
    }
  });

  bindAnswerEvents();
  bindPlanEvents();
  if (typeof bindOcrEvents === "function") bindOcrEvents();
  if (typeof bindFocusEvents === "function") bindFocusEvents();
  if (typeof bindLeechEvents === "function") bindLeechEvents();

  window.addEventListener("dragover", (event) => {
    if (event.dataTransfer && Array.from(event.dataTransfer.types || []).includes("Files")) {
      event.preventDefault();
    }
  });
  window.addEventListener("drop", (event) => {
    if (!event.dataTransfer || !Array.from(event.dataTransfer.types || []).includes("Files")) return;
    event.preventDefault();
    toast(
      "Browsers don't share the original path for files dragged from Explorer. " +
        "Use Open file or Library \u2192 Add files to keep the location only.",
      "info",
      8000
    );
  });

  window.addEventListener("beforeunload", () => flushDrafts({ beacon: true }));
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) flushDrafts({ beacon: true });
  });
}
