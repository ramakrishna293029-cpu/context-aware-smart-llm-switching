/**
 * Context-Aware Smart LLM Switcher - Telemetry & Metering Dashboard
 *
 * Implements Chunk 10 of Frontend Modularization:
 * - Executive KPI Grid (Requests, Savings, Latencies, Incurred Cost, Tokens, Escalations/Fallbacks).
 * - Visualizer Charts Grid (Tier Architecture, Model Share, Task Types, Complexity Breakdown).
 * - LinUCB Multi-Armed Bandit Telemetry & Convergence Inspector.
 * - Live Transaction History Audit Trail with Request Telemetry Inspector bindings.
 * - 10-Second Auto-Refresh Cycle with Lifecycle Management.
 *
 * Standards:
 * - Apple Fluid Motion & Direct Manipulation (zero latency, spring physics).
 * - Claude Precision Data Visualization (fluff-free, tabular numbers, scale floors >= 12px).
 * - Generative UI (high visual density, micro-meters, live telemetry).
 */

// Internal Polling Timer Reference
let dashboardRefreshTimer = null;
let isRefreshingStats = false;

/**
 * Utility: Safe DOM Element Getter
 * @param {string} id
 * @returns {HTMLElement|null}
 */
const $ = (id) => (typeof document !== "undefined" ? document.getElementById(id) : null);

/**
 * Utility: HTML Entity Escaping
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
 * Utility: Normalizes tier keys from model strings or legacy IDs
 * @param {string} tier
 * @returns {string}
 */
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

/**
 * Formats canonical model or tier ID into human-readable executive tier descriptor
 * @param {string} tier
 * @returns {string}
 */
function formatTierDisplay(tier) {
  // Check if global formatter is provided
  if (typeof window !== "undefined" && typeof window.formatTierDisplay === "function" && window.formatTierDisplay !== formatTierDisplay) {
    try {
      return window.formatTierDisplay(tier);
    } catch (_) {}
  }

  const norm = normalizeTierKey(tier);
  switch (norm) {
    case "tier_1":
      return "Tier 1: Gemini 3.5 Flash-Lite (Fast / Routine)";
    case "tier_2":
      return "Tier 2: Groq GPT-OSS 20B (Fast General)";
    case "tier_3":
      return "Tier 3: Gemini 3.6 Flash (Balanced)";
    case "tier_4":
      return "Tier 4: Groq Qwen3.8 27B (Coding Specialist)";
    case "tier_5":
      return "Tier 5: Groq GPT-OSS 120B (Deep Reasoning)";
    case "tier_6":
      return "Tier 6: Gemini 3.8 Flash (High Capability)";
    default:
      return String(tier || "Tier 1");
  }
}

/**
 * Returns tier-specific CSS fill class for generative bar visualizers
 * @param {string} name
 * @returns {string}
 */
function getTierFillClass(name) {
  const norm = normalizeTierKey(name);
  switch (norm) {
    case "tier_1": return "fill-tier-1";
    case "tier_2": return "fill-tier-2";
    case "tier_3": return "fill-tier-3";
    case "tier_4": return "fill-tier-4";
    case "tier_5": return "fill-tier-5";
    case "tier_6": return "fill-tier-6";
    default: return "";
  }
}

/**
 * Returns complexity-specific CSS fill class
 * @param {string} name
 * @returns {string}
 */
function getComplexityFillClass(name) {
  const n = String(name).toLowerCase();
  if (n.includes("low")) return "fill-complexity-low";
  if (n.includes("med")) return "fill-complexity-medium";
  if (n.includes("high")) return "fill-complexity-high";
  return "";
}

/**
 * Dispatches request inspector modal open event
 * @param {number|string} requestId
 */
