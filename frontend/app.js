/* ============================================================
   Smart LLM Switcher - Client Application
   Inspired by Antigravity 2.0 · Clean Developer Experience
   Context-Aware Cost & Performance Routing Gateway
   ============================================================ */

"use strict";

// Helper for element selection
const $ = (id) => document.getElementById(id);
const $$ = (sel) => document.querySelectorAll(sel);

/* ============================================================
   1. Storage & State Managers
   ============================================================ */

/**
 * SettingsManager handles persistence of API keys, custom endpoints,
 * model tier overrides, and preferences in localStorage — encrypted at
 * rest with AES-GCM (WebCrypto).
 */
class SettingsManager {
  static STORAGE_KEY = "smart_llm_settings";
  static CRYPTO_KEY_NAME = "smart_llm_settings_v1";
  static _cryptoKey = null;
  static _cryptoKeyPromise = null;

  static getDefaults() {
    return {
      apiKeys: {
        gemini: "",
        groq: "",
        openrouter: "",
        openai: "",
        custom: "",
      },
      customEndpoints: {
        custom: "",
      },
      providerModels: {
        geminiTier1: "gemini-3.5-flash-lite",
        geminiTier3: "gemini-3.6-flash",
        geminiTier6: "gemini-3.8-flash",
        groqTier2: "openai/gpt-oss-20b",
        groqTier4: "qwen/qwen3.8-27b",
        groqTier5: "openai/gpt-oss-120b",
        custom: "",
      },
      preferences: {
        theme: "dark",
        strategy: "balanced",
      },
    };
  }

  static async _getCryptoKey() {
    if (this._cryptoKey) return this._cryptoKey;
    if (this._cryptoKeyPromise) return this._cryptoKeyPromise;
    this._cryptoKeyPromise = (async () => {
      try {
        let rawB64 = localStorage.getItem(this.CRYPTO_KEY_NAME);
        let raw;
        if (rawB64) {
          raw = Uint8Array.from(atob(rawB64), c => c.charCodeAt(0));
        } else {
          raw = window.crypto.getRandomValues(new Uint8Array(32));
          localStorage.setItem(this.CRYPTO_KEY_NAME, btoa(String.fromCharCode(...raw)));
        }
        this._cryptoKey = await window.crypto.subtle.importKey("raw", raw, "AES-GCM", false, ["encrypt", "decrypt"]);
        return this._cryptoKey;
      } catch (e) {
        console.warn("WebCrypto unavailable; falling back to plaintext-safe mode:", e);
        return null;
      } finally {
        this._cryptoKeyPromise = null;
      }
    })();
    return this._cryptoKeyPromise;
  }

  static async _encrypt(obj) {
    const key = await this._getCryptoKey();
    if (!key) return null;
    const iv = window.crypto.getRandomValues(new Uint8Array(12));
    const data = new TextEncoder().encode(JSON.stringify(obj));
    const ct = await window.crypto.subtle.encrypt({ name: "AES-GCM", iv }, key, data);
    const out = new Uint8Array(iv.length + ct.byteLength);
    out.set(iv, 0);
    out.set(new Uint8Array(ct), iv.length);
    return btoa(String.fromCharCode(...out));
  }

  static async _decrypt(b64) {
    const key = await this._getCryptoKey();
    if (!key) return null;
    const blob = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
    const iv = blob.slice(0, 12);
    const data = blob.slice(12);
    const pt = await window.crypto.subtle.decrypt({ name: "AES-GCM", iv }, key, data);
    return JSON.parse(new TextDecoder().decode(pt));
  }

  static _merge(parsed) {
    return {
      apiKeys: { ...this.getDefaults().apiKeys, ...(parsed.apiKeys || {}) },
      customEndpoints: { ...this.getDefaults().customEndpoints, ...(parsed.customEndpoints || {}) },
      providerModels: { ...this.getDefaults().providerModels, ...(parsed.providerModels || {}) },
      preferences: { ...this.getDefaults().preferences, ...(parsed.preferences || {}) },
    };
  }

  static async load() {
    try {
      const raw = localStorage.getItem(this.STORAGE_KEY);
      if (!raw) return this.getDefaults();
      if (raw.startsWith("enc:")) {
        const parsed = await this._decrypt(raw.slice(4));
        return parsed ? this._merge(parsed) : this.getDefaults();
      }
      const legacy = JSON.parse(raw);
      const merged = this._merge(legacy);
      await this.save(merged);
      return merged;
    } catch (e) {
      console.warn("Failed to load settings from localStorage:", e);
      return this.getDefaults();
    }
  }

  static async save(settings) {
    try {
      const enc = await this._encrypt(settings);
      localStorage.setItem(this.STORAGE_KEY, enc ? "enc:" + enc : JSON.stringify(settings));
    } catch (e) {
      console.error("Failed to save settings to localStorage:", e);
    }
  }

  static async clearKeys() {
    const settings = await this.load();
    settings.apiKeys = this.getDefaults().apiKeys;
    settings.customEndpoints = this.getDefaults().customEndpoints;
    await this.save(settings);
  }

  static async getHeaders() {
    const settings = await this.load();
    const headers = { "Content-Type": "application/json" };

    const keys = settings.apiKeys || {};
    if (keys.gemini) headers["X-Gemini-Key"] = keys.gemini.trim();
    if (keys.groq) headers["X-Groq-Key"] = keys.groq.trim();
    if (keys.openrouter) headers["X-OpenRouter-Key"] = keys.openrouter.trim();
    if (keys.openai) headers["X-OpenAI-Key"] = keys.openai.trim();
    if (keys.custom) headers["X-Custom-Key"] = keys.custom.trim();

    const customUrl = (settings.customEndpoints?.custom || "").trim();
    if (customUrl) {
      headers["X-Custom-Base-URL"] = customUrl;
      headers["X-Custom-Endpoint"] = customUrl;
    }

    const providerModels = settings.providerModels || {};
    if (providerModels.custom) headers["X-Custom-Model"] = providerModels.custom.trim();

    return headers;
  }
}

/**
 * Centralized API Fetch Helper
 */
async function apiFetch(url, options = {}) {
  const defaultHeaders = await SettingsManager.getHeaders();
  const customHeaders = options.headers || {};
  const mergedHeaders = { ...defaultHeaders, ...customHeaders };
  return fetch(url, { ...options, headers: mergedHeaders });
}

/**
 * SessionManager handles multi-session conversation history stored in localStorage.
 */
class SessionManager {
  static SESSIONS_KEY = "smart_llm_sessions";
  static ACTIVE_KEY = "smart_llm_active_session";

  constructor() {
    this.sessions = [];
    this.activeSessionId = null;
    this.load();
  }

  load() {
    try {
      const raw = localStorage.getItem(SessionManager.SESSIONS_KEY);
      this.sessions = raw ? JSON.parse(raw) : [];
      this.activeSessionId = localStorage.getItem(SessionManager.ACTIVE_KEY);

      if (!Array.isArray(this.sessions)) this.sessions = [];

      if (this.sessions.length === 0) {
        this.createSession("New Conversation", false);
      } else if (!this.activeSessionId || !this.sessions.some(s => s.id === this.activeSessionId)) {
        this.activeSessionId = this.sessions[0].id;
        this.persistActiveId();
      }
    } catch (e) {
      console.warn("Failed to load sessions from localStorage:", e);
      this.sessions = [];
      this.createSession("New Conversation", false);
    }
  }

  save() {
    try {
      localStorage.setItem(SessionManager.SESSIONS_KEY, JSON.stringify(this.sessions));
      this.persistActiveId();
    } catch (e) {
      console.error("Failed to save sessions to localStorage:", e);
    }
  }

  persistActiveId() {
    if (this.activeSessionId) {
      localStorage.setItem(SessionManager.ACTIVE_KEY, this.activeSessionId);
    }
  }

  getAll() {
    return this.sessions;
  }

  getActive() {
    return this.sessions.find(s => s.id === this.activeSessionId) || this.sessions[0];
  }

  createSession(title = "New Conversation", activate = true) {
    const newSession = {
      id: "sess_" + Date.now() + "_" + Math.random().toString(36).substring(2, 8),
      title: title,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      messages: [],
    };
    this.sessions.unshift(newSession);
    if (activate) {
      this.activeSessionId = newSession.id;
    }
    this.save();
    return newSession;
  }

  switchSession(id) {
    if (this.sessions.some(s => s.id === id)) {
      this.activeSessionId = id;
      this.persistActiveId();
      return true;
    }
    return false;
  }

  deleteSession(id) {
    this.sessions = this.sessions.filter(s => s.id !== id);
    if (this.sessions.length === 0) {
      this.createSession("New Conversation", true);
    } else if (this.activeSessionId === id) {
      this.activeSessionId = this.sessions[0].id;
      this.persistActiveId();
    }
    this.save();
  }

  renameSession(id, newTitle) {
    const s = this.sessions.find(item => item.id === id);
    if (s && newTitle.trim()) {
      s.title = newTitle.trim();
      s.updatedAt = Date.now();
      this.save();
    }
  }

  clearAll() {
    this.sessions = [];
    this.createSession("New Conversation", true);
    this.save();
  }

  addMessage(role, content, meta = {}) {
    const active = this.getActive();
    if (!active) return;

    active.messages.push({
      role,
      content,
      timestamp: Date.now(),
      meta,
    });
    active.updatedAt = Date.now();

    // Auto-title if first message
    if (role === "user" && (active.title === "New Conversation" || active.messages.length <= 2)) {
      const clean = content.trim().replace(/\n+/g, " ");
      active.title = clean.length > 32 ? clean.substring(0, 32) + "..." : clean;
    }
    this.save();
  }

  getRecentHistoryForAPI(maxTurns = 10) {
    const active = this.getActive();
    if (!active || !Array.isArray(active.messages)) return [];

    return active.messages
      .slice(-maxTurns * 2)
      .map(m => ({
        role: m.role,
        content: m.content,
      }));
  }
}

/* ============================================================
   2. Global Application State
   ============================================================ */
let sessionManager = null;
let activeAbortController = null;
let dashboardRefreshTimer = null;
let isUserScrolledUp = false;
let lastUserQuery = "";

/* ============================================================
   3. Initialization & Lifecycle
   ============================================================ */
document.addEventListener("DOMContentLoaded", async () => {
  sessionManager = new SessionManager();

  // Load and apply theme & preferences
  await applyStoredPreferences();

  // Setup DOM Event Listeners
  setupSidebarControls();
  setupCanvasNavigation();
  setupComposer();
  setupRibbonToggle();
  setupSettingsModal();
  setupInspectorModal();
  setupBenchmarkView();
  setupModelRegistryView();
  setupCodeCopyHandler();

  // Initial renders
  renderSidebarSessions();
  renderActiveSessionMessages();
  checkEngineHealth();

  // Load dynamic models in background
  loadRegistryModels();
});

/* ============================================================
   4. Theme & Preferences
   ============================================================ */
async function applyStoredPreferences() {
  const settings = await SettingsManager.load();
  const theme = settings.preferences?.theme || "dark";
  document.documentElement.setAttribute("data-theme", theme);
  updateThemeIcon(theme);

  const strat = settings.preferences?.strategy || "balanced";
  const stratSelect = $("strategy-select");
  if (stratSelect) stratSelect.value = strat;
  updateStrategyBadge(strat);
}

function updateThemeIcon(theme) {
  const icon = $("theme-icon");
  const text = $("theme-text");
  if (theme === "dark") {
    if (icon) icon.innerHTML = "<svg class='icon-sym' aria-hidden='true'><use href='#i-moon'/></svg>";
    if (text) text.textContent = "Dark Mode";
  } else {
    if (icon) icon.innerHTML = "<svg class='icon-sym' aria-hidden='true'><use href='#i-sun'/></svg>";
    if (text) text.textContent = "Light Mode";
  }
}

async function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  updateThemeIcon(next);

  const settings = await SettingsManager.load();
  settings.preferences.theme = next;
  await SettingsManager.save(settings);
}

function updateStrategyBadge(strategy) {
  const badge = $("header-strategy-badge");
  if (!badge) return;
  const label = badge.querySelector(".pill-label");
  const names = {
    balanced: "Balanced",
    lowest_cost: "Lowest Cost",
    fastest: "Fastest",
    highest_quality: "Highest Quality",
  };
  if (label) label.textContent = names[strategy] || "Balanced";
}

/* ============================================================
   5. Sidebar Controls & Session List
   ============================================================ */
function setupSidebarControls() {
  // New Chat Button
  $("new-chat-btn")?.addEventListener("click", () => {
    sessionManager.createSession("New Conversation", true);
    renderSidebarSessions();
    renderActiveSessionMessages();
    switchView("chat");
    $("query-input")?.focus();
  });

  // Sidebar Collapse / Expand
  $("sidebar-collapse-btn")?.addEventListener("click", () => {
    $("sidebar")?.classList.toggle("collapsed");
  });

  $("sidebar-open-btn")?.addEventListener("click", () => {
    const sb = $("sidebar");
    if (sb) {
      if (sb.classList.contains("collapsed")) {
        sb.classList.remove("collapsed");
      } else {
        sb.classList.toggle("mobile-open");
        $("sidebar-backdrop")?.classList.toggle("active");
      }
    }
  });

  $("sidebar-backdrop")?.addEventListener("click", () => {
    $("sidebar")?.classList.remove("mobile-open");
    $("sidebar-backdrop")?.classList.remove("active");
  });

  // Theme Toggles
  $("theme-toggle-btn")?.addEventListener("click", toggleTheme);
  $("header-theme-btn")?.addEventListener("click", toggleTheme);

  // Clear All Sessions
  $("clear-all-sessions-btn")?.addEventListener("click", () => {
    if (confirm("Are you sure you want to delete all saved conversations?")) {
      sessionManager.clearAll();
      renderSidebarSessions();
      renderActiveSessionMessages();
      showToast("All conversations cleared", "info");
    }
  });

  // Search Sessions Filter
  const searchInput = $("session-search-input");
  const clearSearchBtn = $("clear-search-btn");

  searchInput?.addEventListener("input", () => {
    const q = searchInput.value.trim().toLowerCase();
    if (q) {
      clearSearchBtn?.classList.remove("hidden");
    } else {
      clearSearchBtn?.classList.add("hidden");
    }
    renderSidebarSessions(q);
  });

  clearSearchBtn?.addEventListener("click", () => {
    if (searchInput) searchInput.value = "";
    clearSearchBtn.classList.add("hidden");
    renderSidebarSessions();
  });

  // Keyboard shortcut listener (Apple HIG & Power-User Desktop Ergonomics)
  document.addEventListener("keydown", (e) => {
    // Escape: Close any open modal
    if (e.key === "Escape") {
      const settingsModal = $("settings-modal");
      if (settingsModal && !settingsModal.classList.contains("hidden")) {
        settingsModal.classList.add("hidden");
        return;
      }
      const inspectorModal = $("inspector-modal");
      if (inspectorModal && !inspectorModal.classList.contains("hidden")) {
        inspectorModal.classList.add("hidden");
        return;
      }
    }
    // Ctrl+B / Cmd+B: Toggle sidebar
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
      e.preventDefault();
      $("sidebar")?.classList.toggle("collapsed");
    }
    // Ctrl+N / Cmd+N: New conversation
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "n") {
      e.preventDefault();
      $("new-chat-btn")?.click();
    }
    // Ctrl+, / Cmd+,: Open Settings (Canonical macOS standard)
    if ((e.metaKey || e.ctrlKey) && e.key === ",") {
      e.preventDefault();
      $("header-settings-btn")?.click();
    }
    // Ctrl+K / Cmd+K or '/': Focus composer query input (when not already typing)
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      $("query-input")?.focus();
    } else if (e.key === "/" && document.activeElement?.tagName !== "INPUT" && document.activeElement?.tagName !== "TEXTAREA") {
      e.preventDefault();
      $("query-input")?.focus();
    }
  });
}

