"use strict";

/* Path-based file library and opening files */

function applyLibrary(data) {
  state.library = {
    groups: Array.isArray(data.groups) ? data.groups : [],
    files: Array.isArray(data.files) ? data.files : [],
    lastOpenedFileId: data.lastOpenedFileId || null,
  };
  updateLibraryCount();
  if (els.libraryDialog.open) renderLibrary();
}

function updateLibraryCount() {
  els.libraryCount.textContent = String(state.library.files.length);
}

async function loadLibrary({ quiet = false } = {}) {
  try {
    const data = await api("/api/library");
    applyLibrary(data);
  } catch (error) {
    if (!quiet) toast(`Couldn't load the library: ${error.message}`, "error", 7000);
  }
}

async function restoreLastFile() {
  await loadLibrary({ quiet: true });
  if (!state.library.lastOpenedFileId) return;
  const file = state.library.files.find(
    (item) => item.id === state.library.lastOpenedFileId
  );
  if (!file || !file.exists) return;
  await openLibraryFile(file.id, { quiet: true, skipConfirm: true });
}

async function openLibraryDialog() {
  if (state.batch.running) {
    toast("A library batch is running. Stop it first.", "error", 5000);
    return;
  }
  if (!els.libraryDialog.open) {
    els.librarySearch.value = "";
    renderLibrary();
    els.libraryDialog.showModal();
  }
  await loadLibrary({ quiet: true });
  renderLibrary();
  setTimeout(() => els.librarySearch.focus(), 40);
}

function groupName(groupId) {
  const group = state.library.groups.find((item) => item.id === groupId);
  return group ? group.name : "Unsorted";
}

function renderLibrary() {
  const query = els.librarySearch.value.trim().toLowerCase();
  const allFiles = state.library.files;
  const availableIds = new Set(
    allFiles.filter((file) => file.exists).map((file) => file.id)
  );
  state.librarySelection = new Set(
    [...state.librarySelection].filter((id) => availableIds.has(id))
  );
  updateLibraryBatchButton();
  const files = query
    ? allFiles.filter(
        (file) =>
          file.name.toLowerCase().includes(query) ||
          file.path.toLowerCase().includes(query)
      )
    : allFiles;

  els.libraryGroups.replaceChildren();
  updateLibraryPathGroupOptions();

  const userGroups = state.library.groups.filter((group) => !group.builtin);
  if (!allFiles.length && !userGroups.length) {
    const empty = document.createElement("div");
    empty.className = "library-empty";
    empty.textContent =
      "No files yet. Use Add files to remember a location — the original file stays where it is.";
    els.libraryGroups.appendChild(empty);
    return;
  }

  if (query && !files.length) {
    const empty = document.createElement("div");
    empty.className = "library-empty";
    empty.textContent = "No files match that search.";
    els.libraryGroups.appendChild(empty);
    return;
  }

  state.library.groups.forEach((group) => {
    const groupFiles = files.filter((file) => file.groupId === group.id);
    if (query && groupFiles.length === 0) return;

    const section = document.createElement("section");
    section.className = "library-group";
    section.dataset.groupId = group.id;

    const head = document.createElement("div");
    head.className = "library-group-head";

    const name = document.createElement("span");
    name.className = "library-group-name";
    name.textContent = group.name;

    const count = document.createElement("span");
    count.className = "library-group-count";
    count.textContent = String(groupFiles.length);

    const actions = document.createElement("div");
    actions.className = "library-group-actions";

    const addButton = document.createElement("button");
    addButton.type = "button";
    addButton.className = "library-icon-btn";
    addButton.dataset.action = "add-group";
    addButton.dataset.groupId = group.id;
    addButton.title = `Add files to ${group.name}`;
    addButton.textContent = "+";
    actions.appendChild(addButton);

    if (!group.builtin) {
      const renameButton = document.createElement("button");
      renameButton.type = "button";
      renameButton.className = "library-icon-btn";
      renameButton.dataset.action = "rename-group";
      renameButton.dataset.groupId = group.id;
      renameButton.title = `Rename ${group.name}`;
      renameButton.textContent = "\u270e";
      actions.appendChild(renameButton);

      const deleteButton = document.createElement("button");
      deleteButton.type = "button";
      deleteButton.className = "library-icon-btn danger";
      deleteButton.dataset.action = "delete-group";
      deleteButton.dataset.groupId = group.id;
      deleteButton.title = `Delete ${group.name}`;
      deleteButton.textContent = "\u00d7";
      actions.appendChild(deleteButton);
    }

    head.append(name, count, actions);
    section.appendChild(head);

    const list = document.createElement("div");
    list.className = "library-files";
    if (!groupFiles.length) {
      const empty = document.createElement("div");
      empty.className = "library-group-empty";
      empty.textContent = "No files in this group.";
      list.appendChild(empty);
    } else {
      groupFiles.forEach((file) => list.appendChild(buildLibraryFile(file)));
    }
    section.appendChild(list);
    els.libraryGroups.appendChild(section);
  });
}

