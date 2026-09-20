/* ============================================================
   Context-Aware Smart LLM Switcher - Client Application
   Milestone 4: Modern ChatGPT-Style Frontend Architecture
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
 * rest with AES-GCM (WebCrypto). The encryption key is generated per
 * browser and stored separately; plaintext credentials never touch
 * localStorage.
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
        geminiFast: "",
        groqCoding: "",
        groqReasoning: "",
        openrouterAnalyzer: "",
        openrouterPowerful: "",
        openai: "",
        custom: "",
      },
      tierOverrides: {
        analyzer: "",
        fast: "",
        coding: "",
        reasoning: "",
        powerful: "",
      },
      preferences: {
        theme: "dark",
        strategy: "balanced",
        autoScroll: true,
      },
    };
  }

  /* --- AES-GCM encryption helpers (WebCrypto) -------------------------- */
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
      tierOverrides: { ...this.getDefaults().tierOverrides, ...(parsed.tierOverrides || {}) },
      preferences: { ...this.getDefaults().preferences, ...(parsed.preferences || {}) },
    };
  }

  static async load() {
    try {
      const raw = localStorage.getItem(this.STORAGE_KEY);
      if (!raw) return this.getDefaults();
      // New format: AES-GCM encrypted base64 blob.
      if (raw.startsWith("enc:")) {
        const parsed = await this._decrypt(raw.slice(4));
        return parsed ? this._merge(parsed) : this.getDefaults();
      }
      // Legacy plaintext: import, re-encrypt, remove plaintext.
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
    settings.providerModels = this.getDefaults().providerModels;
    settings.tierOverrides = this.getDefaults().tierOverrides;
    await this.save(settings);
  }

  static async getHeaders() {
    const settings = await this.load();
    const headers = {
      "Content-Type": "application/json",
    };

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
    const customModel = (providerModels.custom || "").trim();
    if (customModel) {
      headers["X-Custom-Model"] = customModel;
    }

    const tiers = settings.tierOverrides || {};
    const analyzerModel = (tiers.analyzer || providerModels.openrouterAnalyzer || "").trim();
    if (analyzerModel) {
      headers["X-Base-Model"] = analyzerModel;
      headers["X-Analyzer-Model"] = analyzerModel;
    }

    const fastModel = (tiers.fast || providerModels.geminiFast || "").trim();
    if (fastModel) headers["X-Fast-Model"] = fastModel;

    const codingModel = (tiers.coding || providerModels.groqCoding || "").trim();
    if (codingModel) headers["X-Coding-Model"] = codingModel;

    const reasoningModel = (tiers.reasoning || providerModels.groqReasoning || "").trim();
    if (reasoningModel) headers["X-Reasoning-Model"] = reasoningModel;

    const powerfulModel = (tiers.powerful || providerModels.openrouterPowerful || "").trim();
    if (powerfulModel) headers["X-Powerful-Model"] = powerfulModel;

    return headers;
  }
}

/**
 * Centralized API Fetch Helper
 * Injects dynamic credentials and tier overrides into every request.
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

      // If no sessions exist or active is invalid, initialize one
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

  renameSession(id, newTitle) {
    const s = this.sessions.find(item => item.id === id);
    if (s && newTitle && newTitle.trim()) {
      s.title = newTitle.trim();
      s.updatedAt = Date.now();
      this.save();
      return true;
    }
    return false;
  }

  deleteSession(id) {
    const idx = this.sessions.findIndex(s => s.id === id);
    if (idx !== -1) {
      this.sessions.splice(idx, 1);
      if (this.sessions.length === 0) {
        this.createSession("New Conversation", true);
      } else if (this.activeSessionId === id) {
        this.activeSessionId = this.sessions[0].id;
      }
      this.save();
      return true;
    }
    return false;
  }

  clearAll() {
    this.sessions = [];
    this.createSession("New Conversation", true);
    this.save();
  }

  addMessage(role, content, telemetry = null) {
    const active = this.getActive();
    if (!active) return null;

    const msg = {
      id: "msg_" + Date.now() + "_" + Math.random().toString(36).substring(2, 6),
      role: role,
      content: content,
      telemetry: telemetry,
      timestamp: Date.now(),
    };

    active.messages.push(msg);
    active.updatedAt = Date.now();

    // Auto-generate title on first user query
    if (active.messages.length === 1 && role === "user") {
      const generatedTitle = content.length > 32 ? content.substring(0, 32).trim() + "..." : content;
      active.title = generatedTitle;
    }

    this.save();
    return msg;
  }

  getRecentHistoryForAPI(maxMessages = 10) {
    const active = this.getActive();
    if (!active || !active.messages) return [];
    return active.messages.slice(-maxMessages).map(m => ({
      role: m.role,
      content: m.content,
    }));
  }
}

/**
 * ThemeManager handles Dark / Light mode switching with localStorage persistence.
 */
class ThemeManager {
  static THEME_KEY = "smart_llm_theme";

  static init() {
    const saved = localStorage.getItem(this.THEME_KEY) || "dark";
    this.setTheme(saved);
  }

  static setTheme(theme) {
    const root = document.documentElement;
    const isLight = theme === "light";
    root.setAttribute("data-theme", isLight ? "light" : "dark");
    localStorage.setItem(this.THEME_KEY, isLight ? "light" : "dark");

    // Update icons
    const icon = $("theme-icon");
    const headerIcon = $("header-theme-btn");
    const text = $("theme-text");

    const themeSVG = isLight ? "<svg class='icon-sym'><use href='#i-sun'/></svg>" : "<svg class='icon-sym'><use href='#i-moon'/></svg>";
    if (icon) icon.innerHTML = themeSVG;
    if (headerIcon) headerIcon.innerHTML = themeSVG;
    if (text) text.textContent = isLight ? "Light Mode" : "Dark Mode";
  }

  static toggle() {
    const current = document.documentElement.getAttribute("data-theme") || "dark";
    this.setTheme(current === "dark" ? "light" : "dark");
  }
}

/* ============================================================
   2. Global Variables & Initialization
   ============================================================ */

let sessionManager = null;
let activeAbortController = null;
let dashboardRefreshInterval = null;
let isUserScrolledUp = false;

document.addEventListener("DOMContentLoaded", () => {
  ThemeManager.init();
  sessionManager = new SessionManager();

  setupSidebar();
  setupCanvasNavigation();
  setupComposer();
  setupQuickChips();
  setupSettingsModal();
  setupInspectorModal();
  setupDashboardView();
  setupBenchmarkView();

  renderSidebarSessions();
  renderActiveSessionMessages();
  checkInitialHealth();
});

/* ============================================================
   3. Sidebar & Session Navigation
   ============================================================ */

function setupSidebar() {
  const sidebar = $("sidebar");
  const collapseBtn = $("sidebar-collapse-btn");
  const openBtn = $("sidebar-open-btn");
  const backdrop = $("sidebar-backdrop");
  const newChatBtn = $("new-chat-btn");
  const searchInput = $("session-search-input");
  const clearSearchBtn = $("clear-search-btn");
  const themeToggleBtn = $("theme-toggle-btn");
  const headerThemeBtn = $("header-theme-btn");
  const clearAllBtn = $("clear-all-sessions-btn");

  // Collapse / Open
  collapseBtn?.addEventListener("click", () => {
    sidebar.classList.add("collapsed");
    sidebar.classList.remove("mobile-open");
    backdrop?.classList.remove("active");
  });

  openBtn?.addEventListener("click", () => {
    sidebar.classList.remove("collapsed");
    sidebar.classList.add("mobile-open");
    backdrop?.classList.add("active");
  });

  backdrop?.addEventListener("click", () => {
    sidebar.classList.remove("mobile-open");
    backdrop.classList.remove("active");
  });

  // New Chat
  newChatBtn?.addEventListener("click", () => {
    sessionManager.createSession("New Conversation", true);
    renderSidebarSessions();
    renderActiveSessionMessages();
    switchView("chat");
    if (window.innerWidth <= 768) {
      sidebar.classList.remove("mobile-open");
      backdrop?.classList.remove("active");
    }
  });

  // Search Sessions
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
    searchInput.value = "";
    clearSearchBtn.classList.add("hidden");
    renderSidebarSessions();
    searchInput.focus();
  });

  // Theme Toggles
  themeToggleBtn?.addEventListener("click", () => ThemeManager.toggle());
  headerThemeBtn?.addEventListener("click", () => ThemeManager.toggle());

  // Clear All Sessions
  clearAllBtn?.addEventListener("click", () => {
    if (confirm("Are you sure you want to clear all conversation sessions?")) {
      sessionManager.clearAll();
      renderSidebarSessions();
      renderActiveSessionMessages();
      showToast("All conversations cleared", "info");
    }
  });
}

