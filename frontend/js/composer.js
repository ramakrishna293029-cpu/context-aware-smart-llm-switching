/**
 * Context-Aware Smart LLM Switcher - Floating Island Prompt Composer
 * Chunk 6: composer.js (Apple HIG & Fluid Motion Principles)
 * 
 * Features:
 * - Floating monolithic island anchored to viewport bottom with backdrop blur.
 * - Fluid auto-resizing textarea with strict scale bounds (38px to 180px).
 * - Responsive platform-aware keyboard shortcut indicators (Cmd/Ctrl+Enter, Shift+Enter).
 * - Routing mode selector pills (Smart LinUCB, Balanced, Cost, Fast, Quality, Direct).
 * - Dynamic dual-state circular action button (Send / Stop generation) with tactile press feedback.
 * - Quick prompt suggestion chips with one-click insertion.
 * - Real-time conversation memory context pill synchronization.
 * - Clean modular ES6+ exports with global fallback attachments.
 */

// Helper to safely escape HTML attributes and strings
function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

// Full strategy display name and alias mapping
export const STRATEGY_NAMES = {
  smart: "Smart LinUCB",
  linucb: "Smart LinUCB",
  smart_linucb: "Smart LinUCB",
  balanced: "Balanced",
  lowest_cost: "Cost",
  cost: "Cost",
  fastest: "Fast",
  fast: "Fast",
  highest_quality: "Quality",
  quality: "Quality",
  direct: "Direct",
};

// Routing mode selector pills definition
export const ROUTING_MODES = [
  { id: "smart", value: "balanced", label: "Smart LinUCB", short: "Smart", title: "Smart LinUCB Contextual Bandit Dynamic Routing" },
  { id: "balanced", value: "balanced", label: "Balanced", short: "Balanced", title: "Balanced Cost & Capability Tradeoff" },
  { id: "lowest_cost", value: "lowest_cost", label: "Cost", short: "Cost", title: "Lowest Cost Optimization Priority" },
  { id: "fastest", value: "fastest", label: "Fast", short: "Fast", title: "Lowest Latency Velocity Priority" },
  { id: "highest_quality", value: "highest_quality", label: "Quality", short: "Quality", title: "Frontier Highest Intelligence Tier" },
  { id: "direct", value: "lowest_cost", label: "Direct", short: "Direct", title: "Direct Gemini Flash-Lite Single-Pass" },
];

// Curated prompt suggestion chips
export const QUICK_PROMPTS = [
  { id: "semantic", label: "Semantic Caching", icon: "⚡", query: "Summarize the primary benefits of semantic caching in 2 bullet points." },
  { id: "database", label: "Relational vs NoSQL", icon: "⚖️", query: "Compare relational databases and document stores for high-throughput write workloads." },
  { id: "cache", label: "Thread-Safe LRU", icon: "🐍", query: "Write a thread-safe Python implementation of an LRU Cache with TTL expiration." },
  { id: "proof", label: "Proof of √2", icon: "📐", query: "Prove that the square root of 2 is irrational and analyze its algebraic implications." },
  { id: "summary", label: "Model Routing", icon: "🚀", query: "Explain how context-aware LLM switching optimizes API costs and latency." },
];

/**
 * Helper to query DOM elements safely by ID.
 * @param {string} id 
 * @returns {HTMLElement|null}
 */
function getEl(id) {
  return typeof document !== "undefined" ? document.getElementById(id) : null;
}

/**
 * Detects client OS platform to provide authentic Apple vs PC keyboard shortcut formatting.
 * @returns {{isMac: boolean, modKey: string, keySymbol: string, sendShortcut: string, sendTitle: string, newlineHint: string, fullHint: string}}
 */
export function getPlatformShortcutInfo() {
  const isMac = typeof navigator !== "undefined" &&
    Boolean(
      (navigator.userAgentData?.platform && navigator.userAgentData.platform.toLowerCase().includes("mac")) ||
      /Mac|iPod|iPhone|iPad/.test(navigator.platform || navigator.userAgent)
    );

  return {
    isMac,
    modKey: isMac ? "⌘" : "Ctrl",
    keySymbol: "↵",
    sendShortcut: isMac ? "⌘↵" : "Ctrl↵",
    sendTitle: isMac ? "Send Message (⌘+Enter or Enter)" : "Send Message (Ctrl+Enter or Enter)",
    newlineHint: "Shift+Enter for newline",
    fullHint: isMac ? "⌘↵ to send · ⇧↵ for newline" : "Ctrl↵ to send · ⇧↵ for newline",
  };
}