function renderSidebarSessions(filterQuery = "") {
  const listContainer = $("session-list");
  if (!listContainer) return;

  const sessions = sessionManager.getAll();
  const activeId = sessionManager.activeSessionId;

  const filtered = filterQuery
    ? sessions.filter(s => s.title.toLowerCase().includes(filterQuery))
    : sessions;

  if ($("sessions-count-badge")) {
    $("sessions-count-badge").textContent = filtered.length.toString();
  }

  if (filtered.length === 0) {
    listContainer.innerHTML = `
      <div style="padding:12px 10px;font-size:12px;color:var(--text-muted);text-align:center;">
        ${filterQuery ? "No matching conversations" : "No conversations yet"}
      </div>
    `;
    return;
  }

  listContainer.innerHTML = filtered.map(s => {
    const isActive = s.id === activeId;
    return `
      <div class="session-item ${isActive ? 'active' : ''}" data-id="${s.id}">
        <span class="session-item-title" title="${escapeHtml(s.title)}">${escapeHtml(s.title)}</span>
        <div class="session-item-actions">
          <button class="btn-session-action rename" title="Rename" data-action="rename" data-id="${s.id}">✎</button>
          <button class="btn-session-action delete" title="Delete" data-action="delete" data-id="${s.id}">✕</button>
        </div>
      </div>
    `;
  }).join("");

  // Attach session item click handlers
  listContainer.querySelectorAll(".session-item").forEach(el => {
    el.addEventListener("click", (e) => {
      const act = e.target.closest("button");
      const id = el.dataset.id;
      if (act) {
        e.stopPropagation();
        const action = act.dataset.action;
        if (action === "delete") {
          sessionManager.deleteSession(id);
          renderSidebarSessions(filterQuery);
          renderActiveSessionMessages();
        } else if (action === "rename") {
          promptRenameSession(id);
        }
        return;
      }

      sessionManager.switchSession(id);
      renderSidebarSessions(filterQuery);
      renderActiveSessionMessages();
      switchView("chat");

      if (window.innerWidth <= 768) {
        $("sidebar")?.classList.remove("mobile-open");
        $("sidebar-backdrop")?.classList.remove("active");
      }
    });
  });
}

function promptRenameSession(id) {
  const session = sessionManager.sessions.find(s => s.id === id);
  if (!session) return;
  const newTitle = prompt("Enter conversation title:", session.title);
  if (newTitle !== null) {
    sessionManager.renameSession(id, newTitle);
    renderSidebarSessions();
    updateActiveSessionHeader();
  }
}

function updateActiveSessionHeader() {
  const active = sessionManager.getActive();
  const titleEl = $("active-session-title");
  if (titleEl && active) {
    titleEl.textContent = active.title;
  }
}

/* ============================================================
   6. Navigation Views Controller
   ============================================================ */
function setupCanvasNavigation() {
  const sidebarNavItems = $$(".sidebar-nav-item");

  sidebarNavItems.forEach(item => {
    item.addEventListener("click", () => {
      const view = item.dataset.view;
      switchView(view);
      if (window.innerWidth <= 768) {
        $("sidebar")?.classList.remove("mobile-open");
        $("sidebar-backdrop")?.classList.remove("active");
      }
    });
  });
}

function switchView(viewName) {
  $$(".view-panel").forEach(p => p.classList.remove("active"));
  $$(".sidebar-nav-item").forEach(i => i.classList.remove("active"));

  const targetPanel = $(`view-${viewName}`);
  const targetNav = $(`nav-${viewName}-btn`);

  if (targetPanel) targetPanel.classList.add("active");
  if (targetNav) targetNav.classList.add("active");

  if (viewName === "dashboard") {
    loadDashboardStats();
    startDashboardAutoRefresh();
  } else {
    stopDashboardAutoRefresh();
  }

  if (viewName === "registry") {
    loadRegistryModels();
  }
}

/* ============================================================
   7. Composer & Chat Execution
   ============================================================ */
function setupComposer() {
  const form = $("composer-form");
  const input = $("query-input");
  const strategySelect = $("strategy-select");
  const clearContextBtn = $("clear-context-btn");
  const messagesContainer = $("chat-messages");

  if (messagesContainer) {
    messagesContainer.addEventListener("scroll", () => {
      const threshold = 80;
      const distFromBottom = messagesContainer.scrollHeight - messagesContainer.scrollTop - messagesContainer.clientHeight;
      isUserScrolledUp = distFromBottom > threshold;
    });
  }

  // Auto-resize textarea
  input?.addEventListener("input", () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
  });

  // Enter or Cmd/Ctrl+Enter to send (Shift+Enter for newline)
  input?.addEventListener("keydown", (e) => {
    const isSend = (e.key === "Enter" && !e.shiftKey) || (e.key === "Enter" && (e.metaKey || e.ctrlKey));
    if (isSend && !e.isComposing) {
      e.preventDefault();
      form.requestSubmit();
    }
  });

  // Clear context in active session
  clearContextBtn?.addEventListener("click", () => {
    const active = sessionManager.getActive();
    if (active && active.messages.length > 0) {
      if (confirm("Clear memory for this session?")) {
        active.messages = [];
        sessionManager.save();
        renderActiveSessionMessages();
        showToast("Conversation memory cleared", "info");
      }
    }
  });

  // Strategy Selector change
  strategySelect?.addEventListener("change", async () => {
    const val = strategySelect.value;
    updateStrategyBadge(val);
    const settings = await SettingsManager.load();
    settings.preferences.strategy = val;
    await SettingsManager.save(settings);
  });

  // Routing Mode Selector Pills Handlers
  document.querySelectorAll(".composer-mode-pill").forEach(pill => {
    pill.addEventListener("click", async () => {
      const strat = pill.dataset.strategy;
      const modeId = pill.dataset.modeId;
      document.querySelectorAll(".composer-mode-pill").forEach(p => p.classList.toggle("active", p === pill));
      if (strategySelect && strategySelect.querySelector(`option[value="${strat}"]`)) {
        strategySelect.value = strat;
      }
      updateStrategyBadge(modeId || strat);
      try {
        const settings = await SettingsManager.load();
        settings.preferences.strategy = strat;
        await SettingsManager.save(settings);
      } catch (_) {}
    });
  });

  // Quick Prompt Suggestion Chips Handlers
  document.querySelectorAll(".composer-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const q = chip.dataset.query;
      if (input && q) {
        input.value = q;
        input.style.height = "auto";
        input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
        input.focus();
      }
    });
  });

  // Form Submit / Streaming Execution
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();

    if (activeAbortController) {
      stopGeneration();
      return;
    }

    const query = input.value.trim();
    if (!query) return;

    lastUserQuery = query;
    input.value = "";
    input.style.height = "auto";

    appendUserMessageToUI(query);
    sessionManager.addMessage("user", query);
    renderSidebarSessions();
    updateActiveSessionHeader();

    const welcome = $("welcome-hero");
    if (welcome) welcome.style.display = "none";

    const placeholder = createStreamingPlaceholder();
    const strategy = strategySelect ? strategySelect.value : "balanced";
    const historyPayload = sessionManager.getRecentHistoryForAPI(10);

    setStreamingState(true);
    updatePipelineToAnalyzing();

    let streamedText = "";
    let reasoningText = "";
    let isFirstDelta = true;

    try {
      activeAbortController = new AbortController();

      await executeStreamingChat(
        { query, history: historyPayload, strategy },
        activeAbortController.signal,
        // onAnalyzer
        (info) => {
          placeholder.updateAnalyzer(info);
          updatePipelineAnalyzerResult(info);
        },
        // onRouting
        (route) => {
          placeholder.updateRouting(route);
          updatePipelineRouting(route);
        },
        // onReasoningDelta
        (chunk) => {
          reasoningText += chunk;
          placeholder.appendReasoningDelta(reasoningText);
        },
        // onDelta
        (chunk) => {
          if (isFirstDelta) {
            placeholder.startResponse();
            isFirstDelta = false;
          }
          streamedText += chunk;
          placeholder.appendDelta(streamedText);
        },
        // onDone
        (doneData) => {
          placeholder.card.remove();
          const finalResponse = doneData.response || streamedText;
          appendAssistantResponseToUI(query, finalResponse, doneData);
          sessionManager.addMessage("assistant", finalResponse, { ...doneData, query });
          updateContextCounter();
          updatePipelineDone(doneData);
          loadDashboardStats();
        },
        // onError
        (errorMsg) => {
          placeholder.showError(errorMsg);
        }
      );
    } catch (err) {
      if (err.name === "AbortError") {
        placeholder.showStoppedState(streamedText);
        sessionManager.addMessage("assistant", streamedText || "[Generation stopped by user]", { stopped: true, query });
      } else {
        console.warn("SSE Stream failed, falling back to standard /api/chat:", err);
        try {
          const resp = await apiFetch("/api/chat", {
            method: "POST",
            body: JSON.stringify({ query, history: historyPayload, strategy }),
          });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || "Request failed");

          placeholder.card.remove();
          appendAssistantResponseToUI(query, data.response, data);
          sessionManager.addMessage("assistant", data.response, { ...data, query });
          updateContextCounter();
          updatePipelineDone(data);
          loadDashboardStats();
        } catch (postErr) {
          placeholder.showError(postErr.message);
        }
      }
    } finally {
      setStreamingState(false);
      activeAbortController = null;
      input?.focus();
    }
  });
}

function stopGeneration() {
  if (activeAbortController) {
    activeAbortController.abort();
    activeAbortController = null;
    setStreamingState(false);
    showToast("Generation stopped", "info");
  }
}

function setStreamingState(isStreaming) {
  const btn = $("send-stop-btn");
  const icon = $("send-btn-icon");
  if (!btn || !icon) return;

  if (isStreaming) {
    btn.classList.add("stop-state");
    btn.title = "Stop Generation";
    icon.innerHTML = "<svg class='icon-sym' aria-hidden='true'><use href='#i-stop'/></svg>";
  } else {
    btn.classList.remove("stop-state");
    btn.title = "Send Message (Enter)";
    icon.innerHTML = "<svg class='icon-sym' aria-hidden='true'><use href='#i-arrow-up'/></svg>";
  }
}

/* ============================================================
   8. Compact Architecture Ribbon Controller
   ============================================================ */
function setupRibbonToggle() {
  const toggleBtn = $("ribbon-toggle-btn");
  const drawer = $("ribbon-drawer");
  const arrow = $("ribbon-toggle-arrow");

  toggleBtn?.addEventListener("click", () => {
    if (!drawer) return;
    drawer.classList.toggle("collapsed");
    const isCollapsed = drawer.classList.contains("collapsed");
    if (arrow) arrow.textContent = isCollapsed ? "▾" : "▴";
  });
}

function normalizeTierKey(tier) {
  if (!tier) return "tier_1";
  const s = String(tier).toLowerCase();
  if (s.includes("tier_1") || s.includes("tier 1") || s.includes("flash-lite")) return "tier_1";
  if (s.includes("tier_2") || s.includes("tier 2") || s.includes("20b")) return "tier_2";
  if (s.includes("tier_3") || s.includes("tier 3") || s.includes("3.6")) return "tier_3";
  if (s.includes("tier_4") || s.includes("tier 4") || s.includes("qwen") || s.includes("coding")) return "tier_4";
  if (s.includes("tier_5") || s.includes("tier 5") || s.includes("120b") || s.includes("reasoning")) return "tier_5";
  if (s.includes("tier_6") || s.includes("tier 6") || s.includes("3.8") || s.includes("powerful")) return "tier_6";
  return "tier_1";
}

function formatTierDisplay(tier) {
  const norm = normalizeTierKey(tier);
  switch (norm) {
    case "tier_1": return "Tier 1: Gemini 3.5 Flash-Lite (Fast / Routine)";
    case "tier_2": return "Tier 2: Groq GPT-OSS 20B (Fast General)";
    case "tier_3": return "Tier 3: Gemini 3.6 Flash (Balanced)";
    case "tier_4": return "Tier 4: Groq Qwen3.8 27B (Coding Specialist)";
    case "tier_5": return "Tier 5: Groq GPT-OSS 120B (Deep Reasoning)";
    case "tier_6": return "Tier 6: Gemini 3.8 Flash (High Capability)";
    default: return String(tier || "Tier 1");
  }
}

function resetPipelineRibbon() {
  const an = $("pnode-analyzer");
  if (an) {
    an.className = "ribbon-node analyzer";
    const stateEl = $("pnode-analyzer-state");
    if (stateEl) stateEl.textContent = "Online Bandit";
  }
  $$(".rnode-tier").forEach(c => {
    c.classList.remove("active-tier", "escalated-tier");
  });
  const dot = $("pipeline-status-dot");
  if (dot) dot.className = "status-indicator-dot";
  const msg = $("pipeline-status-msg");
  if (msg) msg.textContent = "LinUCB Contextual Router Active · 6 Model Arms Online";
  const esc = $("pipeline-escalation-pill");
  if (esc) esc.classList.add("hidden");
}

function updatePipelineToAnalyzing() {
  resetPipelineRibbon();
  const an = $("pnode-analyzer");
  if (an) {
    an.classList.add("analyzing");
    const stateEl = $("pnode-analyzer-state");
    if (stateEl) stateEl.textContent = "TF-IDF + LinUCB Scoring...";
  }
  const dot = $("pipeline-status-dot");
  if (dot) dot.className = "status-indicator-dot analyzing";
  const msg = $("pipeline-status-msg");
  if (msg) msg.textContent = "LinUCB Contextual Bandit evaluating candidate arms...";
}

