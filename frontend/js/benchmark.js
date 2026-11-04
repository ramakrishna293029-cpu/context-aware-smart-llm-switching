/**
 * Context-Aware Smart LLM Switcher — Research Benchmark Lab Module
 * Chunk 11: Modular Benchmark Controller & Evaluator Matrix Renderer
 *
 * Implements:
 * 1. Multi-domain comparative benchmark runner against:
 *    - Baseline 1: Uniform Tier 6 (Gemini 3.8 Flash)
 *    - Baseline 2: Static Rule-Based Routing
 *    - System: Context-Aware Smart LLM Switcher (LinUCB Bandit)
 * 2. Apple HIG 0-latency micro-interactions and loading state management.
 * 3. Tabular numeric formatting and high-density matrix visualization.
 * 4. Resilient cross-module integration with safe fallbacks and custom events.
 */

"use strict";

/**
 * Fast DOM element lookup with fallback.
 * @param {string} id - Element ID.
 * @returns {HTMLElement|null}
 */
const getElem = (id) => {
  if (typeof window !== "undefined" && typeof window.$ === "function") {
    return window.$(id);
  }
  if (typeof document !== "undefined") {
    const cleanId = id.startsWith("#") ? id.slice(1) : id;
    return document.getElementById(cleanId);
  }
  return null;
};

/**
 * HTML string escaping to prevent XSS in dynamic table rows.
 * @param {unknown} str - Input value.
 * @returns {string} Escaped string.
 */