/**
 * Dynamically updates the keyboard shortcut indicator badge based on active platform.
 */
export function updateKeyboardShortcutIndicator() {
  const kbdHint = document.querySelector(".kbd-hint") || getEl("kbd-shortcut-hint");
  if (!kbdHint) return;
  const info = getPlatformShortcutInfo();
  kbdHint.innerHTML = `<kbd class="kbd-mod">${info.modKey}</kbd><kbd class="kbd-sym">${info.keySymbol}</kbd>`;
  kbdHint.setAttribute("title", `${info.sendTitle} · ${info.newlineHint}`);
}

/**
 * Synchronizes header strategy badge, composer strategy selector dropdown, and mode pills.
 * 
 * @param {string} strategy - 'smart' | 'balanced' | 'lowest_cost' | 'fastest' | 'highest_quality' | 'direct'
 */
export function updateStrategyBadge(strategy) {
  const normStrategy = (strategy || "balanced").toLowerCase().trim();
  const displayName = STRATEGY_NAMES[normStrategy] || "Balanced";

  // Update header pill label
  const headerBadge = getEl("header-strategy-badge");
  if (headerBadge) {
    const label = headerBadge.querySelector(".pill-label");
    if (label) {
      label.textContent = displayName;
    }
  }

  // Update composer dropdown selector if out of sync
  const strategySelect = getEl("strategy-select");
  if (strategySelect) {
    const mappedVal = (normStrategy === "smart" || normStrategy === "direct") ? "balanced" : normStrategy;
    if (strategySelect.value !== mappedVal && strategySelect.querySelector(`option[value="${mappedVal}"]`)) {
      strategySelect.value = mappedVal;
    }
  }

  // Update active state in mode pills if present
  document.querySelectorAll(".composer-mode-pill").forEach((pill) => {
    const pillStrat = pill.dataset.strategy || pill.dataset.modeId;
    const isMatch = pillStrat === normStrategy || pill.dataset.modeId === normStrategy;
    pill.classList.toggle("active", isMatch);
  });
}

/**
 * Updates the conversation context memory counter in the composer toolbar pill.
 * 
 * @param {number} [count] - Optional explicit turn count. If omitted, queries sessionManager.
 */
export function updateContextCounter(count) {
  let turns = count;

  if (typeof turns !== "number") {
    const active = typeof window !== "undefined" && window.sessionManager
      ? window.sessionManager.getActive()
      : null;
    turns = (active && Array.isArray(active.messages)) ? active.messages.length : 0;
  }

  const counterEl = getEl("context-turn-count");
  if (counterEl) {
    counterEl.textContent = turns.toString();
  }

  const contextPill = getEl("context-pill");
  if (contextPill) {
    contextPill.setAttribute("title", `Conversation Memory Window: ${turns} turns active`);
  }
}

/**
 * Toggles the action button state between Send (arrow up) and Stop (square stop) states with tactile press feedback.
 * 
 * @param {boolean} isStreaming - True if generation is currently streaming
 */
export function setStreamingState(isStreaming) {
  const btn = getEl("send-stop-btn");
  const icon = getEl("send-btn-icon");
  if (!btn || !icon) return;

  if (isStreaming) {
    btn.classList.add("stop-state");
    btn.title = "Stop Generation (Esc)";
    btn.setAttribute("aria-label", "Stop Generation");
    icon.innerHTML = '<svg class="icon-sym" aria-hidden="true"><use href="#i-stop"/></svg>';
  } else {
    btn.classList.remove("stop-state");
    const info = getPlatformShortcutInfo();
    btn.title = `Send Message (${info.sendShortcut} or Enter)`;
    btn.setAttribute("aria-label", "Send Message");
    icon.innerHTML = '<svg class="icon-sym" aria-hidden="true"><use href="#i-arrow-up"/></svg>';
  }
}

/**
 * Checks whether generation is currently marked as streaming.
 * @returns {boolean}
 */
export function isStreamingActive() {
  const btn = getEl("send-stop-btn");
  return btn ? btn.classList.contains("stop-state") : false;
}

/**
 * Automatically adjusts the textarea height based on content strictly between 38px and 180px.
 * @param {HTMLTextAreaElement} [textareaEl] 
 */