function buildLibraryFile(file) {
  const row = document.createElement("div");
  row.className = `library-file${file.id === state.activeLibraryFileId ? " is-active" : ""}`;
  row.dataset.fileId = file.id;
  row.draggable = true;

  const grip = document.createElement("span");
  grip.className = "library-file-grip";
  grip.draggable = true;
  grip.title = "Drag to a group";
  grip.setAttribute("aria-hidden", "true");
  grip.textContent = "\u28ff";

  const check = document.createElement("input");
  check.type = "checkbox";
  check.className = "library-file-check";
  check.dataset.fileId = file.id;
  check.checked = state.librarySelection.has(file.id) && file.exists;
  check.disabled = !file.exists;
  check.title = file.exists ? `Include ${file.name} in batch generation` : "File is missing";
  check.setAttribute("aria-label", `Include ${file.name} in batch generation`);
  check.addEventListener("change", () => {
    if (check.checked) state.librarySelection.add(file.id);
    else state.librarySelection.delete(file.id);
    updateLibraryBatchButton();
  });
  check.addEventListener("mousedown", (event) => event.stopPropagation());

  const open = document.createElement("button");
  open.type = "button";
  open.className = "library-file-open";
  open.dataset.action = "open-file";
  open.dataset.fileId = file.id;
  open.title = file.exists ? `Open ${file.name}` : "File is missing from its saved location";
  open.innerHTML = `
    <svg width="15" height="15" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6.5 3.5h7l4 4v13h-11z" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
      <path d="M13.5 3.5v4h4" stroke="currentColor" stroke-width="1.6" stroke-linejoin="round"/>
    </svg>
    <span class="library-file-info">
      <span class="library-file-name"></span>
      <span class="library-file-path"></span>
      <span class="library-file-stats"></span>
    </span>
  `;
  open.querySelector(".library-file-name").textContent = file.name;
  const pathEl = open.querySelector(".library-file-path");
  pathEl.textContent = file.path;
  pathEl.title = file.path;

  const sent = Number(file.sentCount) || 0;
  const drafts = Number(file.draftCount) || 0;
  const statsEl = open.querySelector(".library-file-stats");
  const stats = [];
  if (sent) stats.push(`${sent} in Anki`);
  if (drafts) stats.push(`${drafts} draft${drafts === 1 ? "" : "s"}`);
  if (stats.length) {
    statsEl.textContent = stats.join(" \u00b7 ");
  } else {
    statsEl.remove();
  }

  if (!file.exists) {
    const missing = document.createElement("span");
    missing.className = "missing";
    missing.textContent = "Missing";
    open.appendChild(missing);
  }

  const select = document.createElement("select");
  select.dataset.action = "move-file";
  select.dataset.fileId = file.id;
  select.setAttribute("aria-label", `Group for ${file.name}`);
  state.library.groups.forEach((group) => {
    const option = document.createElement("option");
    option.value = group.id;
    option.textContent = group.name;
    select.appendChild(option);
  });
  select.value = file.groupId;

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "library-file-remove";
  remove.dataset.action = "remove-file";
  remove.dataset.fileId = file.id;
  remove.title = "Remove from library (the file stays on disk)";
  remove.setAttribute("aria-label", `Remove ${file.name} from library`);
  remove.textContent = "\u00d7";

  row.append(check, grip, open, select, remove);
  return row;
}

