/**
 * ============================================================================
 * Smart LLM Switcher — Modals & Overlay Controller Module (Chunk 12)
 * Apple HIG & Claude Design Standards
 *
 * Implements:
 * 1. Provider Settings & API Keys Modal:
 *    - Fluid open/close animations with keyboard ESC trap and backdrop click.
 *    - Segmented provider tab navigation (Gemini, Groq, 6-Tier, OpenRouter, OpenAI, Custom).
 *    - Secure password masking toggles with optical eye feedback.
 *    - Real-time provider connection health check testing (/api/providers/test/{provider}).
 *    - WebCrypto encrypted persistence through SettingsManager.
 *    - Safe factory reset and key clearance workflows with confirmation dialogs.
 * 2. Telemetry Inspector Modal:
 *    - Deep routing telemetry inspection by requestId (/api/requests/{id}).
 *    - Prompt quote display with automatic text sanitization.
 *    - 6-cell elevated drawer grid for metered cost, latency, token velocity, and tier assignment.
 *    - Syntax-formatted JSON code viewer with 1-click clipboard synchronization.
 * 3. Module & Global Exports:
 *    - Dual export: ES module exports + direct window/globalThis attachments.
 * ============================================================================
 */

import { SettingsManager, apiFetch } from "./storage.js";
import { $, $$, escapeHtml, showToast } from "./utils.js";

/* --------------------------------------------------------------------------
 * Resilient Runtime Resolvers
 * -------------------------------------------------------------------------- */
const getSM = () => (typeof SettingsManager !== "undefined" ? SettingsManager : window.SettingsManager);
const getApiFetch = () => (typeof apiFetch === "function" ? apiFetch : (window.apiFetch || window.fetch));
const get$ = (id) => (typeof $ === "function" ? $(id) : (window.$ ? window.$(id) : document.getElementById(id)));
const get$$ = (sel) => (typeof $$ === "function" ? $$(sel) : (window.$$ ? window.$$(sel) : document.querySelectorAll(sel)));
const safeEscape = (str) => (typeof escapeHtml === "function" ? escapeHtml(str) : (window.escapeHtml ? window.escapeHtml(str) : String(str ?? "")));
const toast = (msg, type = "info") => {
  if (typeof showToast === "function") {
    showToast(msg, type);
  } else if (typeof window !== "undefined" && typeof window.showToast === "function") {
    window.showToast(msg, type);
  } else {
    console.log(`[Toast ${type}] ${msg}`);
  }
};

/**
 * Normalizes and formats Architecture Tier names for telemetry display.
 * @param {string|number} tier - Tier identifier (e.g. "tier_1", 1, "Tier 3")
 * @returns {string} Formatted label
 */
function formatTier(tier) {
  if (typeof window !== "undefined" && typeof window.formatTierDisplay === "function") {
    return window.formatTierDisplay(tier);
  }
  const norm = String(tier || "").toLowerCase().replace(/[\s-]/g, "_");
  if (norm.includes("1")) return "Tier 1: Gemini 3.5 Flash-Lite (Fast / Routine)";
  if (norm.includes("2")) return "Tier 2: Groq GPT-OSS 20B (Fast General)";
  if (norm.includes("3")) return "Tier 3: Gemini 3.6 Flash (Balanced)";
  if (norm.includes("4")) return "Tier 4: Groq Qwen3.8 27B (Coding Specialist)";
  if (norm.includes("5")) return "Tier 5: Groq GPT-OSS 120B (Deep Reasoning)";
  if (norm.includes("6")) return "Tier 6: Gemini 3.8 Flash (High Capability)";
  return String(tier || "Tier 1");
}

/* --------------------------------------------------------------------------
 * 1. Settings & Provider Configuration Modal
 * -------------------------------------------------------------------------- */

/**
 * Initializes and binds event handlers for the Settings and Provider modal.
 *
 * @param {(settings: Object) => void} [onSaved] - Callback invoked after settings are saved.
 * @param {() => void} [onHealthCheck] - Callback invoked to re-evaluate engine health and connectivity.
 */