export function autoResizeComposerInput(textareaEl) {
  const input = textareaEl || getEl("query-input");
  if (!input) return;

  input.style.height = "auto";
  const newHeight = Math.min(Math.max(input.scrollHeight, 38), 180);
  input.style.height = `${newHeight}px`;
}

/**
 * Resets the query input value and restores default 38px height.
 */
export function resetComposerInput() {
  const input = getEl("query-input");
  if (input) {
    input.value = "";
    input.style.height = "38px";
  }
}

/**
 * Programmatically sets value in the query input, recalculates height, and focuses.
 * @param {string} text 
 */
export function setComposerValue(text) {
  const input = getEl("query-input");
  if (input) {
    input.value = text || "";
    autoResizeComposerInput(input);
    input.focus();
  }
}

/**
 * Focuses the prompt input textarea.
 */
export function focusComposer() {
  const input = getEl("query-input");
  if (input) {
    input.focus();
  }
}

/**
 * Retrieves the current prompt query from the textarea.
 * @returns {string}
 */
export function getComposerQuery() {
  const input = getEl("query-input");
  return input ? input.value.trim() : "";
}

/**
 * Retrieves the currently selected routing strategy value.
 * @returns {string}
 */
export function getComposerStrategy() {
  const strategySelect = getEl("strategy-select");
  return strategySelect ? strategySelect.value : "balanced";
}

/**
 * Halts active streaming generation.
 */
export function stopGeneration() {
  if (typeof window !== "undefined") {
    if (window.activeAbortController) {
      window.activeAbortController.abort();
      window.activeAbortController = null;
    }
    if (typeof window.showToast === "function") {
      window.showToast("Generation stopped", "info");
    }
  }
  setStreamingState(false);
}

/**
 * Renders or synchronizes the routing mode selector pills in the composer toolbar.
 * 
 * @param {HTMLElement} [containerEl] - Target container element
 * @param {string} [currentStrategy='balanced'] - Current active strategy
 * @param {Function} [onSelect] - Selection callback: (strategy) => void
 */
export function renderComposerModePills(containerEl, currentStrategy = "balanced", onSelect) {
  let target = containerEl || getEl("composer-mode-pills");
  if (!target) {
    const wrapper = document.querySelector(".strategy-selector-wrapper");
    if (wrapper) {
      target = document.createElement("div");
      target.id = "composer-mode-pills";
      target.className = "composer-mode-pills";
      wrapper.appendChild(target);
    }
  }
  if (!target) return;

  const norm = (currentStrategy || "balanced").toLowerCase().trim();
  target.innerHTML = ROUTING_MODES.map((mode) => {
    const isActive = mode.id === norm || mode.value === norm;
    return `
      <button 
        type="button" 
        class="composer-mode-pill ${isActive ? "active" : ""}" 
        data-mode-id="${mode.id}"
        data-strategy="${mode.value || mode.id}"
        title="${escapeHtml(mode.title || mode.label)}"
      >
        <span class="mode-pill-label">${escapeHtml(mode.label)}</span>
      </button>
    `;
  }).join("");

  target.querySelectorAll(".composer-mode-pill").forEach((btn) => {
    btn.addEventListener("click", () => {
      const strat = btn.dataset.strategy;
      updateStrategyBadge(strat);
      if (typeof onSelect === "function") {
        onSelect(strat);
      }
    });
  });
}

/**
 * Mounts and wires quick prompt suggestion chips above the composer dock.
 * 
 * @param {Object} [options]
 * @param {boolean} [options.autoSubmit=false] - Whether to submit immediately upon chip click
 */
export function setupQuickPromptChips(options = {}) {
  const chipsContainer = getEl("composer-quick-chips") || document.querySelector(".composer-quick-chips");
  const composerContainer = document.querySelector(".composer-container");
  const composerCard = getEl("composer-form") || document.querySelector(".composer-card");

  let container = chipsContainer;
  if (!container && composerContainer && composerCard) {
    container = document.createElement("div");
    container.id = "composer-quick-chips";
    container.className = "composer-quick-chips";
    composerContainer.insertBefore(container, composerCard);
  }

  if (!container) return;

  container.innerHTML = QUICK_PROMPTS.map((prompt) => `
    <button type="button" class="composer-chip" data-query="${escapeHtml(prompt.query)}" title="${escapeHtml(prompt.query)}">
      <span class="chip-icon">${prompt.icon}</span>
      <span class="chip-text">${escapeHtml(prompt.label)}</span>
    </button>
  `).join("");

  container.querySelectorAll(".composer-chip").forEach((chip) => {
    chip.addEventListener("click", () => {
      const q = chip.dataset.query;
      if (!q) return;
      setComposerValue(q);
      if (options.autoSubmit) {
        const form = getEl("composer-form");
        if (form) {
          if (typeof form.requestSubmit === "function") form.requestSubmit();
          else form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        }
      }
    });
  });
}

