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
        geminiAnalyzer: "gemini-3.1-flash-lite",
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

  // Keyboard shortcut listener
  document.addEventListener("keydown", (e) => {
    if ((e.metaKey || e.ctrlKey) && e.key === "b") {
      e.preventDefault();
      $("sidebar")?.classList.toggle("collapsed");
    }
    if ((e.metaKey || e.ctrlKey) && e.key === "n") {
      e.preventDefault();
      $("new-chat-btn")?.click();
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
    if (stateEl) stateEl.textContent = "Single-Pass Decision";
  }
  $$(".rnode-tier").forEach(c => {
    c.classList.remove("active-tier", "escalated-tier");
  });
  const dot = $("pipeline-status-dot");
  if (dot) dot.className = "status-indicator-dot";
  const msg = $("pipeline-status-msg");
  if (msg) msg.textContent = "Analyzer Ready · 6 Response Tiers Active";
  const esc = $("pipeline-escalation-pill");
  if (esc) esc.classList.add("hidden");
}

function updatePipelineToAnalyzing() {
  resetPipelineRibbon();
  const an = $("pnode-analyzer");
  if (an) {
    an.classList.add("analyzing");
    const stateEl = $("pnode-analyzer-state");
    if (stateEl) stateEl.textContent = "Evaluating intent & complexity...";
  }
  const dot = $("pipeline-status-dot");
  if (dot) dot.className = "status-indicator-dot analyzing";
  const msg = $("pipeline-status-msg");
  if (msg) msg.textContent = "Gemini 3.1 Flash-Lite Analyzer running...";
}

function updatePipelineAnalyzerResult(info) {
  const an = $("pnode-analyzer");
  const isSelf = info.answer_mode === "self";
  if (an) {
    an.classList.remove("analyzing");
    const stateEl = $("pnode-analyzer-state");
    if (stateEl) {
      stateEl.textContent = isSelf
        ? "Direct Self-Answer (0 downstream tokens)"
        : `Triage: ${(info.task_type || 'General').toUpperCase()} (${info.complexity || 'Medium'})`;
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
      ? "Resolved in Single-Pass Self-Answer Mode"
      : `Analyzer: ${(info.task_type || 'General').toUpperCase()} ➔ ${formatTierDisplay(targetTier)}`;
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
      <div class="welcome-hero" id="welcome-hero">
        <div class="welcome-badge">
          <svg class='icon-sym' aria-hidden='true'><use href='#i-node-switch'/></svg>
          <span>Context-Aware Multi-Tier Gateway</span>
        </div>
        <h2 class="welcome-title">Smart LLM Switcher</h2>
        <p class="welcome-desc">
          Two-stage intelligent routing: <strong>Gemini 3.1 Flash-Lite Analyzer</strong> triages incoming intent and complexity in real time. Routine requests resolve immediately in single-pass self-mode with zero downstream calls, while complex coding, reasoning, and multi-turn tasks switch dynamically across 6 calibrated response tiers.
        </p>

        <div class="welcome-prompts-section">
          <span class="welcome-prompts-label">Choose a scenario to test context-aware switching across tiers:</span>
          <div class="welcome-prompts-grid" id="welcome-quick-chips">
            <button class="quick-chip-card" data-query="Summarize the primary benefits of semantic caching in 2 bullet points.">
              <div class="chip-top">
                <span class="chip-tier-tag"><svg class='icon-sym'><use href='#i-bolt'/></svg> Tier 1: Fast / Routine</span>
                <span class="chip-arrow">→</span>
              </div>
              <div class="chip-query">Summarize the primary benefits of semantic caching in 2 bullet points.</div>
            </button>
            <button class="quick-chip-card" data-query="Explain the difference between TCP and UDP with real-world networking examples.">
              <div class="chip-top">
                <span class="chip-tier-tag"><svg class='icon-sym'><use href='#i-cpu'/></svg> Tier 2: Fast General</span>
                <span class="chip-arrow">→</span>
              </div>
              <div class="chip-query">Explain the difference between TCP and UDP with real-world networking examples.</div>
            </button>
            <button class="quick-chip-card" data-query="Compare relational databases and document stores for high-throughput write workloads.">
              <div class="chip-top">
                <span class="chip-tier-tag"><svg class='icon-sym'><use href='#i-scale'/></svg> Tier 3: Balanced Workhorse</span>
                <span class="chip-arrow">→</span>
              </div>
              <div class="chip-query">Compare relational databases and document stores for high-throughput write workloads.</div>
            </button>
            <button class="quick-chip-card" data-query="Write a thread-safe Python implementation of an LRU Cache with TTL expiration.">
              <div class="chip-top">
                <span class="chip-tier-tag"><svg class='icon-sym'><use href='#i-code'/></svg> Tier 4: Coding Specialist</span>
                <span class="chip-arrow">→</span>
              </div>
              <div class="chip-query">Write a thread-safe Python implementation of an LRU Cache with TTL expiration.</div>
            </button>
            <button class="quick-chip-card" data-query="Prove that the square root of 2 is irrational and analyze its algebraic implications.">
              <div class="chip-top">
                <span class="chip-tier-tag"><svg class='icon-sym'><use href='#i-node-switch'/></svg> Tier 5: Deep Reasoning</span>
                <span class="chip-arrow">→</span>
              </div>
              <div class="chip-query">Prove that the square root of 2 is irrational and analyze its algebraic implications.</div>
            </button>
            <button class="quick-chip-card" data-query="Design a globally distributed payment ledger ensuring exactly-once processing with high availability.">
              <div class="chip-top">
                <span class="chip-tier-tag"><svg class='icon-sym'><use href='#i-layers'/></svg> Tier 6: High Capability</span>
                <span class="chip-arrow">→</span>
              </div>
              <div class="chip-query">Design a globally distributed payment ledger with exactly-once processing.</div>
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
        
        <div class="routing-badge-bar">
          <span class="routing-tier-pill" id="${cardId}_tier">Analyzing...</span>
          <span class="routing-model-name" id="${cardId}_model">Gemini 3.1 Flash-Lite</span>
          <div class="routing-telemetry-meta" id="${cardId}_meta">
            <span id="${cardId}_lat">Evaluating prompt...</span>
          </div>
        </div>

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
      const tierEl = $(`${cardId}_tier`);
      const modelEl = $(`${cardId}_model`);
      if (tierEl) tierEl.textContent = isSelf ? "Self-Answer" : (info.required_capability || "Tier 1").toUpperCase();
      if (modelEl) modelEl.textContent = isSelf ? "Resolved in Single Pass" : `Routing (${info.task_type || 'General'})`;
    },
    updateRouting: (route) => {
      const tierEl = $(`${cardId}_tier`);
      const modelEl = $(`${cardId}_model`);
      if (tierEl) tierEl.textContent = (route.target_tier || "Tier 1").toUpperCase();
      if (modelEl) modelEl.textContent = route.target_name || route.target_model || "Model";
    },
    appendReasoningDelta: (reasoning) => {},
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
        body.innerHTML = `<span style="color:var(--accent-red);">Stream error: ${escapeHtml(err)}</span>`;
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
  const routingReason = data.routing_reason || analyzer.reason || model.reason || "Cost-optimal model selection";

  const isEscalated = Boolean(data.escalation_used || data.escalated);

  const costNumber = data.total_cost_usd != null ? data.total_cost_usd : (data.estimated_cost_usd || 0.0);
  const costStr = `$${costNumber.toFixed(6)}`;
  const latencyNumber = data.total_latency_ms != null ? data.total_latency_ms : (data.latency_ms || 0.0);
  const latencyStr = `${Math.round(latencyNumber)} ms`;
  const savingsPct = data.savings_percent != null && data.savings_percent > 0 ? `${data.savings_percent.toFixed(1)}% saved` : null;

  // Build candidate scoreboard rows
  let scoreboardRows = "";
  if (Array.isArray(data.candidates) && data.candidates.length > 0) {
    scoreboardRows = data.candidates.map(c => `
      <tr class="${c.selected ? 'selected' : ''}">
        <td><strong>${escapeHtml(c.tier.toUpperCase())}</strong></td>
        <td>${escapeHtml(c.name)}</td>
        <td>${c.total.toFixed(2)}</td>
        <td>${Math.round(c.expected_latency_ms)}ms</td>
        <td>$${c.expected_cost_usd.toFixed(6)}</td>
        <td>${c.selected ? '✓ Selected' : '—'}</td>
      </tr>
    `).join("");
  }

  msgEl.innerHTML = `
    <div class="msg-avatar"><svg class='icon-sym' aria-hidden='true'><use href='#i-node-switch'/></svg></div>
    <div class="msg-content-wrap">
      <div class="assistant-card">
        
        <!-- Humanized Routing Badge Bar -->
        <div class="routing-badge-bar">
          <span class="routing-tier-pill">${isSelf ? 'Self-Answer' : servedTierNorm.toUpperCase()}</span>
          <span class="routing-model-name">${escapeHtml(targetModelName)}</span>
          <div class="routing-telemetry-meta">
            <span>${latencyStr}</span>
            <span>·</span>
            <span>${costStr}</span>
            ${savingsPct ? `<span>·</span><span class="savings-text">${savingsPct} vs baseline</span>` : ''}
          </div>
        </div>

        <!-- Assistant Markdown Answer -->
        <div class="msg-text-body">
          ${formatMarkdown(text)}
        </div>

        <!-- Expandable Routing & Scoreboard Drawer -->
        <div class="routing-drawer" id="${drawerId}">
          <div class="routing-drawer-head" data-action="toggle-drawer" data-target="${drawerId}">
            <span>Routing Rationale &amp; Scoreboard</span>
            <span class="drawer-arrow">▾</span>
          </div>
          <div class="routing-drawer-content hidden" id="${drawerId}_content">
            <div class="drawer-grid">
              <div class="drawer-cell">
                <span class="drawer-cell-label">Task Type</span>
                <span class="drawer-cell-val">${escapeHtml(taskType.toUpperCase())}</span>
              </div>
              <div class="drawer-cell">
                <span class="drawer-cell-label">Complexity</span>
                <span class="drawer-cell-val">${escapeHtml(complexity.toUpperCase())} (${complexityScore})</span>
              </div>
              <div class="drawer-cell">
                <span class="drawer-cell-label">Verification</span>
                <span class="drawer-cell-val ${isEscalated ? 'text-amber' : 'text-green'}">
                  ${isEscalated ? '⚡ Escalated to Frontier' : '✓ Quality Verified'}
                </span>
              </div>
            </div>
            
            <div class="drawer-reason">
              "${escapeHtml(routingReason)}"
            </div>

            ${scoreboardRows ? `
              <div style="margin-top:6px;">
                <span class="drawer-cell-label">Candidate Tier Scoreboard:</span>
                <table class="scoreboard-table">
                  <thead>
                    <tr>
                      <th>Tier</th>
                      <th>Model</th>
                      <th>Score</th>
                      <th>Latency</th>
                      <th>Est. Cost</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>${scoreboardRows}</tbody>
                </table>
              </div>
            ` : ''}
          </div>
        </div>

        <!-- Telemetry Actions Bar -->
        <div class="telemetry-footer">
          <div class="telemetry-actions">
            <button class="btn-icon-action" data-action="copy-message" data-text="${escapeHtml(text)}" title="Copy Response">
              <svg class='icon-sym' aria-hidden='true'><use href='#i-copy'/></svg> Copy Answer
            </button>
            ${data.request_id ? `
              <button class="btn-icon-action" data-action="open-inspector" data-id="${data.request_id}" title="Inspect Full Telemetry">
                <svg class='icon-sym' aria-hidden='true'><use href='#i-search'/></svg> Inspect
              </button>
              <button class="btn-icon-action" data-action="feedback" data-id="${data.request_id}" data-rating="1" title="Helpful Response">
                <svg class='icon-sym' aria-hidden='true'><use href='#i-thumb-up'/></svg>
              </button>
              <button class="btn-icon-action" data-action="feedback" data-id="${data.request_id}" data-rating="-1" title="Poor Response">
                <svg class='icon-sym' aria-hidden='true'><use href='#i-thumb-down'/></svg>
              </button>
            ` : ''}
          </div>
        </div>

      </div>
    </div>
  `;

  // Drawer Toggle Handler
  const drawerHead = msgEl.querySelector(`[data-target="${drawerId}"]`);
  const drawerContent = msgEl.querySelector(`#${drawerId}_content`);
  const arrow = msgEl.querySelector(".drawer-arrow");

  drawerHead?.addEventListener("click", () => {
    if (!drawerContent) return;
    drawerContent.classList.toggle("hidden");
    if (arrow) arrow.textContent = drawerContent.classList.contains("hidden") ? "▾" : "▴";
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
          if (resp.ok) {
            btn.classList.add("active-feedback");
            showToast("Feedback recorded", "success");
          }
        } catch (e) {
          console.error("Feedback error:", e);
        }
      });
    }
  });

  container.appendChild(msgEl);
  _renderMathInElement(msgEl.querySelector(".msg-text-body"));
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