function updatePipelineAnalyzerResult(info) {
  const an = $("pnode-analyzer");
  const isSelf = info.answer_mode === "self";
  if (an) {
    an.classList.remove("analyzing");
    const stateEl = $("pnode-analyzer-state");
    if (stateEl) {
      stateEl.textContent = isSelf
        ? "Self-Answer"
        : `${(info.task_type || 'General')} · ${(info.complexity || 'Med')}`;
    }
  }

  const targetTier = normalizeTierKey(info.target_tier || info.required_capability);
  if (targetTier && !isSelf) {
    const card = $(`pnode-${targetTier}`);
    if (card) card.classList.add("active-tier");
  }

  const msg = $("pipeline-status-msg");
  if (msg) {
    msg.textContent = isSelf
      ? "Resolved in Zero-Latency Self-Answer Mode"
      : `LinUCB Routed: ${(info.task_type || 'General').toUpperCase()} ➔ ${formatTierDisplay(targetTier)}`;
  }
}

function updatePipelineRouting(route) {
  $$(".rnode-tier").forEach(c => c.classList.remove("active-tier"));
  const tierKey = normalizeTierKey(route.target_tier);
  if (tierKey) {
    const card = $(`pnode-${tierKey}`);
    if (card) card.classList.add("active-tier");
  }
  const dot = $("pipeline-status-dot");
  if (dot) dot.className = "status-indicator-dot active";
  const msg = $("pipeline-status-msg");
  if (msg) {
    msg.textContent = `Routed to ${route.target_name || route.target_model || 'Model'} (${route.target_tier || ''})`;
  }
}

function updatePipelineDone(outcome) {
  const isEscalated = Boolean(outcome.escalation_used || outcome.escalated);
  const servedTier = normalizeTierKey(outcome.escalated_tier || outcome.model?.tier || outcome.original_tier || "tier_1");

  $$(".rnode-tier").forEach(c => c.classList.remove("active-tier", "escalated-tier"));
  const card = $(`pnode-${servedTier}`);
  if (card) {
    card.classList.add("active-tier");
    if (isEscalated) card.classList.add("escalated-tier");
  }

  if (isEscalated) {
    const escPill = $("pipeline-escalation-pill");
    const escText = $("pipeline-escalation-text");
    if (escPill && escText) {
      escPill.classList.remove("hidden");
      escText.textContent = `Escalated: ${formatTierDisplay(outcome.original_tier)} → ${formatTierDisplay(outcome.escalated_tier || servedTier)}`;
    }
  }

  const dot = $("pipeline-status-dot");
  if (dot) dot.className = "status-indicator-dot";
  const msg = $("pipeline-status-msg");
  if (msg) {
    const modelName = outcome.model?.model_name || outcome.selected_model || "Model";
    const costVal = outcome.total_cost_usd != null ? outcome.total_cost_usd : (outcome.estimated_cost_usd || 0);
    const costStr = `$${costVal.toFixed(6)}`;
    const latVal = outcome.total_latency_ms != null ? outcome.total_latency_ms : (outcome.latency_ms || 0);
    const latStr = `${Math.round(latVal)}ms`;
    msg.textContent = `Served: ${modelName} · ${latStr} · ${costStr}`;
  }
}

/* ============================================================
   9. Chat Messages Rendering
   ============================================================ */
function renderActiveSessionMessages() {
  const container = $("chat-messages");
  if (!container) return;

  const active = sessionManager.getActive();
  updateActiveSessionHeader();
  updateContextCounter();

  if (!active || active.messages.length === 0) {
    container.innerHTML = `
      <div class="welcome-hero hud-welcome-hero" id="welcome-hero">
        <div class="welcome-eyebrow-badge hud-eyebrow">
          <span class="hud-blink-dot"></span>
          <span>✦ ROUTING ENGAGED ✦</span>
        </div>
        <h2 class="welcome-title hud-glitch-title">AUTONOMOUS PROMPT OPTIMIZATION IN PROGRESS... ESCALATING TIER CAPABILITY.</h2>
        <p class="welcome-desc hud-telemetry-lead">
          DISPATCH DIRECTIVE TO NEURAL MATRIX. REAL-TIME MULTI-TIER METERING AND CAPABILITY RESOLUTION ACTIVE.
        </p>

        <div class="welcome-prompts-section">
          <span class="welcome-prompts-label">TACTICAL SCENARIO NODES // SELECT DIRECTIVE</span>
          <div class="welcome-prompts-grid hud-scenarios-grid" id="welcome-quick-chips">
            
            <!-- SCENARIO NODE 1: T1 ROUTINE DIRECTIVE -->
            <button class="quick-chip-card hud-scenario-node t1-node" data-query="Summarize the primary benefits of semantic caching in 2 bullet points.">
              <span class="hud-corner tl"></span><span class="hud-corner tr"></span>
              <span class="hud-corner bl"></span><span class="hud-corner br"></span>
              <div class="chip-top">
                <span class="hud-bracket-label">[ T1: ROUTINE DIRECTIVE ]</span>
                <span class="hud-status-badge armed">STATUS: ARMED</span>
              </div>
              <div class="chip-telemetry">TARGET MODEL: gemini-3.5-flash-lite</div>
              <div class="chip-title">Semantic Caching Benefits</div>
              <div class="chip-query">Summarize the primary benefits of semantic caching in 2 bullet points.</div>
              <div class="chip-footer-hud">
                <span class="hud-indicator-txt">READY FOR DISPATCH</span>
                <span class="hud-pulse-ping"></span>
              </div>
            </button>

            <!-- SCENARIO NODE 2: T3 BALANCED SYNTHESIS -->
            <button class="quick-chip-card hud-scenario-node t3-node" data-query="Compare relational databases and document stores for high-throughput write workloads.">
              <span class="hud-corner tl"></span><span class="hud-corner tr"></span>
              <span class="hud-corner bl"></span><span class="hud-corner br"></span>
              <div class="chip-top">
                <span class="hud-bracket-label">[ T3: BALANCED SYNTHESIS ]</span>
                <span class="hud-status-badge armed">STATUS: ARMED</span>
              </div>
              <div class="chip-telemetry">TARGET MODEL: gemini-3.6-flash</div>
              <div class="chip-title">Database Workload Tradeoffs</div>
              <div class="chip-query">Compare relational databases and document stores for high-throughput write workloads.</div>
              <div class="chip-footer-hud">
                <span class="hud-indicator-txt">READY FOR DISPATCH</span>
                <span class="hud-pulse-ping"></span>
              </div>
            </button>

            <!-- SCENARIO NODE 3: T4 CODING SPECIALIST -->
            <button class="quick-chip-card hud-scenario-node t4-node" data-query="Write a thread-safe Python implementation of an LRU Cache with TTL expiration.">
              <span class="hud-corner tl"></span><span class="hud-corner tr"></span>
              <span class="hud-corner bl"></span><span class="hud-corner br"></span>
              <div class="chip-top">
                <span class="hud-bracket-label">[ T4: CODING SPECIALIST ]</span>
                <span class="hud-status-badge armed">STATUS: ARMED</span>
              </div>
              <div class="chip-telemetry">TARGET MODEL: qwen3.8-27b</div>
              <div class="chip-title">Thread-Safe LRU Cache</div>
              <div class="chip-query">Write a thread-safe Python implementation of an LRU Cache with TTL expiration.</div>
              <div class="chip-footer-hud">
                <span class="hud-indicator-txt">READY FOR DISPATCH</span>
                <span class="hud-pulse-ping"></span>
              </div>
            </button>

            <!-- SCENARIO NODE 4: T5 DEEP REASONING -->
            <button class="quick-chip-card hud-scenario-node t5-node" data-query="Prove that the square root of 2 is irrational and analyze its algebraic implications.">
              <span class="hud-corner tl"></span><span class="hud-corner tr"></span>
              <span class="hud-corner bl"></span><span class="hud-corner br"></span>
              <div class="chip-top">
                <span class="hud-bracket-label">[ T5: DEEP REASONING ]</span>
                <span class="hud-status-badge armed">STATUS: ARMED</span>
              </div>
              <div class="chip-telemetry">TARGET MODEL: gpt-oss-120b</div>
              <div class="chip-title">Irrationality of √2 Proof</div>
              <div class="chip-query">Prove that the square root of 2 is irrational and analyze its algebraic implications.</div>
              <div class="chip-footer-hud">
                <span class="hud-indicator-txt">READY FOR DISPATCH</span>
                <span class="hud-pulse-ping"></span>
              </div>
            </button>
          </div>
        </div>
      </div>
    `;

    // Attach chip clicks
    container.querySelectorAll(".quick-chip-card").forEach(chip => {
      chip.addEventListener("click", () => {
        const query = chip.dataset.query;
        const input = $("query-input");
        if (input) {
          input.value = query;
          input.focus();
          $("composer-form")?.requestSubmit();
        }
      });
    });
    return;
  }

  container.innerHTML = "";
  active.messages.forEach(msg => {
    if (msg.role === "user") {
      appendUserMessageToUI(msg.content, false);
    } else if (msg.role === "assistant") {
      appendAssistantResponseToUI("", msg.content, msg.meta || {}, false);
    }
  });

  smoothScrollToBottom(container);
}

function updateContextCounter() {
  const active = sessionManager.getActive();
  const count = active && Array.isArray(active.messages) ? active.messages.length : 0;
  if ($("context-turn-count")) {
    $("context-turn-count").textContent = count.toString();
  }
}

function appendUserMessageToUI(content, shouldScroll = true) {
  const container = $("chat-messages");
  if (!container) return;

  const msgEl = document.createElement("div");
  msgEl.className = "chat-msg user";
  msgEl.innerHTML = `<div class="user-bubble">${escapeHtml(content)}</div>`;
  container.appendChild(msgEl);

  if (shouldScroll) smoothScrollToBottom(container);
}

function createStreamingPlaceholder() {
  const container = $("chat-messages");
  const cardId = "stream_" + Date.now();

  const msgEl = document.createElement("div");
  msgEl.className = "chat-msg assistant";
  msgEl.id = cardId;

  msgEl.innerHTML = `
    <div class="msg-avatar"><svg class='icon-sym' aria-hidden='true'><use href='#i-node-switch'/></svg></div>
    <div class="msg-content-wrap">
      <div class="assistant-card">
        
        <!-- Live Monospace Streaming Trace -->
        <div class="agentic-trace-stream" id="${cardId}_trace">
          <span class="trace-pulse-dot"></span>
          <span class="trace-text" id="${cardId}_tracetext">Routing via Gemini 3.1 Flash-Lite · Evaluating prompt &amp; intent...</span>
        </div>

        <!-- Hidden compatibility hooks -->
        <span id="${cardId}_tier" style="display:none;"></span>
        <span id="${cardId}_model" style="display:none;"></span>
        <span id="${cardId}_lat" style="display:none;"></span>

        <div class="msg-text-body" id="${cardId}_body">
          <span style="color:var(--text-muted);font-style:italic;">Routing query across calibrated model tiers...</span>
        </div>

      </div>
    </div>
  `;

  container.appendChild(msgEl);
  smoothScrollToBottom(container);

  return {
    card: msgEl,
    updateAnalyzer: (info) => {
      const isSelf = info.answer_mode === "self";
      const tracetext = $(`${cardId}_tracetext`);
      if (tracetext) {
        if (isSelf) {
          tracetext.textContent = "[⚡ SELF-ANSWER] Gemini 3.1 Flash-Lite · Direct resolution (0 downstream tokens)";
        } else {
          const tierNorm = normalizeTierKey(info.target_tier || info.required_capability || "tier_1").toUpperCase();
          const compScore = (info.complexity_score ?? 0.5).toFixed(2);
          const task = (info.task_type || "general").toUpperCase();
          tracetext.textContent = `Routing via Gemini 3.1 Flash-Lite → Escalated to ${tierNorm} · Complexity ${compScore} · ${task}`;
        }
      }
    },
    updateRouting: (route) => {
      const tracetext = $(`${cardId}_tracetext`);
      if (tracetext) {
        const tierNorm = normalizeTierKey(route.target_tier || "tier_1").toUpperCase();
        const modelName = route.target_name || route.target_model || "Target Model";
        tracetext.textContent = `Routing via Gemini 3.1 Flash-Lite → Switched to ${tierNorm} (${modelName}) · Streaming tokens...`;
      }
    },
    appendReasoningDelta: (reasoning) => {
      if (!reasoning) return;
      let thoughtAccordion = $(`${cardId}_thought`);
      const body = $(`${cardId}_body`);
      if (!thoughtAccordion && body) {
        thoughtAccordion = document.createElement("details");
        thoughtAccordion.className = "thought-accordion streaming";
        thoughtAccordion.id = `${cardId}_thought`;
        thoughtAccordion.open = true;
        thoughtAccordion.innerHTML = `
          <summary class="thought-header">
            <div class="thought-header-left">
              <span class="thought-icon-pulse">🧠</span>
              <span class="thought-title">Chain-of-Thought Reasoning</span>
              <span class="thought-badge">Live Reasoning</span>
            </div>
            <span class="thought-status">Generating thoughts...</span>
          </summary>
          <div class="thought-body" id="${cardId}_thought_body"></div>
        `;
        body.parentNode.insertBefore(thoughtAccordion, body);
      }
      const thoughtBody = $(`${cardId}_thought_body`);
      if (thoughtBody) {
        thoughtBody.innerHTML = formatMarkdown(reasoning);
        _renderMathInElement(thoughtBody);
      }
      smoothScrollToBottom(container);
    },
    startResponse: () => {
      const body = $(`${cardId}_body`);
      if (body) body.innerHTML = "";
    },
    appendDelta: (text) => {
      const body = $(`${cardId}_body`);
      if (body) {
        body.innerHTML = formatMarkdown(text);
        _renderMathInElement(body);
      }
      smoothScrollToBottom(container);
    },
    showError: (err) => {
      const body = $(`${cardId}_body`);
      if (body) {
        body.innerHTML = `<span style="color:var(--signal-red);">Stream error: ${escapeHtml(err)}</span>`;
      }
    },
    showStoppedState: (text) => {
      const body = $(`${cardId}_body`);
      if (body && text) {
        body.innerHTML = formatMarkdown(text) + `<p style="color:var(--text-muted);font-style:italic;margin-top:8px;">[Generation stopped by user]</p>`;
        _renderMathInElement(body);
      }
    }
  };
}