function updateLibraryBatchButton() {
  if (!els.libraryBatchBtn) return;
  const available = state.library.files.filter((file) => file.exists);
  const selected = available.filter((file) => state.librarySelection.has(file.id));
  const busy = state.batch.running || state.auto.running || state.generating;
  els.libraryBatchBtn.disabled = !selected.length || busy;
  els.libraryBatchBtn.textContent = selected.length
    ? `Generate selected (${selected.length})`
    : "Generate selected";
  if (els.libraryPlanBtn) {
    els.libraryPlanBtn.disabled = !selected.length || busy;
    els.libraryPlanBtn.textContent = selected.length
      ? `Plan selected (${selected.length})`
      : "Plan selected";
  }
  if (els.librarySelectAllBtn) {
    els.librarySelectAllBtn.textContent =
      available.length && selected.length === available.length ? "Clear" : "Select all";
  }
}

function toggleLibrarySelection() {
  const available = state.library.files.filter((file) => file.exists);
  const allSelected =
    available.length > 0 &&
    available.every((file) => state.librarySelection.has(file.id));
  state.librarySelection = allSelected
    ? new Set()
    : new Set(available.map((file) => file.id));
  renderLibrary();
}

function updateLibraryPathGroupOptions() {
  const current = els.libraryPathGroup.value;
  els.libraryPathGroup.replaceChildren();
  state.library.groups.forEach((group) => {
    const option = document.createElement("option");
    option.value = group.id;
    option.textContent = group.name;
    els.libraryPathGroup.appendChild(option);
  });
  if (state.library.groups.some((group) => group.id === current)) {
    els.libraryPathGroup.value = current;
  } else if (state.library.groups.length) {
    els.libraryPathGroup.value = state.library.groups[0].id;
  }
}

function handleLibraryClick(event) {
  const actionEl = event.target.closest("[data-action]");
  if (!actionEl) return;
  const action = actionEl.dataset.action;
  if (action === "open-file") {
    openLibraryFile(actionEl.dataset.fileId);
  } else if (action === "remove-file") {
    removeLibraryFile(actionEl.dataset.fileId);
  } else if (action === "add-group") {
    addLibraryFiles(actionEl.dataset.groupId);
  } else if (action === "rename-group") {
    renameLibraryGroup(actionEl.dataset.groupId);
  } else if (action === "delete-group") {
    deleteLibraryGroup(actionEl.dataset.groupId);
  }
}

function handleLibraryChange(event) {
  if (event.target.matches("select[data-action='move-file']")) {
    moveLibraryFile(event.target.dataset.fileId, event.target.value);
  }
}

function handleLibraryDragStart(event) {
  if (event.target.closest("select")) return;
  const row = event.target.closest(".library-file");
  if (!row) return;
  state.dragFileId = row.dataset.fileId;
  row.classList.add("is-dragging");
  if (!event.dataTransfer) return;
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("application/x-anki-scribe-file", row.dataset.fileId);
  event.dataTransfer.setData("text/plain", row.dataset.fileId);
}

function handleLibraryDragOver(event) {
  const section = event.target.closest(".library-group");
  if (!section) return;
  event.preventDefault();
  event.stopPropagation();
  if (event.dataTransfer) event.dataTransfer.dropEffect = "move";
  section.classList.add("is-drop-target");
}

function handleLibraryDragLeave(event) {
  const section = event.target.closest(".library-group");
  if (!section) return;
  if (event.relatedTarget && section.contains(event.relatedTarget)) return;
  section.classList.remove("is-drop-target");
}

function handleLibraryDrop(event) {
  const section = event.target.closest(".library-group");
  if (!section) return;
  event.preventDefault();
  event.stopPropagation();
  section.classList.remove("is-drop-target");
  const groupId = section.dataset.groupId;
  const transfer = event.dataTransfer;
  if (transfer && transfer.files && transfer.files.length) {
    handleExternalFileDrop(transfer, groupId);
    handleLibraryDragEnd();
    return;
  }
  const fileId =
    state.dragFileId ||
    (transfer &&
      (transfer.getData("application/x-anki-scribe-file") ||
        transfer.getData("text/plain")));
  handleLibraryDragEnd();
  if (fileId) moveLibraryFile(fileId, groupId);
}

