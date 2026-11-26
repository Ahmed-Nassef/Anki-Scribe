"use strict";

/* Application bootstrap: DOM references, startup and periodic checks. */

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}

async function init() {
  [
    "ankiStatus", "ankiLabel", "openBtn", "settingsBtn", "docBar", "docName",
    "aiBalanceStatus", "aiBalanceLabel", "settingsBalance", "settingsBalanceDetail",
    "refreshBalanceBtn",
    "coverageBlock", "coverageTitle", "coveragePercent", "coveragePages",
    "coverageBar", "coverageNote", "coverageCheckBtn", "coverageDialog",
    "coverageDialogSummary", "coverageSummary", "coveragePageList",
    "closeCoverage", "closeCoverageBtn",
    "pagePill", "prevPage", "nextPage", "stageToolbar", "scroller", "emptyState",
    "chooseBtn", "pages", "uploading", "uploadText",
    "zoomOut", "zoomIn", "zoomLabel", "fitBtn", "figureBtn", "selectionMeta", "clearSelection",
    "hideAnswersBtn", "hideAnswersLabel", "hideAnswersCount", "hideSelectionBtn",
    "revealAnswersBtn", "clearMasksBtn", "toolbarHint", "aiAnswersBtn", "aiAnswersLabel",
    "answerLegend",
    "selectionText", "charCount", "charLimit", "modeToggle", "cardCount",
    "generateBtn", "generateLabel", "generateCancel", "keyBanner", "bannerSettings", "cardsBlock",
    "cardsMeta", "clearCards", "cardsList", "pushBar", "deckInput", "deckOptions",
    "deckFieldLabel", "undoBtn", "clearHistory",
    "pushDialog", "pushDialogSummary", "pushDialogDetail", "pushSendNew",
    "pushSendAll", "pushSendAnyway", "pushCancel", "closePush",
    "sheetRow", "sheetHint", "studyBtn", "exportPdfBtn", "exportHtmlBtn", "planBtn",
    "planDialog", "planForm", "closePlan", "planCancel", "planRun", "planCopy",
    "planDeadline", "planCards", "planCardsHint", "planMinutes", "planBuffer",
    "planRetention", "planRetentionValue", "planRating", "planNewSeconds",
    "planReviewSeconds", "planResult", "planSubtitle", "planNote",
    "triageBtn", "triageDialog", "triageTitle", "closeTriage",
    "triageSourceLabel", "triageLocate", "triageQuote", "triageQuestion",
    "triageAnswerWrap", "triageAnswer", "triageDetail", "triageMeta",
    "triageReject", "triageReveal", "triageAccept", "triageCounter", "triageBar",
    "triageRewrite",
    "riskBtn", "strictToggle", "styleSelect",
    "objectivesPanel", "objectivesMeta", "objectivesScore", "objectivesList",
    "studyDialog", "studyBody", "studyTitle", "studySection", "studyCounter",
    "studyQuestion", "studyAnswer", "studyAnswerText", "studyDetail",
    "studyReveal", "studyRevealLabel", "studyRevealHint", "studyPrev",
    "studyNext", "studyBar", "closeStudy",
    "refreshDecks", "extraTags", "pushBtn", "pushLabel", "pushStatus", "panelScroll",
    "browseDecksBtn", "renameDeckBtn", "newSubdeckBtn", "deckDialog", "deckForm",
    "closeDecks", "cancelDecks", "deckSearch", "deckList", "deckSelectedLabel",
    "deckChildField", "deckChildSelect", "deckPathInput", "deckExact", "deckModeHint",
    "subdeckName", "subdeckPathPreview", "createSubdeckBtn", "useDeckBtn",
    "libraryBtn", "libraryCount", "emptyLibraryBtn", "libraryDialog", "libraryForm",
    "closeLibrary", "libraryClose", "libraryAddBtn", "libraryNewGroupBtn",
    "librarySearch", "libraryGroups", "libraryPathInput", "libraryPathGroup",
    "libraryPathAdd", "librarySelectAllBtn", "libraryBatchBtn",
    "autoDocBtn", "autoPanel", "autoStatus", "autoBar", "autoDetail", "autoCancel",
    "autoSpinner", "autoBadge", "splitDocBtn", "splitLabel", "splitBadge", "imageFileInput",
    "settingsDialog", "settingsForm", "closeSettings", "cancelSettings",
    "apiKeyInput", "keyState", "clearKey", "baseUrlInput", "modelInput",
    "ankiUrlInput", "defaultDeckInput", "defaultTagsInput", "saveSettings", "toasts",
    "diagnosticsBtn",
  ].forEach((id) => { els[id] = $(id); });

  bindEvents();
  updateDeckModeLabel();
  if (els.strictToggle) els.strictToggle.checked = Boolean(state.strict);
  if (els.styleSelect) els.styleSelect.value = state.style;
  renderCards();
  updateSelectionUi();
  updateDeckActions();
  updateUndoButton();

  const resize = new ResizeObserver(debounce(() => applyPageWidth(), 100));
  resize.observe(els.scroller);

  await loadSettings();
  refreshAiBalance({ quiet: true });
  const ankiCheck = checkAnki({ quiet: true });
  await restoreLastFile();
  await ankiCheck;

  setInterval(() => checkAnki({ quiet: true }), 60000);
}