function appendAssistantResponseToUI(query, text, data = {}, shouldScroll = true) {
  const container = $("chat-messages");
  if (!container) return;

  const msgEl = document.createElement("div");
  msgEl.className = "chat-msg assistant";
  const drawerId = "drawer_" + (data.request_id || Date.now() + "_" + Math.random().toString(36).substring(2, 6));

  const analyzer = data.analyzer || {};
  const model = data.model || {};

  const isSelf = (data.answer_mode === "self" || analyzer.answer_mode === "self");
  const taskType = analyzer.task_type || data.task_type || "general";
  const complexity = analyzer.complexity || data.complexity || "medium";
  const complexityScore = analyzer.complexity_score ?? data.complexity_score ?? 0.5;
  const servedTierNorm = normalizeTierKey(data.tier || model.tier || analyzer.required_capability || "tier_1");
  const targetModelName = model.model_name || model.model_id || data.selected_model || "Gemini Flash";
  const shortModel = (targetModelName || "").split(" ")[0].replace(/^[a-z0-9_-]+\//i, "");
  const routingReason = data.routing_reason || analyzer.reason || model.reason || "Cost-optimal model selection";

  const isEscalated = Boolean(data.escalation_used || data.escalated);

  const costNumber = data.total_cost_usd != null ? data.total_cost_usd : (data.estimated_cost_usd || 0.0);
  const costStr = `$${costNumber.toFixed(6)}`;
  const microDollars = (costNumber * 1000000).toFixed(1);
  const latencyNumber = data.total_latency_ms != null ? data.total_latency_ms : (data.latency_ms || 0.0);
  const ttftNumber = Number(data.ttft_ms || 0);

  const inTok = data.input_tokens != null ? data.input_tokens : (data.usage?.prompt_tokens ?? (isSelf ? 120 : 380));
  const outTok = data.output_tokens != null ? data.output_tokens : (data.usage?.completion_tokens ?? (isSelf ? 85 : 420));
  const savingsPct = data.savings_percent != null && data.savings_percent > 0 ? `${data.savings_percent.toFixed(1)}%` : null;

  // Selected candidate factors
  const selectedCandidate = Array.isArray(data.candidates) ? data.candidates.find(c => c.selected) : null;
  const reasoningScore = (selectedCandidate?.factors?.reasoning_compatibility != null)
    ? selectedCandidate.factors.reasoning_compatibility
    : (analyzer.reasoning_required ? 0.95 : (complexityScore > 0.6 ? 0.80 : 0.25));
  const codingScore = (selectedCandidate?.factors?.coding_compatibility != null)
    ? selectedCandidate.factors.coding_compatibility
    : (taskType === 'coding' || analyzer.coding_required ? 0.95 : 0.15);

  const pComp = Math.min(100, Math.max(5, Math.round(complexityScore * 100)));
  const pReason = Math.min(100, Math.max(5, Math.round(reasoningScore * 100)));
  const pCode = Math.min(100, Math.max(5, Math.round(codingScore * 100)));

  // Routing Confidence calculation
  let confidenceVal = 0.94;
  if (typeof data.confidence === "number") {
    confidenceVal = data.confidence;
  } else if (selectedCandidate && typeof selectedCandidate.total === "number") {
    confidenceVal = Math.min(0.99, Math.max(0.60, selectedCandidate.total));
  } else if (data.bandit_score != null) {
    confidenceVal = Math.min(0.99, Math.max(0.60, data.bandit_score));
  } else if (data.expected_reward != null) {
    confidenceVal = Math.min(0.99, Math.max(0.60, data.expected_reward));
  } else if (data.uncertainty != null) {
    confidenceVal = Math.min(0.99, Math.max(0.60, 1.0 - Math.min(0.35, data.uncertainty)));
  } else {
    confidenceVal = Number((0.90 + (1.0 - complexityScore) * 0.08).toFixed(2));
  }
  const confPercent = Math.round(confidenceVal * 100);

  // Tier Badge Class & Label
  const tierClass = isSelf ? "self" : isEscalated ? "escalated" : servedTierNorm.replace("_", "-");
  const tierBadgeLabel = isSelf ? "SELF" : isEscalated ? "⚡ ESCALATED" : servedTierNorm.replace("_", " ").toUpperCase();

  // Chain-of-Thought Reasoning content check
  const reasoningContent = data.reasoning || data.thinking || data.reasoning_content || data.thought || data.meta?.reasoning || "";
  const hasReasoning = Boolean(reasoningContent && reasoningContent.trim().length > 0);

  // Existing user feedback status
  const existingFeedback = data.feedback != null ? Number(data.feedback) : null;

  // Stage Latency Waterfall calculations (LinUCB Architecture: zero analyzer latency)
  const routerLat = Number(data.routing_latency_ms || 1.2);
  const prepLat = ttftNumber > 0 ? Math.max(5, ttftNumber - routerLat) : (isSelf ? 0.5 : 25);
  const genLat = isSelf ? 0 : Math.max(10, Number(data.latency_ms || Math.max(0, latencyNumber - routerLat - prepLat)));
  const verifLat = Number(data.verification_latency_ms || 0.5);

  const totalStages = Math.max(1, routerLat + prepLat + genLat + verifLat);
  const pRouter = Math.max(2, (routerLat / totalStages) * 100).toFixed(1);
  const pPrep = Math.max(2, (prepLat / totalStages) * 100).toFixed(1);
  const pGen = Math.max(5, (genLat / totalStages) * 100).toFixed(1);
  const pVerif = Math.max(1, (verifLat / totalStages) * 100).toFixed(1);

  // LinUCB Contextual Bandit Telemetry extraction
  const banditScore = data.bandit_score != null ? data.bandit_score : null;
  const expReward = data.expected_reward != null ? data.expected_reward : null;
  const uncertainty = data.uncertainty != null ? data.uncertainty : null;
  const rewardVal = data.reward != null ? data.reward : null;
  const scoresObj = data.scores || {};
  const scoreEntries = Object.entries(scoresObj);

  let linucbScoreboardRows = "";
  if (scoreEntries.length > 0) {
    scoreEntries.sort((a, b) => (b[1].ucb_score || 0) - (a[1].ucb_score || 0));
    const selectedArmId = data.selected_model || data.model?.model_id || "";
    linucbScoreboardRows = scoreEntries.map(([armId, s]) => {
      const isWinner = (armId === selectedArmId) || (data.model?.model_id === armId) || (data.model?.endpoint_model === armId);
      return `
        <tr class="${isWinner ? 'selected' : ''}">
          <td><strong>${escapeHtml(armId)}</strong></td>
          <td style="color:#38BDF8; font-weight:600;">${s.ucb_score != null ? s.ucb_score.toFixed(4) : '—'}</td>
          <td style="color:#34D399;">${s.expected_reward != null ? s.expected_reward.toFixed(4) : '—'}</td>
          <td style="color:#FBBF24;">${s.uncertainty != null ? s.uncertainty.toFixed(4) : '—'}</td>
          <td>${s.pull_count != null ? s.pull_count : 0}</td>
          <td>${isWinner ? '<span class="status-pill status-pill-active" style="background:rgba(56,189,248,0.2); color:#38BDF8;">✓ Selected</span>' : '<span style="color:var(--text-muted);">—</span>'}</td>
        </tr>
      `;
    }).join("");
  }

  msgEl.innerHTML = `
    <div class="msg-avatar"><svg class='icon-sym' aria-hidden='true'><use href='#i-node-switch'/></svg></div>
    <div class="msg-content-wrap">
      <div class="assistant-card">
        
        <!-- One-Line Agentic Telemetry HUD -->
        <div class="agentic-telemetry-bar" data-action="toggle-drawer" data-target="${drawerId}">
          <div class="telemetry-bar-left">
            <span class="telemetry-badge-tier ${tierClass}">
              ${tierBadgeLabel}
            </span>
            <span class="routing-model-name">${escapeHtml(shortModel)}</span>
            <span class="telemetry-sep">·</span>
            <span class="telemetry-stat" title="Roundtrip Latency: ${latencyNumber.toFixed(1)}ms · TTFT: ${ttftNumber}ms">${Math.round(latencyNumber)}ms</span>
            <span class="telemetry-sep">·</span>
            <span class="telemetry-stat" title="Prompt: ${inTok} tok · Output: ${outTok} tok">${inTok + outTok} tok</span>
            <span class="telemetry-sep">·</span>
            <span class="telemetry-stat telemetry-cost" title="${microDollars} µ$ micro-dollars (${costStr})">${costStr}</span>
            <span class="telemetry-sep">·</span>
            <span class="telemetry-stat telemetry-conf" title="Routing Confidence: ${confidenceVal.toFixed(4)}">${confPercent}% conf</span>
            ${savingsPct ? `<span class="savings-pill">+${savingsPct}</span>` : ''}
          </div>
          <button type="button" class="btn-inspect-drawer" data-action="toggle-drawer" data-target="${drawerId}" title="Inspect Decision Trace">
            <span>Trace</span>
            <span class="drawer-arrow">▾</span>
          </button>
        </div>

        <!-- Expandable Decision Reasoning Drawer -->
        <div class="routing-drawer" id="${drawerId}">
          <div class="routing-drawer-content hidden" id="${drawerId}_content">
            
            <!-- 3 Horizontal Micro-Meters -->
            <div class="drawer-meters-row">
              <div class="micro-meter">
                <div class="meter-head">
                  <span>Complexity</span>
                  <span class="mono">${complexityScore.toFixed(2)} (${complexity.toUpperCase()})</span>
                </div>
                <div class="meter-bar">
                  <div class="meter-fill ${complexityScore > 0.7 ? 'amber' : 'indigo'}" style="width: ${pComp}%;"></div>
                </div>
              </div>

              <div class="micro-meter">
                <div class="meter-head">
                  <span>Reasoning</span>
                  <span class="mono">${reasoningScore.toFixed(2)}</span>
                </div>
                <div class="meter-bar">
                  <div class="meter-fill indigo" style="width: ${pReason}%;"></div>
                </div>
              </div>

              <div class="micro-meter">
                <div class="meter-head">
                  <span>Coding</span>
                  <span class="mono">${codingScore.toFixed(2)}</span>
                </div>
                <div class="meter-bar">
                  <div class="meter-fill emerald" style="width: ${pCode}%;"></div>
                </div>
              </div>
            </div>

            <!-- Stage Latency Waterfall (LinUCB Architecture) -->
            <div class="waterfall-section">
              <div class="waterfall-header">Stage Latency Waterfall</div>
              <div class="waterfall-bar">
                <div class="wf-seg router" style="width: ${pRouter}%;" title="LinUCB Routing: ${routerLat.toFixed(1)}ms"></div>
                <div class="wf-seg prep" style="width: ${pPrep}%;" title="TTFT / Prep: ${Math.round(prepLat)}ms">${Math.round(prepLat)}ms</div>
                <div class="wf-seg generation" style="width: ${pGen}%;" title="Generation: ${Math.round(genLat)}ms">${Math.round(genLat)}ms</div>
                <div class="wf-seg verification" style="width: ${pVerif}%;" title="Verification: ${verifLat.toFixed(1)}ms"></div>
              </div>
              <div class="waterfall-legend">
                <span style="color:#8B5CF6;">⚡ LinUCB Routing: ${routerLat.toFixed(1)}ms</span>
                <span style="color:#94A3B8;">⏱ Prep: ${Math.round(prepLat)}ms</span>
                <span style="color:var(--signal-indigo);">💬 Gen: ${Math.round(genLat)}ms</span>
                <span style="color:var(--signal-emerald);">✓ Verif: ${verifLat.toFixed(1)}ms</span>
              </div>
            </div>

            <!-- LinUCB Contextual Bandit Telemetry Box -->
            <div class="linucb-drawer-box" style="margin-top:12px; margin-bottom:10px; padding:10px 12px; background:rgba(30, 27, 75, 0.4); border:1px solid rgba(139, 92, 246, 0.25); border-radius:var(--radius-sm);">
              <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
                <div style="font-size:11px; font-weight:700; letter-spacing:0.04em; color:#C084FC; text-transform:uppercase;">
                  ⚡ LinUCB Contextual Bandit Routing
                </div>
                <div style="font-family:var(--font-mono); font-size:11px; color:var(--text-muted);">
                  Selected Arm: <strong style="color:#F8FAFC;">${escapeHtml(data.selected_model || targetModelName)}</strong>
                </div>
              </div>

              <!-- 4-Stat Metric Strip -->
              <div style="display:grid; grid-template-columns:repeat(4, 1fr); gap:8px; margin-bottom:10px;">
                <div style="background:rgba(0,0,0,0.3); padding:6px 8px; border-radius:4px; border:1px solid rgba(255,255,255,0.05);">
                  <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase;">UCB Score</div>
                  <div style="font-family:var(--font-mono); font-size:13px; font-weight:700; color:#38BDF8;">
                    ${banditScore != null ? banditScore.toFixed(4) : (selectedCandidate ? selectedCandidate.total.toFixed(4) : '—')}
                  </div>
                </div>
                <div style="background:rgba(0,0,0,0.3); padding:6px 8px; border-radius:4px; border:1px solid rgba(255,255,255,0.05);">
                  <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase;">Exploitation (θ̂ᵀx)</div>
                  <div style="font-family:var(--font-mono); font-size:13px; font-weight:700; color:#34D399;">
                    ${expReward != null ? expReward.toFixed(4) : '—'}
                  </div>
                </div>
                <div style="background:rgba(0,0,0,0.3); padding:6px 8px; border-radius:4px; border:1px solid rgba(255,255,255,0.05);">
                  <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase;">Exploration (α·σ)</div>
                  <div style="font-family:var(--font-mono); font-size:13px; font-weight:700; color:#FBBF24;">
                    ${uncertainty != null ? uncertainty.toFixed(4) : '—'}
                  </div>
                </div>
                <div style="background:rgba(0,0,0,0.3); padding:6px 8px; border-radius:4px; border:1px solid rgba(255,255,255,0.05);">
                  <div style="font-size:10px; color:var(--text-muted); text-transform:uppercase;">Reward (R)</div>
                  <div style="font-family:var(--font-mono); font-size:13px; font-weight:700; color:${rewardVal != null && rewardVal >= 0 ? '#4ADE80' : '#F87171'};">
                    ${rewardVal != null ? (rewardVal >= 0 ? '+' : '') + rewardVal.toFixed(4) : '—'}
                  </div>
                </div>
              </div>

              <!-- Candidate Arm Scoreboard Table -->
              ${linucbScoreboardRows ? `
                <div class="waterfall-header" style="margin-bottom:6px; font-size:10.5px;">LinUCB Candidate Arm Scoreboard</div>
                <div class="table-responsive">
                  <table class="scoreboard-table">
                    <thead>
                      <tr>
                        <th>Arm / Model ID</th>
                        <th>UCB Score</th>
                        <th>Exploitation (θ̂ᵀx)</th>
                        <th>Exploration (α·σ)</th>
                        <th>Pulls</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>${linucbScoreboardRows}</tbody>
                  </table>
                </div>
              ` : ''}
            </div>

            <!-- Decision Rationale Quote Box -->
            <div class="drawer-rationale-quote">
              <span class="rationale-label">ROUTING RATIONALE</span>
              "${escapeHtml(routingReason)}"
            </div>

          </div>
        </div>

        <!-- Collapsible Reasoning / Thinking Accordion (Chain-of-Thought Models) -->
        ${hasReasoning ? `
          <details class="thought-accordion">
            <summary class="thought-header">
              <div class="thought-header-left">
                <span class="thought-icon">🧠</span>
                <span class="thought-title">Chain-of-Thought Reasoning</span>
                <span class="thought-badge">${escapeHtml(shortModel)} CoT</span>
              </div>
              <span class="thought-meta">${Math.round(reasoningContent.length / 4)} tokens · Expand to view</span>
            </summary>
            <div class="thought-body">
              ${formatMarkdown(reasoningContent)}
            </div>
          </details>
        ` : ""}

        <!-- Assistant Markdown Answer -->
        <div class="msg-text-body">
          ${formatMarkdown(text)}
        </div>

        <!-- Telemetry Actions Bar -->
        <div class="telemetry-footer">
          <div class="telemetry-actions">
            <button class="btn-icon-action" data-action="copy-message" data-text="${escapeHtml(text)}" title="Copy Response">
              <svg class='icon-sym' aria-hidden='true'><use href='#i-copy'/></svg> <span>Copy Answer</span>
            </button>
            ${data.request_id ? `
              <button class="btn-icon-action" data-action="open-inspector" data-id="${data.request_id}" title="Inspect Full Telemetry">
                <svg class='icon-sym' aria-hidden='true'><use href='#i-search'/></svg> <span>Inspect</span>
              </button>
              <button 
                class="btn-icon-action btn-thumb-up ${existingFeedback === 1 ? "active-feedback thumb-up" : ""}" 
                data-action="feedback" 
                data-id="${data.request_id}" 
                data-rating="1" 
                title="Helpful Response (+1.0 LinUCB Reward)"
              >
                <svg class='icon-sym' aria-hidden='true'><use href='#i-thumb-up'/></svg>
              </button>
              <button 
                class="btn-icon-action btn-thumb-down ${existingFeedback === -1 ? "active-feedback thumb-down" : ""}" 
                data-action="feedback" 
                data-id="${data.request_id}" 
                data-rating="-1" 
                title="Poor Response (-1.0 LinUCB Penalty)"
              >
                <svg class='icon-sym' aria-hidden='true'><use href='#i-thumb-down'/></svg>
              </button>
            ` : ''}
          </div>
        </div>

      </div>
    </div>
  `;

  // Drawer Toggle Handlers (Handles clicking anywhere on telemetry bar or inspect button)
  const drawerContent = msgEl.querySelector(`#${drawerId}_content`);
  const arrow = msgEl.querySelector(".drawer-arrow");

  msgEl.querySelectorAll(`[data-target="${drawerId}"]`).forEach(toggleTarget => {
    toggleTarget.addEventListener("click", (e) => {
      // Don't toggle if clicking an inner button
      if (e.target.closest("button") && e.target.closest("button") !== toggleTarget && !toggleTarget.classList.contains("btn-inspect-drawer")) {
        return;
      }
      if (!drawerContent) return;
      drawerContent.classList.toggle("hidden");
      if (arrow) arrow.textContent = drawerContent.classList.contains("hidden") ? "▾" : "▴";
    });
  });

  // Action Button Handlers (Copy, Feedback, Inspector)
  msgEl.querySelectorAll("[data-action]").forEach(btn => {
    const act = btn.dataset.action;
    if (act === "copy-message") {
      btn.addEventListener("click", () => {
        navigator.clipboard.writeText(btn.dataset.text || text);
        showToast("Answer copied to clipboard", "success");
      });
    } else if (act === "open-inspector") {
      btn.addEventListener("click", () => {
        openInspectorModal(btn.dataset.id);
      });
    } else if (act === "feedback") {
      btn.addEventListener("click", async () => {
        const reqId = parseInt(btn.dataset.id, 10);
        const rating = parseInt(btn.dataset.rating, 10);
        try {
          const resp = await apiFetch("/api/feedback", {
            method: "POST",
            body: JSON.stringify({ request_id: reqId, rating }),
          });
          if (resp && resp.ok) {
            const parent = btn.closest(".telemetry-actions");
            if (parent) {
              parent.querySelectorAll("[data-action='feedback']").forEach((b) => {
                b.classList.remove("active-feedback", "thumb-up", "thumb-down");
              });
            }
            btn.classList.add("active-feedback", rating === 1 ? "thumb-up" : "thumb-down");

            if (typeof sessionManager !== "undefined" && sessionManager.getActive) {
              const active = sessionManager.getActive();
              if (active && Array.isArray(active.messages)) {
                const targetMsg = active.messages.find((m) => m.meta && m.meta.request_id === reqId);
                if (targetMsg) {
                  targetMsg.meta.feedback = rating;
                  sessionManager.save();
                }
              }
            }

            const rewardMsg = rating === 1 ? "+1.0 reward trained to LinUCB arm" : "-1.0 penalty applied to LinUCB arm";
            showToast(`Feedback recorded (${rewardMsg})`, "success");
          }
        } catch (e) {
          console.error("Feedback error:", e);
        }
      });
    }
  });

  container.appendChild(msgEl);
  _renderMathInElement(msgEl.querySelector(".msg-text-body"));
  const thoughtBody = msgEl.querySelector(".thought-body");
  if (thoughtBody) _renderMathInElement(thoughtBody);
  if (shouldScroll) smoothScrollToBottom(container);
}

/* ============================================================
   10. SSE Stream Reader
   ============================================================ */
async function executeStreamingChat(payload, signal, onAnalyzer, onRouting, onReasoningDelta, onDelta, onDone, onError) {
  const resp = await apiFetch("/api/chat/stream", {
    method: "POST",
    body: JSON.stringify(payload),
    signal: signal,
  });

  if (!resp.ok || !resp.body) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || "";

    for (const block of lines) {
      const trimmed = block.trim();
      if (!trimmed.startsWith("data:")) continue;

      const rawJson = trimmed.replace(/^data:\s*/, "");
      try {
        const evt = JSON.parse(rawJson);
        const eventType = evt.event || evt.type;

        if (eventType === "analyzer" && onAnalyzer) {
          onAnalyzer(evt.info || evt.data || evt);
        } else if (eventType === "routing" && onRouting) {
          onRouting(evt.data || evt);
        } else if ((eventType === "reasoning_delta" || eventType === "reasoning") && onReasoningDelta) {
          const chunk = evt.text || evt.delta || (evt.data && (evt.data.text || evt.data.delta)) || "";
          onReasoningDelta(chunk);
        } else if (eventType === "delta" && onDelta) {
          const chunk = evt.text || evt.delta || (evt.data && (evt.data.text || evt.data.delta)) || "";
          onDelta(chunk);
        } else if (eventType === "done" && onDone) {
          onDone(evt.data || evt);
        } else if (eventType === "error" && onError) {
          onError(evt.detail || evt.message || (evt.data && evt.data.message) || "Unknown error");
        }
      } catch (jsonErr) {
        console.warn("SSE json parse error:", jsonErr, rawJson);
      }
    }
  }
}