function fileUriToPath(uri) {
  try {
    const parsed = new URL(uri);
    if (parsed.protocol !== "file:") return "";
    let path = decodeURIComponent(parsed.pathname || "");
    if (parsed.host) {
      path = `\\\\${parsed.host}${path}`;
    } else if (/^\/[A-Za-z]:/.test(path)) {
      path = path.slice(1);
    }
    return path.replace(/\//g, "\\");
  } catch {
    return "";
  }
}

function droppedFilePaths(transfer) {
  if (!transfer) return [];
  const candidates = [];
  const uriList = transfer.getData("text/uri-list") || "";
  uriList
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith("#"))
    .forEach((line) => {
      const path = fileUriToPath(line);
      if (path) candidates.push(path);
    });
  const plain = (transfer.getData("text/plain") || "").trim();
  if (/^(?:[A-Za-z]:[\\/]|\\\\)/.test(plain)) candidates.push(plain);
  return Array.from(new Set(candidates));
}

async function handleExternalFileDrop(transfer, groupId) {
  const paths = droppedFilePaths(transfer);
  if (!paths.length) {
    toast(
      "Windows doesn't share the original path when you drag a file from Explorer. " +
        "Use Add files or paste the path below so only the location is saved.",
      "info",
      10000
    );
    if (state.library.groups.some((group) => group.id === groupId)) {
      els.libraryPathGroup.value = groupId;
    }
    els.libraryAddBtn.focus();
    return;
  }
  try {
    const data = await api("/api/library/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths, group_id: groupId }),
    });
    applyLibrary(data.library || {});
    const errors = data.errors || [];
    errors.forEach((message) => toast(message, "error", 9000));
    const added = data.added || [];
    if (added.length) {
      toast(
        `Added ${added.length} file${added.length === 1 ? "" : "s"} to \u201c${groupName(groupId)}\u201d.`,
        "success"
      );
    } else if (!errors.length) {
      toast("Those files were already in the library.", "info");
    }
  } catch (error) {
    toast(error.message, "error", 9000);
  }
}

function handleLibraryDragEnd() {
  state.dragFileId = null;
  document.querySelectorAll(".library-file.is-dragging").forEach((row) => {
    row.classList.remove("is-dragging");
  });
  document.querySelectorAll(".library-group.is-drop-target").forEach((section) => {
    section.classList.remove("is-drop-target");
  });
}

async function addLibraryFiles(groupId) {
  if (state.uploading) return;
  const target = groupId && state.library.groups.some((group) => group.id === groupId)
    ? groupId
    : "unsorted";
  state.uploading = true;
  els.uploadText.textContent = "Choose files in the dialog\u2026";
  els.uploading.hidden = false;
  try {
    const data = await api("/api/library/pick", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group_id: target }),
    });
    applyLibrary(data.library || {});
    (data.errors || []).forEach((message) => toast(message, "error", 9000));
    const added = data.added || [];
    if (added.length) {
      toast(
        `Added ${added.length} file${added.length === 1 ? "" : "s"} to \u201c${groupName(target)}\u201d.`,
        "success"
      );
    }
  } catch (error) {
    toast(
      `${error.message} You can also paste a path below.`,
      "error",
      9000
    );
  } finally {
    state.uploading = false;
    els.uploading.hidden = true;
  }
}

async function addLibraryPath() {
  const raw = els.libraryPathInput.value.trim();
  if (!raw) {
    els.libraryPathInput.focus();
    return;
  }
  const paths = raw
    .split(";")
    .map((item) => item.trim())
    .filter(Boolean);
  const groupId = els.libraryPathGroup.value || "unsorted";
  try {
    const data = await api("/api/library/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths, group_id: groupId }),
    });
    applyLibrary(data.library || {});
    const errors = data.errors || [];
    errors.forEach((message) => toast(message, "error", 9000));
    const added = data.added || [];
    if (added.length) {
      els.libraryPathInput.value = "";
      toast(
        `Added ${added.length} file${added.length === 1 ? "" : "s"} to \u201c${groupName(groupId)}\u201d.`,
        "success"
      );
    } else if (!errors.length) {
      els.libraryPathInput.value = "";
      toast("Those files were already in the library.", "info");
    }
  } catch (error) {
    toast(error.message, "error", 9000);
  }
}

