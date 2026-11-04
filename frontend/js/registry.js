/**
 * @file registry.js
 * @description Context-Aware Smart LLM Switcher — Model Registry & Architecture Tiers Module.
 * Chunk 9 of Frontend Modularization.
 * 
 * Embodies Apple HIG & Claude Design Principles:
 * - Deterministic, zero-latency state transitions.
 * - Tabular mono precision numbers (font-variant-numeric: tabular-nums).
 * - Micro-meter visualizations for multi-dimensional capability scores.
 * - Fluff-free, grounded multi-tier architecture catalog.
 * - Resilient fallback states when network or backend services are unavailable.
 */

// Canonical fallback models matching backend/app/registry.py in case backend is offline
const CANONICAL_FALLBACK_MODELS = [
  {
    model_id: "gemini-3.5-flash-lite",
    name: "Gemini 3.5 Flash-Lite",
    provider: "gemini",
    endpoint_model: "gemini-3.5-flash-lite",
    available: true,
    demo_mode: false,
    mode: "live",
    quality: 0.88,
    reasoning: 0.82,
    coding: 0.78,
    context_window: 1000000,
    input_price_per_mtok: 0.075,
    output_price_per_mtok: 0.300,
    expected_latency_ms: 300,
    tier: "tier1",
    fallback_model: "gpt-oss-20b"
  },
  {
    model_id: "gpt-oss-20b",
    name: "GPT-OSS 20B",
    provider: "groq",
    endpoint_model: "openai/gpt-oss-20b",
    available: true,
    demo_mode: false,
    mode: "live",
    quality: 0.84,
    reasoning: 0.78,
    coding: 0.75,
    context_window: 128000,
    input_price_per_mtok: 0.050,
    output_price_per_mtok: 0.150,
    expected_latency_ms: 200,
    tier: "tier2",
    fallback_model: "gemini-3.5-flash-lite"
  },
  {
    model_id: "gemini-3.6-flash",
    name: "Gemini 3.6 Flash",
    provider: "gemini",
    endpoint_model: "gemini-3.6-flash",
    available: true,
    demo_mode: false,
    mode: "live",
    quality: 0.92,
    reasoning: 0.88,
    coding: 0.85,
    context_window: 1000000,
    input_price_per_mtok: 0.100,
    output_price_per_mtok: 0.400,
    expected_latency_ms: 450,
    tier: "tier3",
    fallback_model: "gemini-3.5-flash-lite"
  },
  {
    model_id: "qwen3.8-27b",
    name: "Qwen3.8 27B",
    provider: "groq",
    endpoint_model: "qwen/qwen3.8-27b",
    available: true,
    demo_mode: false,
    mode: "live",
    quality: 0.91,
    reasoning: 0.86,
    coding: 0.96,
    context_window: 128000,
    input_price_per_mtok: 0.200,
    output_price_per_mtok: 0.600,
    expected_latency_ms: 380,
    tier: "tier4",
    fallback_model: "gemini-3.6-flash"
  },
  {
    model_id: "gpt-oss-120b",
    name: "GPT-OSS 120B",
    provider: "groq",
    endpoint_model: "openai/gpt-oss-120b",
    available: true,
    demo_mode: false,
    mode: "live",
    quality: 0.94,
    reasoning: 0.92,
    coding: 0.88,
    context_window: 128000,
    input_price_per_mtok: 0.350,
    output_price_per_mtok: 0.900,
    expected_latency_ms: 520,
    tier: "tier5",
    fallback_model: "gemini-3.6-flash"
  },
  {
    model_id: "gemini-3.8-flash",
    name: "Gemini 3.8 Flash",
    provider: "gemini",
    endpoint_model: "gemini-3.8-flash",
    available: true,
    demo_mode: false,
    mode: "live",
    quality: 0.96,
    reasoning: 0.94,
    coding: 0.92,
    context_window: 1000000,
    input_price_per_mtok: 0.300,
    output_price_per_mtok: 1.200,
    expected_latency_ms: 650,
    tier: "tier6",
    fallback_model: "gemini-3.5-flash-lite"
  }
];

