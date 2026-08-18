/* ============================================================
   Context-Aware Smart LLM Switcher - Client Application
   ============================================================ */

const $ = (id) => document.getElementById(id);
const chatHistory = [];
let lastRequestId = null;
let dashboardRefreshInterval = null;

// Initialize on DOM load
document.addEventListener("DOMContentLoaded", () => {
  setupTabs();
  setupChat();
  setupQuickChips();
  setupDashboard();
  setupBenchmark();
  setupHealthCheck();
});

/* ============================================================
   1. Tab Navigation
   ============================================================ */
function setupTabs() {
  document.querySelectorAll(".nav-tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".nav-tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-view").forEach(v => v.classList.remove("active"));

      tab.classList.add("active");
      const targetId = `tab-${tab.dataset.tab}`;
      const targetView = $(targetId);
      if (targetView) targetView.classList.add("active");

      // Actions on tab switch
      if (tab.dataset.tab === "dashboard") {
        loadDashboardStats();
        startDashboardAutoRefresh();
      } else {
        stopDashboardAutoRefresh();
      }

      if (tab.dataset.tab === "health") {
        checkProviderHealth();
      }
    });
  });
}

/* ============================================================
   2. Chat Studio & Streaming
   ============================================================ */
function setupChat() {
  const chatForm = $("chat-form");
  const queryInput = $("query-input");
  const clearHistoryBtn = $("clear-history-btn");

  // Auto-resize textarea
  queryInput.addEventListener("input", () => {
    queryInput.style.height = "auto";
    queryInput.style.height = `${Math.min(queryInput.scrollHeight, 160)}px`;
  });

  // Enter to send (Shift+Enter for newline)
  queryInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      chatForm.requestSubmit();
    }
  });

  // Clear history
  clearHistoryBtn?.addEventListener("click", () => {
    chatHistory.length = 0;
    updateContextCounter();
    const msgsContainer = $("chat-messages");
    msgsContainer.innerHTML = `
      <div class="welcome-card">
        <div class="welcome-icon">🧠</div>
        <h2>Conversation History Cleared</h2>
        <p>You have started a fresh context session. Ask any query to begin.</p>
      </div>
    `;
  });

  chatForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const query = queryInput.value.trim();
    if (!query) return;

    // Reset input
    queryInput.value = "";
    queryInput.style.height = "auto";
    $("send-btn").disabled = true;

    // Append User Message
    appendUserMessage(query);

    // Create streaming placeholder for assistant
    const placeholder = createStreamingPlaceholder();
    const strategy = $("strategy-select").value;

    let streamedText = "";
    let isFirstDelta = true;
    let analyzerInfo = null;
    let routingInfo = null;

    try {
      await executeStreamingChat(
        { query, history: chatHistory.slice(-10), strategy },
        // onAnalyzer
        (info) => {
          analyzerInfo = info;
          placeholder.updateStatus(
            `🧠 <strong>Analyzer (${escapeHtml(info.provider.toUpperCase())}):</strong> ` +
            `Classified as <em>${escapeHtml(info.task_type)}</em> (complexity: ${info.complexity})`
          );
        },
        // onRouting
        (route) => {
          routingInfo = route;
          placeholder.updateStatus(
            `🔄 <strong>Routing:</strong> Selected <em>${escapeHtml(route.target_name || route.target_model)}</em> ` +
            `(${escapeHtml(route.target_tier.toUpperCase())} Tier) · <em>${escapeHtml(route.reason)}</em>`
          );
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
          appendAssistantResponse(query, doneData.response || streamedText, doneData);
          chatHistory.push({ role: "user", content: query }, { role: "assistant", content: doneData.response || streamedText });
          updateContextCounter();
          lastRequestId = doneData.request_id;
        },
        // onError
        (errorMsg) => {
          placeholder.showError(errorMsg);
        }
      );
    } catch (err) {
      // Fallback to standard POST request if SSE stream fails
      console.warn("SSE Stream failed, falling back to /api/chat:", err);
      try {
        const resp = await fetch("/api/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query, history: chatHistory.slice(-10), strategy }),
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || "Request failed");

        placeholder.card.remove();
        appendAssistantResponse(query, data.response, data);
        chatHistory.push({ role: "user", content: query }, { role: "assistant", content: data.response });
        updateContextCounter();
        lastRequestId = data.request_id;
      } catch (postErr) {
        placeholder.showError(postErr.message);
      }
    } finally {
      $("send-btn").disabled = false;
      queryInput.focus();
    }
  });
}