async function moveLibraryFile(fileId, groupId) {
  const file = state.library.files.find((item) => item.id === fileId);
  if (!file) return;
  if (file.groupId === groupId) {
    toast(`\u201c${file.name}\u201d is already in \u201c${groupName(groupId)}\u201d.`, "info", 3000);
    return;
  }
  try {
    const data = await api(`/api/library/files/${fileId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group_id: groupId }),
    });
    const destination = groupName(groupId);
    applyLibrary(data);
    toast(`Moved \u201c${file.name}\u201d to \u201c${destination}\u201d.`, "success", 3500);
  } catch (error) {
    toast(error.message, "error", 7000);
    await loadLibrary({ quiet: true });
  }
}

async function removeLibraryFile(fileId) {
  const file = state.library.files.find((item) => item.id === fileId);
  if (!file) return;
  const proceed = window.confirm(
    `Remove \u201c${file.name}\u201d from the library?\n\nThe original file stays on disk.`
  );
  if (!proceed) return;
  try {
    const data = await api(`/api/library/files/${fileId}`, { method: "DELETE" });
    if (state.activeLibraryFileId === fileId) state.activeLibraryFileId = null;
    applyLibrary(data);
    toast("Removed from the library. The file wasn't deleted.", "success");
  } catch (error) {
    toast(error.message, "error", 7000);
  }
}

async function createLibraryGroup() {
  const name = window.prompt("New group name");
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed) return;
  try {
    const data = await api("/api/library/groups", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: trimmed }),
    });
    applyLibrary(data);
    toast(`Created group \u201c${trimmed}\u201d.`, "success");
  } catch (error) {
    toast(error.message, "error", 7000);
  }
}

async function renameLibraryGroup(groupId) {
  const group = state.library.groups.find((item) => item.id === groupId);
  if (!group || group.builtin) return;
  const name = window.prompt("Rename group", group.name);
  if (name === null) return;
  const trimmed = name.trim();
  if (!trimmed || trimmed === group.name) return;
  try {
    const data = await api(`/api/library/groups/${groupId}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: trimmed }),
    });
    applyLibrary(data);
    toast(`Renamed group to \u201c${trimmed}\u201d.`, "success");
  } catch (error) {
    toast(error.message, "error", 7000);
  }
}

async function deleteLibraryGroup(groupId) {
  const group = state.library.groups.find((item) => item.id === groupId);
  if (!group || group.builtin) return;
  const proceed = window.confirm(
    `Delete the group \u201c${group.name}\u201d?\n\nIts files move to Unsorted. Original files are not touched.`
  );
  if (!proceed) return;
  try {
    const data = await api(`/api/library/groups/${groupId}`, { method: "DELETE" });
    applyLibrary(data);
    toast(`Deleted \u201c${group.name}\u201d. Files moved to Unsorted.`, "success");
  } catch (error) {
    toast(error.message, "error", 7000);
  }
}

function confirmDiscardDrafts(action) {
  if (!state.doc || !state.cards.length) return true;
  // Drafts autosave and restore on reopen, so switching files normally loses
  // nothing. Only warn when the current batch never reached disk.
  if (state.drafts.ready && state.drafts.path) return true;
  const count = state.cards.length;
  return window.confirm(
    `${action} before ${count === 1 ? "1 card has" : `${count} cards have`} been saved. Continue?`
  );
}

async function openFilePicker() {
  if (state.batch.running) {
    toast("Stop the library batch first.", "error", 5000);
    return;
  }
  if (state.uploading) return;
  if (state.auto.running) {
    toast("Stop the whole-file generation first.", "error");
    return;
  }
  if (state.generating) {
    toast("Wait for these cards to finish, or press Stop.", "error", 7000);
    return;
  }
  if (!confirmDiscardDrafts("Opening a new file")) return;

  state.uploading = true;
  els.uploadText.textContent = "Choose a file in the dialog\u2026";
  els.uploading.hidden = false;
  try {
    const data = await api("/api/library/pick", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ group_id: "unsorted" }),
    });
    applyLibrary(data.library || {});
    (data.errors || []).forEach((message) => toast(message, "error", 9000));
    const added = data.added || [];
    if (!added.length) return;
    const opened = await openLibraryFile(added[0].id, {
      alreadyBusy: true,
      skipConfirm: true,
      quiet: true,
    });
    if (!opened) return;
    toast(
      added.length === 1
        ? `Opened ${added[0].name}.`
        : `Added ${added.length} files. Opened ${added[0].name}.`,
      "success"
    );
  } catch (error) {
    toast(
      `${error.message}\n\nIf the file dialog didn't open, add the file by path from the Library.`,
      "error",
      10000
    );
  } finally {
    state.uploading = false;
    els.uploading.hidden = true;
  }
}

