/**
 * ============================================================================
 * Smart LLM Switcher — Master Application Orchestrator & Bootstrap
 * Chunk 13: Core Application Lifecycle, View Routing, and Reactive Event Bus
 * 
 * Implements Apple HIG & Claude Design Standards:
 * - OLED True Black (#000000) canvas & translucent liquid glass surfaces
 * - Fluid view transitions with critically damped spring timing
 * - Zero-latency pointer-down tactile feedback
 * - Tabular monospace numeric telemetry alignment
 * - Resilient Server-Sent Events (SSE) streaming with seamless unary fallback
 * ============================================================================
 */

import { SettingsManager, apiFetch } from "./storage.js";
import {
  $,
  $$,
  escapeHtml,
  formatMarkdown,
  _renderMathInElement,
  smoothScrollToBottom,
  setupCodeCopyHandler,
  showToast,
} from "./utils.js";
import { SessionManager } from "./session.js";
import { executeStreamingChat } from "./stream.js";
import {
  setupSidebarControls,
  renderSidebarSessions,
  promptRenameSession,
  setupKeyboardShortcuts,
} from "./sidebar.js";
import {
  renderActiveSessionMessages,
  appendUserMessageToUI,
  createStreamingPlaceholder,
  appendAssistantResponseToUI,
} from "./chat.js?v=3.3";
import {
  setupComposer,
  updateStrategyBadge,
  updateContextCounter,
  setStreamingState,
  isStreamingActive,
  autoResizeComposerInput,
  resetComposerInput,
  setComposerValue,
  focusComposer,
  getComposerQuery,
  getComposerStrategy,
  stopGeneration,
} from "./composer.js";
import {
  loadDashboardStats,
  renderBarChart,
  renderHistoryTable,
  startDashboardAutoRefresh,
  stopDashboardAutoRefresh,
} from "./dashboard.js";
import {
  setupBenchmarkView,
  runBenchmarkSuite,
  updateBenchmarkSummaryCards,
  renderBenchmarkMatrix,
} from "./benchmark.js";
import {
  setupModelRegistryView,
  loadRegistryModels,
  renderRegistryTable,
  renderTierGuidelines,
  updateRegistrySummaryMetrics,
} from "./registry.js";
import {
  setupRibbonToggle,
  resetPipelineRibbon,
  updatePipelineToAnalyzing,
  updatePipelineAnalyzerResult,
  updatePipelineRouting,
  updatePipelineDone,
  Topology,
} from "./topology.js";
import {
  setupSettingsModal,
  populateSettingsForm,
  setupInspectorModal,
  openInspectorModal,
} from "./modals.js";

/* --------------------------------------------------------------------------
 * Global Application State
 * -------------------------------------------------------------------------- */
let sessionManager = null;
let currentAbortController = null;
let activeView = "chat";

/**
 * Main View Switcher
 * Transitions active panel with fluid fade and coordinates lifecycle hooks.
 * 
 * @param {string} viewName - "chat" | "registry" | "dashboard" | "benchmark"
 */
export function switchView(viewName) {
  const normalized = (viewName || "chat").toLowerCase().trim();
  activeView = normalized;

  // Deactivate all panels & navigation buttons
  $$(".view-panel").forEach((p) => p.classList.remove("active"));
  $$(".sidebar-nav-item").forEach((i) => i.classList.remove("active"));
  $$(".nav-btn").forEach((b) => b.classList.remove("active"));

  // Activate target panel & button
  const targetPanel = $(`view-${normalized}`);
  const targetNavBtn = $(`nav-${normalized}-btn`);
  const targetSidebarBtn = $(`sidebar-nav-${normalized}`);

  if (targetPanel) targetPanel.classList.add("active");
  if (targetNavBtn) targetNavBtn.classList.add("active");
  if (targetSidebarBtn) targetSidebarBtn.classList.add("active");

  // View-specific lifecycle hooks
  if (normalized === "dashboard") {
    loadDashboardStats();
    startDashboardAutoRefresh();
  } else {
    stopDashboardAutoRefresh();
  }

  if (normalized === "registry") {
    loadRegistryModels();
  }

  if (normalized === "chat") {
    focusComposer();
    const chatContainer = $("chat-messages") || $("chat-container");
    if (chatContainer) smoothScrollToBottom(chatContainer);
  }

  // Dismiss mobile drawer if open
  if (window.innerWidth <= 768) {
    $("sidebar")?.classList.remove("mobile-open");
    $("sidebar-backdrop")?.classList.remove("active");
  }
}

/**
 * Synchronizes header and sidebar navigation controls.
 */
function setupCanvasNavigation() {
  // Sidebar navigation items
  $$(".sidebar-nav-item").forEach((item) => {
    item.addEventListener("click", () => {
      const view = item.dataset.view;
      if (view) switchView(view);
    });
  });

  // Topbar navigation buttons
  $$(".nav-btn[data-view]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const view = btn.dataset.view;
      if (view) switchView(view);
    });
  });
}