function safeEscape(str) {
  if (typeof window !== "undefined" && typeof window.escapeHtml === "function") {
    return window.escapeHtml(str);
  }
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Display toast notification via window.showToast or resilient fallback.
 * @param {string} message - Toast message.
 * @param {"info"|"success"|"error"|"warning"} [type="info"] - Variant.
 */
function notifyToast(message, type = "info") {
  if (typeof window !== "undefined" && typeof window.showToast === "function") {
    window.showToast(message, type);
    return;
  }
  console.log(`[Benchmark ${type.toUpperCase()}] ${message}`);
}

/**
 * Authenticated API fetch helper with automatic provider headers.
 * @param {string} url - API Endpoint URL.
 * @param {RequestInit} [options={}] - Fetch configuration.
 * @returns {Promise<Response>}
 */
async function executeApiFetch(url, options = {}) {
  if (typeof window !== "undefined" && typeof window.apiFetch === "function") {
    return window.apiFetch(url, options);
  }

  let headers = { "Content-Type": "application/json" };
  try {
    if (typeof window !== "undefined" && window.SettingsManager && typeof window.SettingsManager.getHeaders === "function") {
      const authHeaders = await window.SettingsManager.getHeaders();
      headers = { ...headers, ...authHeaders };
    }
  } catch (err) {
    console.warn("[Benchmark] Failed to load SettingsManager headers:", err);
  }

  const customHeaders = options.headers || {};
  return fetch(url, { ...options, headers: { ...headers, ...customHeaders } });
}

/**
 * Formats a numeric USD value with precision for micro-costs.
 * @param {number|undefined|null} cost - Cost in USD.
 * @returns {string}
 */
function formatCostUSD(cost) {
  if (cost === null || cost === undefined || Number.isNaN(Number(cost))) {
    return "$0.000000";
  }
  const num = Number(cost);
  if (num === 0) return "$0.000000";
  if (num < 0.01) return `$${num.toFixed(6)}`;
  return `$${num.toFixed(4)}`;
}

/**
 * Formats latency value with millisecond unit.
 * @param {number|undefined|null} ms - Latency in milliseconds.
 * @returns {string}
 */
function formatLatencyMs(ms) {
  if (ms === null || ms === undefined || Number.isNaN(Number(ms))) {
    return "0.0ms";
  }
  const num = Number(ms);
  return `${num.toFixed(1)}ms`;
}

/**
 * Maps task_type string to semantic CSS class and label.
 * @param {string} taskType - Task domain string.
 * @returns {{ cssClass: string, label: string }}
 */
function resolveDomainBadge(taskType) {
  const norm = (taskType || "general").toLowerCase();
  if (norm.includes("code") || norm.includes("program")) {
    return { cssClass: "domain-coding", label: "CODING" };
  }
  if (norm.includes("reason") || norm.includes("logic") || norm.includes("math")) {
    return { cssClass: "domain-reasoning", label: "REASONING" };
  }
  if (norm.includes("fact") || norm.includes("search") || norm.includes("qa")) {
    return { cssClass: "domain-factual", label: "FACTUAL" };
  }
  if (norm.includes("plan") || norm.includes("strat")) {
    return { cssClass: "domain-planning", label: "PLANNING" };
  }
  return { cssClass: "domain-general", label: (taskType || "GENERAL").toUpperCase() };
}

/**
 * State flag to prevent simultaneous overlapping runs.
 */
let isBenchmarkRunning = false;

/**
 * Executes the multi-domain benchmark evaluation suite against Baseline 1 & 2.
 * Toggles CTA button states, calls `/api/benchmark/run`, updates summary metrics,
 * and renders the evaluation matrix table.
 *
 * @param {Object} [options={}] - Optional configuration overrides.
 * @param {string[]} [options.queries] - Optional custom query list.
 * @param {boolean} [options.includeReasoning=true] - Include complex reasoning prompts.
 * @param {boolean} [options.includeCoding=true] - Include software engineering prompts.
 * @param {boolean} [options.includeFactual=true] - Include high-throughput factual prompts.
 * @returns {Promise<Object|null>} BenchmarkResult payload or null on failure.
 */
async function runBenchmarkSuite(options = {}) {
  if (isBenchmarkRunning) {
    console.warn("[Benchmark] Benchmark execution already in progress.");
    return null;
  }

  const runBtn = getElem("run-benchmark-btn");
  let originalBtnHtml = "";

  if (runBtn) {
    originalBtnHtml = runBtn.innerHTML;
    runBtn.disabled = true;
    runBtn.classList.add("loading");
    runBtn.setAttribute("aria-busy", "true");
    runBtn.innerHTML = `
      <span class="btn-loading-spinner" aria-hidden="true"></span>
      <span>Running Multi-Domain Suite...</span>
    `;
  }

  isBenchmarkRunning = true;

  try {
    const payload = {
      queries: options.queries || undefined,
      include_reasoning: options.includeReasoning !== false,
      include_coding: options.includeCoding !== false,
      include_factual: options.includeFactual !== false,
    };

    const resp = await executeApiFetch("/api/benchmark/run", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    const data = await resp.json();

    if (!resp.ok) {
      throw new Error(data.detail || `Benchmark failed with status ${resp.status}`);
    }

    // 1. Update Benchmark KPI Summary Cards
    updateBenchmarkSummaryCards(data);

    // 2. Render Comparative Evaluation Matrix Table
    renderBenchmarkMatrix(data.items || []);

    // 3. Notify user and dispatch completion event
    notifyToast("Multi-domain benchmark completed successfully", "success");

    if (typeof document !== "undefined") {
      document.dispatchEvent(new CustomEvent("benchmark:completed", { detail: data }));
    }

    return data;
  } catch (err) {
    console.error("[Benchmark] Suite execution failed:", err);
    notifyToast(err.message || "Failed to execute benchmark suite", "error");

    const tbody = getElem("benchmark-tbody");
    if (tbody && tbody.children.length <= 1) {
      tbody.innerHTML = `
        <tr class="bm-row-error">
          <td colspan="6" class="empty-state">
            <span class="bm-empty-icon">⚠️</span>
            <strong style="color:var(--signal-red, #FF453A);">Benchmark execution failed</strong><br>
            <span style="font-size:12px;color:var(--text-muted);">${safeEscape(err.message)}</span>
          </td>
        </tr>
      `;
    }
    return null;
  } finally {
    isBenchmarkRunning = false;
    if (runBtn) {
      runBtn.disabled = false;
      runBtn.classList.remove("loading");
      runBtn.removeAttribute("aria-busy");
      runBtn.innerHTML = originalBtnHtml || `
        <span class="btn-play-icon" aria-hidden="true">▶</span>
        <span>Run Multi-Domain Benchmark</span>
      `;
    }
  }
}

/**
 * Updates KPI Summary Cards with aggregate cost savings and speedup metrics.
 * @param {Object} data - BenchmarkResult payload.
 */
function updateBenchmarkSummaryCards(data) {
  const cardsContainer = getElem("benchmark-summary-cards");
  if (cardsContainer) {
    cardsContainer.style.display = "grid";
  }

  const overallSavingsElem = getElem("bm-overall-savings");
  if (overallSavingsElem) {
    const savingsPct = Number(data.overall_cost_savings_percent || 0).toFixed(1);
    overallSavingsElem.textContent = `${savingsPct}%`;
  }

  const savedDollarsElem = getElem("bm-saved-dollars");
  if (savedDollarsElem) {
    const savedDollars = Number(data.total_cost_saved_usd || 0).toFixed(4);
    savedDollarsElem.textContent = `$${savedDollars} saved vs Baseline 1`;
  }

  const overallSpeedupElem = getElem("bm-overall-speedup");
  if (overallSpeedupElem) {
    const speedupPct = Number(data.overall_speedup_percent || 0);
    const sign = speedupPct > 0 ? "+" : "";
    overallSpeedupElem.textContent = `${sign}${speedupPct.toFixed(1)}%`;
  }

  const smartCostElem = getElem("bm-smart-cost");
  if (smartCostElem) {
    const smartCost = Number(data.smart_total_cost_usd || 0).toFixed(4);
    smartCostElem.textContent = `$${smartCost}`;
  }

  const baselineCostElem = getElem("bm-baseline-cost");
  if (baselineCostElem) {
    const b1Cost = Number(data.baseline1_total_cost_usd || 0).toFixed(4);
    const b2Cost = data.baseline2_total_cost_usd != null ? ` · vs B2: $${Number(data.baseline2_total_cost_usd).toFixed(4)}` : "";
    baselineCostElem.textContent = `vs Baseline 1: $${b1Cost}${b2Cost}`;
  }
}

/**
 * Renders evaluation rows into `#benchmark-tbody`.
 * @param {Array<Object>} items - List of BenchmarkComparisonItem items.
 */
function renderBenchmarkMatrix(items) {
  const tbody = getElem("benchmark-tbody");
  if (!tbody) return;

  if (!Array.isArray(items) || items.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="empty-state">
          <span class="bm-empty-icon">📊</span>
          <span>No benchmark evaluation records returned from server.</span>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = items.map((item) => {
    const { cssClass, label } = resolveDomainBadge(item.task_type);
    const complexity = item.complexity || "moderate";

    const b1Cost = formatCostUSD(item.baseline1_cost_usd);
    const b1Lat = formatLatencyMs(item.baseline1_latency_ms);

    const b2Cost = formatCostUSD(item.baseline2_cost_usd);
    const b2Lat = formatLatencyMs(item.baseline2_latency_ms);

    const smartCost = formatCostUSD(item.smart_cost_usd);
    const smartLat = formatLatencyMs(item.smart_latency_ms);

    const savingsNum = Number(item.smart_savings_percent || 0);
    const speedupNum = Number(item.smart_speedup_percent || 0);

    let savingsClass = "bm-savings-pill";
    let savingsText = `+${savingsNum.toFixed(1)}%`;
    if (savingsNum === 0) {
      savingsClass = "bm-savings-pill neutral";
      savingsText = "0.0%";
    } else if (savingsNum < 0) {
      savingsClass = "bm-savings-pill negative";
      savingsText = `${savingsNum.toFixed(1)}%`;
    }

    let speedupClass = "bm-speedup-pill";
    let speedupText = speedupNum > 0 ? `+${speedupNum.toFixed(1)}%` : `${speedupNum.toFixed(1)}%`;
    if (speedupNum === 0) {
      speedupClass = "bm-speedup-pill neutral";
      speedupText = "0.0%";
    } else if (speedupNum < 0) {
      speedupClass = "bm-speedup-pill negative";
    }

    const dollarDelta = Math.max(0, (Number(item.baseline1_cost_usd || 0) - Number(item.smart_cost_usd || 0)));
    const deltaSub = dollarDelta > 0
      ? `<span class="bm-delta-cost" style="display:block;font-size:10.5px;color:var(--text-muted);margin-top:2px;font-variant-numeric:tabular-nums;">-$${dollarDelta < 0.01 ? dollarDelta.toFixed(6) : dollarDelta.toFixed(4)}</span>`
      : "";

    const hasError = Boolean(item.error);

    return `
      <tr class="${hasError ? "bm-row-error" : ""}">
        <td class="col-query">
          <span class="bm-query-title">${safeEscape(item.query)}</span>
          <div class="bm-meta-row">
            <span class="bm-domain-badge ${cssClass}">${safeEscape(label)}</span>
            <span class="bm-complexity-badge">${safeEscape(complexity)}</span>
            ${hasError ? `<span class="bm-domain-badge" style="color:var(--signal-red,#FF453A);">ERROR</span>` : ""}
          </div>
        </td>
        <td>
          <span class="bm-model-pill b1-model">${safeEscape(item.baseline1_model || "Tier 6 Gemini 3.8 Flash")}</span>
          <span class="bm-submetric" style="font-variant-numeric:tabular-nums;">${b1Cost} · ${b1Lat}</span>
        </td>
        <td>
          <span class="bm-model-pill b2-model">${safeEscape(item.baseline2_model || "Static Routing")}</span>
          <span class="bm-submetric" style="font-variant-numeric:tabular-nums;">${b2Cost} · ${b2Lat}</span>
        </td>
        <td>
          <span class="bm-model-pill smart-model">${safeEscape(item.smart_model || "Smart LLM Switcher")}</span>
          <span class="bm-submetric" style="font-variant-numeric:tabular-nums;">${smartCost} · ${smartLat}</span>
        </td>
        <td>
          <span class="${savingsClass}">${savingsText}</span>
          ${deltaSub}
        </td>
        <td>
          <span class="${speedupClass}">${speedupText}</span>
        </td>
      </tr>
    `;
  }).join("");
}

/**
 * Initializes the Benchmark view by binding the execution CTA button.
 * Ensures idempotent listener attachment.
 */
function setupBenchmarkView() {
  const runBtn = getElem("run-benchmark-btn");
  if (!runBtn) return;

  // Prevent duplicate event listener registration
  if (runBtn.dataset.benchmarkBound === "true") {
    return;
  }
  runBtn.dataset.benchmarkBound = "true";

  runBtn.addEventListener("click", (evt) => {
    evt.preventDefault();
    runBenchmarkSuite();
  });
}

// Auto-bind on DOMContentLoaded if document is still parsing
if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => setupBenchmarkView());
  } else {
    setupBenchmarkView();
  }
}

// Universal browser window attachments
if (typeof window !== "undefined") {
  window.setupBenchmarkView = setupBenchmarkView;
  window.runBenchmarkSuite = runBenchmarkSuite;
  window.updateBenchmarkSummaryCards = updateBenchmarkSummaryCards;
  window.renderBenchmarkMatrix = renderBenchmarkMatrix;
}

export {
  setupBenchmarkView,
  runBenchmarkSuite,
  updateBenchmarkSummaryCards,
  renderBenchmarkMatrix,
};

export default {
  setupBenchmarkView,
  runBenchmarkSuite,
  updateBenchmarkSummaryCards,
  renderBenchmarkMatrix,
};
