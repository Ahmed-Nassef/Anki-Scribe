"use strict";

/* Distraction-free study mode.
 *
 * The normal screen is built for generating cards: a side panel, a toolbar,
 * answer controls and a pager. This mode strips all of that away and keeps only
 * the pages, a small heads-up display and keyboard-first navigation. */

function studyPageCount() {
  if (!state.doc) return 0;
  return Number(state.doc.pageCount || state.doc.segmentCount || state.models.size || 0);
}

function studyTyping(target) {
  if (!target) return false;
  const tag = String(target.tagName || "").toLowerCase();
  return (
    tag === "input" ||
    tag === "textarea" ||
    tag === "select" ||
    Boolean(target.isContentEditable)
  );
}

function updateStudyHud() {
  if (!els.studyHud || !state.focus.active) return;
  const count = studyPageCount();
  const page = Math.min(Math.max(0, Number(state.activePage) || 0), Math.max(0, count - 1));
  if (els.studyDocTitle) {
    els.studyDocTitle.textContent = state.doc?.filename || "Study mode";
  }
  if (els.studyPage) els.studyPage.textContent = `${count ? page + 1 : 0} / ${count}`;
  const answers = typeof answerMaskCount === "function" ? answerMaskCount() : 0;
  const revealed =
    typeof revealedAnswerCount === "function" ? revealedAnswerCount() : 0;
  if (els.studyAnswersMeta) {
    els.studyAnswersMeta.textContent = state.doc?.kind === "transcript"
      ? "Transcript"
      : answers
        ? `${answers} hidden answer${answers === 1 ? "" : "s"}`
        : "No hidden answers";
  }
  if (els.studyToggleAnswers) {
    els.studyToggleAnswers.disabled = state.doc?.kind === "transcript" || answers === 0;
    els.studyToggleAnswers.textContent = revealed > 0 ? "Hide answers" : "Reveal answers";
    els.studyToggleAnswers.classList.toggle("is-active", revealed > 0);
  }
  if (els.focusPrev) els.focusPrev.disabled = page <= 0;
  if (els.focusNext) els.focusNext.disabled = !count || page >= count - 1;
  if (els.studyProgressBar) {
    els.studyProgressBar.style.width = count
      ? `${Math.round(((page + 1) / count) * 100)}%`
      : "0%";
  }
}

function enterStudyMode() {
  if (state.focus.active) return;
  if (!state.doc) {
    toast("Open a file first.", "info", 3000);
    return;
  }
  if (document.querySelector("dialog[open]")) {
    toast("Close the open dialog first.", "info", 3000);
    return;
  }
  state.focus.active = true;
  state.focus.previousAnswers = Boolean(state.answers.active);
  document.body.classList.add("is-studying");
  if (els.studyHud) els.studyHud.hidden = false;
  if (els.studyHelp) els.studyHelp.hidden = true;
  if (state.doc.kind !== "transcript") {
    // Force a refresh even when the persisted preference was already on: the
    // document may have loaded before its cards/masks finished restoring.
    setHideAnswers(true, { persist: false });
  }
  updateStudyHud();
  if (typeof applyPageWidth === "function") applyPageWidth();
  const model = state.models.get(state.activePage);
  if (model) scrollViewerTo(model.el);
}

function exitStudyMode({ restoreAnswers = true } = {}) {
  if (!state.focus.active) return;
  state.focus.active = false;
  document.body.classList.remove("is-studying");
  if (els.studyHud) els.studyHud.hidden = true;
  if (els.studyHelp) els.studyHelp.hidden = true;
  if (document.fullscreenElement && document.exitFullscreen) {
    document.exitFullscreen().catch(() => {});
  }
  if (restoreAnswers) {
    setHideAnswers(Boolean(state.focus.previousAnswers), { persist: false });
  }
  if (typeof applyPageWidth === "function") applyPageWidth();
}

function toggleStudyMode() {
  if (state.focus.active) exitStudyMode();
  else enterStudyMode();
}

function studyNextPage() {
  const count = studyPageCount();
  const page = Number(state.activePage) || 0;
  if (page >= count - 1) return;
  goToPage(page + 1);
  updateStudyHud();
}