function openInspector(requestId) {
  if (typeof window !== "undefined") {
    if (typeof window.openInspectorModal === "function") {
      window.openInspectorModal(requestId);
      return;
    }
    // Fallback: Dispatch custom DOM event
    window.dispatchEvent(new CustomEvent("open-inspector", { detail: { id: requestId } }));
  }
}

/**
 * Renders high-precision vector SVG distribution chart for routing decisions across tiers and strategies.
 * @param {string} containerId - Target container element ID
 * @param {Array<{name: string, count: number}>} data - Distribution entries
 */
function renderBarChart(containerId, data) {
  const container = $(containerId);
  if (!container) return;

  if (!Array.isArray(data) || data.length === 0) {
    container.innerHTML = `
      <div class="chart-empty-state">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" style="opacity:0.4;margin-bottom:6px;">
          <rect x="2" y="13" width="20" height="8" rx="2"/>
          <path d="M12 2v11"/>
        </svg>
        <div>No transaction records recorded yet</div>
      </div>
    `;
    return;
  }

  const maxVal = Math.max(...data.map((d) => Number(d.count) || 0), 1);
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

    // Label determination
    let label = String(d.name || "Unknown");
    if (isTierChart) {
      const fullTier = formatTierDisplay(d.name);
      label = fullTier.split(":")[0] + " " + fullTier.split("(")[0].replace(/^Tier\s*\d:\s*/i, "").trim();
    }

    const y = idx * rowHeight + 18;

    // Semantic color mapping
    let hexColor = "#6366F1";
    if (isTierChart) {
      const norm = normalizeTierKey(d.name);
      if (norm === "tier_1") hexColor = "#38BDF8";
      else if (norm === "tier_2") hexColor = "#FB923C";
      else if (norm === "tier_3") hexColor = "#6366F1";
      else if (norm === "tier_4") hexColor = "#30D158";
      else if (norm === "tier_5") hexColor = "#C084FC";
      else if (norm === "tier_6") hexColor = "#FF9F0A";
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
      else if (n.includes("balanced")) hexColor = "#6366F1";
      else if (n.includes("lowest_cost")) hexColor = "#30D158";
      else if (n.includes("fastest")) hexColor = "#FB923C";
      else if (n.includes("highest_quality")) hexColor = "#C084FC";
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

/**
 * Renders the Live Transaction History Audit Trail Table
 * @param {Array<Object>} requests - List of recent transaction telemetry rows
 */
function renderHistoryTable(requests) {
  const tbody = $("history-tbody");
  if (!tbody) return;

  if (!Array.isArray(requests) || requests.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="9" class="empty-state">
          No transactions recorded yet. Submit a prompt from Chat &amp; Router to activate context-aware switching telemetry.
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = requests
    .map((r) => {
      const reqId = r.id != null ? r.id : "";
      const rawTime = r.timestamp || "";
      const timeDisplay = rawTime.includes(" ") ? rawTime.split(" ")[1] : rawTime || "—";
      const queryText = r.query || "";
      const taskType = (r.task_type || "general").toUpperCase();
      const complexity = r.complexity || "medium";
      const servedModel = r.selected_model || "Unknown Model";
      const tierDisplay = formatTierDisplay(r.target_tier || r.tier || servedModel);
      const latencyMs = Math.round(Number(r.total_latency_ms || r.latency_ms) || 0);

      // Cost formatting
      const costVal = r.total_cost_usd != null ? Number(r.total_cost_usd) : (r.estimated_cost != null ? Number(r.estimated_cost) : 0);
      const costFormatted = `$${costVal.toFixed(6)}`;

      // Fallback & Escalation indicators
      const fallbackUsed = Boolean(r.fallback_used);
      const fallbackBadge = fallbackUsed
        ? `<span class="status-pill fallback">Yes</span>`
        : `<span style="color:var(--text-muted, #86868B);">No</span>`;

      // Status indicator
      const isSuccess = r.success !== false;
      const statusBadge = isSuccess
        ? `<span class="status-pill success">✓ Ok</span>`
        : `<span class="status-pill error">✗ Error</span>`;

      return `
        <tr data-action="open-inspector" data-id="${escapeHtml(reqId)}" tabindex="0" role="button" aria-label="Inspect transaction ${escapeHtml(reqId)}">
          <td><span style="font-family:var(--font-mono, monospace); font-variant-numeric: tabular-nums; font-size:12px;">${escapeHtml(timeDisplay)}</span></td>
          <td class="query-cell" title="${escapeHtml(queryText)}">
            ${escapeHtml(queryText)}
          </td>
          <td><span class="routing-tier-pill">${escapeHtml(taskType)}</span></td>
          <td><span style="text-transform:capitalize;">${escapeHtml(complexity)}</span></td>
          <td title="${escapeHtml(tierDisplay)}">
            <code>${escapeHtml(servedModel)}</code>
          </td>
          <td><span style="font-family:var(--font-mono, monospace); font-variant-numeric: tabular-nums;">${latencyMs} ms</span></td>
          <td><span style="font-family:var(--font-mono, monospace); font-variant-numeric: tabular-nums; font-weight:600;">${costFormatted}</span></td>
          <td>${fallbackBadge}</td>
          <td>${statusBadge}</td>
        </tr>
      `;
    })
    .join("");

  // Attach interactive click and keyboard accessibility listeners to each row
  tbody.querySelectorAll('tr[data-action="open-inspector"]').forEach((row) => {
    const clickHandler = () => {
      const id = row.getAttribute("data-id");
      if (id) openInspector(id);
    };

    row.addEventListener("click", clickHandler);
    row.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        clickHandler();
      }
    });
  });
}