// 7 Architecture Tier Role Profiles & Cost Guidelines
const TIER_GUIDELINE_DATA = [
  {
    tier: "ANALYZER",
    tierClass: "tier-pill-analyzer",
    provider: "gemini",
    providerLabel: "Google Gemini",
    name: "Gemini 3.1 Flash-Lite",
    role: "LinUCB Router & Multi-Signal Intent Classifier",
    desc: "Real-time query evaluation, task classification (Coding, Reasoning, General), context length inspection, and budget-constrained decision engine. Resolves routine queries directly in Self-Answer mode with 0 downstream model hops; dynamically routes remaining tasks using contextual bandit exploration (α=1.0).",
    inPrice: "$0.075",
    outPrice: "$0.30",
    latency: "~180 ms",
    context: "1,000,000"
  },
  {
    tier: "TIER 1",
    tierClass: "tier-pill-t1",
    provider: "gemini",
    providerLabel: "Google Gemini",
    name: "Gemini 3.5 Flash-Lite (Fast / Routine)",
    role: "High-Throughput Conversational Turns",
    desc: "Optimized for short summaries, conversational greetings, definitions, and high-frequency queries. Provides the fastest token return and lowest baseline cost for routine conversational turns ($0.075 / $0.30 per Mtok).",
    inPrice: "$0.075",
    outPrice: "$0.30",
    latency: "~300 ms",
    context: "1,000,000"
  },
  {
    tier: "TIER 2",
    tierClass: "tier-pill-t2",
    provider: "groq",
    providerLabel: "Groq LPU",
    name: "GPT-OSS 20B (Fast General Purpose)",
    role: "Sub-200ms Token Velocity Engine",
    desc: "Unmatched token generation velocity accelerated on Groq LPU tensor hardware. Excels at rapid multi-turn chat, casual Q&A, entity extraction, and high-velocity factual synthesis (~200 ms latency).",
    inPrice: "$0.05",
    outPrice: "$0.15",
    latency: "~200 ms",
    context: "128,000"
  },
  {
    tier: "TIER 3",
    tierClass: "tier-pill-t3",
    provider: "gemini",
    providerLabel: "Google Gemini",
    name: "Gemini 3.6 Flash (Balanced Workhorse)",
    role: "Pareto-Optimal General Intelligence",
    desc: "The primary workhorse arm balancing high semantic accuracy and low cost. Ideal for long-form document comprehension, complex multi-step dialogue, and structured knowledge synthesis with 1M context.",
    inPrice: "$0.10",
    outPrice: "$0.40",
    latency: "~450 ms",
    context: "1,000,000"
  },
  {
    tier: "TIER 4",
    tierClass: "tier-pill-t4",
    provider: "groq",
    providerLabel: "Groq LPU",
    name: "Qwen3.8 27B (Coding Specialist)",
    role: "Technical Software Engineering Arm",
    desc: "Deeply calibrated model weights for code generation, syntax refactoring, algorithmic DSA challenges, SQL query authoring, and AST error diagnosis (0.96 benchmark coding capability index).",
    inPrice: "$0.20",
    outPrice: "$0.60",
    latency: "~380 ms",
    context: "128,000"
  },
  {
    tier: "TIER 5",
    tierClass: "tier-pill-t5",
    provider: "groq",
    providerLabel: "Groq LPU",
    name: "GPT-OSS 120B (Deep Reasoning)",
    role: "Multi-Constraint Deductive Logic",
    desc: "Dense high-parameter reasoning engine designed for mathematical proofs, intricate logic puzzles, multi-constraint deduction, counterfactual evaluation, and complex decision trees (0.92 reasoning index).",
    inPrice: "$0.35",
    outPrice: "$0.90",
    latency: "~520 ms",
    context: "128,000"
  },
  {
    tier: "TIER 6",
    tierClass: "tier-pill-t6",
    provider: "gemini",
    providerLabel: "Google Gemini",
    name: "Gemini 3.8 Flash (High Capability)",
    role: "Frontier Escalation & System Architecture",
    desc: "Sovereign top-tier frontier model for difficult research, multi-domain system architecture, ambiguous prompts, and automated fallback escalation when lower tiers experience latency or rate limits.",
    inPrice: "$0.30",
    outPrice: "$1.20",
    latency: "~650 ms",
    context: "1,000,000"
  }
];