/**
 * Initializes and wires up the Floating Island Prompt Composer.
 * 
 * @param {Object} [options]
 * @param {Function} [options.onSubmit] - Callback invoked when prompt is submitted: (query, strategy, event)
 * @param {Function} [options.onStop] - Callback invoked when stop button is clicked during stream
 * @param {Function} [options.onStrategyChange] - Callback invoked when strategy selector changes: (strategy)
 * @param {Function} [options.onClearContext] - Callback invoked when clear context button is clicked
 */
export function setupComposer(options = {}, onStop) {
  let opts = options;
  if (typeof options === "function") {
    opts = { onSubmit: options, onStop: onStop };
  }

  const form = getEl("composer-form");
  const input = getEl("query-input");
  const strategySelect = getEl("strategy-select");
  const clearContextBtn = getEl("clear-context-btn");
  const messagesContainer = getEl("chat-messages");

  // Prevent default HTML form submission unconditionally
  if (form && !form._hasDefaultPrevent) {
    form._hasDefaultPrevent = true;
    form.addEventListener("submit", (e) => e.preventDefault());
  }

  // Track user scroll position in chat messages container
  if (messagesContainer && !messagesContainer._hasScrollTracker) {
    messagesContainer._hasScrollTracker = true;
    messagesContainer.addEventListener("scroll", () => {
      const threshold = 80;
      const distFromBottom = messagesContainer.scrollHeight - messagesContainer.scrollTop - messagesContainer.clientHeight;
      if (typeof window !== "undefined") {
        window.isUserScrolledUp = distFromBottom > threshold;
      }
    });
  }

  // Auto-resize textarea on input with strict scale bounds (38px to 180px)
  if (input && !input._hasAutoResize) {
    input._hasAutoResize = true;
    input.addEventListener("input", () => {
      autoResizeComposerInput(input);
    });

    // Enter or Cmd/Ctrl+Enter to send (Shift+Enter for multiline newline)
    input.addEventListener("keydown", (e) => {
      const isSend = (e.key === "Enter" && !e.shiftKey) || (e.key === "Enter" && (e.metaKey || e.ctrlKey));
      if (isSend && !e.isComposing) {
        e.preventDefault();
        if (isStreamingActive()) {
          if (typeof opts.onStop === "function") {
            opts.onStop();
          } else {
            stopGeneration();
          }
        } else if (form) {
          if (typeof form.requestSubmit === "function") {
            form.requestSubmit();
          } else {
            form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
          }
        }
      } else if (e.key === "Escape" && isStreamingActive()) {
        e.preventDefault();
        if (typeof opts.onStop === "function") {
          opts.onStop();
        } else {
          stopGeneration();
        }
      }
    });
  }

  // Update platform-aware shortcut hint
  updateKeyboardShortcutIndicator();

  // Strategy Selector change handler
  if (strategySelect && !strategySelect._hasChangeHandler) {
    strategySelect._hasChangeHandler = true;
    strategySelect.addEventListener("change", async () => {
      const val = strategySelect.value;
      updateStrategyBadge(val);

      // Persist strategy preference to SettingsManager if available
      try {
        if (typeof window !== "undefined" && window.SettingsManager) {
          const settings = await window.SettingsManager.load();
          if (settings && settings.preferences) {
            settings.preferences.strategy = val;
            await window.SettingsManager.save(settings);
          }
        }
      } catch (err) {
        console.warn("[composer.js] Could not persist strategy preference:", err);
      }

      if (typeof opts.onStrategyChange === "function") {
        opts.onStrategyChange(val);
      }
    });
  }

  // Clear Context button handler
  if (clearContextBtn && !clearContextBtn._hasClickHandler) {
    clearContextBtn._hasClickHandler = true;
    clearContextBtn.addEventListener("click", () => {
      if (typeof opts.onClearContext === "function") {
        opts.onClearContext();
        return;
      }

      // Default context clearing behavior
      if (typeof window !== "undefined" && window.sessionManager) {
        const active = window.sessionManager.getActive();
        if (active && Array.isArray(active.messages) && active.messages.length > 0) {
          if (confirm("Clear memory for this session?")) {
            active.messages = [];
            window.sessionManager.save();
            if (typeof window.renderActiveSessionMessages === "function") {
              window.renderActiveSessionMessages();
            }
            if (typeof window.showToast === "function") {
              window.showToast("Conversation memory cleared", "info");
            }
            updateContextCounter(0);
          }
        } else {
          updateContextCounter(0);
        }
      }
    });
  }

  // Form submit handler (if consumer passed an onSubmit callback)
  if (form && typeof opts.onSubmit === "function" && !form._hasCustomSubmit) {
    form._hasCustomSubmit = true;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();

      if (isStreamingActive()) {
        if (typeof opts.onStop === "function") {
          opts.onStop();
        } else {
          stopGeneration();
        }
        return;
      }

      const query = input ? input.value.trim() : "";
      if (!query) return;

      const strategy = strategySelect ? strategySelect.value : "balanced";
      resetComposerInput();

      await opts.onSubmit(query, strategy, e);
    });
  }

  // Mount quick prompt suggestion chips
  setupQuickPromptChips({ autoSubmit: false });

  // Initialize context counter from active session on setup
  updateContextCounter();
}