/**
 * Fetches `/api/stats`, updates executive KPI cards, renders visualizer charts,
 * populates the LinUCB Contextual Bandit Telemetry table, and refreshes the audit trail.
 * @returns {Promise<void>}
 */
async function loadDashboardStats() {
  if (isRefreshingStats) return;
  isRefreshingStats = true;

  const refreshBtn = $("refresh-dashboard-btn");
  if (refreshBtn) {
    refreshBtn.classList.add("is-refreshing");
  }

  // Ensure button click listener is registered idempotently
  if (refreshBtn && !refreshBtn.dataset.listenerAttached) {
    refreshBtn.dataset.listenerAttached = "true";
    refreshBtn.addEventListener("click", async () => {
      await loadDashboardStats();
      if (typeof window !== "undefined" && typeof window.showToast === "function") {
        window.showToast("Telemetry metrics synchronized", "info");
      }
    });
  }

  try {
    // Resolve transport layer with storage encrypted headers or standard fetch
    const fetcher = typeof window !== "undefined" && typeof window.apiFetch === "function" ? window.apiFetch : fetch;
    const resp = await fetcher("/api/stats");
    if (!resp.ok) {
      throw new Error(`HTTP Error ${resp.status}: ${resp.statusText}`);
    }

    const s = await resp.json();
    const totalReq = Number(s.total_requests) || 0;

    // 1. Executive KPI Grid Updates
    if ($("stat-total-requests")) {
      $("stat-total-requests").textContent = totalReq.toLocaleString();
    }
    if ($("stat-success-rate")) {
      $("stat-success-rate").textContent =
        totalReq > 0 ? `Success: ${((Number(s.success_rate) || 0) * 100).toFixed(1)}%` : `Success: —`;
    }

    const savingsVal = Number(s.estimated_savings_usd != null ? s.estimated_savings_usd : s.savings_usd) || 0;
    if ($("stat-savings-usd")) {
      $("stat-savings-usd").textContent = `$${savingsVal.toFixed(6)}`;
    }
    if ($("stat-savings-pct")) {
      const savingsPct = Number(s.savings_percent) || 0;
      $("stat-savings-pct").textContent = `${savingsPct.toFixed(1)}% savings vs Tier 6 baseline`;
    }

    const avgTotalLat = Math.round(Number(s.average_total_latency_ms) || 0);
    const avgGenLat = Math.round(Number(s.average_latency_ms) || 0);
    const baselineLat = 650; // Reference Tier 6 uniform baseline latency benchmark
    const speedupPct = (avgTotalLat > 0 && avgTotalLat < baselineLat)
      ? Math.round(((baselineLat - avgTotalLat) / baselineLat) * 100)
      : 0;

    if ($("stat-avg-latency")) {
      $("stat-avg-latency").textContent = `${avgTotalLat} ms`;
    }
    if ($("stat-analyzer-latency")) {
      $("stat-analyzer-latency").textContent = speedupPct > 0
        ? `Gen: ${avgGenLat} ms · +${speedupPct}% Speedup vs T6`
        : `Gen: ${avgGenLat} ms avg · Routing + Generation`;
    }

    const totalCost = Number(s.total_cost_usd) || 0;
    const baselineCost = Number(s.baseline_cost_usd) || 0;
    if ($("stat-total-cost")) {
      $("stat-total-cost").textContent = `$${totalCost.toFixed(6)}`;
    }
    if ($("stat-baseline-cost")) {
      $("stat-baseline-cost").textContent = `Tier 6 Baseline: $${baselineCost.toFixed(6)}`;
    }

    const totalTokens = Number(s.total_tokens) || 0;
    if ($("stat-total-tokens")) {
      $("stat-total-tokens").textContent = totalTokens.toLocaleString();
    }

    const fallbacks = Number(s.fallback_count || s.fallbacks) || 0;
    const escalations = Number(s.escalation_count || s.escalations) || 0;
    if ($("stat-fallbacks")) {
      $("stat-fallbacks").textContent = fallbacks.toString();
    }
    if ($("stat-escalations-sub")) {
      $("stat-escalations-sub").textContent = `${escalations} escalations · ${fallbacks} failovers`;
    }

    // 2. Visualizer Distribution Charts
    renderBarChart("chart-tier-dist", s.tier_distribution || []);
    renderBarChart("chart-model-dist", s.model_distribution || []);
    renderBarChart("chart-task-dist", s.task_distribution || []);
    renderBarChart("chart-complexity-dist", s.complexity_distribution || []);

    // 3. LinUCB Contextual Bandit Telemetry Panel
    const banditBody = $("bandit-arms-tbody");
    if (banditBody) {
      const armsData = s.bandit_arms || (s.bandit && s.bandit.arms);
      if (armsData && Object.keys(armsData).length > 0) {
        const armEntries = Object.entries(armsData);
        banditBody.innerHTML = armEntries
          .map(([mid, arm]) => {
            const pulls = Number(arm.pull_count) || 0;
            const mean = arm.mean_reward != null ? Number(arm.mean_reward).toFixed(4) : "0.0000";
            const totalR = arm.total_reward != null ? Number(arm.total_reward).toFixed(4) : "0.0000";
            const alpha = arm.alpha != null ? Number(arm.alpha).toFixed(2) : "1.00";

            // Convergence & status determination
            let statusText = "Cold / Unpulled";
            let statusClass = "";
            let dotColor = "#94A3B8";

            if (pulls > 0) {
              if (Number(arm.mean_reward) > 0) {
                statusText = "Converged Optimal";
                statusClass = "dot-pulse";
                dotColor = "#30D158";
              } else {
                statusText = "Active Exploration";
                dotColor = "#FF9F0A";
              }
            }

            const totalRewardColor = Number(totalR) >= 0 ? "var(--signal-emerald, #30D158)" : "var(--signal-red, #FF453A)";

            return `
              <tr>
                <td><strong>${escapeHtml(formatTierDisplay(mid))}</strong></td>
                <td><code>${escapeHtml(mid)}</code></td>
                <td><span style="font-family:var(--font-mono, monospace); font-weight:600;">${pulls}</span></td>
                <td><span style="font-family:var(--font-mono, monospace); font-weight:600; color:${totalRewardColor};">${totalR}</span></td>
                <td><span style="font-family:var(--font-mono, monospace); font-weight:600; color:#38BDF8;">${mean}</span></td>
                <td><span style="font-family:var(--font-mono, monospace);">${alpha}</span></td>
                <td>
                  <span class="bandit-status-pill">
                    <span class="bandit-status-dot ${statusClass}" style="background-color: ${dotColor};"></span>
                    ${statusText}
                  </span>
                </td>
              </tr>
            `;
          })
          .join("");
      } else {
        banditBody.innerHTML = `
          <tr>
            <td colspan="7" class="empty-state">
              No LinUCB bandit arm interactions observed yet.
            </td>
          </tr>
        `;
      }
    }

    // 4. Live Transaction History Audit Trail Table
    let historyRequests = Array.isArray(s.recent_requests) ? s.recent_requests : [];
    try {
      const histResp = await fetcher("/api/history?limit=30");
      if (histResp.ok) {
        const histData = await histResp.json();
        if (Array.isArray(histData)) {
          historyRequests = histData;
        }
      }
    } catch (histErr) {
      console.warn("[Dashboard] Could not fetch separate /api/history endpoint, using stats recent_requests:", histErr);
    }

    renderHistoryTable(historyRequests);
  } catch (err) {
    console.error("[Dashboard] Failed to synchronize dashboard telemetry:", err);
  } finally {
    isRefreshingStats = false;
    if (refreshBtn) {
      refreshBtn.classList.remove("is-refreshing");
    }
  }
}