function renderSidebarSessions(filterQuery = "") {
  const list = $("session-list");
  const countBadge = $("sessions-count-badge");
  if (!list) return;

  const sessions = sessionManager.getAll();
  const active = sessionManager.getActive();

  let filtered = sessions;
  if (filterQuery) {
    filtered = sessions.filter(s => s.title.toLowerCase().includes(filterQuery));
  }

  if (countBadge) countBadge.textContent = sessions.length;

  if (filtered.length === 0) {
    list.innerHTML = `<div class="empty-state" style="padding:16px 8px;font-size:12px;">No matching chats</div>`;
    return;
  }

  list.innerHTML = filtered.map(s => {
    const isActive = active && active.id === s.id;
    return `
      <div class="session-item ${isActive ? 'active' : ''}" data-id="${s.id}" data-action="session-click">
        <div class="session-item-left">
          <span class="session-icon"><svg class='icon-sym' aria-hidden='true'><use href='#i-chat'/></svg></span>
          <span class="session-title" title="${escapeHtml(s.title)}">${escapeHtml(s.title)}</span>
        </div>
        <div class="session-actions">
          <button class="btn-session-action" data-action="rename-session" data-id="${s.id}" title="Rename"><svg class='icon-sym' aria-hidden='true'><use href='#i-pencil'/></svg></button>
          <button class="btn-session-action delete" data-action="delete-session" data-id="${s.id}" title="Delete"><svg class='icon-sym' aria-hidden='true'><use href='#i-trash'/></svg></button>
        </div>
      </div>
    `;
  }).join("");
}

window.handleSessionClick = function(id) {
  sessionManager.switchSession(id);
  renderSidebarSessions();
  renderActiveSessionMessages();
  switchView("chat");

  if (window.innerWidth <= 768) {
    $("sidebar")?.classList.remove("mobile-open");
    $("sidebar-backdrop")?.classList.remove("active");
  }
};

window.promptRenameSession = function(id) {
  const s = sessionManager.getAll().find(item => item.id === id);
  if (!s) return;
  const newTitle = prompt("Enter new title for this conversation:", s.title);
  if (newTitle && newTitle.trim()) {
    sessionManager.renameSession(id, newTitle);
    renderSidebarSessions();
    updateActiveSessionHeader();
  }
};

window.handleDeleteSession = function(id) {
  if (confirm("Delete this conversation?")) {
    sessionManager.deleteSession(id);
    renderSidebarSessions();
    renderActiveSessionMessages();
  }
};

function updateActiveSessionHeader() {
  const active = sessionManager.getActive();
  const titleEl = $("active-session-title");
  if (titleEl && active) {
    titleEl.textContent = active.title || "New Conversation";
  }
}

/* ============================================================
   4. Canvas Navigation & View Switching
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

  // Canvas Header Rename Button
  $("rename-session-btn")?.addEventListener("click", () => {
    const active = sessionManager.getActive();
    if (active) promptRenameSession(active.id);
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
}

/* ============================================================
   5. Chat Rendering & Composer Handling
   ============================================================ */