async function openLibraryFile(fileId, options = {}) {
  if (state.batch.running && !options.batch) {
    toast("A library batch is running. Stop it before opening another file.", "error", 6000);
    return false;
  }
  if (state.auto.running) {
    toast("Stop the whole-file generation first.", "error");
    return false;
  }
  if (state.generating) {
    toast("Wait for these cards to finish, or press Stop.", "error", 7000);
    return false;
  }
  const file = state.library.files.find((item) => item.id === fileId);
  if (!file) return false;
  if (!file.exists) {
    toast("That file is missing from its saved location.", "error", 7000);
    return false;
  }
  if (!options.skipConfirm && !confirmDiscardDrafts("Opening another file")) {
    return false;
  }

  const manageBusy = !options.alreadyBusy;
  if (manageBusy) {
    state.uploading = true;
    els.uploadText.textContent = `Opening ${file.name}\u2026`;
    els.uploading.hidden = false;
  }
  try {
    const doc = await api(`/api/library/files/${fileId}/open`, { method: "POST" });
    state.activeLibraryFileId = fileId;
    state.library.lastOpenedFileId = fileId;
    loadDocument(doc);
    if (els.libraryDialog.open) {
      renderLibrary();
      els.libraryDialog.close();
    }
    if (!options.quiet) toast(`Opened ${doc.filename}.`, "success");
    return true;
  } catch (error) {
    toast(error.message, "error", 9000);
    return false;
  } finally {
    if (manageBusy) {
      state.uploading = false;
      els.uploading.hidden = true;
    }
  }
}

/* ------------------------------------------------------------------ */
/* batch generation across library files                              */
/* ------------------------------------------------------------------ */

function batchSleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitForDraftsReady(timeout = 30_000) {
  const started = Date.now();
  while (state.drafts.loading && Date.now() - started < timeout) {
    await batchSleep(100);
  }
  return Boolean(state.drafts.ready);
}

async function planSelectedLibraryFiles() {
  if (state.batch.running || state.auto.running || state.generating) {
    toast("Finish the current generation before planning.", "info", 4000);
    return;
  }
  const selected = state.library.files.filter(
    (file) => file.exists && state.librarySelection.has(file.id)
  );
  if (!selected.length) {
    toast("Tick at least one library file first.", "info", 4000);
    return;
  }
  if (els.libraryDialog.open) els.libraryDialog.close();
  if (typeof openPlanDialog !== "function") {
    toast("The study plan isn't available in this version.", "error", 5000);
    return;
  }
  await openPlanDialog({ fileIds: selected.map((file) => file.id) });
}

async function runServerBatch(selected) {
  const job = await api("/api/batch-jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      file_ids: selected.map((file) => file.id),
      mode: state.mode,
      style: state.style,
      strict: Boolean(state.strict),
      send_to_anki: Boolean(els.libraryAutoSend && els.libraryAutoSend.checked),
      deck:
        (els.deckInput && els.deckInput.value.trim()) ||
        state.settings.default_deck ||
        "Anki Scribe",
      deck_mode: state.deckMode || "parent",
      tags: (els.extraTags && els.extraTags.value.trim()) || "",
    }),
  });
  await pollServerBatch(job, selected);
}

async function pollServerBatch(job, files) {
  state.batch.jobId = job.id;
  state.batch.total = files.length;
  let latest = job;
  while (true) {
    if (
      state.batch.cancelled &&
      ["queued", "running"].includes(latest.status)
    ) {
      try {
        latest = await api(`/api/batch-jobs/${latest.id}/cancel`, {
          method: "POST",
        });
      } catch {
        // The job may have just finished; the next GET settles it.
      }
    }
    latest = await api(`/api/batch-jobs/${latest.id}`);
    state.batch.index = Math.min(
      files.length,
      Number(latest.nextFile) + (latest.status === "running" ? 1 : 0)
    );
    state.batch.results = Array.isArray(latest.results) ? latest.results : [];
    if (["queued", "running"].includes(latest.status)) {
      const fileLabel = latest.currentFile
        ? `File ${Math.min(files.length, Number(latest.nextFile) + 1)}/${files.length} \u00b7 ${latest.currentFile}`
        : `Starting ${files.length} files\u2026`;
      showAutoPanel(
        fileLabel,
        `${latest.cards} card${latest.cards === 1 ? "" : "s"} \u00b7 ${latest.percent}%`
      );
      await batchSleep(900);
      continue;
    }
    await finishServerBatch(latest);
    return;
  }
}