// Global browser window attachment for non-bundled scripts
if (typeof window !== "undefined") {
  window.setupComposer = setupComposer;
  window.setStreamingState = setStreamingState;
  window.updateContextCounter = updateContextCounter;
  window.updateStrategyBadge = updateStrategyBadge;
  window.autoResizeComposerInput = autoResizeComposerInput;
  window.resetComposerInput = resetComposerInput;
  window.setComposerValue = setComposerValue;
  window.focusComposer = focusComposer;
  window.getComposerQuery = getComposerQuery;
  window.getComposerStrategy = getComposerStrategy;
  window.stopGeneration = stopGeneration;
  window.isStreamingActive = isStreamingActive;
  window.renderComposerModePills = renderComposerModePills;
  window.setupQuickPromptChips = setupQuickPromptChips;
  window.getPlatformShortcutInfo = getPlatformShortcutInfo;
  window.updateKeyboardShortcutIndicator = updateKeyboardShortcutIndicator;
  window.ROUTING_MODES = ROUTING_MODES;
  window.STRATEGY_NAMES = STRATEGY_NAMES;
  window.QUICK_PROMPTS = QUICK_PROMPTS;

  window.ComposerModule = {
    setupComposer,
    setStreamingState,
    updateContextCounter,
    updateStrategyBadge,
    autoResizeComposerInput,
    resetComposerInput,
    setComposerValue,
    focusComposer,
    getComposerQuery,
    getComposerStrategy,
    stopGeneration,
    isStreamingActive,
    renderComposerModePills,
    setupQuickPromptChips,
    getPlatformShortcutInfo,
    updateKeyboardShortcutIndicator,
    ROUTING_MODES,
    STRATEGY_NAMES,
    QUICK_PROMPTS,
  };
}

if (typeof globalThis !== "undefined") {
  globalThis.setupComposer = setupComposer;
  globalThis.setStreamingState = setStreamingState;
  globalThis.updateContextCounter = updateContextCounter;
  globalThis.updateStrategyBadge = updateStrategyBadge;
  globalThis.ComposerModule = typeof window !== "undefined" ? window.ComposerModule : {
    setupComposer,
    setStreamingState,
    updateContextCounter,
    updateStrategyBadge,
    autoResizeComposerInput,
    resetComposerInput,
    setComposerValue,
    focusComposer,
    getComposerQuery,
    getComposerStrategy,
    stopGeneration,
    isStreamingActive,
    renderComposerModePills,
    setupQuickPromptChips,
    getPlatformShortcutInfo,
    updateKeyboardShortcutIndicator,
    ROUTING_MODES,
    STRATEGY_NAMES,
    QUICK_PROMPTS,
  };
}

export default {
  setupComposer,
  setStreamingState,
  updateContextCounter,
  updateStrategyBadge,
  autoResizeComposerInput,
  resetComposerInput,
  setComposerValue,
  focusComposer,
  getComposerQuery,
  getComposerStrategy,
  stopGeneration,
  isStreamingActive,
  renderComposerModePills,
  setupQuickPromptChips,
  getPlatformShortcutInfo,
  updateKeyboardShortcutIndicator,
  ROUTING_MODES,
  STRATEGY_NAMES,
  QUICK_PROMPTS,
};