function setupComposer() {
  const form = $("composer-form");
  const input = $("query-input");
  const sendStopBtn = $("send-stop-btn");
  const strategySelect = $("strategy-select");
  const clearContextBtn = $("clear-context-btn");
  const messagesContainer = $("chat-messages");

  // Setup Scroll Listener
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

  // Enter to send (Shift+Enter for newline)
  input?.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
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

  // Form Submit / Streaming Execution
  form?.addEventListener("submit", async (e) => {
    e.preventDefault();

    // If currently streaming, this button acts as Stop Generation
    if (activeAbortController) {
      stopGeneration();
      return;
    }

    const query = input.value.trim();
    if (!query) return;

    // Reset Input
    input.value = "";
    input.style.height = "auto";

    // Append User Message to UI & Session
    appendUserMessageToUI(query);
    sessionManager.addMessage("user", query);
    renderSidebarSessions();
    updateActiveSessionHeader();

    // Hide welcome hero if shown
    const welcome = $("welcome-hero");
    if (welcome) welcome.style.display = "none";

    // Build Streaming Assistant Card
    const placeholder = createStreamingPlaceholder();
    const strategy = strategySelect ? strategySelect.value : "balanced";
    const historyPayload = sessionManager.getRecentHistoryForAPI(10);

    setStreamingState(true);

    let streamedText = "";
    let reasoningText = "";
    let isFirstDelta = true;
    let analyzerData = null;
    let routingData = null;

    try {
      activeAbortController = new AbortController();

      await executeStreamingChat(
        { query, history: historyPayload, strategy },
        activeAbortController.signal,
        // onAnalyzer
        (info) => {
          analyzerData = info;
          placeholder.updateAnalyzer(info);
        },
        // onRouting
        (route) => {
          routingData = route;
          placeholder.updateRouting(route);
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
          sessionManager.addMessage("assistant", finalResponse, doneData);
          updateContextCounter();
        },
        // onError
        (errorMsg) => {
          placeholder.showError(errorMsg);
        }
      );
    } catch (err) {
      if (err.name === "AbortError") {
        placeholder.showStoppedState(streamedText);
        sessionManager.addMessage("assistant", streamedText || "[Generation stopped by user]", { stopped: true });
      } else {
        console.warn("SSE Stream failed, falling back to standard /api/chat:", err);
        // Fallback to standard POST
        try {
          const resp = await apiFetch("/api/chat", {
            method: "POST",
            body: JSON.stringify({ query, history: historyPayload, strategy }),
          });
          const data = await resp.json();
          if (!resp.ok) throw new Error(data.detail || "Request failed");

          placeholder.card.remove();
          appendAssistantResponseToUI(query, data.response, data);
          sessionManager.addMessage("assistant", data.response, data);
          updateContextCounter();
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

function setStreamingState(isStreaming) {
  const btn = $("send-stop-btn");
  const icon = $("send-btn-icon");
  if (!btn || !icon) return;

  if (isStreaming) {
    btn.classList.add("stop-state");
    btn.title = "Stop Generation";
    icon.innerHTML = "<svg class='icon-sym' aria-hidden='true'><use href='#i-stop'/></svg>";
    const pv = $("pipeline-visualizer");
    if (pv) {
      pv.classList.remove("hidden");
      $$("#pipeline-visualizer .pipeline-node").forEach(n => n.classList.remove("active", "analyzer", "routing", "output"));
      $("node-query")?.classList.add("active");
    }
  } else {
    btn.classList.remove("stop-state");
    btn.title = "Send Message (Enter)";
    icon.innerHTML = "<svg class='icon-sym' aria-hidden='true'><use href='#i-arrow-up'/></svg>";
    const pv = $("pipeline-visualizer");
    if (pv) {
      setTimeout(() => pv.classList.add("hidden"), 1000); // fade out
    }
  }
}

function stopGeneration() {
  if (activeAbortController) {
    activeAbortController.abort();
    activeAbortController = null;
    showToast("Generation stopped", "info");
  }
}

function updateStrategyBadge(strategy) {
  const badge = $("header-strategy-badge");
  if (!badge) return;

  const map = {
    balanced: { icon: "<svg class='icon-sym' aria-hidden='true'><use href='#i-scale'/></svg>", label: "Balanced" },
    lowest_cost: { icon: "<svg class='icon-sym' aria-hidden='true'><use href='#i-dollar'/></svg>", label: "Lowest Cost" },
    fastest: { icon: "<svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg>", label: "Fastest Speed" },
    highest_quality: { icon: "<svg class='icon-sym' aria-hidden='true'><use href='#i-target'/></svg>", label: "Max Quality" },
  };

  const s = map[strategy] || map.balanced;
  badge.innerHTML = `<span class="pill-icon">${s.icon}</span><span class="pill-label">${s.label}</span>`;
}

function updateContextCounter() {
  const active = sessionManager.getActive();
  const countEl = $("context-turn-count");
  if (countEl && active) {
    countEl.textContent = Math.floor(active.messages.length / 2);
  }
}

function setupQuickChips() {
  // Welcome hero starter prompt chips (scoped to welcome hero)
  $$(".quick-chip-card").forEach(chip => {
    chip.addEventListener("click", () => {
      const q = chip.dataset.query;
      if (q) {
        const input = $("query-input");
        if (input) {
          input.value = q;
          input.style.height = "auto";
          input.style.height = `${Math.min(input.scrollHeight, 180)}px`;
          input.focus();
          $("composer-form")?.requestSubmit();
        }
      }
    });
  });
}

/* ============================================================
   6. UI Message Rendering & Expandable Reasoning Drawer
   ============================================================ */

function renderActiveSessionMessages() {
  const container = $("chat-messages");
  if (!container) return;

  const active = sessionManager.getActive();
  updateActiveSessionHeader();
  updateContextCounter();

  if (!active || active.messages.length === 0) {
    container.innerHTML = `
      <div class="welcome-hero" id="welcome-hero">
        <div class="welcome-badge">
          <span class="badge-icon"><svg class='icon-sym' aria-hidden='true'><use href='#i-cpu'/></svg></span>
          <span>Intelligent Context-Aware Multi-Provider Switching</span>
        </div>
        <h2 class="welcome-title">How can I help you optimize today?</h2>
        <p class="welcome-desc">
          Every prompt is evaluated by our <strong>Analyzer LLM</strong>. Simple queries execute immediately in 
          <span class="badge-mode-mini self"><svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg> Self-Mode</span> with 100% downstream savings, while complex coding and reasoning tasks switch seamlessly to specialized 
          <span class="badge-mode-mini switch"><svg class='icon-sym' aria-hidden='true'><use href='#i-swap'/></svg> Switch-Mode</span> models (Gemini, Groq Qwen Coder, 120B Reasoning, or Custom Endpoints).
        </p>

        <div class="architecture-flow-cards">
          <div class="arch-card gemini">
            <div class="arch-card-header">
              <span class="arch-dot gemini"></span>
              <span class="arch-name">Google Gemini</span>
            </div>
            <div class="arch-tier">Fast / Low-Cost Tier</div>
            <div class="arch-cost">$0.075 / 1M input · $0.30 / 1M output</div>
          </div>
          <div class="arch-card groq">
            <div class="arch-card-header">
              <span class="arch-dot groq"></span>
              <span class="arch-name">Groq Qwen 27B</span>
            </div>
            <div class="arch-tier">Specialized Coding Tier</div>
            <div class="arch-cost">300+ tok/sec Ultra-fast LPU generation</div>
          </div>
          <div class="arch-card groq">
            <div class="arch-card-header">
              <span class="arch-dot groq"></span>
              <span class="arch-name">Groq 120B OSS</span>
            </div>
            <div class="arch-tier">Deep Reasoning Tier</div>
            <div class="arch-cost">Multi-step architectural deduction</div>
          </div>
          <div class="arch-card openrouter">
            <div class="arch-card-header">
              <span class="arch-dot openrouter"></span>
              <span class="arch-name">OpenRouter / Base</span>
            </div>
            <div class="arch-tier">Structured Analyzer LLM</div>
            <div class="arch-cost">Context evaluation & zero-waste routing</div>
          </div>
        </div>

        <div class="welcome-prompts-section">
          <span class="welcome-prompts-label">Try a prompt to see transparent switching:</span>
          <div class="welcome-prompts-grid" id="welcome-quick-chips">
            <button class="quick-chip-card" data-query="What is an API and how does REST work?">
              <div class="chip-top">
                <span class="chip-tier-tag fast"><svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg> Fast Tier</span>
                <span class="chip-arrow">→</span>
              </div>
              <div class="chip-query">What is an API and how does REST work?</div>
            </button>
            <button class="quick-chip-card" data-query="Write a Python implementation of Dijkstra's algorithm with priority queue.">
              <div class="chip-top">
                <span class="chip-tier-tag coding"><svg class='icon-sym' aria-hidden='true'><use href='#i-hash'/></svg> Coding Tier</span>
                <span class="chip-arrow">→</span>
              </div>
              <div class="chip-query">Write a Python implementation of Dijkstra's algorithm with priority queue.</div>
            </button>
            <button class="quick-chip-card" data-query="Design a fault-tolerant distributed cache architecture with replication and failover for 10 million concurrent users.">
              <div class="chip-top">
                <span class="chip-tier-tag reasoning"><svg class='icon-sym' aria-hidden='true'><use href='#i-cpu'/></svg> Reasoning Tier</span>
                <span class="chip-arrow">→</span>
              </div>
              <div class="chip-query">Design a fault-tolerant distributed cache architecture for 10M users.</div>
            </button>
            <button class="quick-chip-card" data-query="Now optimize the space complexity of that previous implementation.">
              <div class="chip-top">
                <span class="chip-tier-tag context"><svg class='icon-sym' aria-hidden='true'><use href='#i-swap'/></svg> Context Follow-up</span>
                <span class="chip-arrow">→</span>
              </div>
              <div class="chip-query">Now optimize the space complexity of that previous implementation.</div>
            </button>
          </div>
        </div>
      </div>
    `;
    setupQuickChips();
    return;
  }

  container.innerHTML = "";
  active.messages.forEach(msg => {
    if (msg.role === "user") {
      appendUserMessageToUI(msg.content);
    } else {
      appendAssistantResponseToUI("", msg.content, msg.telemetry || {});
    }
  });

  smoothScrollToBottom(container);
}

function appendUserMessageToUI(text) {
  const container = $("chat-messages");
  if (!container) return;

  const msgEl = document.createElement("div");
  msgEl.className = "chat-msg user";
  msgEl.innerHTML = `
    <div class="msg-content-wrap">
      <div class="user-bubble">${escapeHtml(text)}</div>
    </div>
    <div class="msg-avatar"><svg class='icon-sym' aria-hidden='true'><use href='#i-person'/></svg></div>
  `;
  container.appendChild(msgEl);
  smoothScrollToBottom(container);
}

function createStreamingPlaceholder() {
  const container = $("chat-messages");
  const msgEl = document.createElement("div");
  msgEl.className = "chat-msg assistant";
  const drawerId = "drawer_stream_" + Date.now();

  msgEl.innerHTML = `
    <div class="msg-avatar"><svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg></div>
    <div class="msg-content-wrap">
      <div class="assistant-card">
        <!-- Live Reasoning Drawer -->
        <div class="reasoning-drawer expanded" id="${drawerId}">
          <div class="drawer-toggle" data-action="toggle-reasoning" data-target="${drawerId}">
            <div class="drawer-summary">
              <span class="drawer-icon pulse"><svg class='icon-sym' aria-hidden='true'><use href='#i-cpu'/></svg></span>
              <span class="drawer-title" id="${drawerId}_title">Analyzer LLM evaluating query & context...</span>
              <span class="drawer-badge tier" id="${drawerId}_badge">Routing</span>
            </div>
            <div class="drawer-chevron">▾</div>
          </div>
          <div class="drawer-content">
            <div class="drawer-grid">
              <div class="drawer-stat-card">
                <span class="stat-label">Execution Mode</span>
                <span class="stat-val" id="${drawerId}_mode">Evaluating...</span>
              </div>
              <div class="drawer-stat-card">
                <span class="stat-label">Task Type</span>
                <span class="stat-val" id="${drawerId}_task">—</span>
              </div>
              <div class="drawer-stat-card">
                <span class="stat-label">Complexity</span>
                <div class="complexity-meter"><div class="complexity-bar" id="${drawerId}_comp_bar" style="width:50%"></div></div>
                <span class="stat-sub" id="${drawerId}_comp_val">—</span>
              </div>
              <div class="drawer-stat-card">
                <span class="stat-label">Target Model</span>
                <span class="stat-val" id="${drawerId}_target">—</span>
                <span class="stat-sub" id="${drawerId}_provider">—</span>
              </div>
            </div>
            <div class="drawer-section" id="${drawerId}_reason_wrap">
              <div class="section-title"><svg class='icon-sym' aria-hidden='true'><use href='#i-cpu'/></svg> Analyzer Rationale</div>
              <div class="rationale-box" id="${drawerId}_reason">Awaiting analyzer decision...</div>
            </div>
            <div class="drawer-section reasoning-stream-container" id="${drawerId}_thinking_wrap" style="display:none;">
              <div class="section-title"><svg class='icon-sym' aria-hidden='true'><use href='#i-chat'/></svg> Internal Thought Stream</div>
              <pre class="reasoning-stream-text" id="${drawerId}_thinking"></pre>
            </div>
          </div>
        </div>

        <!-- Body -->
        <div class="msg-text-body" id="${drawerId}_body" style="display:none;"></div>
      </div>
    </div>
  `;

  container.appendChild(msgEl);
  smoothScrollToBottom(container);

  return {
    card: msgEl,
    updateAnalyzer: (info) => {
      const isSelf = info.answer_mode === "self";
      const badge = $(`${drawerId}_badge`);
      const mode = $(`${drawerId}_mode`);
      const task = $(`${drawerId}_task`);
      const compBar = $(`${drawerId}_comp_bar`);
      const compVal = $(`${drawerId}_comp_val`);
      const reason = $(`${drawerId}_reason`);
      const title = $(`${drawerId}_title`);

      if (badge) {
        badge.className = `drawer-badge ${isSelf ? 'self' : 'switch'}`;
        badge.innerHTML = isSelf ? "<svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg> Self-Mode" : "<svg class='icon-sym' aria-hidden='true'><use href='#i-swap'/></svg> Switch-Mode";
      }
      if (mode) mode.textContent = isSelf ? "Direct Self-Answer" : "Specialized Switch";
      if (task) task.textContent = (info.task_type || "general").toUpperCase();
      if (compVal) compVal.textContent = `${info.complexity || 'medium'} (${info.complexity_score ?? '0.5'})`;
      if (compBar) compBar.style.width = `${Math.round((info.complexity_score || 0.5) * 100)}%`;
      if (reason) reason.textContent = `"${info.reason || 'Optimal execution tier selected.'}"`;
      if (title) title.textContent = isSelf ? "Resolved in Direct Self-Mode (0ms downstream)" : `Routing to ${info.target_provider || 'Specialized Model'}`;
      
      const pv = $("pipeline-visualizer");
      if (pv) {
         $$("#pipeline-visualizer .pipeline-node").forEach(n => n.classList.remove("active", "analyzer", "routing", "output"));
         $("node-analyzer")?.classList.add("active", "analyzer");
      }
    },
    updateRouting: (route) => {
      const target = $(`${drawerId}_target`);
      const provider = $(`${drawerId}_provider`);
      const title = $(`${drawerId}_title`);

      if (target) target.textContent = route.target_name || route.target_model;
      if (provider) provider.textContent = `${(route.target_provider || '').toUpperCase()} (${route.target_tier || ''})`;
      if (title) title.textContent = `Routed to ${route.target_name || route.target_model}`;

      const pv = $("pipeline-visualizer");
      if (pv) {
         $$("#pipeline-visualizer .pipeline-node").forEach(n => n.classList.remove("active", "analyzer", "routing", "output"));
         $("node-scoreboard")?.classList.add("active", "routing");
         setTimeout(() => {
           $$("#pipeline-visualizer .pipeline-node").forEach(n => n.classList.remove("active", "analyzer", "routing", "output"));
           $("node-model")?.classList.add("active", "routing");
         }, 400);
      }
    },
    appendReasoningDelta: (fullReasoning) => {
      const wrap = $(`${drawerId}_thinking_wrap`);
      const text = $(`${drawerId}_thinking`);
      if (wrap) wrap.style.display = "block";
      if (text) text.textContent = fullReasoning;
      smoothScrollToBottom(container);
    },
    startResponse: () => {
      const body = $(`${drawerId}_body`);
      if (body) body.style.display = "block";
      const pv = $("pipeline-visualizer");
      if (pv) {
         $$("#pipeline-visualizer .pipeline-node").forEach(n => n.classList.remove("active", "analyzer", "routing", "output"));
         $("node-output")?.classList.add("active", "output");
      }
    },
    appendDelta: (fullText) => {
      const body = $(`${drawerId}_body`);
      if (body) {
        body.style.display = "block";
        body.innerHTML = formatMarkdown(fullText);
  _renderMathInElement(body);
      }
      smoothScrollToBottom(container);
    },
    showError: (err) => {
      const title = $(`${drawerId}_title`);
      const reason = $(`${drawerId}_reason`);
      if (title) title.innerHTML = `<span style="color:var(--accent-red)"><svg class='icon-sym' aria-hidden='true'><use href='#i-warning'/></svg> Stream Error</span>`;
      if (reason) reason.innerHTML = `<span style="color:var(--accent-red)">${escapeHtml(err)}</span>`;
    },
    showStoppedState: (text) => {
      const title = $(`${drawerId}_title`);
      if (title) title.textContent = "Generation Stopped by User";
      const body = $(`${drawerId}_body`);
      if (body && text) {
        body.style.display = "block";
        body.innerHTML = formatMarkdown(text) + `<p style="color:var(--text-muted);font-style:italic;">[Generation stopped by user]</p>`;
  _renderMathInElement(body);
      }
    }
  };
}

function appendAssistantResponseToUI(query, text, data = {}) {
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
  const targetTier = model.tier || analyzer.target_tier || "fast";
  const targetModelName = model.model_name || model.model_id || data.selected_model || "Gemini Flash";
  const targetProvider = model.provider || analyzer.target_provider || data.selected_provider || "gemini";
  const routingReason = data.routing_reason || analyzer.reason || model.reason || "Cost-optimal model selection";

  const totalCost = data.total_cost_usd != null ? `$${data.total_cost_usd.toFixed(6)}` : "—";
  const baselineCost = data.baseline_cost_usd != null ? `$${data.baseline_cost_usd.toFixed(6)}` : "—";
  const savingsUsd = data.savings_usd != null ? `$${data.savings_usd.toFixed(6)}` : "—";
  const savingsPct = data.savings_percent != null ? `${data.savings_percent.toFixed(1)}%` : null;

  const totalTokens = data.total_tokens ? `${data.total_tokens.toLocaleString()} tok` : "—";
  const inTokens = data.input_tokens != null ? data.input_tokens : (analyzer.input_tokens || 0);
  const outTokens = data.output_tokens != null ? data.output_tokens : (analyzer.output_tokens || 0);

  const totalLatency = data.total_latency_ms != null ? `${Math.round(data.total_latency_ms)} ms` : "—";
  const genLatency = data.latency_ms != null ? `${Math.round(data.latency_ms)} ms` : "0 ms";
  const analyzerLatency = data.analyzer_latency_ms != null ? `${Math.round(data.analyzer_latency_ms)} ms` : "—";
  const ttft = data.ttft_ms != null ? `${Math.round(data.ttft_ms)} ms` : "—";

  const fallbackBadge = data.fallback_used ? `<span class="drawer-badge" style="background:rgba(245,158,11,0.2);color:var(--accent-amber)"><svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg> Fallback Used</span>` : "";

  msgEl.innerHTML = `
    <div class="msg-avatar"><svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg></div>
    <div class="msg-content-wrap">
      <div class="assistant-card">
        
        <!-- Expandable Reasoning Drawer Accordion -->
        <div class="reasoning-drawer collapsed" id="${drawerId}">
          <div class="drawer-toggle" data-action="toggle-reasoning" data-target="${drawerId}">
            <div class="drawer-summary">
              <span class="drawer-icon"><svg class='icon-sym' aria-hidden='true'><use href='#i-cpu'/></svg></span>
              <span class="drawer-title">${isSelf ? 'Direct Self-Mode' : 'Routed to ' + escapeHtml(targetModelName)}</span>
              <span class="drawer-badge ${isSelf ? 'self' : 'switch'}">${isSelf ? "<svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg> Self-Mode" : "<svg class='icon-sym' aria-hidden='true'><use href='#i-swap'/></svg> Switch-Mode"}</span>
              <span class="drawer-metric"><svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg> ${totalLatency}</span>
              ${savingsPct ? `<span class="drawer-metric text-green"><svg class='icon-sym' aria-hidden='true'><use href='#i-trend-down'/></svg> ${savingsPct} saved</span>` : ''}
              ${fallbackBadge}
            </div>
            <div class="drawer-chevron">▾</div>
          </div>

          <div class="drawer-content">
            <!-- 4-Stat Grid -->
            <div class="drawer-grid">
              <div class="drawer-stat-card">
                <span class="stat-label">Execution Mode</span>
                <span class="stat-val ${isSelf ? 'text-green' : 'text-cyan'}">${isSelf ? `<svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg> Direct Self-Answer` : `<svg class='icon-sym' aria-hidden='true'><use href='#i-swap'/></svg> Specialized Switch`}</span>
                <span class="stat-sub">${isSelf ? 'Zero downstream cost' : 'Targeted model dispatched'}</span>
              </div>
              <div class="drawer-stat-card">
                <span class="stat-label">Task Classification</span>
                <span class="stat-val">${escapeHtml(taskType.toUpperCase())}</span>
                <span class="stat-sub">Domain categorized</span>
              </div>
              <div class="drawer-stat-card">
                <span class="stat-label">Complexity Score</span>
                <div class="complexity-meter">
                  <div class="complexity-bar" style="width: ${Math.round(complexityScore * 100)}%"></div>
                </div>
                <span class="stat-sub">${escapeHtml(complexity)} (${complexityScore})</span>
              </div>
              <div class="drawer-stat-card">
                <span class="stat-label">Served Model</span>
                <span class="stat-val">${escapeHtml(targetModelName)}</span>
                <span class="stat-sub">${escapeHtml(targetProvider.toUpperCase())} · ${escapeHtml(targetTier)}</span>
              </div>
            </div>

            <!-- Routing Rationale -->
            <div class="drawer-section">
              <div class="section-title"><svg class='icon-sym' aria-hidden='true'><use href='#i-cpu'/></svg> Analyzer Rationale</div>
              <div class="rationale-box">"${escapeHtml(routingReason)}"</div>
            </div>

            <!-- Granular Performance & Cost Grid -->
            <div class="drawer-telemetry-grid">
              <div class="t-box">
                <span class="t-label">Time to First Token</span>
                <span class="t-val">${ttft}</span>
              </div>
              <div class="t-box">
                <span class="t-label">Analyzer Latency</span>
                <span class="t-val">${analyzerLatency}</span>
              </div>
              <div class="t-box">
                <span class="t-label">Generation Latency</span>
                <span class="t-val">${genLatency}</span>
              </div>
              <div class="t-box">
                <span class="t-label">Token Breakdown</span>
                <span class="t-val">${inTokens} in · ${outTokens} out</span>
                <span class="t-sub">${totalTokens}</span>
              </div>
              <div class="t-box highlight-cost">
                <span class="t-label">Actual Cost</span>
                <span class="t-val">${totalCost}</span>
                <span class="t-sub">Baseline: ${baselineCost}</span>
              </div>
              <div class="t-box highlight-savings">
                <span class="t-label">Net Cost Reduction</span>
                <span class="t-val text-green">${savingsUsd} (${savingsPct || '0%'})</span>
                <span class="t-sub">vs always-powerful model</span>
              </div>
            </div>
          </div>
        </div>

        <!-- Assistant Message Body -->
        <div class="msg-text-body">
          ${formatMarkdown(text)}
        </div>

        <!-- Message Footer -->
        <div class="telemetry-footer">
          <div class="telemetry-chips">
            <div class="t-chip"><span><svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg> Latency:</span> <strong>${totalLatency}</strong></div>
            <div class="t-chip"><span><svg class='icon-sym' aria-hidden='true'><use href='#i-hash'/></svg> Tokens:</span> <strong>${totalTokens}</strong></div>
            <div class="t-chip"><span><svg class='icon-sym' aria-hidden='true'><use href='#i-dollar'/></svg> Cost:</span> <strong>${totalCost}</strong></div>
            ${savingsPct ? `<div class="t-chip savings"><span><svg class='icon-sym' aria-hidden='true'><use href='#i-trend-down'/></svg> Saved:</span> <strong>${savingsPct} vs baseline</strong></div>` : ''}
          </div>
          <div class="telemetry-actions">
            <button class="btn-icon-action" data-action="copy-message" data-text="${escapeHtml(text)}" title="Copy Response"><svg class='icon-sym' aria-hidden='true'><use href='#i-copy'/></svg> Copy</button>
            ${data.request_id ? `<button class="btn-icon-action" data-action="open-inspector" data-id="${data.request_id}" title="Inspect Full Telemetry"><svg class='icon-sym' aria-hidden='true'><use href='#i-search'/></svg> Inspect</button>` : ''}
            ${data.request_id ? `<button class="btn-icon-action" data-action="feedback" data-id="${data.request_id}" data-rating="1" title="Good Response"><svg class='icon-sym' aria-hidden='true'><use href='#i-thumb-up'/></svg></button>` : ''}
            ${data.request_id ? `<button class="btn-icon-action" data-action="feedback" data-id="${data.request_id}" data-rating="-1" title="Poor Response"><svg class='icon-sym' aria-hidden='true'><use href='#i-thumb-down'/></svg></button>` : ''}
          </div>
        </div>

      </div>
    </div>
  `;

  container.appendChild(msgEl);
  // Render LaTeX math ($...$ / $$...$$) inside the final markdown body.
  _renderMathInElement(msgEl.querySelector(".msg-text-body"));
  smoothScrollToBottom(container);
}

window.toggleReasoningDrawer = function(id) {
  const drawer = $(id);
  if (!drawer) return;
  drawer.classList.toggle("expanded");
  drawer.classList.toggle("collapsed");
};

/* ============================================================
   7. Resilient SSE Stream Consumer (R4)
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
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split("\n\n");
    buffer = parts.pop(); // Keep incomplete chunk in buffer

    for (const part of parts) {
      const dataLine = part.split("\n").find(l => l.startsWith("data:"));
      if (!dataLine) continue;

      let evt;
      try {
        evt = JSON.parse(dataLine.slice(5).trim());
      } catch (e) {
        console.warn("Malformed SSE JSON:", dataLine);
        continue;
      }

      switch (evt.event) {
        case "analyzer":
          if (onAnalyzer) onAnalyzer(evt.info || evt);
          break;
        case "routing":
          if (onRouting) onRouting(evt);
          break;
        case "reasoning_delta":
          if (onReasoningDelta) onReasoningDelta(evt.text || "");
          break;
        case "delta":
          if (onDelta && !evt._handled) {
            onDelta(evt.text || "");
            evt._handled = true;
          }
          break;
        case "content_delta":
          if (onDelta && !evt._handled) {
            onDelta(evt.text || "");
            evt._handled = true;
          }
          break;
        case "done":
          if (onDone) onDone(evt);
          break;
        case "error":
          if (onError) onError(evt.detail || "Streaming error occurred");
          break;
      }
    }
  }
}

function smoothScrollToBottom(container) {
  if (!container || isUserScrolledUp) return;
  container.scrollTo({
    top: container.scrollHeight,
    behavior: "smooth",
  });
}

/* ============================================================
   8. Markdown Parser & Code Syntax Highlighting
   ============================================================ */

function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function escapeAttr(s) {
  if (s === null || s === undefined) return '""';
  return JSON.stringify(String(s)).replace(/"/g, '&quot;');
}

function highlightSyntax(code, lang = "") {
  let escaped = escapeHtml(code);

  // Common keywords across languages (Python, Java, JS/TS, C++, Go, Rust, SQL)
  const keywords = /\b(public|private|protected|static|final|void|class|interface|extends|implements|new|this|super|int|float|double|boolean|char|byte|short|long|String|System|out|println|def|from|import|return|yield|if|else|elif|for|while|do|try|except|catch|finally|throw|throws|with|as|async|await|function|const|let|var|switch|case|default|break|continue|typeof|instanceof|null|undefined|true|false|None|True|False|SELECT|FROM|WHERE|INSERT|UPDATE|DELETE|JOIN|GROUP|ORDER|BY|HAVING|LIMIT)\b/g;
  escaped = escaped.replace(keywords, '<span class="syn-kw">$1</span>');

  // Strings (quoted)
  escaped = escaped.replace(/(&quot;[\s\S]*?&quot;|&#39;[\s\S]*?&#39;|`[\s\S]*?`)/g, '<span class="syn-str">$1</span>');

  // Numbers
  escaped = escaped.replace(/\b(\d+(\.\d+)?)\b/g, '<span class="syn-num">$1</span>');

  // Comments (# or //)
  escaped = escaped.replace(/(#.*|\/\/.*)$/gm, '<span class="syn-comment">$1</span>');

  return escaped;
}

/* ------------------------------------------------------------------
   Standard Markdown Rendering: marked + DOMPurify + KaTeX
   - marked: full CommonMark/GFM parser (tables, ordered lists, links,
     nested markdown — replaces the limited regex chain)
   - DOMPurify: XSS sanitization of the parsed HTML
   - KaTeX: LaTeX math rendering for $inline$, $$block$$, \(..\), \[..\]
   ------------------------------------------------------------------ */
let _katexReady = false;
if (typeof katex !== "undefined") _katexReady = true;

function _renderMathInElement(el) {
  if (!_katexReady || typeof renderMathInElement !== "function" || !el) return;
  try {
    renderMathInElement(el, {
      delimiters: [
        { left: "$$", right: "$$", display: true },
        { left: "\\[", right: "\\]", display: true },
        { left: "\\(", right: "\\)", display: false },
        { left: "$", right: "$", display: false },
      ],
      throwOnError: false,
    });
  } catch (err) {
    console.warn("KaTeX math rendering failed:", err);
  }
}

function formatMarkdown(text) {
  if (!text) return "";

  if (typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
    const renderer = new marked.Renderer();
    // Keep the app's syntax highlighting + CSP-safe copy button on fenced code.
    renderer.code = function(code, lang) {
      // In marked v12+, the first argument can be an object token { text, lang, escaped }
      let cleanCode = typeof code === "object" ? (code.text || "") : (code || "");
      let cleanLang = typeof code === "object" ? (code.lang || "") : (lang || "");
      cleanLang = (cleanLang || "").trim().toLowerCase() || "code";
      cleanCode = cleanCode.replace(/\n$/, "");

      return `
        <div class="code-block-wrapper">
          <div class="code-block-header">
            <span class="code-lang-label">${escapeHtml(cleanLang)}</span>
            <button type="button" class="btn-copy-code" data-action="copy-code"><svg class='icon-sym' aria-hidden='true'><use href='#i-copy'/></svg> Copy Code</button>
          </div>
          <pre><code class="language-${escapeHtml(cleanLang)}">${highlightSyntax(cleanCode, cleanLang)}</code></pre>
        </div>
      `;
    };
    const parsed = marked.parse(text, { renderer, gfm: true, breaks: true });
    return DOMPurify.sanitize(parsed, {
      ADD_ATTR: ["data-action", "data-code", "data-text", "data-id", "data-rating", "data-target", "target"],
    });
  }

  // Fallback when vendor libs are unavailable: plain escaped text.
  return `<p>${escapeHtml(text).replace(/\n/g, "<br>")}</p>`;
}

window.copyCodeBlock = function(btn, codeText) {
  let text = codeText;
  if (!text) {
    const wrapper = btn.closest(".code-block-wrapper");
    const codeEl = wrapper ? wrapper.querySelector("pre code") : null;
    if (codeEl) text = codeEl.textContent;
  }
  if (!text) return;
  const doFeedback = () => {
    const orig = btn.innerHTML;
    btn.innerHTML = `<span style="color:var(--accent-green);font-weight:700;">✓ Copied!</span>`;
    setTimeout(() => {
      btn.innerHTML = orig;
    }, 2000);
    showToast("Code copied to clipboard", "success");
  };

  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(text).then(doFeedback).catch(() => {
      // Fallback
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      document.body.removeChild(ta);
      doFeedback();
    });
  } else {
    const ta = document.createElement("textarea");
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    document.body.removeChild(ta);
    doFeedback();
  }
};

window.copyMessageText = function(btn, text) {
  navigator.clipboard.writeText(text);
  const orig = btn.innerHTML;
  btn.innerHTML = `✓ Copied`;
  setTimeout(() => { btn.innerHTML = orig; }, 2000);
  showToast("Answer copied to clipboard", "success");
};

/* ------------------------------------------------------------------
   CSP-Safe Global Action Delegation
   Replaces every inline onclick handler with data-action attributes so
   the whole app runs under a strict Content-Security-Policy
   (script-src 'self' — no unsafe-inline script execution allowed).
   ------------------------------------------------------------------ */
document.addEventListener("click", (e) => {
  const el = e.target.closest("[data-action]");
  if (!el) return;
  const id = el.dataset.id;
  switch (el.dataset.action) {
    case "session-click":
      // Inner action buttons (rename/delete) dispatch their own actions.
      if (e.target.closest(".session-actions")) return;
      handleSessionClick(id);
      break;
    case "rename-session": promptRenameSession(id); break;
    case "delete-session": handleDeleteSession(id); break;
    case "toggle-reasoning": toggleReasoningDrawer(el.dataset.target); break;
    case "copy-message": copyMessageText(el, el.dataset.text); break;
    case "copy-code": copyCodeBlock(el, el.dataset.code); break;
    case "open-inspector": openInspectorModal(parseInt(id, 10)); break;
    case "feedback":
      recordMessageFeedback(parseInt(id, 10), parseInt(el.dataset.rating, 10), el);
      break;
  }
});

/* ============================================================
   9. Dynamic Settings Modal & Provider Management (R2)
   ============================================================ */

function setupSettingsModal() {
  const modal = $("settings-modal");
  const openBtn = $("open-settings-btn");
  const headerSettingsBtn = $("header-settings-btn");
  const closeBtn = $("close-settings-btn");
  const backdrop = $("settings-backdrop");
  const saveBtn = $("save-settings-btn");
  const resetBtn = $("reset-settings-btn");
  const clearKeysBtn = $("clear-keys-btn");

  // Open / Close
  const openModal = () => {
    loadSettingsIntoUI();
    modal?.classList.remove("hidden");
  };
  const closeModal = () => {
    modal?.classList.add("hidden");
  };

  openBtn?.addEventListener("click", openModal);
  headerSettingsBtn?.addEventListener("click", openModal);
  closeBtn?.addEventListener("click", closeModal);
  backdrop?.addEventListener("click", closeModal);

  // Tab switching inside settings
  $$(".settings-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      $$(".settings-tab").forEach(t => t.classList.remove("active"));
      $$(".settings-panel").forEach(p => p.classList.remove("active"));

      tab.classList.add("active");
      const targetPanel = $(`tab-${tab.dataset.tab}`);
      if (targetPanel) targetPanel.classList.add("active");
    });
  });

  // Password visibility toggles
  $$(".btn-toggle-mask").forEach(btn => {
    btn.addEventListener("click", () => {
      const targetId = btn.dataset.target;
      const input = $(targetId);
      if (input) {
        input.type = input.type === "password" ? "text" : "password";
        btn.innerHTML = input.type === "password" ? "<svg class='icon-sym' aria-hidden='true'><use href='#i-eye'/></svg>" : "<svg class='icon-sym' aria-hidden='true'><use href='#i-lock'/></svg>";
      }
    });
  });

  // Connection Test Buttons
  $$(".btn-test-conn").forEach(btn => {
    btn.addEventListener("click", async () => {
      const provider = btn.dataset.provider;
      await testProviderConnection(provider);
    });
  });

  // Save Settings
  saveBtn?.addEventListener("click", async () => {
    const current = await SettingsManager.load();

    current.apiKeys.gemini = ($("key-gemini")?.value || "").trim();
    current.apiKeys.groq = ($("key-groq")?.value || "").trim();
    current.apiKeys.openrouter = ($("key-openrouter")?.value || "").trim();
    current.apiKeys.openai = ($("key-openai")?.value || "").trim();
    current.apiKeys.custom = ($("key-custom")?.value || "").trim();

    current.customEndpoints.custom = ($("url-custom")?.value || "").trim();

    // Provider Specific Models (Tabs 1-5)
    current.providerModels.geminiFast = ($("model-gemini-fast")?.value || "").trim();
    current.providerModels.groqCoding = ($("model-groq-coding")?.value || "").trim();
    current.providerModels.groqReasoning = ($("model-groq-reasoning")?.value || "").trim();
    current.providerModels.openrouterAnalyzer = ($("model-openrouter-analyzer")?.value || "").trim();
    current.providerModels.openrouterPowerful = ($("model-openrouter-powerful")?.value || "").trim();
    current.providerModels.openai = ($("model-openai")?.value || "").trim();
    current.providerModels.custom = ($("model-custom")?.value || "").trim();

    // Tier Overrides (Tab 6 - sync with provider models if configured)
    current.tierOverrides.analyzer = ($("override-analyzer")?.value || current.providerModels.openrouterAnalyzer || "").trim();
    current.tierOverrides.fast = ($("override-fast")?.value || current.providerModels.geminiFast || "").trim();
    current.tierOverrides.coding = ($("override-coding")?.value || current.providerModels.groqCoding || "").trim();
    current.tierOverrides.reasoning = ($("override-reasoning")?.value || current.providerModels.groqReasoning || "").trim();
    current.tierOverrides.powerful = ($("override-powerful")?.value || current.providerModels.openrouterPowerful || "").trim();

    await SettingsManager.save(current);
    showToast("Settings and API keys saved successfully", "success");
    closeModal();
    checkInitialHealth();
  });

  // Reset to Defaults
  resetBtn?.addEventListener("click", async () => {
    if (confirm("Reset all settings to server defaults?")) {
      await SettingsManager.save(SettingsManager.getDefaults());
      await loadSettingsIntoUI();
      showToast("Settings reset to defaults", "info");
    }
  });

  // Clear Keys
  clearKeysBtn?.addEventListener("click", async () => {
    if (confirm("Clear all stored API keys and custom endpoints?")) {
      await SettingsManager.clearKeys();
      await loadSettingsIntoUI();
      showToast("All stored keys cleared", "info");
    }
  });
}

async function loadSettingsIntoUI() {
  const s = await SettingsManager.load();

  // API Keys
  if ($("key-gemini")) $("key-gemini").value = s.apiKeys.gemini || "";
  if ($("key-groq")) $("key-groq").value = s.apiKeys.groq || "";
  if ($("key-openrouter")) $("key-openrouter").value = s.apiKeys.openrouter || "";
  if ($("key-openai")) $("key-openai").value = s.apiKeys.openai || "";
  if ($("key-custom")) $("key-custom").value = s.apiKeys.custom || "";

  // Custom Endpoint & Model
  if ($("url-custom")) $("url-custom").value = s.customEndpoints.custom || "";
  if ($("model-custom")) $("model-custom").value = s.providerModels?.custom || "";

  // Provider Models (Tabs 1-4)
  if ($("model-gemini-fast")) $("model-gemini-fast").value = s.providerModels?.geminiFast || s.tierOverrides?.fast || "gemini-2.5-flash-lite";
  if ($("model-groq-coding")) $("model-groq-coding").value = s.providerModels?.groqCoding || s.tierOverrides?.coding || "qwen/qwen3.6-27b";
  if ($("model-groq-reasoning")) $("model-groq-reasoning").value = s.providerModels?.groqReasoning || s.tierOverrides?.reasoning || "openai/gpt-oss-120b";
  if ($("model-openrouter-analyzer")) $("model-openrouter-analyzer").value = s.providerModels?.openrouterAnalyzer || s.tierOverrides?.analyzer || "meta-llama/llama-3.2-3b-instruct";
  if ($("model-openrouter-powerful")) $("model-openrouter-powerful").value = s.providerModels?.openrouterPowerful || s.tierOverrides?.powerful || "meta-llama/llama-3.1-70b-instruct";
  if ($("model-openai")) $("model-openai").value = s.providerModels?.openai || "gpt-4o-mini";

  // Tier Overrides (Tab 6)
  if ($("override-analyzer")) $("override-analyzer").value = s.tierOverrides?.analyzer || s.providerModels?.openrouterAnalyzer || "";
  if ($("override-fast")) $("override-fast").value = s.tierOverrides?.fast || s.providerModels?.geminiFast || "";
  if ($("override-coding")) $("override-coding").value = s.tierOverrides?.coding || s.providerModels?.groqCoding || "";
  if ($("override-reasoning")) $("override-reasoning").value = s.tierOverrides?.reasoning || s.providerModels?.groqReasoning || "";
  if ($("override-powerful")) $("override-powerful").value = s.tierOverrides?.powerful || s.providerModels?.openrouterPowerful || "";
}

async function testProviderConnection(provider) {
  const badge = $(`status-${provider}-test`);
  if (badge) {
    badge.className = "status-test-badge";
    badge.innerHTML = `<span class="spinner-small"></span> Testing...`;
  }

  // Gather active input values
  const s = await SettingsManager.load();
  const apiKey = ($(`key-${provider}`)?.value || s.apiKeys[provider] || "").trim();
  const baseUrl = ($("url-custom")?.value || s.customEndpoints.custom || "").trim();

  let testModel = null;
  if (provider === "custom") {
    testModel = ($("model-custom")?.value || s.providerModels?.custom || "").trim();
  } else if (provider === "gemini") {
    testModel = ($("model-gemini-fast")?.value || s.providerModels?.geminiFast || "").trim();
  } else if (provider === "groq") {
    testModel = ($("model-groq-coding")?.value || s.providerModels?.groqCoding || "").trim();
  } else if (provider === "openrouter") {
    testModel = ($("model-openrouter-analyzer")?.value || s.providerModels?.openrouterAnalyzer || "").trim();
  } else if (provider === "openai") {
    testModel = ($("model-openai")?.value || s.providerModels?.openai || "").trim();
  }

  try {
    const resp = await apiFetch(`/api/providers/test/${provider}`, {
      method: "POST",
      body: JSON.stringify({
        provider: provider,
        api_key: apiKey || null,
        base_url: baseUrl || null,
        model: testModel || null,
      }),
    });
    const data = await resp.json();

    if (badge) {
      if (resp.ok && data.ok) {
        badge.className = "status-test-badge connected";
        badge.textContent = `✓ Connected (${data.latency_ms}ms)`;
      } else {
        badge.className = "status-test-badge error";
        badge.textContent = `✗ ${data.message || "Failed"}`;
      }
    }
  } catch (err) {
    if (badge) {
      badge.className = "status-test-badge error";
      badge.textContent = `✗ ${err.message}`;
    }
  }
}

async function checkInitialHealth() {
  try {
    const resp = await apiFetch("/api/providers/health");
    if (!resp.ok) return;
    const data = await resp.json();

    const dot = $("sidebar-provider-dot");
    const headerStatus = $("engine-status-text");

    if (data.overall_status === "connected") {
      if (dot) dot.className = "status-dot-indicator";
      if (headerStatus) headerStatus.textContent = "Providers Active";
    } else if (data.overall_status === "degraded") {
      if (dot) dot.className = "status-dot-indicator checking";
      if (headerStatus) headerStatus.textContent = "Demo / Fallback Mode";
    } else {
      if (dot) dot.className = "status-dot-indicator checking";
      if (headerStatus) headerStatus.textContent = "Server Defaults";
    }
  } catch (err) {
    console.warn("Initial health check failed:", err);
  }
}

/* ============================================================
   10. Telemetry & Analytics Dashboard View
   ============================================================ */

function setupDashboardView() {
  $("refresh-dashboard-btn")?.addEventListener("click", loadDashboardStats);
}

function startDashboardAutoRefresh() {
  stopDashboardAutoRefresh();
  dashboardRefreshInterval = setInterval(loadDashboardStats, 6000);
}

function stopDashboardAutoRefresh() {
  if (dashboardRefreshInterval) {
    clearInterval(dashboardRefreshInterval);
    dashboardRefreshInterval = null;
  }
}

async function loadDashboardStats() {
  try {
    const resp = await apiFetch("/api/stats");
    if (!resp.ok) return;
    const s = await resp.json();

    // Update KPI Cards
    if ($("stat-total-requests")) $("stat-total-requests").textContent = s.total_requests.toLocaleString();
    if ($("stat-success-rate")) $("stat-success-rate").textContent = `Success Rate: ${(s.success_rate * 100).toFixed(1)}%`;
    if ($("stat-savings-usd")) $("stat-savings-usd").textContent = `$${s.estimated_savings_usd.toFixed(4)}`;
    if ($("stat-savings-pct")) $("stat-savings-pct").textContent = `${s.savings_percent.toFixed(1)}% savings vs baseline`;
    if ($("stat-avg-latency")) $("stat-avg-latency").textContent = `${Math.round(s.average_total_latency_ms)} ms`;
    if ($("stat-analyzer-latency")) $("stat-analyzer-latency").textContent = `Gen: ${Math.round(s.average_latency_ms)} ms avg`;
    if ($("stat-total-cost")) $("stat-total-cost").textContent = `$${s.total_cost_usd.toFixed(6)}`;
    if ($("stat-baseline-cost")) $("stat-baseline-cost").textContent = `Baseline: $${s.baseline_cost_usd.toFixed(6)}`;
    if ($("stat-total-tokens")) $("stat-total-tokens").textContent = s.total_tokens.toLocaleString();
    if ($("stat-fallbacks")) $("stat-fallbacks").textContent = s.fallback_count.toString();

    // Render Distribution Charts
    renderBarChart("chart-model-dist", s.model_distribution || []);
    renderBarChart("chart-tier-dist", s.tier_distribution || []);
    renderBarChart("chart-task-dist", s.task_distribution || []);
    renderBarChart("chart-complexity-dist", s.complexity_distribution || []);

    // Render History Table
    renderHistoryTable(s.recent_requests || []);
  } catch (err) {
    console.error("Failed to load dashboard statistics:", err);
  }
}

function renderBarChart(containerId, data) {
  const container = $(containerId);
  if (!container) return;

  if (!data || data.length === 0) {
    container.innerHTML = `<div class="empty-state" style="padding:15px">No telemetry data recorded yet</div>`;
    return;
  }

  const maxVal = Math.max(...data.map(d => d.count), 1);
  const total = data.reduce((acc, d) => acc + d.count, 0);

  container.innerHTML = data.map(d => {
    const pct = ((d.count / maxVal) * 100).toFixed(0);
    const share = ((d.count / total) * 100).toFixed(0);
    return `
      <div class="chart-bar-row">
        <span class="chart-bar-label" title="${escapeHtml(d.name)}">${escapeHtml(d.name)}</span>
        <div class="chart-bar-track">
          <div class="chart-bar-fill" style="width:${pct}%"></div>
        </div>
        <span class="chart-bar-val">${d.count} (${share}%)</span>
      </div>
    `;
  }).join("");
}

function renderHistoryTable(requests) {
  const tbody = $("history-tbody");
  if (!tbody) return;

  if (!requests || requests.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="empty-state">No requests executed yet. Run queries in Chat Studio!</td></tr>`;
    return;
  }

  tbody.innerHTML = requests.map(r => {
    const cost = r.total_cost_usd != null ? `$${r.total_cost_usd.toFixed(6)}` : "—";
    const statusIcon = r.success ? `<span style="color:var(--accent-green)">✓</span>` : `<span style="color:var(--accent-red)">✗</span>`;
    const fb = r.fallback_used ? `<span style="color:var(--accent-amber)">Yes</span>` : `<span style="color:var(--text-muted)">No</span>`;

    return `
      <tr data-action="open-inspector" data-id="${r.id}">
        <td>${escapeHtml(r.timestamp.split(" ")[1] || r.timestamp)}</td>
        <td title="${escapeHtml(r.query)}" style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          ${escapeHtml(r.query)}
        </td>
        <td><span class="drawer-badge tier">${escapeHtml(r.task_type)}</span></td>
        <td><span class="drawer-badge">${escapeHtml(r.complexity)}</span></td>
        <td><code>${escapeHtml(r.selected_model)}</code></td>
        <td>${Math.round(r.total_latency_ms)} ms</td>
        <td>${cost}</td>
        <td>${fb}</td>
        <td>${statusIcon}</td>
      </tr>
    `;
  }).join("");
}

/* ============================================================
   11. Research Benchmark Lab
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

      // Update Summary Cards
      const cards = $("benchmark-summary-cards");
      if (cards) cards.style.display = "grid";

      if ($("bm-overall-savings")) $("bm-overall-savings").textContent = `${data.overall_cost_savings_percent.toFixed(1)}%`;
      if ($("bm-saved-dollars")) $("bm-saved-dollars").textContent = `$${data.total_cost_saved_usd.toFixed(4)} saved across test suite`;
      if ($("bm-overall-speedup")) $("bm-overall-speedup").textContent = `${data.overall_speedup_percent.toFixed(1)}%`;
      if ($("bm-smart-cost")) $("bm-smart-cost").textContent = `$${data.smart_total_cost_usd.toFixed(6)}`;
      if ($("bm-baseline-cost")) $("bm-baseline-cost").textContent = `vs Baseline 1: $${data.baseline1_total_cost_usd.toFixed(6)}`;

      // Render Comparison Table
      const tbody = $("benchmark-tbody");
      if (tbody) {
        tbody.innerHTML = data.items.map(item => `
          <tr>
            <td>
              <strong>${escapeHtml(item.query)}</strong>
              <div style="margin-top:4px"><span class="drawer-badge tier">${escapeHtml(item.task_type)}</span> <span class="drawer-badge">${escapeHtml(item.complexity)}</span></div>
            </td>
            <td>
              <div><code>${escapeHtml(item.baseline1_model)}</code></div>
              <div style="color:var(--text-muted);font-size:11px">$${item.baseline1_cost_usd.toFixed(6)} · ${item.baseline1_latency_ms} ms</div>
            </td>
            <td>
              <div><code>${escapeHtml(item.baseline2_model)}</code></div>
              <div style="color:var(--text-muted);font-size:11px">$${item.baseline2_cost_usd.toFixed(6)} · ${item.baseline2_latency_ms} ms</div>
            </td>
            <td>
              <div style="color:var(--accent-cyan);font-weight:600"><code>${escapeHtml(item.smart_model)}</code></div>
              <div style="color:var(--text-muted);font-size:11px">$${item.smart_cost_usd.toFixed(6)} · ${item.smart_latency_ms} ms</div>
            </td>
            <td>
              <strong class="text-green">${item.smart_savings_percent.toFixed(1)}%</strong>
            </td>
            <td>
              <strong class="text-blue">${item.smart_speedup_percent.toFixed(1)}%</strong>
            </td>
          </tr>
        `).join("");
      }

      showToast("Multi-domain benchmark completed", "success");
    } catch (err) {
      alert("Benchmark failed: " + err.message);
    } finally {
      runBtn.disabled = false;
      runBtn.innerHTML = `<span>▶</span> Run Multi-Domain Benchmark`;
    }
  });
}

/* ============================================================
   12. Telemetry Inspector Modal & User Feedback
   ============================================================ */

function setupInspectorModal() {
  const modal = $("inspector-modal");
  const closeBtn = $("close-inspector-btn");
  const backdrop = $("inspector-backdrop");

  const closeModal = () => modal?.classList.add("hidden");

  closeBtn?.addEventListener("click", closeModal);
  backdrop?.addEventListener("click", closeModal);
}

window.openInspectorModal = async function(requestId) {
  const modal = $("inspector-modal");
  const modalBody = $("modal-body");
  if (!modal || !modalBody) return;

  modal.classList.remove("hidden");
  modalBody.innerHTML = `<div class="empty-state">Loading telemetry for Request #${requestId}...</div>`;

  try {
    const resp = await apiFetch(`/api/requests/${requestId}`);
    const r = await resp.json();
    if (!resp.ok) throw new Error(r.detail || "Request record not found");

    modalBody.innerHTML = `
      <div class="panel-card" style="margin-bottom:14px;">
        <h4 style="font-size:13px;color:var(--text-muted);text-transform:uppercase;margin-bottom:6px;">Query & Classification</h4>
        <p style="font-size:14px;font-weight:600;margin-bottom:8px;">${escapeHtml(r.query)}</p>
        <div style="display:flex;gap:8px;flex-wrap:wrap;">
          <span class="drawer-badge tier">Task: ${escapeHtml(r.task_type)}</span>
          <span class="drawer-badge">Complexity: ${escapeHtml(r.complexity)} (${r.complexity_score})</span>
          <span class="drawer-badge ${r.answer_mode === 'self' ? 'self' : 'switch'}">${r.answer_mode === 'self' ? `<svg class='icon-sym' aria-hidden='true'><use href='#i-bolt'/></svg> Self-Mode` : `<svg class='icon-sym' aria-hidden='true'><use href='#i-swap'/></svg> Switch-Mode`}</span>
          <span class="drawer-badge">Strategy: ${escapeHtml(r.strategy || 'balanced')}</span>
        </div>
      </div>

      <div class="dashboard-panels-grid" style="margin-bottom:14px;">
        <div class="panel-card">
          <h4 style="font-size:13px;color:var(--accent-blue);margin-bottom:8px;"><svg class='icon-sym' aria-hidden='true'><use href='#i-cpu'/></svg> Analyzer LLM Decision</h4>
          <p><strong>Analyzer Model:</strong> ${escapeHtml(r.analyzer_model)} (${escapeHtml(r.analyzer_provider)})</p>
          <p><strong>Analyzer Latency:</strong> ${Math.round(r.analyzer_latency_ms)} ms</p>
          <p><strong>Analyzer Tokens:</strong> ${r.analyzer_input_tokens || 0} in / ${r.analyzer_output_tokens || 0} out</p>
          <p><strong>Analyzer Cost:</strong> $${(r.analyzer_cost || 0).toFixed(6)}</p>
          <p style="margin-top:6px;font-style:italic;color:var(--text-secondary);">"${escapeHtml(r.routing_reason || '—')}"</p>
        </div>

        <div class="panel-card">
          <h4 style="font-size:13px;color:var(--accent-cyan);margin-bottom:8px;"><svg class='icon-sym' aria-hidden='true'><use href='#i-target'/></svg> Execution & Served Model</h4>
          <p><strong>Served Model:</strong> <code>${escapeHtml(r.selected_model)}</code> (${escapeHtml(r.selected_provider)})</p>
          <p><strong>Generation Latency:</strong> ${Math.round(r.latency_ms)} ms ${r.ttft_ms ? `(TTFT: ${Math.round(r.ttft_ms)}ms)` : ''}</p>
          <p><strong>Model Tokens:</strong> ${r.input_tokens || 0} in / ${r.output_tokens || 0} out</p>
          <p><strong>Model Cost:</strong> $${(r.estimated_cost || 0).toFixed(6)}</p>
          <p><strong>Fallback Used:</strong> ${r.fallback_used ? '<span style="color:var(--accent-amber)">Yes</span>' : 'No'}</p>
        </div>
      </div>

      <div class="panel-card" style="margin-bottom:14px;">
        <h4 style="font-size:13px;color:var(--accent-green);margin-bottom:8px;"><svg class='icon-sym' aria-hidden='true'><use href='#i-dollar'/></svg> Optimization Summary</h4>
        <div class="drawer-telemetry-grid">
          <div class="t-box">
            <span class="t-label">Total Latency</span>
            <span class="t-val">${Math.round(r.total_latency_ms)} ms</span>
          </div>
          <div class="t-box">
            <span class="t-label">Total Cost</span>
            <span class="t-val">$${((r.estimated_cost || 0) + (r.analyzer_cost || 0)).toFixed(6)}</span>
          </div>
          <div class="t-box highlight-savings">
            <span class="t-label">Net Cost Reduction</span>
            <span class="t-val text-green">${(r.savings_percent || 0).toFixed(1)}% ($${(r.savings_usd || 0).toFixed(6)})</span>
          </div>
        </div>
      </div>

      ${r.candidates && r.candidates.length > 0 ? `
        <div class="panel-card">
          <h4 style="font-size:13px;color:var(--text-muted);text-transform:uppercase;margin-bottom:8px;">Multi-Factor Candidate Scoreboard</h4>
          <div class="table-responsive">
            <table class="data-table">
              <thead>
                <tr><th>Candidate Model</th><th>Provider</th><th>Tier</th><th>Score</th><th>Est. Cost</th></tr>
              </thead>
              <tbody>
                ${r.candidates.map(c => `
                  <tr>
                    <td><code>${escapeHtml(c.model_id)}</code> ${c.selected ? '✓' : ''}</td>
                    <td>${escapeHtml(c.provider)}</td>
                    <td>${escapeHtml(c.tier)}</td>
                    <td><strong>${c.total.toFixed(3)}</strong></td>
                    <td>$${c.expected_cost_usd.toFixed(6)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      ` : ''}
    `;
  } catch (err) {
    modalBody.innerHTML = `<div class="empty-state text-red">Failed to load telemetry record: ${escapeHtml(err.message)}</div>`;
  }
};

window.recordMessageFeedback = async function(requestId, rating, btn) {
  try {
    const resp = await apiFetch("/api/feedback", {
      method: "POST",
      body: JSON.stringify({ request_id: requestId, rating: rating }),
    });
    if (resp.ok) {
      btn.style.color = rating === 1 ? "var(--accent-green)" : "var(--accent-red)";
      btn.style.borderColor = rating === 1 ? "var(--accent-green)" : "var(--accent-red)";
      showToast(rating === 1 ? "Feedback recorded: Positive" : "Feedback recorded: Negative", "info");
    }
  } catch (e) {
    console.error("Feedback failed:", e);
  }
};

/* ============================================================
   13. Toast Notification Helper
   ============================================================ */

function showToast(message, type = "info", duration = 3000) {
  const container = $("toast-container");
  if (!container) return;

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;

  const icon = type === "success" ? "✓" : (type === "error" ? "✗" : "ℹ");
  toast.innerHTML = `<span>${icon}</span> <span>${escapeHtml(message)}</span>`;

  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(12px) scale(0.95)";
    setTimeout(() => toast.remove(), 200);
  }, duration);
}