/* ============================================================
   11. View 2: Model Registry & Architecture Tiers
   ============================================================ */
function setupModelRegistryView() {
  $("refresh-registry-btn")?.addEventListener("click", () => {
    loadRegistryModels();
    showToast("Model registry updated", "info");
  });
}

function renderProviderPingStrip(healthData) {
  let strip = $("provider-ping-strip");
  if (!strip) {
    const tableHeader = document.querySelector("#view-registry .table-header");
    if (tableHeader) {
      strip = document.createElement("div");
      strip.id = "provider-ping-strip";
      strip.className = "provider-ping-strip";
      tableHeader.appendChild(strip);
    }
  }
  if (!strip) return;

  const providers = (healthData && healthData.providers) ? healthData.providers : (healthData || {});
  const defaultList = [
    { key: "gemini", label: "Google Gemini" },
    { key: "groq", label: "Groq LPU" },
    { key: "openrouter", label: "OpenRouter" }
  ];

  strip.innerHTML = defaultList.map(item => {
    const p = providers[item.key];
    let statusClass = "inactive";
    let statusText = "Offline";
    let pingText = "";

    if (p) {
      if (p.status === "connected") {
        statusClass = "connected";
        statusText = "Connected";
        pingText = p.latency_ms ? `· ${Math.round(p.latency_ms)} ms` : "· Online";
      } else if (p.status === "missing_api_key") {
        statusClass = "demo";
        statusText = "Demo Mode";
        pingText = "· Calibrated";
      } else if (p.status === "error") {
        statusClass = "error";
        statusText = "Error";
        pingText = "· Outage";
      }
    } else {
      statusClass = "demo";
      statusText = "Standby";
      pingText = "· Ready";
    }

    return `
      <div class="ping-pill ${statusClass}" title="${escapeHtml(item.label)} Status: ${statusText} ${pingText}">
        <span class="ping-dot"></span>
        <span class="ping-provider">${escapeHtml(item.label)}</span>
        <span class="ping-val">${escapeHtml(statusText)} ${escapeHtml(pingText)}</span>
      </div>
    `;
  }).join("");
}

async function loadRegistryModels() {
  const tbody = $("registry-table-body");
  if (!tbody) return;

  try {
    const [modelsResp, healthResp] = await Promise.allSettled([
      apiFetch("/api/models").then(r => r.ok ? r.json() : null),
      apiFetch("/api/providers/health").then(r => r.ok ? r.json() : null).catch(() => null)
    ]);

    const data = modelsResp.status === "fulfilled" ? modelsResp.value : null;
    const healthData = healthResp.status === "fulfilled" ? healthResp.value : null;
    const models = (data && data.models && data.models.length > 0) ? data.models : [];

    if ($("reg-total-models")) $("reg-total-models").textContent = models.length > 0 ? models.length.toString() : "6";

    // Find price range, min latency, max context
    if (models.length > 0) {
      const minIn = Math.min(...models.map(m => m.input_price_per_mtok));
      const maxOut = Math.max(...models.map(m => m.output_price_per_mtok));
      const minLat = Math.min(...models.map(m => m.expected_latency_ms));
      const maxCtx = Math.max(...models.map(m => m.context_window));

      if ($("reg-price-range")) $("reg-price-range").textContent = `$${minIn.toFixed(2)} – $${maxOut.toFixed(2)}`;
      if ($("reg-min-lat")) $("reg-min-lat").textContent = `~${minLat} ms`;
      if ($("reg-max-context")) $("reg-max-context").textContent = maxCtx.toLocaleString();
    }

    renderProviderPingStrip(healthData);

    const providersHealth = (healthData && healthData.providers) ? healthData.providers : (healthData || {});

    tbody.innerHTML = models.map(m => {
      const tierTag = m.tier.toUpperCase();
      const inPrice = `$${m.input_price_per_mtok.toFixed(3)}`;
      const outPrice = `$${m.output_price_per_mtok.toFixed(3)}`;
      const isOnline = m.available;
      const modeStr = m.mode || (m.demo_mode ? "demo" : "live");

      const pHealth = providersHealth[m.provider];
      let statusBadge = "";
      if (pHealth && pHealth.status === "connected") {
        const pingMs = pHealth.latency_ms ? `${Math.round(pHealth.latency_ms)}ms` : "ok";
        statusBadge = `<span class="status-indicator active ping-ok" title="Provider ping: ${pingMs}"><span class="status-dot"></span> Active <span class="mode-badge ping-badge">${pingMs}</span></span>`;
      } else if (pHealth && pHealth.status === "missing_api_key") {
        statusBadge = `<span class="status-indicator demo" title="Simulated evaluation arm / Demo mode"><span class="status-dot"></span> Demo <span class="mode-badge">sim</span></span>`;
      } else if (pHealth && pHealth.status === "error") {
        statusBadge = `<span class="status-indicator error" title="${escapeHtml(pHealth.error || 'Connection error')}"><span class="status-dot"></span> Degraded</span>`;
      } else if (isOnline) {
        statusBadge = `<span class="status-indicator active"><span class="status-dot"></span> Active <span class="mode-badge">${escapeHtml(modeStr)}</span></span>`;
      } else {
        statusBadge = `<span class="status-indicator inactive"><span class="status-dot"></span> Inactive</span>`;
      }

      const qualityVal = m.quality != null ? Math.round(m.quality * 100) : null;
      const reasoningVal = m.reasoning != null ? Math.round(m.reasoning * 100) : null;
      const codingVal = m.coding != null ? Math.round(m.coding * 100) : null;

      const qCell = qualityVal != null
        ? `<div class="metric-meter-cell"><span class="meter-val">${qualityVal}%</span><div class="meter-track"><div class="meter-bar bar-quality" style="width:${qualityVal}%;"></div></div></div>`
        : `<span>—</span>`;
      const rCell = reasoningVal != null
        ? `<div class="metric-meter-cell"><span class="meter-val">${reasoningVal}%</span><div class="meter-track"><div class="meter-bar bar-reasoning" style="width:${reasoningVal}%;"></div></div></div>`
        : `<span>—</span>`;
      const cCell = codingVal != null
        ? `<div class="metric-meter-cell"><span class="meter-val">${codingVal}%</span><div class="meter-track"><div class="meter-bar bar-coding" style="width:${codingVal}%;"></div></div></div>`
        : `<span>—</span>`;

      return `
        <tr>
          <td><span class="routing-tier-pill">${escapeHtml(tierTag)}</span></td>
          <td><strong>${escapeHtml(m.name)}</strong></td>
          <td>${escapeHtml((m.provider || 'gemini').toUpperCase())}</td>
          <td>${qCell}</td>
          <td>${rCell}</td>
          <td>${cCell}</td>
          <td>${inPrice} / ${outPrice}</td>
          <td>~${m.expected_latency_ms} ms</td>
          <td>${m.context_window ? m.context_window.toLocaleString() : '—'}</td>
          <td>${statusBadge}</td>
        </tr>
      `;
    }).join("");

    // Populate Tier Guidelines Cards Grid
    const guidelinesGrid = $("tier-guidelines-grid");
    if (guidelinesGrid) {
      guidelinesGrid.innerHTML = `
        <div class="guideline-card">
          <div class="guideline-card-head">
            <span class="routing-tier-pill">ANALYZER</span>
            <span class="prov-tag gemini">Google Gemini</span>
          </div>
          <div class="guideline-title">Gemini 3.1 Flash-Lite</div>
          <p class="guideline-desc">Evaluates incoming prompts and context in a single pass. Resolves routine queries in Self-Answer mode with 0 downstream calls; classifies tasks into Coding, Reasoning, or General.</p>
        </div>
        <div class="guideline-card">
          <div class="guideline-card-head">
            <span class="routing-tier-pill">TIER 1</span>
            <span class="prov-tag gemini">Google Gemini</span>
          </div>
          <div class="guideline-title">Gemini 3.5 Flash-Lite (Fast / Routine)</div>
          <p class="guideline-desc">Ideal for short summaries, greetings, terminology definitions, and high-frequency, low-latency conversational turns ($0.075 / $0.30 per Mtok).</p>
        </div>
        <div class="guideline-card">
          <div class="guideline-card-head">
            <span class="routing-tier-pill">TIER 2</span>
            <span class="prov-tag groq">Groq LPU</span>
          </div>
          <div class="guideline-title">GPT-OSS 20B (Fast General Purpose)</div>
          <p class="guideline-desc">High token velocity on Groq hardware. Great for quick explanations, casual Q&amp;A, and routine factual synthesis (~200 ms latency).</p>
        </div>
        <div class="guideline-card">
          <div class="guideline-card-head">
            <span class="routing-tier-pill">TIER 3</span>
            <span class="prov-tag gemini">Google Gemini</span>
          </div>
          <div class="guideline-title">Gemini 3.6 Flash (Balanced Workhorse)</div>
          <p class="guideline-desc">Optimal middle-ground balancing quality and cost for general analysis, complex dialogue, and document queries with 1M context window.</p>
        </div>
        <div class="guideline-card">
          <div class="guideline-card-head">
            <span class="routing-tier-pill">TIER 4</span>
            <span class="prov-tag groq">Groq LPU</span>
          </div>
          <div class="guideline-title">Qwen3.8 27B (Coding Specialist)</div>
          <p class="guideline-desc">Trained and calibrated for software engineering, refactoring, algorithmic DSA tasks, and code review (0.96 coding capability score).</p>
        </div>
        <div class="guideline-card">
          <div class="guideline-card-head">
            <span class="routing-tier-pill">TIER 5</span>
            <span class="prov-tag groq">Groq LPU</span>
          </div>
          <div class="guideline-title">GPT-OSS 120B (Deep Reasoning)</div>
          <p class="guideline-desc">Advanced reasoning model for mathematical proofs, complex logic puzzles, multi-constraint deduction, and intricate decision trees.</p>
        </div>
        <div class="guideline-card">
          <div class="guideline-card-head">
            <span class="routing-tier-pill">TIER 6</span>
            <span class="prov-tag gemini">Google Gemini</span>
          </div>
          <div class="guideline-title">Gemini 3.8 Flash (High Capability)</div>
          <p class="guideline-desc">Top-tier high capability model for difficult system architecture, ambiguous research questions, and fallback escalation (backed by gemini-3.5-flash fallback).</p>
        </div>
      `;
    }
  } catch (err) {
    console.error("Failed to load model registry:", err);
    tbody.innerHTML = `<tr><td colspan="10" class="empty-state">Failed to load models. Ensure server is running.</td></tr>`;
  }
}