/**
 * Updates optical theme iconography and meta tags.
 * 
 * @param {string} theme - "dark" | "light"
 */
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

/**
 * Toggles Dark / Light visual theme and persists user preference.
 */
export async function toggleTheme() {
  const current = document.documentElement.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  document.documentElement.setAttribute("data-theme", next);
  updateThemeIcon(next);

  try {
    const settings = await SettingsManager.load();
    settings.preferences = settings.preferences || {};
    settings.preferences.theme = next;
    await SettingsManager.save(settings);
  } catch (err) {
    console.warn("[main.js] Failed to persist theme preference:", err);
  }
}

/**
 * Loads stored user settings and applies theme and default routing strategy.
 */
async function applyStoredPreferences() {
  try {
    const settings = await SettingsManager.load();
    const theme = settings.preferences?.theme || "dark";
    document.documentElement.setAttribute("data-theme", theme);
    updateThemeIcon(theme);

    const strat = settings.preferences?.strategy || "balanced";
    const stratSelect = $("strategy-select");
    if (stratSelect) stratSelect.value = strat;
    updateStrategyBadge(strat);
  } catch (err) {
    console.warn("[main.js] Error applying preferences:", err);
  }
}

/**
 * Checks router engine connectivity and updates header status pill.
 */
async function checkEngineHealth() {
  try {
    const resp = await apiFetch("/health");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const data = await resp.json();
    const mode = data.mode || "demo";

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

/**
 * Coordinates chat submission, real-time SSE streaming, and pipeline HUD updates.
 */
async function handleChatSubmission(queryText, strategyOverride) {
  if (!queryText || !queryText.trim()) return;
  if (isStreamingActive()) {
    showToast("Generation already in progress", "info");
    return;
  }

  const query = queryText.trim();
  const strategy = strategyOverride || getComposerStrategy() || "balanced";

  // Reset composer input & auto-resize
  resetComposerInput();

  // Create new session if none is active
  if (!sessionManager.getActiveSession()) {
    sessionManager.createSession(query.slice(0, 32), true);
  }

  // 1. Append user message to UI and session store
  appendUserMessageToUI(query, true);
  sessionManager.addMessage("user", query);
  renderSidebarSessions();

  // 2. Prepare streaming state & AbortController
  setStreamingState(true);
  currentAbortController = new AbortController();
  const signal = currentAbortController.signal;

  // 3. Reset & prime pipeline ribbon
  resetPipelineRibbon();
  updatePipelineToAnalyzing();

  // 4. Create assistant placeholder in DOM
  const placeholder = createStreamingPlaceholder(query);
  const messageCard = placeholder.element;
  const contentBody = placeholder.contentBody;
  const thinkingExpander = placeholder.thinkingExpander;
  const thinkingContent = placeholder.thinkingContent;
  const hudPill = placeholder.hudPill;

  let accumulatedContent = "";
  let accumulatedReasoning = "";
  let routingMetadata = {};

  // 5. Build request payload from conversation history (excluding the current query just appended)
  const activeSession = sessionManager.getActiveSession();
  const allMessages = activeSession?.messages || [];
  const historyMessages = allMessages.length > 0 && allMessages[allMessages.length - 1].content === query
    ? allMessages.slice(0, -1)
    : allMessages;
  const messagesPayload = historyMessages.map((m) => ({
    role: m.role,
    content: m.content,
  }));

  const payload = {
    query,
    strategy,
    messages: messagesPayload,
  };

  try {
    await executeStreamingChat(
      payload,
      signal,
      // onAnalyzer
      (analyzerInfo) => {
        updatePipelineAnalyzerResult(analyzerInfo);
        if (typeof placeholder.updateAnalyzer === "function") {
          placeholder.updateAnalyzer(analyzerInfo);
        }
      },
      // onRouting
      (routeData) => {
        routingMetadata = routeData || {};
        updatePipelineRouting(routeData);
        if (typeof placeholder.updateRouting === "function") {
          placeholder.updateRouting(routeData);
        }

        // Update inline HUD pill if present
        if (hudPill && routeData.selected_tier) {
          hudPill.textContent = routeData.selected_tier.toUpperCase();
          hudPill.className = `tier-badge-pill tier-${routeData.selected_tier}`;
        }
      },
      // onReasoningDelta
      (reasoningChunk) => {
        accumulatedReasoning += reasoningChunk;
        if (typeof placeholder.appendReasoningDelta === "function") {
          placeholder.appendReasoningDelta(accumulatedReasoning);
        } else if (thinkingExpander && thinkingContent) {
          thinkingExpander.classList.remove("hidden");
          thinkingContent.textContent = accumulatedReasoning;
        }
      },
      // onDelta
      (deltaChunk) => {
        accumulatedContent += deltaChunk;
        if (typeof placeholder.appendDelta === "function") {
          placeholder.appendDelta(accumulatedContent);
        } else if (contentBody) {
          contentBody.innerHTML = formatMarkdown(accumulatedContent);
          _renderMathInElement(contentBody);
        }
        const chatContainer = $("chat-container") || $("chat-messages");
        if (chatContainer) smoothScrollToBottom(chatContainer);
      },
      // onDone
      (doneData) => {
        updatePipelineDone(doneData);
        setStreamingState(false);
        currentAbortController = null;

        if (typeof placeholder.finalize === "function") {
          placeholder.finalize(doneData || routingMetadata);
        }

        // Persist completed response in session
        const assistantMessage = {
          role: "assistant",
          content: accumulatedContent,
          reasoning: accumulatedReasoning,
          telemetry: doneData || routingMetadata,
          timestamp: new Date().toISOString(),
        };
        sessionManager.addMessage(
          "assistant",
          accumulatedContent,
          doneData || routingMetadata
        );

        // Update active session header & sidebar snippet
        renderSidebarSessions();
        updateContextCounter();
      },
      // onError
      (errorMessage) => {
        setStreamingState(false);
        currentAbortController = null;
        if (typeof placeholder.showError === "function") {
          placeholder.showError(errorMessage);
        } else if (contentBody) {
          contentBody.innerHTML = `<div class="error-banner"><p>Error: ${escapeHtml(errorMessage)}</p></div>`;
        }
        showToast(errorMessage, "error");
      }
    );
  } catch (err) {
    setStreamingState(false);
    currentAbortController = null;
    if (err.name === "AbortError" || signal.aborted) {
      showToast("Generation cancelled", "info");
      if (typeof placeholder.showStoppedState === "function") {
        placeholder.showStoppedState(accumulatedContent);
      } else if (contentBody) {
        contentBody.innerHTML += `<p class="generation-aborted"><em>(Generation stopped by user)</em></p>`;
      }
    } else {
      console.error("[main.js] Chat execution failed:", err);
      showToast(`Request failed: ${err.message}`, "error");
      if (typeof placeholder.showError === "function") {
        placeholder.showError(err.message);
      } else if (contentBody) {
        contentBody.innerHTML = `<div class="error-banner"><p>Execution Error: ${escapeHtml(err.message)}</p></div>`;
      }
    }
  }
}

/**
 * Stops generation if streaming is in progress.
 */
function handleStopGeneration() {
  if (currentAbortController) {
    currentAbortController.abort();
    currentAbortController = null;
    setStreamingState(false);
  }
}

/**
 * Initializes the entire application upon DOM readiness.
 */
export async function initApp() {
  console.log("⚡ [Smart LLM Switcher] Initializing S-Tier Frontend Architecture...");

  // 1. Initialize persistent managers
  sessionManager = new SessionManager();
  window.sessionManager = sessionManager;

  // 2. Load and apply stored preferences & visual theme
  await applyStoredPreferences();

  // 3. Initialize components & UI controllers
  setupSidebarControls(
    sessionManager,
    () => {
      // onNewChat
      sessionManager.createSession("New Conversation", true);
      renderSidebarSessions();
      renderActiveSessionMessages();
      switchView("chat");
      focusComposer();
    },
    (sessionId) => {
      // onSwitchSession
      sessionManager.setActiveSession(sessionId);
      renderSidebarSessions();
      renderActiveSessionMessages();
      switchView("chat");
      updateContextCounter();
    },
    () => toggleTheme(),
    () => {
      // onOpenSettings
      const modal = $("settings-modal");
      if (modal) {
        modal.classList.remove("hidden");
        populateSettingsForm();
      }
    }
  );

  setupCanvasNavigation();
  setupComposer(handleChatSubmission, handleStopGeneration);
  setupRibbonToggle();
  setupCodeCopyHandler();
  setupSettingsModal();
  setupInspectorModal();
  setupBenchmarkView();
  setupModelRegistryView();
  setupKeyboardShortcuts();

  // 4. Initial rendering passes
  renderSidebarSessions();
  renderActiveSessionMessages();
  checkEngineHealth();
  updateContextCounter();

  // 5. Background data warmup
  loadRegistryModels();

  // 6. Global window fallback attachments
  window.switchView = switchView;
  window.toggleTheme = toggleTheme;
  window.checkEngineHealth = checkEngineHealth;
  window.openInspectorModal = openInspectorModal;

  console.log("✓ [Smart LLM Switcher] S-Tier Frontend Architecture successfully mounted.");
}

// Auto-boot if DOM is ready, or hook DOMContentLoaded
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initApp);
} else {
  initApp();
}