function updateContextCounter() {
  const countEl = $("context-count");
  if (countEl) countEl.textContent = Math.floor(chatHistory.length / 2);
}

function setupQuickChips() {
  document.querySelectorAll(".quick-chip").forEach(chip => {
    chip.addEventListener("click", () => {
      const q = chip.dataset.query;
      if (q) {
        $("query-input").value = q;
        $("query-input").focus();
        $("chat-form").requestSubmit();
      }
    });
  });
}

function appendUserMessage(text) {
  const container = $("chat-messages");
  const msgEl = document.createElement("div");
  msgEl.className = "chat-msg user";
  msgEl.innerHTML = `
    <div class="msg-avatar">👤</div>
    <div class="msg-content-wrap">
      <div class="user-bubble">${escapeHtml(text)}</div>
    </div>
  `;
  container.appendChild(msgEl);
  container.scrollTop = container.scrollHeight;
}

function createStreamingPlaceholder() {
  const container = $("chat-messages");
  const msgEl = document.createElement("div");
  msgEl.className = "chat-msg assistant";

  const card = document.createElement("div");
  card.className = "assistant-card";

  const statusWrap = document.createElement("div");
  statusWrap.className = "streaming-step";
  statusWrap.innerHTML = `<span class="spinner"></span> <span class="step-text">OpenRouter Analyzer LLM evaluating query & context...</span>`;

  const bodyWrap = document.createElement("div");
  bodyWrap.className = "msg-text-body";
  bodyWrap.style.display = "none";

  card.appendChild(statusWrap);
  card.appendChild(bodyWrap);
  msgEl.appendChild(document.createElement("div")).className = "msg-avatar";
  msgEl.querySelector(".msg-avatar").textContent = "⚡";
  msgEl.appendChild(card);
  container.appendChild(msgEl);
  container.scrollTop = container.scrollHeight;

  return {
    card: msgEl,
    updateStatus: (html) => {
      statusWrap.innerHTML = `<span class="spinner"></span> <span class="step-text">${html}</span>`;
    },
    startResponse: () => {
      bodyWrap.style.display = "block";
    },
    appendDelta: (fullText) => {
      bodyWrap.innerHTML = formatMarkdown(fullText);
      container.scrollTop = container.scrollHeight;
    },
    showError: (errText) => {
      statusWrap.innerHTML = `<span style="color:var(--accent-red)">⚠️ ${escapeHtml(errText)}</span>`;
    }
  };
}

function appendAssistantResponse(query, text, data) {
  const container = $("chat-messages");
  const msgEl = document.createElement("div");
  msgEl.className = "chat-msg assistant";

  const analyzer = data.analyzer || {};
  const model = data.model || {};

  const taskType = analyzer.task_type || "general";
  const complexity = analyzer.complexity || "medium";
  const targetTier = analyzer.target_tier || "fast";
  const targetProvider = analyzer.target_provider || model.provider || "gemini";
  const reason = data.routing_reason || analyzer.reason || model.reason || "Optimal intelligence tier";

  const totalCost = data.total_cost_usd != null ? `$${data.total_cost_usd.toFixed(6)}` : "—";
  const savingsPct = data.savings_percent != null ? `${data.savings_percent.toFixed(1)}%` : null;
  const totalTokens = data.total_tokens ? `${data.total_tokens.toLocaleString()} tok` : "—";
  const latency = data.total_latency_ms != null ? `${Math.round(data.total_latency_ms)} ms` : `${Math.round(data.latency_ms || 0)} ms`;

  const fallbackBadge = data.fallback_used ? `<span class="tag-pill" style="border-color:var(--accent-amber);color:var(--accent-amber)">Fallback Used</span>` : "";

  msgEl.innerHTML = `
    <div class="msg-avatar">⚡</div>
    <div class="msg-content-wrap" style="width:100%">
      <div class="assistant-card">
        <!-- Routing Card -->
        <div class="routing-card">
          <div class="routing-header">
            <div class="routing-flow">
              <span class="badge-analyzer">🧠 Analyzer: ${escapeHtml(analyzer.model_name || "OpenRouter")}</span>
              <span style="color:var(--text-muted)">➔</span>
              <span class="badge-target ${targetTier}">🎯 Routed: ${escapeHtml(model.model_name || model.model_id || targetTier)}</span>
            </div>
            <div class="routing-tags">
              <span class="tag-pill complexity-${complexity}">${complexity.toUpperCase()}</span>
              <span class="tag-pill">${taskType.toUpperCase()}</span>
              ${data.context_relevant ? '<span class="tag-pill" style="color:var(--accent-blue)">Context Active</span>' : ''}
              ${fallbackBadge}
            </div>
          </div>
          <div class="routing-reason">"${escapeHtml(reason)}"</div>
        </div>

        <!-- Body -->
        <div class="msg-text-body">
          ${formatMarkdown(text)}
        </div>

        <!-- Telemetry Footer -->
        <div class="telemetry-footer">
          <div class="telemetry-chips">
            <div class="t-chip"><span>⚡ Latency:</span> <strong>${latency}</strong></div>
            <div class="t-chip"><span>🔢 Tokens:</span> <strong>${totalTokens}</strong></div>
            <div class="t-chip"><span>💰 Cost:</span> <strong>${totalCost}</strong></div>
            ${savingsPct ? `<div class="t-chip savings"><span>📉 Saved:</span> <strong>${savingsPct} vs baseline</strong></div>` : ''}
          </div>
          <div class="telemetry-actions">
            <button class="btn-icon" onclick="copyText(this, ${JSON.stringify(text)})" title="Copy Answer">📋 Copy</button>
            <button class="btn-icon" onclick="openInspector(${data.request_id})" title="Inspect Decision & Telemetry">🔍 Inspect</button>
            <button class="btn-icon" onclick="recordFeedback(${data.request_id}, 1, this)" title="Good Response">👍</button>
            <button class="btn-icon" onclick="recordFeedback(${data.request_id}, -1, this)" title="Poor Response">👎</button>
          </div>
        </div>
      </div>
    </div>
  `;

  container.appendChild(msgEl);
  container.scrollTop = container.scrollHeight;
}