/* ============================================================
   12. View 3: Telemetry & Dashboard Analytics
   ============================================================ */
function startDashboardAutoRefresh() {
  stopDashboardAutoRefresh();
  dashboardRefreshTimer = setInterval(loadDashboardStats, 10000);
}

function stopDashboardAutoRefresh() {
  if (dashboardRefreshTimer) {
    clearInterval(dashboardRefreshTimer);
    dashboardRefreshTimer = null;
  }
}

async function loadDashboardStats() {
  $("refresh-dashboard-btn")?.addEventListener("click", () => {
    loadDashboardStats();
    showToast("Telemetry refreshed", "info");
  });

  try {
    const resp = await apiFetch("/api/stats");
    if (!resp.ok) return;

    const s = await resp.json();
    const totalReq = s.total_requests || 0;

    // Update KPI Cards
    if ($("stat-total-requests")) $("stat-total-requests").textContent = totalReq.toLocaleString();
    if ($("stat-success-rate")) {
      $("stat-success-rate").textContent = totalReq > 0
        ? `Success: ${((s.success_rate || 0) * 100).toFixed(1)}%`
        : `Success: —`;
    }
    if ($("stat-savings-usd")) $("stat-savings-usd").textContent = `$${(s.estimated_savings_usd || s.savings_usd || 0).toFixed(6)}`;
    if ($("stat-savings-pct")) $("stat-savings-pct").textContent = `${(s.savings_percent || 0).toFixed(1)}% savings vs Tier 6 baseline`;

    const avgTotalLat = Math.round(Number(s.average_total_latency_ms) || 0);
    const avgGenLat = Math.round(Number(s.average_latency_ms) || 0);
    const baselineLat = 650;
    const speedupPct = (avgTotalLat > 0 && avgTotalLat < baselineLat) ? Math.round(((baselineLat - avgTotalLat) / baselineLat) * 100) : 0;

    if ($("stat-avg-latency")) $("stat-avg-latency").textContent = `${avgTotalLat} ms`;
    if ($("stat-analyzer-latency")) {
      $("stat-analyzer-latency").textContent = speedupPct > 0
        ? `Gen: ${avgGenLat} ms · +${speedupPct}% Speedup vs T6`
        : `Gen: ${avgGenLat} ms avg · Routing + Generation`;
    }
    if ($("stat-total-cost")) $("stat-total-cost").textContent = `$${(s.total_cost_usd || 0).toFixed(6)}`;
    if ($("stat-baseline-cost")) $("stat-baseline-cost").textContent = `Tier 6 Baseline: $${(s.baseline_cost_usd || 0).toFixed(6)}`;
    if ($("stat-total-tokens")) $("stat-total-tokens").textContent = (s.total_tokens || 0).toLocaleString();
    if ($("stat-fallbacks")) $("stat-fallbacks").textContent = (s.fallback_count || 0).toString();
    if ($("stat-escalations-sub")) $("stat-escalations-sub").textContent = `${s.escalations || s.escalation_count || 0} escalations · ${s.fallback_count || 0} failovers`;

    // Render Charts
    renderBarChart("chart-tier-dist", s.tier_distribution || []);
    renderBarChart("chart-model-dist", s.model_distribution || []);
    renderBarChart("chart-task-dist", s.task_distribution || []);
    renderBarChart("chart-complexity-dist", s.complexity_distribution || []);

    // Render LinUCB Bandit Arms Table
    const banditBody = $("bandit-arms-tbody");
    if (banditBody && s.bandit_arms) {
      const armEntries = Object.entries(s.bandit_arms);
      if (armEntries.length > 0) {
        banditBody.innerHTML = armEntries.map(([mid, arm]) => {
          const pulls = arm.pull_count || 0;
          const mean = arm.mean_reward != null ? Number(arm.mean_reward).toFixed(4) : "0.0000";
          const totalR = arm.total_reward != null ? Number(arm.total_reward).toFixed(4) : "0.0000";
          const alpha = arm.alpha != null ? Number(arm.alpha).toFixed(2) : "1.00";
          const statusText = pulls > 0 ? (arm.mean_reward > 0 ? "Converged Positive" : "Active Exploration") : "Cold / Unpulled";
          const statusColor = pulls > 0 ? (arm.mean_reward > 0 ? "#34D399" : "#FBBF24") : "#94A3B8";
          return `
            <tr>
              <td><strong>${escapeHtml(formatTierDisplay(mid))}</strong></td>
              <td><code>${escapeHtml(mid)}</code></td>
              <td><span style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;font-weight:600;">${pulls}</span></td>
              <td style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;color:${Number(totalR) >= 0 ? '#34D399' : '#F87171'};font-weight:600;">${totalR}</td>
              <td style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;color:#38BDF8; font-weight:600;">${mean}</td>
              <td style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;">${alpha}</td>
              <td><span style="display:inline-block; width:8px; height:8px; border-radius:50%; background:${statusColor}; margin-right:6px;"></span>${statusText}</td>
            </tr>
          `;
        }).join("");
      }
    }

    // Render Live History Table
    let requests = s.recent_requests || [];
    try {
      const histResp = await apiFetch("/api/history?limit=30");
      if (histResp.ok) {
        const histData = await histResp.json();
        if (Array.isArray(histData)) requests = histData;
      }
    } catch (_) {}

    renderHistoryTable(requests);
  } catch (err) {
    console.error("Failed to load telemetry stats:", err);
  }
}

function renderBarChart(containerId, data) {
  const container = $(containerId);
  if (!container) return;

  if (!data || data.length === 0) {
    container.innerHTML = `
      <div style="padding:16px 10px;text-align:center;font-size:12px;color:var(--text-muted);">
        No records yet
      </div>
    `;
    return;
  }

  const maxVal = Math.max(...data.map(d => Number(d.count) || 0), 1);
  const total = data.reduce((acc, d) => acc + (Number(d.count) || 0), 0) || 1;
  const isTierChart = containerId === "chart-tier-dist" || containerId.includes("tier");
  const isComplexityChart = containerId === "chart-complexity-dist" || containerId.includes("complexity");

  const rowHeight = 32;
  const totalHeight = Math.max(80, data.length * rowHeight + 12);
  const svgWidth = 460;
  const barStart = 165;
  const barMaxLen = 195;

  const rowsSvg = data.map((d, idx) => {
    const count = Number(d.count) || 0;
    const ratio = count / maxVal;
    const barWidth = Math.max(4, Math.round(ratio * barMaxLen));
    const share = Math.round((count / total) * 100);

    let label = String(d.name || "Unknown");
    if (isTierChart) {
      const fullTier = formatTierDisplay(d.name);
      label = fullTier.split(":")[0] + " " + fullTier.split("(")[0].replace(/^Tier\s*\d:\s*/i, "").trim();
    }

    const y = idx * rowHeight + 18;

    let hexColor = "#6366F1";
    if (isTierChart) {
      const s = String(d.name).toLowerCase();
      if (s.includes("1")) hexColor = "#38BDF8";
      else if (s.includes("2")) hexColor = "#FB923C";
      else if (s.includes("3")) hexColor = "#6366F1";
      else if (s.includes("4")) hexColor = "#30D158";
      else if (s.includes("5")) hexColor = "#C084FC";
      else if (s.includes("6")) hexColor = "#FF9F0A";
    } else if (isComplexityChart) {
      const c = String(d.name).toLowerCase();
      if (c.includes("low")) hexColor = "#30D158";
      else if (c.includes("med")) hexColor = "#FF9F0A";
      else if (c.includes("high")) hexColor = "#FF453A";
    } else {
      const n = String(d.name).toLowerCase();
      if (n.includes("code")) hexColor = "#10B981";
      else if (n.includes("reason")) hexColor = "#8B5CF6";
      else if (n.includes("fact")) hexColor = "#06B6D4";
      else if (n.includes("gemini")) hexColor = "#38BDF8";
      else if (n.includes("groq")) hexColor = "#F97316";
    }

    return `
      <g class="svg-bar-row" data-name="${escapeHtml(label)}" data-count="${count}" tabindex="0">
        <text x="4" y="${y + 4}" class="svg-bar-label">${escapeHtml(label)}</text>
        <rect x="${barStart}" y="${y - 7}" width="${barMaxLen}" height="14" rx="7" class="svg-bar-bg" />
        <rect x="${barStart}" y="${y - 7}" width="${barWidth}" height="14" rx="7" fill="${hexColor}" class="svg-bar-fill">
          <animate attributeName="width" from="0" to="${barWidth}" dur="0.32s" fill="freeze" calcMode="spline" keySplines="0.16 1 0.3 1" />
        </rect>
        <text x="${svgWidth - 4}" y="${y + 4}" text-anchor="end" class="svg-bar-val">${count} (${share}%)</text>
      </g>
    `;
  }).join("");

  container.innerHTML = `
    <svg class="distribution-svg" viewBox="0 0 ${svgWidth} ${totalHeight}" preserveAspectRatio="xMidYMid meet" role="img" aria-label="Routing distribution chart">
      ${rowsSvg}
    </svg>
  `;
}

