"use strict";

/* Settings and DeepSeek balance */

/* ------------------------------------------------------------------ */
/* DeepSeek balance                                                    */
/* ------------------------------------------------------------------ */

function balanceSymbol(currency) {
  if (currency === "CNY") return "\u00a5";
  if (currency === "USD") return "$";
  return "";
}

function formatBalanceAmount(value, currency) {
  const amount = Number(value);
  const symbol = balanceSymbol(currency);
  if (Number.isFinite(amount)) return `${symbol}${amount.toFixed(2)}`;
  return `${value || ""}${symbol ? "" : ` ${currency || ""}`}`.trim();
}

function balanceSummary(data) {
  const balances = data && Array.isArray(data.balances) ? data.balances : [];
  return balances
    .map(
      (item) =>
        `${item.currency} ${item.total} (granted ${item.granted}, topped up ${item.toppedUp})`
    )
    .join(" \u00b7 ");
}

function renderAiBalance() {
  const hasKey = Boolean(state.settings.has_key);
  const balance = state.aiBalance;
  els.aiBalanceStatus.classList.remove("ok", "low", "off", "checking");

  if (!hasKey) {
    els.aiBalanceStatus.classList.add("off");
    els.aiBalanceLabel.textContent = "AI \u2014";
    els.aiBalanceStatus.title = "Add a DeepSeek API key to see remaining credit";
    els.settingsBalance.textContent = "\u2014";
    els.settingsBalanceDetail.textContent = "Add a key to check remaining credit.";
    return;
  }

  if (balance.loading) {
    els.aiBalanceStatus.classList.add("checking");
    els.aiBalanceLabel.textContent = "AI \u2026";
    els.aiBalanceStatus.title = "Checking DeepSeek balance\u2026";
    els.settingsBalance.textContent = "\u2026";
    els.settingsBalanceDetail.textContent = "Checking DeepSeek balance\u2026";
    return;
  }

  if (balance.error) {
    els.aiBalanceStatus.classList.add("off");
    els.aiBalanceLabel.textContent = "AI ?";
    els.aiBalanceStatus.title = balance.error;
    els.settingsBalance.textContent = "\u2014";
    els.settingsBalanceDetail.textContent = balance.error;
    return;
  }

  const data = balance.data;
  const balances = data && Array.isArray(data.balances) ? data.balances : [];
  if (!balances.length) {
    els.aiBalanceStatus.classList.add("off");
    els.aiBalanceLabel.textContent = "AI ?";
    els.aiBalanceStatus.title = "No balance information returned.";
    els.settingsBalance.textContent = "\u2014";
    els.settingsBalanceDetail.textContent = "No balance information returned.";
    return;
  }

  const primary = balances[0];
  const low = !data.isAvailable || Number(primary.total) <= 0;
  els.aiBalanceStatus.classList.add(low ? "low" : "ok");
  els.aiBalanceLabel.textContent = formatBalanceAmount(primary.total, primary.currency);
  const summary = balanceSummary(data);
  els.aiBalanceStatus.title =
    `DeepSeek balance: ${summary}` +
    (data.isAvailable ? "" : " \u00b7 insufficient for API calls");
  els.settingsBalance.textContent = formatBalanceAmount(primary.total, primary.currency);
  els.settingsBalanceDetail.textContent =
    summary + (data.isAvailable ? "" : " \u00b7 Balance is too low for API calls.");
}

async function refreshAiBalance({ quiet = true, announce = false } = {}) {
  if (!state.settings.has_key) {
    state.aiBalance = { loading: false, data: null, error: "" };
    renderAiBalance();
    return;
  }
  if (state.aiBalance.loading) return;

  state.aiBalance = { loading: true, data: null, error: "" };
  renderAiBalance();
  try {
    const data = await api("/api/ai/balance");
    state.aiBalance = { loading: false, data, error: "" };
    renderAiBalance();
    if (announce) {
      const summary = balanceSummary(data);
      toast(`DeepSeek balance: ${summary || "unknown"}.`, "success", 7000);
    }
  } catch (error) {
    state.aiBalance = { loading: false, data: null, error: error.message };
    renderAiBalance();
    if (!quiet) toast(error.message, "error", 9000);
  }
}

/* ------------------------------------------------------------------ */
/* settings                                                           */
/* ------------------------------------------------------------------ */

async function loadSettings() {
  try {
    state.settings = await api("/api/settings");
  } catch (error) {
    toast(`Couldn't load settings: ${error.message}`, "error");
  }
  if (!els.deckInput.value.trim()) {
    els.deckInput.value = state.settings.default_deck || "Anki Scribe";
  }
  updateDeckActions();
  updateKeyBanner();
}

function updateKeyBanner() {
  els.keyBanner.hidden = Boolean(state.settings.has_key);
}

function openSettings() {
  const settings = state.settings;
  els.apiKeyInput.value = "";
  els.apiKeyInput.placeholder = settings.has_key
    ? `Saved key ending ${settings.key_hint || "\u2026"}`
    : "sk-\u2026";
  els.keyState.textContent = settings.has_key ? "saved" : "not set";
  els.clearKey.checked = false;
  els.baseUrlInput.value = settings.base_url || "";
  els.modelInput.value = settings.model || "";
  els.ankiUrlInput.value = settings.anki_url || "";
  els.defaultDeckInput.value = settings.default_deck || "";
  els.defaultTagsInput.value = settings.default_tags || "";
  renderAiBalance();
  if (state.settings.has_key) refreshAiBalance({ quiet: true });
  if (!els.settingsDialog.open) els.settingsDialog.showModal();
  setTimeout(() => els.apiKeyInput.focus(), 40);
}

async function saveSettings(event) {
  event.preventDefault();
  const oldDefault = state.settings.default_deck;
  const payload = {
    base_url: els.baseUrlInput.value.trim(),
    model: els.modelInput.value.trim(),
    anki_url: els.ankiUrlInput.value.trim(),
    default_deck: els.defaultDeckInput.value.trim(),
    default_tags: els.defaultTagsInput.value,
  };
  const key = els.apiKeyInput.value.trim();
  if (key) payload.api_key = key;
  if (els.clearKey.checked) payload.clear_api_key = true;

  els.saveSettings.disabled = true;
  try {
    state.settings = await api("/api/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    els.settingsDialog.close();
    toast("Settings saved.", "success");
    updateKeyBanner();
    refreshAiBalance({ quiet: true });
    const currentDeck = els.deckInput.value.trim();
    if (!currentDeck || currentDeck === oldDefault) {
      els.deckInput.value = state.settings.default_deck;
    }
    checkAnki({ quiet: true });
  } catch (error) {
    toast(error.message, "error", 7000);
  } finally {
    els.saveSettings.disabled = false;
  }
}