async function finishServerBatch(job) {
  state.batch.running = false;
  state.auto.batch = null;
  const results = Array.isArray(job.results) ? job.results : [];
  const cards = Number(job.cards) || 0;
  const sent = Number(job.sent) || 0;
  const duplicates = Number(job.duplicates) || 0;
  const blocked = Number(job.blocked) || 0;
  const failed = results.filter((entry) => !entry.ok);
  const completed = results.filter((entry) => entry.ok).length;
  const stopped = job.status === "cancelled" || state.batch.cancelled;
  const jobError = job.status === "error" ? job.error || "The job stopped." : "";
  finishAuto(
    stopped
      ? `Batch stopped \u00b7 ${cards} card${cards === 1 ? "" : "s"}`
      : jobError
        ? "Batch stopped on an error"
        : `Batch finished \u00b7 ${cards} card${cards === 1 ? "" : "s"}`,
    (sent ? `${sent} sent to Anki \u00b7 ` : "") +
      (duplicates ? `${duplicates} duplicate${duplicates === 1 ? "" : "s"} \u00b7 ` : "") +
      (blocked ? `${blocked} blocked \u00b7 ` : "") +
      `${completed} of ${state.batch.total} file${state.batch.total === 1 ? "" : "s"} finished` +
      (failed.length ? ` \u00b7 ${failed.length} failed` : "") +
      ".",
    stopped || failed.length || jobError || blocked ? "info" : "success"
  );
  toast(
    jobError
      ? `Batch stopped: ${jobError}`
      : stopped
        ? `Batch stopped after ${cards} cards; ${sent} sent to Anki.`
        : `Generated ${cards} card${cards === 1 ? "" : "s"} from ${completed} file${completed === 1 ? "" : "s"}` +
            (sent ? `; ${sent} sent to Anki` : "") +
            (duplicates ? `; ${duplicates} duplicate${duplicates === 1 ? "" : "s"}` : "") +
            (blocked ? `; ${blocked} blocked in drafts` : "") +
            ".",
    stopped || failed.length || jobError || blocked ? "info" : "success",
    9000
  );
  state.librarySelection.clear();
  try {
    await loadLibrary({ quiet: true });
  } catch {
    // The library refresh is cosmetic after a batch.
  }
  renderLibrary();
  updateLibraryBatchButton();
  const last = results.filter((entry) => entry.ok).at(-1);
  if (last && last.fileId) {
    await openLibraryFile(last.fileId, {
      skipConfirm: true,
      quiet: true,
      alreadyBusy: false,
    });
  }
}

async function resumeServerBatch() {
  if (state.batch.running) return;
  try {
    const data = await api("/api/batch-jobs");
    const active = Array.isArray(data.active) ? data.active : [];
    if (!active.length) return;
    const job = active[0];
    state.batch = {
      running: true,
      cancelled: false,
      index: 0,
      total: job.files?.length || job.fileIds?.length || 0,
      results: [],
      jobId: job.id,
    };
    state.auto.batch = null;
    showAutoPanel("Resuming server batch\u2026", job.currentFile || "Reading progress");
    await pollServerBatch(job, job.files || []);
  } catch {
    // Older servers have no batch-job API; normal client batch still works.
  }
}