function renderHistoryTable(requests) {
  const tbody = $("history-tbody");
  if (!tbody) return;

  if (!requests || requests.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="9" class="empty-state">
          No transactions recorded yet. Ask a question to begin live context-aware switching.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = requests.map(r => {
    const cost = r.total_cost_usd != null ? `$${r.total_cost_usd.toFixed(6)}` : "—";
    const statusIcon = r.success
      ? `<span style="color:var(--signal-emerald, #30D158);font-weight:600;">✓ Ok</span>`
      : `<span style="color:var(--signal-red, #FF453A);font-weight:600;">✗ Error</span>`;
    const fb = r.fallback_used
      ? `<span style="color:var(--signal-amber, #FF9F0A);font-weight:600;">Yes</span>`
      : `<span style="color:var(--text-muted);">No</span>`;
    const tierDisplay = formatTierDisplay(r.target_tier || r.tier);
    const latency = Math.round(Number(r.total_latency_ms || r.latency_ms) || 0);

    return `
      <tr data-action="open-inspector" data-id="${r.id}">
        <td><span style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;font-size:12px;">${escapeHtml(r.timestamp ? (r.timestamp.split(" ")[1] || r.timestamp) : "—")}</span></td>
        <td title="${escapeHtml(r.query)}" style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          ${escapeHtml(r.query)}
        </td>
        <td><span class="routing-tier-pill">${escapeHtml((r.task_type || "general").toUpperCase())}</span></td>
        <td>${escapeHtml(r.complexity || "medium")}</td>
        <td title="${escapeHtml(tierDisplay)}"><code>${escapeHtml(r.selected_model || "Model")}</code></td>
        <td><span style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;">${latency} ms</span></td>
        <td><span style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;font-weight:600;">${cost}</span></td>
        <td>${fb}</td>
        <td>${statusIcon}</td>
      </tr>
    `;
  }).join("");

  tbody.querySelectorAll("tr").forEach(row => {
    row.addEventListener("click", () => {
      const id = row.dataset.id;
      if (id) openInspectorModal(id);
    });
  });
}

/* ============================================================
   13. View 4: Research Benchmark Lab
   ============================================================ */
function setupBenchmarkView() {
  const runBtn = $("run-benchmark-btn");
  if (!runBtn) return;

  runBtn.addEventListener("click", async () => {
    runBtn.disabled = true;
    runBtn.innerHTML = `<span>⏳</span> Running Benchmark Suite...`;

    try {
      const resp = await apiFetch("/api/benchmark/run", {
        method: "POST",
        body: JSON.stringify({}),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Benchmark failed");

      const cards = $("benchmark-summary-cards");
      if (cards) cards.style.display = "grid";

      if ($("bm-overall-savings")) $("bm-overall-savings").textContent = `${data.overall_cost_savings_percent.toFixed(1)}%`;
      if ($("bm-saved-dollars")) $("bm-saved-dollars").textContent = `$${data.total_cost_saved_usd.toFixed(4)} saved across suite`;
      if ($("bm-overall-speedup")) $("bm-overall-speedup").textContent = `${data.overall_speedup_percent.toFixed(1)}%`;
      if ($("bm-smart-cost")) $("bm-smart-cost").textContent = `$${data.smart_total_cost_usd.toFixed(4)}`;
      if ($("bm-baseline-cost")) {
        const b2 = data.baseline2_total_cost_usd != null ? ` · vs B2: $${data.baseline2_total_cost_usd.toFixed(4)}` : "";
        $("bm-baseline-cost").textContent = `vs Baseline 1: $${data.baseline1_total_cost_usd.toFixed(4)}${b2}`;
      }

      // Render Matrix Table
      const tbody = $("benchmark-tbody");
      if (tbody && Array.isArray(data.items)) {
        tbody.innerHTML = data.items.map(item => {
          const savingsNum = Number(item.smart_savings_percent || 0);
          const speedupNum = Number(item.smart_speedup_percent || 0);
          const savingsClass = savingsNum > 0 ? "bm-savings-pill" : (savingsNum === 0 ? "bm-savings-pill neutral" : "bm-savings-pill negative");
          const speedupClass = speedupNum > 0 ? "bm-speedup-pill" : (speedupNum === 0 ? "bm-speedup-pill neutral" : "bm-speedup-pill negative");
          const dollarDelta = Math.max(0, (Number(item.baseline1_cost_usd || 0) - Number(item.smart_cost_usd || 0)));
          const deltaSub = dollarDelta > 0
            ? `<span style="display:block;font-size:10.5px;color:var(--text-muted);margin-top:2px;font-variant-numeric:tabular-nums;">-$${dollarDelta < 0.01 ? dollarDelta.toFixed(6) : dollarDelta.toFixed(4)}</span>`
            : "";

          return `
            <tr>
              <td>
                <strong class="bm-query-title">${escapeHtml(item.query)}</strong><br>
                <span style="font-size:11px;color:var(--text-muted);">${escapeHtml(item.task_type.toUpperCase())} · ${escapeHtml(item.complexity)}</span>
              </td>
              <td>
                <span class="bm-model-pill b1-model">${escapeHtml(item.baseline1_model)}</span><br>
                <span style="font-size:11px;color:var(--text-muted);font-variant-numeric:tabular-nums;">$${item.baseline1_cost_usd.toFixed(6)} · ${item.baseline1_latency_ms.toFixed(1)}ms</span>
              </td>
              <td>
                <span class="bm-model-pill b2-model">${escapeHtml(item.baseline2_model)}</span><br>
                <span style="font-size:11px;color:var(--text-muted);font-variant-numeric:tabular-nums;">$${item.baseline2_cost_usd.toFixed(6)} · ${item.baseline2_latency_ms.toFixed(1)}ms</span>
              </td>
              <td>
                <span class="bm-model-pill smart-model">${escapeHtml(item.smart_model)}</span><br>
                <span style="font-size:11px;color:var(--text-muted);font-variant-numeric:tabular-nums;">$${item.smart_cost_usd.toFixed(6)} · ${item.smart_latency_ms.toFixed(1)}ms</span>
              </td>
              <td>
                <span class="${savingsClass}">${savingsNum > 0 ? '+' : ''}${savingsNum.toFixed(1)}%</span>
                ${deltaSub}
              </td>
              <td><span class="${speedupClass}">${speedupNum > 0 ? '+' : ''}${speedupNum.toFixed(1)}%</span></td>
            </tr>
          `;
        }).join("");
      }

      showToast("Benchmark completed successfully", "success");
    } catch (err) {
      console.error("Benchmark error:", err);
      showToast(err.message, "error");
    } finally {
      runBtn.disabled = false;
      runBtn.innerHTML = `<span>▶</span> Run Multi-Domain Benchmark`;
    }
  });
}

/* ============================================================
   14. Settings & Provider Modal
   ============================================================ */
function setupSettingsModal() {
  const modal = $("settings-modal");
  const openBtn = $("open-settings-btn");
  const headerOpenBtn = $("header-settings-btn");
  const closeBtn = $("close-settings-btn");
  const backdrop = $("settings-backdrop");
  const saveBtn = $("save-settings-btn");
  const resetBtn = $("reset-settings-btn");
  const clearKeysBtn = $("clear-keys-btn");

  const openModal = async () => {
    modal?.classList.remove("hidden");
    await populateSettingsForm();
  };

  const closeModal = () => {
    modal?.classList.add("hidden");
  };

  openBtn?.addEventListener("click", openModal);
  headerOpenBtn?.addEventListener("click", openModal);
  closeBtn?.addEventListener("click", closeModal);
  backdrop?.addEventListener("click", closeModal);

  // Tab switching
  $$(".settings-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      $$(".settings-tab").forEach(t => t.classList.remove("active"));
      $$(".settings-panel").forEach(p => p.classList.remove("active"));

      tab.classList.add("active");
      const targetPanel = $(`tab-${tab.dataset.tab}`);
      if (targetPanel) targetPanel.classList.add("active");
    });
  });

  // Password mask toggles
  $$(".btn-toggle-mask").forEach(btn => {
    btn.addEventListener("click", () => {
      const targetInput = $(btn.dataset.target);
      if (targetInput) {
        targetInput.type = targetInput.type === "password" ? "text" : "password";
      }
    });
  });

  // Test provider connection buttons
  $$(".btn-test-conn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const prov = btn.dataset.provider;
      const statusBadge = $(`status-${prov}-test`);
      if (!statusBadge) return;

      statusBadge.textContent = "Testing...";
      statusBadge.className = "status-test-badge";

      const keyInput = $(`key-${prov}`);
      const apiKey = keyInput ? keyInput.value.trim() : "";
      const basePayload = { provider: prov };
      if (apiKey) basePayload.api_key = apiKey;

      if (prov === "custom") {
        basePayload.base_url = $("url-custom")?.value.trim() || "";
        basePayload.model = $("model-custom")?.value.trim() || "";
      }

      try {
        const resp = await apiFetch(`/api/providers/test/${prov}`, {
          method: "POST",
          body: JSON.stringify(basePayload),
        });
        const res = await resp.json();
        if (res.ok) {
          statusBadge.textContent = `Connected (${res.latency_ms} ms)`;
          statusBadge.className = "status-test-badge success";
        } else {
          statusBadge.textContent = res.message || "Failed";
          statusBadge.className = "status-test-badge error";
        }
      } catch (e) {
        statusBadge.textContent = "Error testing";
        statusBadge.className = "status-test-badge error";
      }
    });
  });

  // Save Settings
  saveBtn?.addEventListener("click", async () => {
    const settings = await SettingsManager.load();

    settings.apiKeys.gemini = $("key-gemini")?.value.trim() || "";
    settings.apiKeys.groq = $("key-groq")?.value.trim() || "";
    settings.apiKeys.openrouter = $("key-openrouter")?.value.trim() || "";
    settings.apiKeys.openai = $("key-openai")?.value.trim() || "";
    settings.apiKeys.custom = $("key-custom")?.value.trim() || "";

    settings.customEndpoints.custom = $("url-custom")?.value.trim() || "";

    settings.providerModels.geminiTier1 = $("model-gemini-tier1")?.value.trim() || "gemini-3.5-flash-lite";
    settings.providerModels.geminiTier3 = $("model-gemini-tier3")?.value.trim() || "gemini-3.6-flash";
    settings.providerModels.geminiTier6 = $("model-gemini-tier6")?.value.trim() || "gemini-3.8-flash";
    settings.providerModels.groqTier2 = $("model-groq-tier2")?.value.trim() || "openai/gpt-oss-20b";
    settings.providerModels.groqTier4 = $("model-groq-tier4")?.value.trim() || "qwen/qwen3.8-27b";
    settings.providerModels.groqTier5 = $("model-groq-tier5")?.value.trim() || "openai/gpt-oss-120b";
    settings.providerModels.custom = $("model-custom")?.value.trim() || "";

    await SettingsManager.save(settings);
    showToast("Settings saved securely", "success");
    closeModal();
    checkEngineHealth();
    loadRegistryModels();
  });

  // Reset Defaults
  resetBtn?.addEventListener("click", async () => {
    if (confirm("Reset settings to defaults?")) {
      const defs = SettingsManager.getDefaults();
      await SettingsManager.save(defs);
      await populateSettingsForm();
      showToast("Reset to default settings", "info");
    }
  });

  // Clear Keys
  clearKeysBtn?.addEventListener("click", async () => {
    if (confirm("Clear all configured API keys?")) {
      await SettingsManager.clearKeys();
      await populateSettingsForm();
      showToast("All API keys cleared", "info");
      checkEngineHealth();
    }
  });
}

async function populateSettingsForm() {
  const settings = await SettingsManager.load();

  if ($("key-gemini")) $("key-gemini").value = settings.apiKeys.gemini || "";
  if ($("key-groq")) $("key-groq").value = settings.apiKeys.groq || "";
  if ($("key-openrouter")) $("key-openrouter").value = settings.apiKeys.openrouter || "";
  if ($("key-openai")) $("key-openai").value = settings.apiKeys.openai || "";
  if ($("key-custom")) $("key-custom").value = settings.apiKeys.custom || "";

  if ($("url-custom")) $("url-custom").value = settings.customEndpoints.custom || "";
  if ($("model-custom")) $("model-custom").value = settings.providerModels.custom || "";

  if ($("model-gemini-tier1")) $("model-gemini-tier1").value = settings.providerModels.geminiTier1 || "gemini-3.5-flash-lite";
  if ($("model-gemini-tier3")) $("model-gemini-tier3").value = settings.providerModels.geminiTier3 || "gemini-3.6-flash";
  if ($("model-gemini-tier6")) $("model-gemini-tier6").value = settings.providerModels.geminiTier6 || "gemini-3.8-flash";

  if ($("model-groq-tier2")) $("model-groq-tier2").value = settings.providerModels.groqTier2 || "openai/gpt-oss-20b";
  if ($("model-groq-tier4")) $("model-groq-tier4").value = settings.providerModels.groqTier4 || "qwen/qwen3.8-27b";
  if ($("model-groq-tier5")) $("model-groq-tier5").value = settings.providerModels.groqTier5 || "openai/gpt-oss-120b";
}

async function checkEngineHealth() {
  try {
    const resp = await apiFetch("/health");
    if (!resp.ok) return;

    const data = await resp.json();
    const mode = data.mode || "demo";

    const badge = $("engine-status-badge");
    const text = $("engine-status-text");
    const dot = $("sidebar-provider-dot");

    if (mode === "real") {
      if (text) text.textContent = "Router Online · Real API";
      if (dot) dot.className = "status-dot-indicator";
    } else {
      if (text) text.textContent = "Router Online · Demo Mode";
      if (dot) dot.className = "status-dot-indicator warning";
    }
  } catch (err) {
    const text = $("engine-status-text");
    const dot = $("sidebar-provider-dot");
    if (text) text.textContent = "Router Offline";
    if (dot) dot.className = "status-dot-indicator error";
  }
}

/* ============================================================
   15. Telemetry Inspector Modal
   ============================================================ */
function setupInspectorModal() {
  const modal = $("inspector-modal");
  const closeBtn = $("close-inspector-btn");
  const backdrop = $("inspector-backdrop");

  const closeModal = () => modal?.classList.add("hidden");
  closeBtn?.addEventListener("click", closeModal);
  backdrop?.addEventListener("click", closeModal);
}

function resolve16DFeatures(query, data) {
  if (Array.isArray(data.feature_vector) && data.feature_vector.length === 16) {
    const dimNames = [
      "d1: Code & Syntax", "d2: DSA & Algorithms", "d3: Mathematics", "d4: Deductive Logic",
      "d5: Social & Chit-Chat", "d6: Token Density", "d7: Factual QA", "d8: System Design",
      "d9: Data & SQL", "d10: Error Diagnostics", "d11: Structured Output", "d12: Multi-Turn Memory",
      "d13: Low-Latency Velocity", "d14: Synthesis", "d15: Abstract Logic", "d16: Frontier Capability"
    ];
    return data.feature_vector.map((val, i) => ({
      dim: `d${i + 1}`,
      label: dimNames[i] || `Dimension ${i + 1}`,
      val: Number(val)
    }));
  }

  const q = String(query || "").toLowerCase();
  const task = String(data.task_type || "").toLowerCase();
  const comp = String(data.complexity || "").toLowerCase();
  const cScore = Number(data.complexity_score || (comp.includes("high") ? 0.85 : comp.includes("low") ? 0.25 : 0.5));

  const has = (terms) => terms.some(t => q.includes(t));

  const f1 = has(["def ", "class ", "import ", "function", "const ", "let ", "var ", "return ", "{", "}", "()", "=>", "python", "javascript", "c++", "rust"]) ? 0.88 : (task.includes("code") ? 0.72 : 0.08);
  const f2 = has(["binary search", "dijkstra", "algorithm", "tree", "graph", "dynamic programming", "dp", "sort", "recursion", "time complexity", "o(n)"]) ? 0.94 : (task.includes("code") ? 0.35 : 0.05);
  const f3 = has(["calculus", "derivative", "integral", "matrix", "eigenvalue", "equation", "proof", "solve", "dx", "pi", "algebra", "theorem"]) ? 0.91 : (task.includes("reason") ? 0.40 : 0.04);
  const f4 = has(["prove", "contradiction", "deduce", "syllogism", "logic", "puzzle", "truth table", "modus ponens", "induction"]) ? 0.89 : (task.includes("reason") ? 0.55 : 0.06);
  const f5 = has(["hi", "hello", "hey", "how are you", "good morning", "thanks", "thank you", "bye", "who are you"]) ? 0.95 : 0.03;
  const f6 = Math.min(1.0, (q.length / 300) * 0.8 + 0.1);
  const f7 = has(["what is", "capital", "when was", "who is", "definition", "explain", "meaning of", "where is"]) ? 0.82 : 0.15;
  const f8 = has(["distributed", "kafka", "microservices", "throughput", "concurrency", "load balancer", "database", "cluster", "sharding"]) ? 0.92 : 0.05;
  const f9 = has(["select", "join", "from", "where", "group by", "sql", "index", "table", "schema", "query"]) ? 0.90 : 0.04;
  const f10 = has(["error", "traceback", "exception", "failed", "bug", "crash", "segmentation fault", "nullpointer", "fix"]) ? 0.87 : 0.05;
  const f11 = has(["json", "yaml", "xml", "markdown", "table", "csv", "list", "format", "schema"]) ? 0.78 : 0.12;
  const f12 = Number(data.context_relevant) === 1 || Number(data.history_turns || 0) > 0 ? 0.75 : 0.10;
  const f13 = f5 > 0.6 || q.length < 40 ? 0.85 : 0.20;
  const f14 = has(["summary", "summarize", "write an essay", "article", "creative", "rephrase", "tone"]) ? 0.81 : 0.18;
  const f15 = has(["riddle", "chess", "sudoku", "counterfactual", "optimal", "game theory"]) ? 0.86 : 0.10;
  const f16 = (cScore >= 0.7 || f8 > 0.8 || f4 > 0.8) ? Math.min(1.0, cScore + 0.1) : 0.12;

  const raw = [
    { dim: "d1", label: "Software & Code Syntax", val: f1 },
    { dim: "d2", label: "Algorithmic & DSA Depth", val: f2 },
    { dim: "d3", label: "Mathematics & Calculus", val: f3 },
    { dim: "d4", label: "Deductive Proofs & Logic", val: f4 },
    { dim: "d5", label: "Conversational / Social", val: f5 },
    { dim: "d6", label: "Token / Context Density", val: f6 },
    { dim: "d7", label: "Factual Knowledge / QA", val: f7 },
    { dim: "d8", label: "Distributed Architecture", val: f8 },
    { dim: "d9", label: "Data Engineering / SQL", val: f9 },
    { dim: "d10", label: "Error Diagnostic Signature", val: f10 },
    { dim: "d11", label: "Structured Constraints", val: f11 },
    { dim: "d12", label: "Multi-Turn Memory Drift", val: f12 },
    { dim: "d13", label: "Low-Latency Affinity", val: f13 },
    { dim: "d14", label: "Creative Synthesis", val: f14 },
    { dim: "d15", label: "Abstract Constraints", val: f15 },
    { dim: "d16", label: "Frontier Capability Need", val: f16 },
  ];

  const norm = Math.sqrt(raw.reduce((sum, d) => sum + (d.val * d.val), 0)) || 1.0;
  return raw.map(d => ({
    ...d,
    val: Math.round((d.val / norm) * 1000) / 1000
  }));
}