async function executeStreamingChat(payload, onAnalyzer, onRouting, onDelta, onDone, onError) {
  const resp = await fetch("/api/chat/stream", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
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
    buffer = parts.pop();

    for (const part of parts) {
      const line = part.split("\n").find(l => l.startsWith("data:"));
      if (!line) continue;
      let evt;
      try {
        evt = JSON.parse(line.slice(5).trim());
      } catch {
        continue;
      }

      if (evt.event === "analyzer") onAnalyzer(evt.info);
      else if (evt.event === "routing") onRouting(evt);
      else if (evt.event === "delta") onDelta(evt.text);
      else if (evt.event === "done") onDone(evt);
      else if (evt.event === "error") onError(evt.detail);
    }
  }
}

/* ============================================================
   3. Telemetry & Analytics Dashboard
   ============================================================ */
function setupDashboard() {
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
    const resp = await fetch("/api/stats");
    if (!resp.ok) return;
    const s = await resp.json();

    // KPIs
    $("stat-total-requests").textContent = s.total_requests.toLocaleString();
    $("stat-success-rate").textContent = `Success Rate: ${(s.success_rate * 100).toFixed(1)}%`;
    $("stat-savings-usd").textContent = `$${s.estimated_savings_usd.toFixed(4)}`;
    $("stat-savings-pct").textContent = `${s.savings_percent.toFixed(1)}% savings vs baseline`;
    $("stat-avg-latency").textContent = `${Math.round(s.average_total_latency_ms)} ms`;
    $("stat-analyzer-latency").textContent = `Gen: ${Math.round(s.average_latency_ms)} ms avg`;
    $("stat-total-cost").textContent = `$${s.total_cost_usd.toFixed(6)}`;
    $("stat-baseline-cost").textContent = `Baseline: $${s.baseline_cost_usd.toFixed(6)}`;
    $("stat-total-tokens").textContent = s.total_tokens.toLocaleString();
    $("stat-fallbacks").textContent = s.fallback_count.toString();

    // Render Distribution Charts
    renderBarChart("chart-model-dist", s.model_distribution || []);
    renderBarChart("chart-tier-dist", s.tier_distribution || []);
    renderBarChart("chart-task-dist", s.task_distribution || []);
    renderBarChart("chart-complexity-dist", s.complexity_distribution || []);

    // Render Recent Requests Table
    renderHistoryTable(s.recent_requests || []);
  } catch (err) {
    console.error("Failed to load dashboard stats:", err);
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
      <tr onclick="openInspector(${r.id})">
        <td>${escapeHtml(r.timestamp.split(" ")[1] || r.timestamp)}</td>
        <td title="${escapeHtml(r.query)}" style="max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
          ${escapeHtml(r.query)}
        </td>
        <td><span class="tag-pill">${escapeHtml(r.task_type)}</span></td>
        <td><span class="tag-pill complexity-${r.complexity}">${escapeHtml(r.complexity)}</span></td>
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
   4. Research Benchmark Lab (Section 27)
   ============================================================ */
function setupBenchmark() {
  const runBtn = $("run-benchmark-btn");
  if (!runBtn) return;

  runBtn.addEventListener("click", async () => {
    runBtn.disabled = true;
    runBtn.innerHTML = `<span class="spinner"></span> Executing Benchmark...`;

    try {
      const resp = await fetch("/api/benchmark/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({}),
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.detail || "Benchmark failed");

      // Show summary cards
      $("benchmark-summary-cards").style.display = "grid";
      $("bm-overall-savings").textContent = `${data.overall_cost_savings_percent.toFixed(1)}%`;
      $("bm-saved-dollars").textContent = `$${data.total_cost_saved_usd.toFixed(4)} saved across test suite`;
      $("bm-overall-speedup").textContent = `${data.overall_speedup_percent.toFixed(1)}%`;
      $("bm-smart-cost").textContent = `$${data.smart_total_cost_usd.toFixed(6)}`;
      $("bm-baseline-cost").textContent = `vs Baseline 1: $${data.baseline1_total_cost_usd.toFixed(6)}`;

      // Render Table
      const tbody = $("benchmark-tbody");
      tbody.innerHTML = data.items.map(item => `
        <tr>
          <td>
            <strong>${escapeHtml(item.query)}</strong>
            <div style="margin-top:4px"><span class="tag-pill">${escapeHtml(item.task_type)}</span> <span class="tag-pill complexity-${item.complexity}">${escapeHtml(item.complexity)}</span></div>
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
    } catch (err) {
      alert("Benchmark failed: " + err.message);
    } finally {
      runBtn.disabled = false;
      runBtn.innerHTML = `<span>▶</span> Run Multi-Domain Benchmark`;
    }
  });
}

/* ============================================================
   5. Provider Health Monitoring
   ============================================================ */
function setupHealthCheck() {
  $("test-providers-btn")?.addEventListener("click", checkProviderHealth);
}

async function checkProviderHealth() {
  const btn = $("test-providers-btn");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `<span class="spinner"></span> Testing...`;
  }

  // Set checking states
  ["openrouter", "gemini", "groq"].forEach(p => {
    const el = $(`status-${p}`);
    if (el) {
      el.className = "p-status-pill checking";
      el.textContent = "Checking...";
    }
  });

  try {
    const resp = await fetch("/api/providers/health");
    const data = await resp.json();

    // Update OpenRouter
    updateProviderCard("openrouter", data.openrouter);
    // Update Gemini
    updateProviderCard("gemini", data.gemini);
    // Update Groq
    updateProviderCard("groq", data.groq);

    // Update engine status header pill
    const allConnected = (data.openrouter?.status === "connected" && data.gemini?.status === "connected" && data.groq?.status === "connected");
    $("engine-status").textContent = allConnected ? "3 Providers Active" : "Orchestrator Online";
  } catch (err) {
    console.error("Health check failed:", err);
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `<span>⚡</span> Ping All Providers`;
    }
  }
}

function updateProviderCard(provider, info) {
  const pill = $(`status-${provider}`);
  const ping = $(`ping-${provider}`);

  if (!info) return;

  if (info.status === "connected") {
    pill.className = "p-status-pill connected";
    pill.textContent = "● Connected";
    ping.textContent = `${info.latency_ms} ms`;
  } else {
    pill.className = "p-status-pill error";
    pill.textContent = "● Error";
    ping.textContent = info.error ? escapeHtml(info.error.slice(0, 30)) : "Unavailable";
  }
}

/* ============================================================
   6. Inspector Modal & Feedback
   ============================================================ */
async function openInspector(requestId) {
  const modal = $("inspector-modal");
  const modalBody = $("modal-body");
  modal.classList.remove("hidden");
  modalBody.innerHTML = `<div class="loading-spinner">Loading telemetry for Request #${requestId}...</div>`;

  try {
    const resp = await fetch(`/api/requests/${requestId}`);
    const r = await resp.json();
    if (!resp.ok) throw new Error(r.detail || "Request not found");

    modalBody.innerHTML = `
      <div class="modal-section-card">
        <h4>Query & Classification</h4>
        <p><strong>Query:</strong> ${escapeHtml(r.query)}</p>
        <div style="margin-top:6px;display:flex;gap:8px">
          <span class="tag-pill">Task: ${escapeHtml(r.task_type)}</span>
          <span class="tag-pill complexity-${r.complexity}">Complexity: ${escapeHtml(r.complexity)} (${r.complexity_score})</span>
          <span class="tag-pill">Strategy: ${escapeHtml(r.strategy || "balanced")}</span>
        </div>
      </div>

      <div class="modal-grid">
        <div class="modal-section-card">
          <h4>Analyzer LLM Decision</h4>
          <p><strong>Analyzer Model:</strong> ${escapeHtml(r.analyzer_model)} (${escapeHtml(r.analyzer_provider)})</p>
          <p><strong>Analyzer Latency:</strong> ${Math.round(r.analyzer_latency_ms)} ms</p>
          <p><strong>Analyzer Tokens:</strong> ${r.analyzer_input_tokens || 0} in / ${r.analyzer_output_tokens || 0} out</p>
          <p><strong>Analyzer Cost:</strong> $${(r.analyzer_cost || 0).toFixed(6)}</p>
          <p style="margin-top:6px"><strong>Reason:</strong> <em>${escapeHtml(r.routing_reason || "—")}</em></p>
        </div>

        <div class="modal-section-card">
          <h4>Execution & Served Model</h4>
          <p><strong>Served Model:</strong> <code>${escapeHtml(r.selected_model)}</code> (${escapeHtml(r.selected_provider)})</p>
          <p><strong>Generation Latency:</strong> ${Math.round(r.latency_ms)} ms ${r.ttft_ms ? `(TTFT: ${Math.round(r.ttft_ms)}ms)` : ''}</p>
          <p><strong>Model Tokens:</strong> ${r.input_tokens || 0} in / ${r.output_tokens || 0} out</p>
          <p><strong>Model Cost:</strong> $${(r.estimated_cost || 0).toFixed(6)}</p>
          <p><strong>Fallback Used:</strong> ${r.fallback_used ? '<span style="color:var(--accent-amber)">Yes</span>' : 'No'}</p>
        </div>
      </div>

      <div class="modal-section-card">
        <h4>Cost & Latency Optimization Outcome</h4>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px">
          <div><span>Total End-to-End Latency:</span> <strong>${Math.round(r.total_latency_ms)} ms</strong></div>
          <div><span>Total Request Cost:</span> <strong>$${((r.estimated_cost || 0) + (r.analyzer_cost || 0)).toFixed(6)}</strong></div>
          <div><span>Savings vs Baseline:</span> <strong class="text-green">${(r.savings_percent || 0).toFixed(1)}% ($${(r.savings_usd || 0).toFixed(6)})</strong></div>
        </div>
      </div>

      ${r.candidates && r.candidates.length > 0 ? `
        <div class="modal-section-card">
          <h4>Multi-Factor Candidate Scoreboard</h4>
          <table class="data-table" style="margin-top:6px">
            <thead>
              <tr><th>Candidate Model</th><th>Provider</th><th>Tier</th><th>Score</th><th>Est. Cost</th></tr>
            </thead>
            <tbody>
              ${r.candidates.map(c => `
                <tr class="${c.selected ? 'cand-selected' : ''}">
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
      ` : ''}
    `;
  } catch (err) {
    modalBody.innerHTML = `<div class="empty-state" style="color:var(--accent-red)">Failed to load: ${escapeHtml(err.message)}</div>`;
  }
}

function closeInspector() {
  $("inspector-modal").classList.add("hidden");
}

async function recordFeedback(requestId, rating, btn) {
  try {
    const resp = await fetch("/api/feedback", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: requestId, rating }),
    });
    if (resp.ok) {
      btn.style.color = rating === 1 ? "var(--accent-green)" : "var(--accent-red)";
      btn.style.borderColor = rating === 1 ? "var(--accent-green)" : "var(--accent-red)";
    }
  } catch (e) {
    console.error("Feedback failed:", e);
  }
}

function copyText(btn, text) {
  navigator.clipboard.writeText(text);
  const orig = btn.textContent;
  btn.textContent = "✓ Copied";
  setTimeout(() => { btn.textContent = orig; }, 2000);
}

/* ============================================================
   7. Helpers
   ============================================================ */
function escapeHtml(s) {
  return String(s || "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  }[c]));
}

function formatMarkdown(text) {
  if (!text) return "";
  let formatted = text
    .replace(/```(\w*)\n([\s\S]*?)```/g, (_m, _lang, code) => `<pre><code>${escapeHtml(code.trim())}</code></pre>`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>");
  
  // Wrap non-pre text into paragraphs
  const paragraphs = formatted.split("\n\n").map(p => {
    p = p.trim();
    if (p.startsWith("<pre>") || p.startsWith("<ul>") || p.startsWith("<ol>")) return p;
    return `<p>${p.replace(/\n/g, "<br>")}</p>`;
  });

  return paragraphs.join("");
}