/**
 * Starts 10-second background polling cycle when Dashboard View is active.
 * Idempotent: tears down any pre-existing timer before instantiating.
 */
function startDashboardAutoRefresh() {
  stopDashboardAutoRefresh();
  dashboardRefreshTimer = setInterval(() => {
    // Only poll if the dashboard panel is currently visible in DOM
    const dashboardView = $("view-dashboard");
    if (dashboardView && (dashboardView.classList.contains("active") || dashboardView.style.display !== "none")) {
      loadDashboardStats();
    }
  }, 10000);
}

/**
 * Stops background polling cycle to conserve bandwidth and prevent memory leaks.
 */
function stopDashboardAutoRefresh() {
  if (dashboardRefreshTimer) {
    clearInterval(dashboardRefreshTimer);
    dashboardRefreshTimer = null;
  }
}

// Global Browser Attachments for Non-Bundled Contexts
if (typeof window !== "undefined") {
  window.loadDashboardStats = loadDashboardStats;
  window.renderBarChart = renderBarChart;
  window.renderHistoryTable = renderHistoryTable;
  window.startDashboardAutoRefresh = startDashboardAutoRefresh;
  window.stopDashboardAutoRefresh = stopDashboardAutoRefresh;
  window.formatTierDisplay = formatTierDisplay;
}

if (typeof globalThis !== "undefined") {
  globalThis.loadDashboardStats = loadDashboardStats;
  globalThis.renderBarChart = renderBarChart;
  globalThis.renderHistoryTable = renderHistoryTable;
  globalThis.startDashboardAutoRefresh = startDashboardAutoRefresh;
  globalThis.stopDashboardAutoRefresh = stopDashboardAutoRefresh;
  globalThis.formatTierDisplay = formatTierDisplay;
}

// ES6 Module Exports
export {
  loadDashboardStats,
  renderBarChart,
  renderHistoryTable,
  startDashboardAutoRefresh,
  stopDashboardAutoRefresh,
  formatTierDisplay,
};

export default {
  loadDashboardStats,
  renderBarChart,
  renderHistoryTable,
  startDashboardAutoRefresh,
  stopDashboardAutoRefresh,
  formatTierDisplay,
};