async function loadRegistryModels() {
  const tbody = $("registry-table-body");
  if (!tbody) return;

  try {
    const resp = await apiFetch("/api/models");
    if (!resp.ok) throw new Error("Failed to fetch models");

    const data = await resp.json();
    const models = data.models || [];

    if ($("reg-total-models")) $("reg-total-models").textContent = models.length.toString();

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

    tbody.innerHTML = models.map(m => {
      const tierTag = m.tier.toUpperCase();
      const inPrice = `$${m.input_price_per_mtok.toFixed(3)}`;
      const outPrice = `$${m.output_price_per_mtok.toFixed(3)}`;
      const isOnline = m.available;
      const statusBadge = isOnline
        ? `<span style="color:var(--accent-green-bright);font-weight:600;">● Active (${m.mode})</span>`
        : `<span style="color:var(--text-muted);">○ Inactive</span>`;

      return `
        <tr>
          <td><span class="routing-tier-pill">${escapeHtml(tierTag)}</span></td>
          <td><strong>${escapeHtml(m.name)}</strong></td>
          <td>${escapeHtml((m.provider || 'gemini').toUpperCase())}</td>
          <td>${m.quality != null ? (m.quality * 100).toFixed(0) + '%' : '—'}</td>
          <td>${m.reasoning != null ? (m.reasoning * 100).toFixed(0) + '%' : '—'}</td>
          <td>${m.coding != null ? (m.coding * 100).toFixed(0) + '%' : '—'}</td>
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
    if ($("stat-savings-pct")) $("stat-savings-pct").textContent = `${(s.savings_percent || 0).toFixed(1)}% savings vs baseline`;
    if ($("stat-avg-latency")) $("stat-avg-latency").textContent = `${Math.round(s.average_total_latency_ms || 0)} ms`;
    if ($("stat-analyzer-latency")) $("stat-analyzer-latency").textContent = `Gen: ${Math.round(s.average_latency_ms || 0)} ms avg`;
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

  const maxVal = Math.max(...data.map(d => d.count), 1);
  const total = data.reduce((acc, d) => acc + d.count, 0);

  container.innerHTML = data.map(d => {
    const pct = ((d.count / maxVal) * 100).toFixed(0);
    const share = ((d.count / total) * 100).toFixed(0);
    const label = containerId === "chart-tier-dist" ? formatTierDisplay(d.name) : d.name;
    return `
      <div class="chart-bar-row">
        <span class="chart-bar-label" title="${escapeHtml(label)}">${escapeHtml(label)}</span>
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
      ? `<span style="color:var(--accent-green-bright);font-weight:600;">✓ Ok</span>`
      : `<span style="color:var(--accent-red);font-weight:600;">✗ Error</span>`;
    const fb = r.fallback_used
      ? `<span style="color:var(--accent-amber);font-weight:600;">Yes</span>`
      : `<span style="color:var(--text-muted);">No</span>`;
    const tierDisplay = formatTierDisplay(r.target_tier || r.tier);

    return `
      <tr data-action="open-inspector" data-id="${r.id}">
        <td>${escapeHtml(r.timestamp ? (r.timestamp.split(" ")[1] || r.timestamp) : "—")}</td>
        <td title="${escapeHtml(r.query)}" style="max-width:240px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          ${escapeHtml(r.query)}
        </td>
        <td><span class="routing-tier-pill">${escapeHtml((r.task_type || "general").toUpperCase())}</span></td>
        <td>${escapeHtml(r.complexity || "medium")}</td>
        <td title="${escapeHtml(tierDisplay)}"><code>${escapeHtml(r.selected_model || "Model")}</code></td>
        <td>${Math.round(r.total_latency_ms || r.latency_ms || 0)} ms</td>
        <td>${cost}</td>
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
      if ($("bm-baseline-cost")) $("bm-baseline-cost").textContent = `vs Baseline 1: $${data.baseline1_total_cost_usd.toFixed(4)}`;

      // Render Matrix Table
      const tbody = $("benchmark-tbody");
      if (tbody && Array.isArray(data.items)) {
        tbody.innerHTML = data.items.map(item => `
          <tr>
            <td>
              <strong>${escapeHtml(item.query)}</strong><br>
              <span style="font-size:11px;color:var(--text-muted);">${escapeHtml(item.task_type.toUpperCase())} · ${escapeHtml(item.complexity)}</span>
            </td>
            <td>
              <code>${escapeHtml(item.baseline1_model)}</code><br>
              <span style="font-size:11px;color:var(--text-muted);">$${item.baseline1_cost_usd.toFixed(6)} · ${item.baseline1_latency_ms}ms</span>
            </td>
            <td>
              <code>${escapeHtml(item.baseline2_model)}</code><br>
              <span style="font-size:11px;color:var(--text-muted);">$${item.baseline2_cost_usd.toFixed(6)} · ${item.baseline2_latency_ms}ms</span>
            </td>
            <td>
              <code>${escapeHtml(item.smart_model)}</code><br>
              <span style="font-size:11px;color:var(--text-muted);">$${item.smart_cost_usd.toFixed(6)} · ${item.smart_latency_ms}ms</span>
            </td>
            <td><strong class="text-green">${item.smart_savings_percent.toFixed(1)}%</strong></td>
            <td><strong class="text-blue">${item.smart_speedup_percent.toFixed(1)}%</strong></td>
          </tr>
        `).join("");
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

    settings.providerModels.geminiAnalyzer = $("model-gemini-analyzer")?.value.trim() || "gemini-3.1-flash-lite";
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

  if ($("model-gemini-analyzer")) $("model-gemini-analyzer").value = settings.providerModels.geminiAnalyzer || "gemini-3.1-flash-lite";
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
    body.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:14px;">
        <div style="padding:10px 14px;background:var(--bg-card);border:1px solid var(--border-subtle);border-radius:var(--radius-md);">
          <strong>Prompt:</strong>
          <p style="margin-top:4px;color:var(--text-secondary);">${escapeHtml(d.query)}</p>
        </div>

        <div class="drawer-grid">
          <div class="drawer-cell">
            <span class="drawer-cell-label">Served Model</span>
            <span class="drawer-cell-val">${escapeHtml(d.selected_model || 'Model')} (${escapeHtml(d.provider || '')})</span>
          </div>
          <div class="drawer-cell">
            <span class="drawer-cell-label">Tier</span>
            <span class="drawer-cell-val">${escapeHtml(formatTierDisplay(d.target_tier))}</span>
          </div>
          <div class="drawer-cell">
            <span class="drawer-cell-label">Total Cost (USD)</span>
            <span class="drawer-cell-val text-green">$${(d.total_cost_usd || d.estimated_cost || 0).toFixed(6)}</span>
          </div>
          <div class="drawer-cell">
            <span class="drawer-cell-label">Latency</span>
            <span class="drawer-cell-val">${Math.round(d.total_latency_ms || d.latency_ms || 0)} ms</span>
          </div>
          <div class="drawer-cell">
            <span class="drawer-cell-label">Tokens Metered</span>
            <span class="drawer-cell-val">${(d.total_tokens || 0).toLocaleString()}</span>
          </div>
          <div class="drawer-cell">
            <span class="drawer-cell-label">Routing Strategy</span>
            <span class="drawer-cell-val">${escapeHtml(d.strategy || 'balanced')}</span>
          </div>
        </div>

        <div style="margin-top:8px;">
          <span class="drawer-cell-label">Complete Telemetry JSON:</span>
          <pre class="code-block-pre" style="margin-top:4px;border-radius:var(--radius-sm);max-height:220px;overflow-y:auto;"><code>${escapeHtml(JSON.stringify(d, null, 2))}</code></pre>
        </div>
      </div>
    `;
  } catch (err) {
    body.innerHTML = `<div style="color:var(--accent-red);padding:16px;">Failed to load request: ${escapeHtml(err.message)}</div>`;
  }
}

/* ============================================================
   16. Utilities: Markdown, LaTeX Math, Scrolling, Toasts
   ============================================================ */
function formatMarkdown(text) {
  if (!text) return "";
  try {
    if (typeof marked !== "undefined") {
      marked.setOptions({
        gfm: true,
        breaks: true,
      });
      const rawHtml = marked.parse(text);
      if (typeof DOMPurify !== "undefined") {
        return DOMPurify.sanitize(rawHtml);
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
  container.scrollTo({
    top: container.scrollHeight,
    behavior: "smooth",
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