/**
 * Escapes HTML entities defensively to eliminate XSS risks.
 * @param {string|number|null|undefined} str
 * @returns {string}
 */
function escapeHtml(str) {
  if (str == null) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Maps a tier identifier string to its corresponding CSS class.
 * @param {string} tier
 * @returns {string}
 */
function getTierPillClass(tier) {
  const t = String(tier || "").toLowerCase().trim();
  if (t === "analyzer" || t === "router") return "tier-pill-analyzer";
  if (t === "tier1" || t === "t1") return "tier-pill-t1";
  if (t === "tier2" || t === "t2") return "tier-pill-t2";
  if (t === "tier3" || t === "t3") return "tier-pill-t3";
  if (t === "tier4" || t === "t4") return "tier-pill-t4";
  if (t === "tier5" || t === "t5") return "tier-pill-t5";
  if (t === "tier6" || t === "t6") return "tier-pill-t6";
  return "tier-pill-t3";
}

/**
 * Normalizes provider string for CSS class styling.
 * @param {string} provider
 * @returns {string}
 */
function getProviderClass(provider) {
  const p = String(provider || "").toLowerCase().trim();
  if (p.includes("gemini") || p.includes("google")) return "gemini";
  if (p.includes("groq")) return "groq";
  if (p.includes("openrouter")) return "openrouter";
  if (p.includes("openai")) return "openai";
  return "gemini";
}

/**
 * Formats provider display label.
 * @param {string} provider
 * @returns {string}
 */
function getProviderLabel(provider) {
  const p = String(provider || "").toLowerCase().trim();
  if (p.includes("gemini") || p.includes("google")) return "Google Gemini";
  if (p.includes("groq")) return "Groq LPU";
  if (p.includes("openrouter")) return "OpenRouter";
  if (p.includes("openai")) return "OpenAI";
  return provider ? provider.toUpperCase() : "GEMINI";
}

/**
 * Safe fetch wrapper that uses window.apiFetch (with credential headers) if available.
 * @param {string} url
 * @param {RequestInit} [options]
 * @returns {Promise<Response>}
 */
async function fetchWithFallback(url, options) {
  if (typeof window !== "undefined" && typeof window.apiFetch === "function") {
    return window.apiFetch(url, options);
  }
  return fetch(url, options);
}

/**
 * Fetches live provider health from /api/providers/health
 * @returns {Promise<Object|null>}
 */
async function checkProviderHealth() {
  try {
    const resp = await fetchWithFallback("/api/providers/health");
    if (resp.ok) {
      return await resp.json();
    }
  } catch (err) {
    console.warn("[ModelRegistry] Failed to fetch provider health ping:", err);
  }
  return null;
}

/**
 * Shows toast notification safely using the global showToast if defined.
 * @param {string} message
 * @param {"success"|"info"|"error"|"warning"} type
 */
function notifyToast(message, type = "info") {
  if (typeof window !== "undefined" && typeof window.showToast === "function") {
    window.showToast(message, type);
  } else {
    console.log(`[Registry Toast] [${type}] ${message}`);
  }
}

/**
 * Updates the 4 executive summary KPI metrics at the top of the Model Registry view.
 * @param {Array<Object>} models
 */
function updateRegistrySummaryMetrics(models) {
  const totalModelsEl = document.getElementById("reg-total-models");
  const priceRangeEl = document.getElementById("reg-price-range");
  const minLatEl = document.getElementById("reg-min-lat");
  const maxContextEl = document.getElementById("reg-max-context");

  if (!models || models.length === 0) {
    if (totalModelsEl) totalModelsEl.textContent = "6";
    if (priceRangeEl) priceRangeEl.textContent = "$0.05 – $1.20";
    if (minLatEl) minLatEl.textContent = "~200 ms";
    if (maxContextEl) maxContextEl.textContent = "1,000,000";
    return;
  }

  // Active Models count
  if (totalModelsEl) {
    totalModelsEl.textContent = models.length.toString();
  }

  // Calculate pricing range
  const validInPrices = models.map(m => Number(m.input_price_per_mtok)).filter(p => !isNaN(p) && p > 0);
  const validOutPrices = models.map(m => Number(m.output_price_per_mtok)).filter(p => !isNaN(p) && p > 0);
  if (priceRangeEl && validInPrices.length > 0 && validOutPrices.length > 0) {
    const minIn = Math.min(...validInPrices);
    const maxOut = Math.max(...validOutPrices);
    priceRangeEl.textContent = `$${minIn.toFixed(2)} – $${maxOut.toFixed(2)}`;
  }

  // Calculate fastest response latency
  const validLatencies = models.map(m => Number(m.expected_latency_ms)).filter(l => !isNaN(l) && l > 0);
  if (minLatEl && validLatencies.length > 0) {
    const minLat = Math.min(...validLatencies);
    minLatEl.textContent = `~${minLat} ms`;
  }

  // Calculate max context window
  const validContexts = models.map(m => Number(m.context_window)).filter(c => !isNaN(c) && c > 0);
  if (maxContextEl && validContexts.length > 0) {
    const maxCtx = Math.max(...validContexts);
    maxContextEl.textContent = maxCtx.toLocaleString();
  }
}

/**
 * Renders the live provider ping status strip above the model registry table.
 * @param {Object|null} healthData
 */
function renderProviderPingStrip(healthData) {
  let strip = document.getElementById("provider-ping-strip");
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
    { key: "gemini", label: "Google Gemini", defaultModel: "Gemini 3.5 / 3.6 / 3.8" },
    { key: "groq", label: "Groq LPU", defaultModel: "GPT-OSS 20B / Qwen3.8 / 120B" },
    { key: "openrouter", label: "OpenRouter", defaultModel: "Optional Fallback" }
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

/**
 * Renders the specifications table rows from model list.
 * @param {Array<Object>} models
 * @param {Object|null} [healthData]
 */
function renderRegistryTable(models, healthData = null) {
  const tbody = document.getElementById("registry-table-body");
  if (!tbody) return;

  if (!models || models.length === 0) {
    tbody.innerHTML = `<tr><td colspan="10" class="empty-state">No registered models found.</td></tr>`;
    return;
  }

  const providersHealth = (healthData && healthData.providers) ? healthData.providers : (healthData || {});

  tbody.innerHTML = models.map(m => {
    const tierDisplay = (m.tier || "tier").toUpperCase();
    const tierPillClass = getTierPillClass(m.tier);
    const providerClass = getProviderClass(m.provider);
    const providerName = getProviderLabel(m.provider);

    const inPrice = Number(m.input_price_per_mtok || 0).toFixed(3);
    const outPrice = Number(m.output_price_per_mtok || 0).toFixed(3);

    const qualityVal = m.quality != null ? Math.round(Number(m.quality) * 100) : null;
    const reasoningVal = m.reasoning != null ? Math.round(Number(m.reasoning) * 100) : null;
    const codingVal = m.coding != null ? Math.round(Number(m.coding) * 100) : null;

    const latencyMs = Number(m.expected_latency_ms || 0);
    const isFast = latencyMs > 0 && latencyMs <= 250;
    const isOnline = m.available !== false;
    const modeStr = m.mode ? String(m.mode).toLowerCase() : (m.demo_mode ? "demo" : "live");

    // Check live provider ping status
    const pHealth = providersHealth[m.provider];
    let statusBadge = "";
    if (pHealth && pHealth.status === "connected") {
      const pingMs = pHealth.latency_ms ? `${Math.round(pHealth.latency_ms)}ms` : "ok";
      statusBadge = `<span class="status-indicator active ping-ok" title="Provider ping: ${pingMs} | Status: Online"><span class="status-dot"></span> Active <span class="mode-badge ping-badge">${pingMs}</span></span>`;
    } else if (pHealth && pHealth.status === "missing_api_key") {
      statusBadge = `<span class="status-indicator demo" title="Simulated evaluation arm / Demo mode"><span class="status-dot"></span> Demo <span class="mode-badge">sim</span></span>`;
    } else if (pHealth && pHealth.status === "error") {
      statusBadge = `<span class="status-indicator error" title="${escapeHtml(pHealth.error || 'Connection error')}"><span class="status-dot"></span> Degraded</span>`;
    } else if (isOnline) {
      statusBadge = `<span class="status-indicator active" title="Model Arm is Online & Active"><span class="status-dot"></span> Active <span class="mode-badge">${escapeHtml(modeStr)}</span></span>`;
    } else {
      statusBadge = `<span class="status-indicator inactive" title="Model Arm is Offline or Disabled"><span class="status-dot"></span> Inactive</span>`;
    }

    const qualityCell = qualityVal != null
      ? `<div class="metric-meter-cell"><span class="meter-val">${qualityVal}%</span><div class="meter-track"><div class="meter-bar bar-quality" style="width: ${qualityVal}%;"></div></div></div>`
      : `<span>—</span>`;

    const reasoningCell = reasoningVal != null
      ? `<div class="metric-meter-cell"><span class="meter-val">${reasoningVal}%</span><div class="meter-track"><div class="meter-bar bar-reasoning" style="width: ${reasoningVal}%;"></div></div></div>`
      : `<span>—</span>`;

    const codingCell = codingVal != null
      ? `<div class="metric-meter-cell"><span class="meter-val">${codingVal}%</span><div class="meter-track"><div class="meter-bar bar-coding" style="width: ${codingVal}%;"></div></div></div>`
      : `<span>—</span>`;

    return `
      <tr>
        <td><span class="routing-tier-pill ${tierPillClass}">${escapeHtml(tierDisplay)}</span></td>
        <td>
          <div class="model-name-cell">
            <span class="model-name-title">${escapeHtml(m.name || m.model_id)}</span>
            <span class="model-endpoint-id">${escapeHtml(m.endpoint_model || m.model_id || "")}</span>
          </div>
        </td>
        <td><span class="prov-tag ${providerClass}">${escapeHtml(providerName)}</span></td>
        <td>${qualityCell}</td>
        <td>${reasoningCell}</td>
        <td>${codingCell}</td>
        <td>
          <div class="pricing-cell">
            <span class="price-in">$${inPrice}</span>
            <span class="price-sep">/</span>
            <span class="price-out">$${outPrice}</span>
          </div>
        </td>
        <td><span class="latency-cell ${isFast ? 'speed-fast' : ''}">~${latencyMs} ms</span></td>
        <td><span class="context-cell">${m.context_window ? Number(m.context_window).toLocaleString() : '—'}</span></td>
        <td>${statusBadge}</td>
      </tr>
    `;
  }).join("");
}

/**
 * Renders the 7 architecture guidelines cards (LinUCB Router + 6 response tiers).
 */
function renderTierGuidelines() {
  const guidelinesGrid = document.getElementById("tier-guidelines-grid");
  if (!guidelinesGrid) return;

  guidelinesGrid.innerHTML = TIER_GUIDELINE_DATA.map(item => `
    <div class="guideline-card">
      <div class="guideline-card-head">
        <span class="routing-tier-pill ${item.tierClass}">${escapeHtml(item.tier)}</span>
        <span class="prov-tag ${item.provider}">${escapeHtml(item.providerLabel)}</span>
      </div>
      <div class="guideline-title-group">
        <div class="guideline-title">${escapeHtml(item.name)}</div>
        <div class="guideline-role-badge">${escapeHtml(item.role)}</div>
      </div>
      <p class="guideline-desc">${escapeHtml(item.desc)}</p>
      <div class="guideline-cost-profile">
        <span class="cost-stat">Pricing: <strong>${item.inPrice}</strong> in / <strong class="highlight">${item.outPrice}</strong> out</span>
        <span class="cost-sep">·</span>
        <span class="cost-stat">Latency: <strong>${item.latency}</strong></span>
        <span class="cost-sep">·</span>
        <span class="cost-stat">Context: <strong>${item.context}</strong> tokens</span>
      </div>
    </div>
  `).join("");
}

/**
 * Fetches dynamic models from /api/models, updates KPI counters, renders the specifications table,
 * and renders the 7 tier guidelines cards.
 * @returns {Promise<void>}
 */
async function loadRegistryModels() {
  const tbody = document.getElementById("registry-table-body");
  const refreshBtn = document.getElementById("refresh-registry-btn");

  if (refreshBtn) {
    refreshBtn.classList.add("is-loading", "spinning");
  }

  try {
    const [modelsSettled, healthSettled] = await Promise.allSettled([
      fetchWithFallback("/api/models").then(r => r.ok ? r.json() : null),
      checkProviderHealth()
    ]);

    const data = modelsSettled.status === "fulfilled" ? modelsSettled.value : null;
    const healthData = healthSettled.status === "fulfilled" ? healthSettled.value : null;

    const models = (data && Array.isArray(data.models) && data.models.length > 0)
      ? data.models
      : CANONICAL_FALLBACK_MODELS;

    updateRegistrySummaryMetrics(models);
    renderProviderPingStrip(healthData);
    renderRegistryTable(models, healthData);
    renderTierGuidelines();
  } catch (err) {
    console.warn("[ModelRegistry] Failed to fetch live models from backend, applying canonical fallback:", err);

    // Apply fallback models gracefully so UI remains fully functional and informative
    updateRegistrySummaryMetrics(CANONICAL_FALLBACK_MODELS);
    renderProviderPingStrip(null);
    renderRegistryTable(CANONICAL_FALLBACK_MODELS, null);
    renderTierGuidelines();

    if (tbody && (!tbody.children || tbody.children.length === 0)) {
      tbody.innerHTML = `<tr><td colspan="10" class="empty-state">Backend unreachable. Showing calibrated defaults.</td></tr>`;
    }
  } finally {
    if (refreshBtn) {
      // Allow fluid spring animation to finish visually
      setTimeout(() => {
        refreshBtn.classList.remove("is-loading", "spinning");
      }, 400);
    }
  }
}

/**
 * Binds the refresh button (#refresh-registry-btn) and initializes the Model Registry view.
 */
function setupModelRegistryView() {
  const refreshBtn = document.getElementById("refresh-registry-btn");
  if (!refreshBtn) return;

  // Avoid duplicate listeners
  if (refreshBtn.dataset.bound === "true") return;
  refreshBtn.dataset.bound = "true";

  refreshBtn.addEventListener("click", async () => {
    try {
      await loadRegistryModels();
      notifyToast("Model registry catalog synchronized", "success");
    } catch (e) {
      notifyToast("Failed to refresh catalog", "error");
    }
  });

  // Ensure guidelines are populated immediately on setup
  renderTierGuidelines();
}

// Global browser window attachment for non-bundled scripts and compatibility
if (typeof window !== "undefined") {
  window.setupModelRegistryView = setupModelRegistryView;
  window.loadRegistryModels = loadRegistryModels;
  window.renderRegistryTable = renderRegistryTable;
  window.renderProviderPingStrip = renderProviderPingStrip;
  window.checkProviderHealth = checkProviderHealth;
  window.renderTierGuidelines = renderTierGuidelines;
  window.updateRegistrySummaryMetrics = updateRegistrySummaryMetrics;
  window.ModelRegistry = {
    setupModelRegistryView,
    loadRegistryModels,
    renderRegistryTable,
    renderProviderPingStrip,
    checkProviderHealth,
    renderTierGuidelines,
    updateRegistrySummaryMetrics,
    CANONICAL_FALLBACK_MODELS,
    TIER_GUIDELINE_DATA
  };
}

if (typeof globalThis !== "undefined") {
  globalThis.setupModelRegistryView = setupModelRegistryView;
  globalThis.loadRegistryModels = loadRegistryModels;
  globalThis.renderProviderPingStrip = renderProviderPingStrip;
}

export {
  setupModelRegistryView,
  loadRegistryModels,
  renderRegistryTable,
  renderProviderPingStrip,
  checkProviderHealth,
  renderTierGuidelines,
  updateRegistrySummaryMetrics,
  CANONICAL_FALLBACK_MODELS,
  TIER_GUIDELINE_DATA
};

export default {
  setupModelRegistryView,
  loadRegistryModels,
  renderRegistryTable,
  renderProviderPingStrip,
  checkProviderHealth,
  renderTierGuidelines,
  updateRegistrySummaryMetrics
};