function studyPreviousPage() {
  const page = Number(state.activePage) || 0;
  if (page <= 0) return;
  goToPage(page - 1);
  updateStudyHud();
}

function toggleStudyAnswers() {
  if (!state.doc || state.doc.kind === "transcript") return;
  if (revealedAnswerCount() > 0) hideAllAnswerMasks();
  else revealAllAnswerMasks();
  updateStudyHud();
}

function toggleStudyHelp(force) {
  if (!els.studyHelp) return;
  const show = typeof force === "boolean" ? force : els.studyHelp.hidden;
  els.studyHelp.hidden = !show;
  if (show && els.studyHelpClose) els.studyHelpClose.focus();
}

async function toggleStudyFullscreen() {
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else if (document.documentElement.requestFullscreen) {
      await document.documentElement.requestFullscreen();
    }
  } catch (error) {
    toast(`Fullscreen isn't available: ${error.message}`, "info", 4000);
  }
}

function bindFocusEvents() {
  if (els.studyModeBtn) els.studyModeBtn.addEventListener("click", enterStudyMode);
  if (els.studyQuizBtn) {
    els.studyQuizBtn.addEventListener("click", () => {
      if (typeof openStudy === "function") openStudy();
    });
  }
  if (els.studyExit) els.studyExit.addEventListener("click", () => exitStudyMode());
  if (els.focusPrev) els.focusPrev.addEventListener("click", studyPreviousPage);
  if (els.focusNext) els.focusNext.addEventListener("click", studyNextPage);
  if (els.studyToggleAnswers) {
    els.studyToggleAnswers.addEventListener("click", toggleStudyAnswers);
  }
  if (els.studyHelpBtn) {
    els.studyHelpBtn.addEventListener("click", () => toggleStudyHelp());
  }
  if (els.studyHelpClose) {
    els.studyHelpClose.addEventListener("click", () => toggleStudyHelp(false));
  }
  if (els.studyFullscreen) {
    els.studyFullscreen.addEventListener("click", toggleStudyFullscreen);
  }
  if (els.studyHelp) {
    els.studyHelp.addEventListener("click", (event) => {
      if (event.target === els.studyHelp) toggleStudyHelp(false);
    });
  }

  document.addEventListener(
    "keydown",
    (event) => {
      if (event.defaultPrevented) return;
      const typing = studyTyping(event.target);
      if (!state.focus.active) {
        if (
          !typing &&
          !event.ctrlKey &&
          !event.metaKey &&
          !event.altKey &&
          event.key.toLowerCase() === "f" &&
          !document.querySelector("dialog[open]") &&
          state.doc
        ) {
          event.preventDefault();
          enterStudyMode();
        }
        return;
      }
      if (studyTyping(event.target)) return;
      if (els.studyHelp && !els.studyHelp.hidden) {
        if (event.key === "Escape" || event.key === "?") {
          event.preventDefault();
          event.stopPropagation();
          toggleStudyHelp(false);
        }
        return;
      }
      if (document.querySelector("dialog[open]")) return;

      const key = event.key;
      if (key === "Escape" || key.toLowerCase() === "f") {
        event.preventDefault();
        event.stopPropagation();
        exitStudyMode();
      } else if (key === "ArrowRight" || key === "PageDown" || key.toLowerCase() === "j") {
        event.preventDefault();
        event.stopPropagation();
        studyNextPage();
      } else if (key === "ArrowLeft" || key === "PageUp" || key.toLowerCase() === "k") {
        event.preventDefault();
        event.stopPropagation();
        studyPreviousPage();
      } else if (key === " " || key === "Spacebar") {
        event.preventDefault();
        event.stopPropagation();
        toggleStudyAnswers();
      } else if (key.toLowerCase() === "r") {
        event.preventDefault();
        event.stopPropagation();
        revealAllAnswerMasks();
        updateStudyHud();
      } else if (key.toLowerCase() === "h") {
        event.preventDefault();
        event.stopPropagation();
        hideAllAnswerMasks();
        updateStudyHud();
      } else if (key === "?") {
        event.preventDefault();
        event.stopPropagation();
        toggleStudyHelp(true);
      }
    },
    true
  );
}