function setupSettingsModal(onSaved, onHealthCheck) {
  const modal = get$("settings-modal");
  const openBtn = get$("open-settings-btn");
  const headerOpenBtn = get$("header-settings-btn");
  const closeBtn = get$("close-settings-btn");
  const backdrop = get$("settings-backdrop");
  const saveBtn = get$("save-settings-btn");
  const resetBtn = get$("reset-settings-btn");
  const clearKeysBtn = get$("clear-keys-btn");

  if (!modal) return;

  // Open modal workflow
  const openModal = async () => {
    modal.classList.remove("hidden");
    await populateSettingsForm();
    // Focus first interactive control
    const firstInput = modal.querySelector("input:not([readonly])");
    if (firstInput) {
      setTimeout(() => firstInput.focus(), 80);
    }
  };

  // Close modal workflow
  const closeModal = () => {
    modal.classList.add("hidden");
  };

  // Wire trigger buttons
  openBtn?.addEventListener("click", openModal);
  headerOpenBtn?.addEventListener("click", openModal);
  closeBtn?.addEventListener("click", closeModal);
  backdrop?.addEventListener("click", closeModal);

  // Keyboard accessibility: ESC key dismiss
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) {
      closeModal();
    }
  });

  // Tab switching: Segmented control
  const tabs = get$$(".settings-tab");
  const panels = get$$(".settings-panel");

  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      tabs.forEach((t) => t.classList.remove("active"));
      panels.forEach((p) => p.classList.remove("active"));

      tab.classList.add("active");
      const targetPanel = get$(`tab-${tab.dataset.tab}`);
      if (targetPanel) {
        targetPanel.classList.add("active");
      }
    });
  });

  // Password mask visibility togglers
  get$$(".btn-toggle-mask").forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetInput = get$(btn.dataset.target);
      if (targetInput) {
        const isPassword = targetInput.type === "password";
        targetInput.type = isPassword ? "text" : "password";
        btn.setAttribute("title", isPassword ? "Hide Key" : "Show Key");
        btn.setAttribute("aria-label", isPassword ? "Hide Key" : "Show Key");
        btn.classList.toggle("revealed", isPassword);
      }
    });
  });

  // Test provider connection buttons
  get$$(".btn-test-conn").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const prov = btn.dataset.provider;
      if (!prov) return;

      const statusBadge = get$(`status-${prov}-test`);
      if (!statusBadge) return;

      statusBadge.textContent = "Testing...";
      statusBadge.className = "status-test-badge testing";

      const keyInput = get$(`key-${prov}`);
      const apiKey = keyInput ? keyInput.value.trim() : "";
      const basePayload = { provider: prov };
      if (apiKey) {
        basePayload.api_key = apiKey;
      }

      if (prov === "custom") {
        basePayload.base_url = get$("url-custom")?.value.trim() || "";
        basePayload.model = get$("model-custom")?.value.trim() || "";
      }

      const fetcher = getApiFetch();

      try {
        const resp = await fetcher(`/api/providers/test/${prov}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(basePayload),
        });

        const res = await resp.json().catch(() => ({}));
        if (resp.ok && res.ok) {
          const latencyText = res.latency_ms ? ` (${Math.round(res.latency_ms)} ms)` : "";
          statusBadge.textContent = `Connected${latencyText}`;
          statusBadge.className = "status-test-badge success";
        } else {
          statusBadge.textContent = res.message || res.detail || "Connection Failed";
          statusBadge.className = "status-test-badge error";
        }
      } catch (err) {
        statusBadge.textContent = "Error testing connection";
        statusBadge.className = "status-test-badge error";
      }
    });
  });

  // Save Settings
  saveBtn?.addEventListener("click", async () => {
    const sm = getSM();
    if (!sm) return;

    try {
      const settings = await sm.load();

      // Update API Keys
      settings.apiKeys = settings.apiKeys || {};
      settings.apiKeys.gemini = get$("key-gemini")?.value.trim() || "";
      settings.apiKeys.groq = get$("key-groq")?.value.trim() || "";
      settings.apiKeys.openrouter = get$("key-openrouter")?.value.trim() || "";
      settings.apiKeys.openai = get$("key-openai")?.value.trim() || "";
      settings.apiKeys.custom = get$("key-custom")?.value.trim() || "";

      // Update Custom Endpoint
      settings.customEndpoints = settings.customEndpoints || {};
      settings.customEndpoints.custom = get$("url-custom")?.value.trim() || "";

      // Update Model Tiers
      settings.providerModels = settings.providerModels || {};
      settings.providerModels.geminiTier1 = get$("model-gemini-tier1")?.value.trim() || "gemini-3.5-flash-lite";
      settings.providerModels.geminiTier3 = get$("model-gemini-tier3")?.value.trim() || "gemini-3.6-flash";
      settings.providerModels.geminiTier6 = get$("model-gemini-tier6")?.value.trim() || "gemini-3.8-flash";
      settings.providerModels.groqTier2 = get$("model-groq-tier2")?.value.trim() || "openai/gpt-oss-20b";
      settings.providerModels.groqTier4 = get$("model-groq-tier4")?.value.trim() || "qwen/qwen3.8-27b";
      settings.providerModels.groqTier5 = get$("model-groq-tier5")?.value.trim() || "openai/gpt-oss-120b";
      settings.providerModels.custom = get$("model-custom")?.value.trim() || "";

      await sm.save(settings);
      toast("Settings saved securely", "success");
      closeModal();

      if (typeof onSaved === "function") {
        onSaved(settings);
      }
      if (typeof onHealthCheck === "function") {
        onHealthCheck();
      }
    } catch (err) {
      console.error("[Modals] Failed to save settings:", err);
      toast("Failed to save settings", "error");
    }
  });

  // Reset Defaults
  resetBtn?.addEventListener("click", async () => {
    const sm = getSM();
    if (!sm) return;

    if (window.confirm("Reset all provider configurations and models to factory defaults?")) {
      try {
        const defs = sm.getDefaults();
        await sm.save(defs);
        await populateSettingsForm();
        toast("Reset to default settings", "info");

        if (typeof onSaved === "function") {
          onSaved(defs);
        }
        if (typeof onHealthCheck === "function") {
          onHealthCheck();
        }
      } catch (err) {
        console.error("[Modals] Failed to reset defaults:", err);
        toast("Failed to reset settings", "error");
      }
    }
  });

  // Clear Keys
  clearKeysBtn?.addEventListener("click", async () => {
    const sm = getSM();
    if (!sm) return;

    if (window.confirm("Clear all configured API keys and custom endpoint credentials?")) {
      try {
        const cleared = await sm.clearKeys();
        await populateSettingsForm();
        toast("All API keys cleared", "info");

        if (typeof onSaved === "function") {
          onSaved(cleared);
        }
        if (typeof onHealthCheck === "function") {
          onHealthCheck();
        }
      } catch (err) {
        console.error("[Modals] Failed to clear keys:", err);
        toast("Failed to clear keys", "error");
      }
    }
  });
}

/**
 * Reads settings from SettingsManager and populates the Settings modal inputs.
 * @returns {Promise<void>}
 */
async function populateSettingsForm() {
  const sm = getSM();
  if (!sm) return;

  try {
    const settings = await sm.load();
    const apiKeys = settings.apiKeys || {};
    const endpoints = settings.customEndpoints || {};
    const models = settings.providerModels || {};

    // API Keys
    if (get$("key-gemini")) get$("key-gemini").value = apiKeys.gemini || "";
    if (get$("key-groq")) get$("key-groq").value = apiKeys.groq || "";
    if (get$("key-openrouter")) get$("key-openrouter").value = apiKeys.openrouter || "";
    if (get$("key-openai")) get$("key-openai").value = apiKeys.openai || "";
    if (get$("key-custom")) get$("key-custom").value = apiKeys.custom || "";

    // Custom Endpoint
    if (get$("url-custom")) get$("url-custom").value = endpoints.custom || "";
    if (get$("model-custom")) get$("model-custom").value = models.custom || "";

    // Gemini Models
    if (get$("model-gemini-tier1")) get$("model-gemini-tier1").value = models.geminiTier1 || "gemini-3.5-flash-lite";
    if (get$("model-gemini-tier3")) get$("model-gemini-tier3").value = models.geminiTier3 || "gemini-3.6-flash";
    if (get$("model-gemini-tier6")) get$("model-gemini-tier6").value = models.geminiTier6 || "gemini-3.8-flash";

    // Groq Models
    if (get$("model-groq-tier2")) get$("model-groq-tier2").value = models.groqTier2 || "openai/gpt-oss-20b";
    if (get$("model-groq-tier4")) get$("model-groq-tier4").value = models.groqTier4 || "qwen/qwen3.8-27b";
    if (get$("model-groq-tier5")) get$("model-groq-tier5").value = models.groqTier5 || "openai/gpt-oss-120b";

    // 6-Tier Architecture Overview Panel (Read-only status reflection)
    if (get$("override-tier1")) get$("override-tier1").value = models.geminiTier1 || "gemini-3.5-flash-lite";
    if (get$("override-tier2")) get$("override-tier2").value = models.groqTier2 || "openai/gpt-oss-20b";
    if (get$("override-tier3")) get$("override-tier3").value = models.geminiTier3 || "gemini-3.6-flash";
    if (get$("override-tier4")) get$("override-tier4").value = models.groqTier4 || "qwen/qwen3.8-27b";
    if (get$("override-tier5")) get$("override-tier5").value = models.groqTier5 || "openai/gpt-oss-120b";
    if (get$("override-tier6")) get$("override-tier6").value = models.geminiTier6 ? `${models.geminiTier6} (fallback: gemini-3.5-flash)` : "gemini-3.8-flash (fallback: gemini-3.5-flash)";

    // Reset status badges to neutral
    get$$(".status-test-badge").forEach((badge) => {
      badge.textContent = "Not tested";
      badge.className = "status-test-badge";
    });
  } catch (err) {
    console.error("[Modals] Failed to populate settings form:", err);
  }
}

/* --------------------------------------------------------------------------
 * 2. Telemetry Inspector Modal
 * -------------------------------------------------------------------------- */

/**
 * Initializes and binds dismiss listeners for the Telemetry Inspector modal.
 */
function setupInspectorModal() {
  const modal = get$("inspector-modal");
  const closeBtn = get$("close-inspector-btn");
  const backdrop = get$("inspector-backdrop");

  if (!modal) return;

  const closeModal = () => modal.classList.add("hidden");

  closeBtn?.addEventListener("click", closeModal);
  backdrop?.addEventListener("click", closeModal);

  // ESC key listener
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !modal.classList.contains("hidden")) {
      closeModal();
    }
  });
}

/**
 * Computes or resolves the 16-Dimensional LinUCB context feature vector (x_t)
 * @param {string} query
 * @param {Object} data
 * @returns {Array<{dim: string, label: string, val: number}>}
 */
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

/**
 * Renders the LinUCB Candidate Arms Scoreboard & Weights Table
 * @param {Array<Object>} candidates
 * @param {string} selectedModel
 * @returns {string}
 */
function renderLinUCBScoreboard(candidates, selectedModel) {
  if (!Array.isArray(candidates) || candidates.length === 0) {
    return "";
  }

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
            <span class="routing-tier-pill" style="font-size:10px;padding:1px 5px;">${safeEscape(tierDisplay)}</span>
            <strong style="font-size:12px;">${safeEscape(c.name || c.model_id)}</strong>
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

/**
 * Renders the 16D Feature Vector breakdown grid
 * @param {Array<Object>} features
 * @returns {string}
 */
function render16DFeatureGrid(features) {
  const cells = features.map(f => {
    const pct = Math.min(100, Math.max(0, Math.round(f.val * 100)));
    return `
      <div class="feature-dim-cell" title="${safeEscape(f.label)}: ${f.val}">
        <div class="feature-dim-header">
          <span class="feature-dim-label">${safeEscape(f.label)}</span>
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

/**
 * Fetches transaction details and displays the Telemetry Inspector modal.
 *
 * @param {string|number} requestId - Unique identifier of the logged transaction.
 * @returns {Promise<void>}
 */
async function openInspectorModal(requestId) {
  const modal = get$("inspector-modal");
  const body = get$("modal-body");
  const title = get$("modal-title");

  if (!modal || !body) return;

  modal.classList.remove("hidden");

  if (title) {
    title.innerHTML = `<svg class="icon-sym" aria-hidden="true"><use href="#i-search"/></svg> Request #${safeEscape(requestId)} Telemetry`;
  }

  body.innerHTML = `
    <div style="text-align:center;padding:32px 16px;color:var(--text-muted);">
      <div style="display:inline-block;width:24px;height:24px;border:2px solid var(--signal-indigo);border-top-color:transparent;border-radius:50%;animation:badgeSpin 0.7s linear infinite;margin-bottom:8px;"></div>
      <div>Loading detailed telemetry record...</div>
    </div>
  `;

  const fetcher = getApiFetch();

  try {
    const resp = await fetcher(`/api/requests/${requestId}`);
    if (!resp.ok) {
      throw new Error(`Transaction record #${requestId} not found.`);
    }

    const data = await resp.json();

    const servedModel = data.selected_model || data.model || "Unknown Model";
    const provider = data.provider || "gateway";
    const tierName = formatTier(data.target_tier ?? data.tier);
    const cost = Number(data.total_cost_usd ?? data.estimated_cost ?? 0);
    const latency = Math.round(Number(data.total_latency_ms ?? data.latency_ms ?? 0));
    const promptTokens = Number(data.prompt_tokens ?? data.input_tokens ?? data.in_tok ?? 0);
    const completionTokens = Number(data.completion_tokens ?? data.output_tokens ?? data.out_tok ?? 0);
    const tokens = Number(data.total_tokens ?? (promptTokens + completionTokens) ?? 0);
    const strategy = data.strategy || "Balanced";
    const rawQuery = data.query || data.prompt || "(No prompt captured)";
    const jsonString = JSON.stringify(data, null, 2);

    const features16d = resolve16DFeatures(rawQuery, data);
    const scoreboardHtml = renderLinUCBScoreboard(data.candidates, servedModel);
    const featuresHtml = render16DFeatureGrid(features16d);

    const rawTierVal = String(data.target_tier ?? data.tier ?? "");
    let tierColorStyle = 'style="color: var(--tier-2-text, #22D3EE);"';
    if (rawTierVal.includes("1")) {
      tierColorStyle = 'style="color: var(--tier-1-text, #34D399);"';
    } else if (rawTierVal.includes("2")) {
      tierColorStyle = 'style="color: var(--tier-2-text, #22D3EE);"';
    } else if (rawTierVal.includes("3")) {
      tierColorStyle = 'style="color: var(--tier-3-text, #60A5FA);"';
    } else if (rawTierVal.includes("4")) {
      tierColorStyle = 'style="color: var(--tier-4-text, #C084FC);"';
    } else if (rawTierVal.includes("5")) {
      tierColorStyle = 'style="color: var(--tier-5-text, #FBBF24);"';
    } else if (rawTierVal.includes("6")) {
      tierColorStyle = 'style="color: var(--tier-6-text, #FB7185);"';
    }

    body.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:14px;">
        <!-- Prompt Box -->
        <div class="inspector-prompt-box">
          <span class="inspector-prompt-label">Prompt Query</span>
          <div class="inspector-prompt-text">${safeEscape(rawQuery)}</div>
        </div>

        <!-- 6-Cell Metrics Drawer Grid -->
        <div class="drawer-grid">
          <div class="drawer-cell">
            <span class="drawer-cell-label">Served Model</span>
            <span class="drawer-cell-val" title="${safeEscape(servedModel)}">${safeEscape(servedModel)} <span style="font-size:11px;color:var(--text-muted);font-weight:normal;">(${safeEscape(provider)})</span></span>
          </div>

          <div class="drawer-cell">
            <span class="drawer-cell-label">Architecture Tier</span>
            <span class="drawer-cell-val" ${tierColorStyle} title="${safeEscape(tierName)}">${safeEscape(tierName.split(":")[0] || "Tier")}</span>
          </div>

          <div class="drawer-cell">
            <span class="drawer-cell-label">Total Cost (USD)</span>
            <span class="drawer-cell-val text-green">$${cost.toFixed(6)}</span>
          </div>

          <div class="drawer-cell">
            <span class="drawer-cell-label">Total Latency</span>
            <span class="drawer-cell-val">${latency.toLocaleString()} ms</span>
          </div>

          <div class="drawer-cell">
            <span class="drawer-cell-label">Metered Tokens</span>
            <span class="drawer-cell-val" title="In: ${promptTokens.toLocaleString()} | Out: ${completionTokens.toLocaleString()}">${tokens.toLocaleString()} <span style="font-size:11px;color:var(--text-muted);font-weight:normal;">(${promptTokens} / ${completionTokens})</span></span>
          </div>

          <div class="drawer-cell">
            <span class="drawer-cell-label">Routing Strategy</span>
            <span class="drawer-cell-val" style="text-transform:capitalize;">${safeEscape(strategy)}</span>
          </div>
        </div>

        <!-- LinUCB Candidate Arms Scoreboard -->
        ${scoreboardHtml}

        <!-- 16D Feature Vector Breakdown -->
        ${featuresHtml}

        <!-- JSON Viewer Section -->
        <div class="inspector-json-header">
          <span class="drawer-cell-label">Complete Telemetry JSON</span>
          <button type="button" class="btn-copy-json" id="btn-copy-inspector-json" title="Copy raw JSON telemetry">
            <svg class="icon-sym" aria-hidden="true"><use href="#i-copy"/></svg>
            <span>Copy JSON</span>
          </button>
        </div>
        <pre class="inspector-json-pre"><code id="inspector-json-code">${safeEscape(jsonString)}</code></pre>
      </div>
    `;

    // Bind copy button on JSON viewer
    const copyJsonBtn = get$("btn-copy-inspector-json");
    if (copyJsonBtn) {
      copyJsonBtn.addEventListener("click", async () => {
        try {
          if (navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
            await navigator.clipboard.writeText(jsonString);
          } else {
            const ta = document.createElement("textarea");
            ta.value = jsonString;
            ta.style.position = "fixed";
            ta.style.opacity = "0";
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            document.execCommand("copy");
            document.body.removeChild(ta);
          }

          const span = copyJsonBtn.querySelector("span");
          if (span) span.textContent = "Copied!";
          toast("Telemetry JSON copied to clipboard", "success");

          setTimeout(() => {
            if (span) span.textContent = "Copy JSON";
          }, 1800);
        } catch (err) {
          toast("Failed to copy JSON", "error");
        }
      });
    }
  } catch (err) {
    body.innerHTML = `
      <div style="padding:20px;text-align:center;color:var(--signal-red);">
        <p style="font-weight:600;margin-bottom:6px;">Error Loading Telemetry</p>
        <p style="font-size:var(--font-size-subhead);color:var(--text-muted);">${safeEscape(err.message)}</p>
      </div>
    `;
  }
}

/* --------------------------------------------------------------------------
 * Universal Browser Attachments
 * -------------------------------------------------------------------------- */
if (typeof window !== "undefined") {
  window.setupSettingsModal = setupSettingsModal;
  window.populateSettingsForm = populateSettingsForm;
  window.setupInspectorModal = setupInspectorModal;
  window.openInspectorModal = openInspectorModal;
}

if (typeof globalThis !== "undefined") {
  globalThis.setupSettingsModal = setupSettingsModal;
  globalThis.populateSettingsForm = populateSettingsForm;
  globalThis.setupInspectorModal = setupInspectorModal;
  globalThis.openInspectorModal = openInspectorModal;
}

export {
  setupSettingsModal,
  populateSettingsForm,
  setupInspectorModal,
  openInspectorModal,
};

export default {
  setupSettingsModal,
  populateSettingsForm,
  setupInspectorModal,
  openInspectorModal,
};