async function runLibraryBatch() {
  if (state.batch.running || state.auto.running || state.generating) {
    toast("A generation run is already in progress.", "info", 4000);
    return;
  }
  if (!state.settings.has_key) {
    toast("Add your DeepSeek API key first.", "error");
    openSettings();
    return;
  }
  const selected = state.library.files.filter(
    (file) => file.exists && state.librarySelection.has(file.id)
  );
  if (!selected.length) {
    toast("Tick at least one library file first.", "info", 4000);
    return;
  }
  const modeLabel = state.mode === "cloze" ? "cloze" : "Q&A";
  const proceed = window.confirm(
    `Generate ${modeLabel} cards for ${selected.length} file${selected.length === 1 ? "" : "s"}?\n\n` +
      selected
        .slice(0, 8)
        .map((file) => `\u2022 ${file.name}`)
        .join("\n") +
      (selected.length > 8 ? `\n\u2022 \u2026 ${selected.length - 8} more` : "") +
      "\n\nAuto reads every page and table, section by section. This uses DeepSeek credit and can take a while." +
      (els.libraryAutoSend && els.libraryAutoSend.checked
        ? "\n\nGenerated cards will be sent to Anki automatically as each file finishes."
        : "\n\nCards will stay as drafts for review before sending.")
  );
  if (!proceed) return;

  if (els.libraryDialog.open) els.libraryDialog.close();
  state.batch = {
    running: true,
    cancelled: false,
    index: 0,
    total: selected.length,
    results: [],
    jobId: null,
  };
  state.auto.batch = null;
  hideAutoPanel();
  updateLibraryBatchButton();
  showAutoPanel("Starting batch\u2026", `${selected.length} files queued`);

  // Prefer the persistent server job: it survives a closed tab and resumes
  // after an app restart. A server from before this endpoint existed returns
  // 404; in that case keep the old browser queue as a compatibility fallback.
  try {
    await saveDraftsNow();
    await runServerBatch(selected);
    return;
  } catch (error) {
    if (!/not found|404|405/i.test(error.message)) {
      state.batch.running = false;
      state.batch.jobId = null;
      finishAuto("Batch didn't start", error.message, "error");
      toast(`Couldn't start the batch: ${error.message}`, "error", 9000);
      updateLibraryBatchButton();
      return;
    }
  }

  try {
    for (let index = 0; index < selected.length; index += 1) {
      if (state.batch.cancelled) break;
      const file = selected[index];
      state.batch.index = index + 1;
      showAutoPanel(
        `Opening file ${index + 1} of ${selected.length}\u2026`,
        file.name
      );
      try {
        const opened = await openLibraryFile(file.id, {
          skipConfirm: true,
          quiet: true,
          alreadyBusy: false,
          batch: true,
        });
        if (!opened) throw new Error("The file could not be opened.");
        if (!(await waitForDraftsReady())) {
          throw new Error("Draft cards did not finish loading.");
        }
        if (state.batch.cancelled) break;
        await startAutoGenerate({
          batch: { index: index + 1, total: selected.length, file: file.name },
        });
        if (
          state.auto.error &&
          /api key|insufficient balance|401|402|429/i.test(state.auto.error)
        ) {
          throw new Error(state.auto.error);
        }
        await saveDraftsNow();
        state.batch.results.push({
          fileId: file.id,
          name: file.name,
          cards: Number(state.auto.cards) || 0,
          ok: true,
        });
      } catch (error) {
        state.batch.results.push({
          fileId: file.id,
          name: file.name,
          cards: 0,
          ok: false,
          error: error.message,
        });
        toast(`${file.name}: ${error.message}`, "error", 8000);
        if (/api key|insufficient balance|401|402|429/i.test(error.message)) {
          state.batch.cancelled = true;
        }
      }
    }
  } finally {
    state.batch.running = false;
    state.auto.batch = null;
    const results = state.batch.results || [];
    const cards = results.reduce((sum, entry) => sum + (entry.cards || 0), 0);
    const failed = results.filter((entry) => !entry.ok);
    const completed = results.filter((entry) => entry.ok).length;
    const stopped = state.batch.cancelled;
    finishAuto(
      stopped
        ? `Batch stopped \u00b7 ${cards} card${cards === 1 ? "" : "s"}`
        : `Batch finished \u00b7 ${cards} card${cards === 1 ? "" : "s"}`,
      `${completed} of ${selected.length} file${selected.length === 1 ? "" : "s"} finished` +
        (failed.length ? ` \u00b7 ${failed.length} failed` : "") +
        ".",
      stopped || failed.length ? "info" : "success"
    );
    toast(
      stopped
        ? `Batch stopped after ${cards} cards.`
        : `Generated ${cards} card${cards === 1 ? "" : "s"} from ${completed} file${completed === 1 ? "" : "s"}.` +
            (failed.length ? ` ${failed.length} failed.` : ""),
      stopped || failed.length ? "info" : "success",
      9000
    );
    state.librarySelection.clear();
    try {
      await loadLibrary({ quiet: true });
    } catch {
      // The library refresh is cosmetic after a batch.
    }
    renderLibrary();
    updateLibraryBatchButton();
  }
}