function renderLinUCBScoreboard(candidates, selectedModel) {
  if (!Array.isArray(candidates) || candidates.length === 0) return "";

  const rows = candidates.map(c => {
    const isSelected = Boolean(c.selected) || (c.model_id === selectedModel);
    const ucbTotal = c.total != null ? Number(c.total).toFixed(4) : "—";
    const factors = c.factors || {};
    const expectedR = factors.expected_reward != null ? Number(factors.expected_reward).toFixed(4) : (c.linucb_score != null ? Number(c.linucb_score).toFixed(4) : "—");
    const exploration = factors.exploration != null ? Number(factors.exploration).toFixed(4) : "—";
    const tierDisplay = (c.tier || "tier").toUpperCase();
    const costUsd = c.expected_cost_usd != null ? `$${Number(c.expected_cost_usd).toFixed(6)}` : "—";
    const latMs = c.expected_latency_ms != null ? `~${Math.round(c.expected_latency_ms)}ms` : "—";

    return `
      <tr class="${isSelected ? 'selected-arm-row' : ''}">
        <td>
          <div style="display:flex;align-items:center;gap:6px;">
            <span class="routing-tier-pill" style="font-size:10px;padding:1px 5px;">${escapeHtml(tierDisplay)}</span>
            <strong style="font-size:12px;">${escapeHtml(c.name || c.model_id)}</strong>
          </div>
        </td>
        <td><span style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;font-weight:700;color:${isSelected ? 'var(--signal-emerald, #30D158)' : 'var(--text-primary)'};">${ucbTotal}</span></td>
        <td><span style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;font-size:11.5px;color:#38BDF8;">${expectedR}</span></td>
        <td><span style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;font-size:11.5px;color:#FBBF24;">+${exploration}</span></td>
        <td><span style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;font-size:11.5px;">${costUsd}</span></td>
        <td><span style="font-family:var(--font-mono, monospace);font-variant-numeric:tabular-nums;font-size:11.5px;">${latMs}</span></td>
        <td>
          ${isSelected
            ? `<span class="arm-status-badge selected">✓ Routed Arm</span>`
            : `<span class="arm-status-badge candidate">Candidate</span>`}
        </td>
      </tr>
    `;
  }).join("");

  return `
    <div class="inspector-section-block">
      <div class="inspector-section-header">
        <span class="drawer-cell-label">LinUCB Bandit Scoreboard &amp; Arm Weights</span>
        <span class="inspector-section-hint">p_{a,t} = x_t^T θ̂_a + α √(x_t^T A_a^{-1} x_t)</span>
      </div>
      <div class="table-responsive" style="margin-top:6px;">
        <table class="data-table inspector-scoreboard-table">
          <thead>
            <tr>
              <th>Model Arm &amp; Tier</th>
              <th>UCB Score (p)</th>
              <th>Expected Reward (μ̂)</th>
              <th>Exploration (α·σ)</th>
              <th>Exp. Cost</th>
              <th>Exp. Latency</th>
              <th>Decision</th>
            </tr>
          </thead>
          <tbody>
            ${rows}
          </tbody>
        </table>
      </div>
    </div>
  `;
}

function render16DFeatureGrid(features) {
  const cells = features.map(f => {
    const pct = Math.min(100, Math.max(0, Math.round(f.val * 100)));
    return `
      <div class="feature-dim-cell" title="${escapeHtml(f.label)}: ${f.val}">
        <div class="feature-dim-header">
          <span class="feature-dim-label">${escapeHtml(f.label)}</span>
          <span class="feature-dim-val">${f.val >= 0 ? '+' : ''}${f.val.toFixed(3)}</span>
        </div>
        <div class="feature-dim-track">
          <div class="feature-dim-bar" style="width:${pct}%;"></div>
        </div>
      </div>
    `;
  }).join("");

  return `
    <div class="inspector-section-block">
      <div class="inspector-section-header">
        <span class="drawer-cell-label">Contextual LinUCB 16D Feature Vector (x_t ∈ ℝ¹⁶)</span>
        <span class="inspector-section-hint">TF-IDF + TruncatedSVD Latent Embeddings</span>
      </div>
      <div class="features-16d-grid">
        ${cells}
      </div>
    </div>
  `;
}

async function openInspectorModal(requestId) {
  const modal = $("inspector-modal");
  const body = $("modal-body");
  const title = $("modal-title");
  if (!modal || !body) return;

  modal.classList.remove("hidden");
  if (title) title.innerHTML = `<svg class='icon-sym'><use href='#i-search'/></svg> Request #${requestId} Telemetry`;
  body.innerHTML = `<div style="text-align:center;padding:24px;color:var(--text-muted);">Loading telemetry record...</div>`;

  try {
    const resp = await apiFetch(`/api/requests/${requestId}`);
    if (!resp.ok) throw new Error("Request record not found");

    const d = await resp.json();
    const servedModel = d.selected_model || d.model || "Unknown Model";
    const provider = d.provider || "gateway";
    const tierName = formatTierDisplay(d.target_tier ?? d.tier);
    const cost = Number(d.total_cost_usd ?? d.estimated_cost ?? 0);
    const latency = Math.round(Number(d.total_latency_ms ?? d.latency_ms ?? 0));
    const tokens = Number(d.total_tokens ?? 0);
    const promptTokens = Number(d.prompt_tokens ?? 0);
    const completionTokens = Number(d.completion_tokens ?? 0);
    const strategy = d.strategy || "Balanced";
    const rawQuery = d.query || d.prompt || "(No prompt captured)";
    const jsonString = JSON.stringify(d, null, 2);

    const features16d = resolve16DFeatures(rawQuery, d);
    const scoreboardHtml = renderLinUCBScoreboard(d.candidates, servedModel);
    const featuresHtml = render16DFeatureGrid(features16d);

    body.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:14px;">
        <div class="inspector-prompt-box">
          <span class="inspector-prompt-label">Prompt Query</span>
          <div class="inspector-prompt-text">${escapeHtml(rawQuery)}</div>
        </div>

        <div class="drawer-grid">
          <div class="drawer-cell">
            <span class="drawer-cell-label">Served Model</span>
            <span class="drawer-cell-val">${escapeHtml(servedModel)} <span style="font-size:11px;color:var(--text-muted);font-weight:normal;">(${escapeHtml(provider)})</span></span>
          </div>
          <div class="drawer-cell">
            <span class="drawer-cell-label">Tier</span>
            <span class="drawer-cell-val text-blue">${escapeHtml(tierName.split(":")[0] || "Tier")}</span>
          </div>
          <div class="drawer-cell">
            <span class="drawer-cell-label">Total Cost (USD)</span>
            <span class="drawer-cell-val text-green">$${cost.toFixed(6)}</span>
          </div>
          <div class="drawer-cell">
            <span class="drawer-cell-label">Latency</span>
            <span class="drawer-cell-val">${latency.toLocaleString()} ms</span>
          </div>
          <div class="drawer-cell">
            <span class="drawer-cell-label">Tokens Metered</span>
            <span class="drawer-cell-val" title="In: ${promptTokens.toLocaleString()} | Out: ${completionTokens.toLocaleString()}">${tokens.toLocaleString()} <span style="font-size:11px;color:var(--text-muted);font-weight:normal;">(${promptTokens} / ${completionTokens})</span></span>
          </div>
          <div class="drawer-cell">
            <span class="drawer-cell-label">Routing Strategy</span>
            <span class="drawer-cell-val" style="text-transform:capitalize;">${escapeHtml(strategy)}</span>
          </div>
        </div>

        ${scoreboardHtml}

        ${featuresHtml}

        <div class="inspector-json-header">
          <span class="drawer-cell-label">Complete Telemetry JSON</span>
          <button type="button" class="btn-copy-json" id="btn-copy-app-inspector-json" title="Copy raw JSON telemetry">
            <svg class="icon-sym" aria-hidden="true"><use href="#i-copy"/></svg>
            <span>Copy JSON</span>
          </button>
        </div>
        <pre class="inspector-json-pre"><code id="app-inspector-json-code">${escapeHtml(jsonString)}</code></pre>
      </div>
    `;

    const copyBtn = $("btn-copy-app-inspector-json");
    if (copyBtn) {
      copyBtn.addEventListener("click", async () => {
        try {
          if (navigator.clipboard) await navigator.clipboard.writeText(jsonString);
          const span = copyBtn.querySelector("span");
          if (span) span.textContent = "Copied!";
          showToast("Telemetry JSON copied to clipboard", "success");
          setTimeout(() => { if (span) span.textContent = "Copy JSON"; }, 1800);
        } catch (_) {
          showToast("Failed to copy JSON", "error");
        }
      });
    }
  } catch (err) {
    body.innerHTML = `<div style="color:var(--signal-red);padding:16px;">Failed to load request: ${escapeHtml(err.message)}</div>`;
  }
}

/* ============================================================
   16. Utilities: Markdown, LaTeX Math, Scrolling, Toasts
   ============================================================ */
function formatMarkdown(text) {
  if (!text) return "";
  try {
    if (typeof marked !== "undefined") {
      const renderer = new marked.Renderer();
      renderer.code = function(code, lang) {
        const language = (lang || 'code').trim();
        let codeHtml = escapeHtml(code);
        if (typeof hljs !== "undefined" && language && language !== "code" && hljs.getLanguage && hljs.getLanguage(language)) {
          try {
            codeHtml = hljs.highlight(code, { language }).value;
          } catch (_) {}
        }
        return `<div class="code-block-wrap">
          <div class="code-block-header">
            <div class="code-header-left">
              <span class="window-dot red"></span>
              <span class="window-dot yellow"></span>
              <span class="window-dot green"></span>
              <span class="code-lang-tag">${escapeHtml(language)}</span>
            </div>
            <button type="button" class="btn-copy-code" title="Copy code snippet">
              <svg class="icon-sym" aria-hidden="true"><use href="#i-copy"/></svg>
              <span>Copy</span>
            </button>
          </div>
          <pre class="code-block-pre"><code class="language-${escapeHtml(language)}">${codeHtml}</code></pre>
        </div>`;
      };

      marked.setOptions({
        renderer: renderer,
        gfm: true,
        breaks: true,
      });
      const rawHtml = marked.parse(text);
      if (typeof DOMPurify !== "undefined") {
        return DOMPurify.sanitize(rawHtml, {
          ADD_TAGS: ['use', 'svg', 'details', 'summary'],
          ADD_ATTR: ['href', 'target', 'open']
        });
      }
      return rawHtml;
    }
  } catch (e) {
    console.warn("Markdown parsing failed:", e);
  }
  return escapeHtml(text);
}

function _renderMathInElement(elem) {
  if (!elem) return;
  try {
    if (typeof renderMathInElement === "function") {
      renderMathInElement(elem, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\[", right: "\\]", display: true },
          { left: "\\(", right: "\\)", display: false }
        ],
        throwOnError: false,
      });
    }
  } catch (e) {
    console.warn("KaTeX render failed:", e);
  }
}

function smoothScrollToBottom(container) {
  if (!container || isUserScrolledUp) return;
  if (typeof container.scrollTo === "function") {
    container.scrollTo({
      top: container.scrollHeight,
      behavior: "smooth",
    });
  } else {
    container.scrollTop = container.scrollHeight;
  }
}

function setupCodeCopyHandler() {
  document.addEventListener("click", (e) => {
    const copyBtn = e.target.closest(".btn-copy-code");
    if (!copyBtn) return;
    const wrap = copyBtn.closest(".code-block-wrap");
    const codeElem = wrap ? wrap.querySelector("code") : null;
    const textToCopy = codeElem ? (codeElem.innerText || codeElem.textContent) : "";
    if (!textToCopy) return;

    const setSuccess = () => {
      const span = copyBtn.querySelector("span");
      if (span) span.textContent = "Copied!";
      copyBtn.classList.add("copied");
      setTimeout(() => {
        if (span) span.textContent = "Copy";
        copyBtn.classList.remove("copied");
      }, 1800);
      showToast("Code copied to clipboard", "success");
    };

    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(textToCopy).then(setSuccess).catch(() => {
        const ta = document.createElement("textarea");
        ta.value = textToCopy;
        ta.style.position = "fixed";
        ta.style.opacity = "0";
        document.body.appendChild(ta);
        ta.select();
        try {
          document.execCommand("copy");
          setSuccess();
        } catch (_) {
          showToast("Failed to copy code", "error");
        }
        document.body.removeChild(ta);
      });
    } else {
      const ta = document.createElement("textarea");
      ta.value = textToCopy;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy");
        setSuccess();
      } catch (_) {
        showToast("Failed to copy code", "error");
      }
      document.body.removeChild(ta);
    }
  });
}

function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

function showToast(message, type = "info") {
  const container = $("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    toast.style.transition = "all 0.2s ease";
    setTimeout(() => toast.remove(), 200);
  }, 2800);
}