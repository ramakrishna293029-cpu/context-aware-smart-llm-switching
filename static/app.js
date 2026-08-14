"use strict";

const $ = (id) => document.getElementById(id);

const history = [];
let lastRequestId = null;

/* ---------------- tabs ---------------- */
document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    $("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "dashboard") loadStats();
  });
});

/* ---------------- chat ---------------- */
function addMessage(role, html) {
  const wrap = document.createElement("div");
  wrap.className = "msg " + role;
  const bubble = document.createElement("div");
  bubble.className = "bubble";
  bubble.innerHTML = html;
  wrap.appendChild(bubble);
  $("messages").appendChild(wrap);
  $("messages").scrollTop = $("messages").scrollHeight;
  return bubble;
}

function renderMeta(data) {
  const m = data.model;
  $("model-badge").textContent = `${m.model_name} · ${m.provider}`;
  $("demo-tag").classList.toggle("hidden", !m.demo_mode);
  $("complexity-bar").style.width = `${m.analysis.complexity * 100}%`;
  $("complexity-val").textContent = m.analysis.complexity.toFixed(2);
  $("reasoning-val").textContent = m.analysis.reasoning_required;
  $("task-val").textContent = m.analysis.task_type;
  $("latency-val").textContent = `${data.latency_ms} ms`;
  $("tokens-val").textContent = `${data.input_tokens} / ${data.output_tokens}`;
  $("cost-val").textContent = `$${data.estimated_cost_usd.toFixed(6)}`;
  $("reason-text").textContent = m.reason;

  const scores = ["quality_suitability", "complexity_compatibility",
    "cost_efficiency", "latency_efficiency", "historical_performance"];
  $("scores").innerHTML =
    "<table class='score-table'>" +
    scores.map((k) =>
      `<tr><td>${k.replace(/_/g, " ")}</td><td>${m.scores[k].toFixed(3)}</td></tr>`
    ).join("") +
    `<tr><td><strong>total</strong></td><td><strong>${m.scores.total.toFixed(3)}</strong></td></tr>` +
    "</table>";

  $("signals").innerHTML =
    "<div class='signal-list'>" +
    m.analysis.signals.map((s) =>
      `<div class='signal-item'>▪ ${s.signal} — <em>${s.detail || ""}</em></div>`
    ).join("") +
    "</div>";

  $("meta-empty").classList.add("hidden");
  $("meta-card").classList.remove("hidden");
}

function attachFeedback(bubble, requestId) {
  const row = document.createElement("div");
  row.className = "feedback";
  row.innerHTML = `
    <button data-rating="1">👍 Good</button>
    <button data-rating="-1">👎 Poor</button>`;
  bubble.appendChild(row);
  row.querySelectorAll("button").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const rating = +btn.dataset.rating;
      const resp = await fetch("/api/feedback", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request_id: requestId, rating }),
      });
      if (resp.ok) {
        row.innerHTML = "<span class='thanks'>Thanks for your feedback!</span>";
      }
    });
  });
}

$("chat-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const query = $("query-input").value.trim();
  if (!query) return;

  $("query-input").value = "";
  $("send-btn").disabled = true;
  addMessage("user", escapeHtml(query));

  const typing = addMessage("assistant", "<em>Analyzing context and routing…</em>");
  try {
    const resp = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, history: history.slice(-10) }),
    });
    const data = await resp.json();
    if (!resp.ok) throw new Error(data.detail || "Request failed");

    typing.innerHTML = formatResponse(data.response) + "<br><br>";
    renderMeta(data);
    attachFeedback(typing, data.request_id);
    lastRequestId = data.request_id;
    history.push({ role: "user", content: query },
                 { role: "assistant", content: data.response });
  } catch (err) {
    typing.innerHTML = `<em>Error: ${escapeHtml(err.message)}</em>`;
  } finally {
    $("send-btn").disabled = false;
    $("query-input").focus();
  }
});

document.querySelectorAll(".chip").forEach((chip) => {
  chip.addEventListener("click", () => {
    $("query-input").value = chip.textContent;
    $("chat-form").requestSubmit();
  });
});

/* ---------------- rendering helpers ---------------- */
function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function formatResponse(text) {
  let out = escapeHtml(text);
  out = out.replace(/```(\w*)\n([\s\S]*?)```/g, (_m, lang, code) =>
    `<pre><code>${code.trim()}</code></pre>`);
  out = out.replace(/`([^`]+)`/g, "<code>$1</code>");
  out = out.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  out = out.replace(/\n{2,}/g, "<br><br>");
  return out;
}

/* ---------------- dashboard ---------------- */
async function loadStats() {
  $("dash-loading").classList.remove("hidden");
  $("dash").classList.add("hidden");
  try {
    const resp = await fetch("/api/stats");
    const s = await resp.json();

    $("d-total").textContent = s.total_requests;
    $("d-success").textContent = `${(s.success_rate * 100).toFixed(1)}%`;
    $("d-latency").textContent = `${s.average_latency_ms.toFixed(0)} ms`;
    $("d-cost").textContent = `$${s.total_estimated_cost_usd.toFixed(4)}`;
    $("d-savings").textContent = `${s.savings_percent.toFixed(1)}% ($${s.estimated_savings_usd.toFixed(4)})`;

    const maxModel = Math.max(...s.model_distribution.map((m) => m.count), 1);
    $("d-distribution").innerHTML = s.model_distribution.length
      ? s.model_distribution.map((m) => `
          <div class="bar-row">
            <span class="bar-label">${m.model}</span>
            <div class="meter-lg"><div class="meter-fill" style="width:${(m.count / maxModel) * 100}%"></div></div>
            <span class="mono">${m.count} (${((m.count / s.total_requests) * 100).toFixed(0)}%)</span>
          </div>`).join("")
      : "<p style='color:var(--muted)'>No requests yet.</p>";

    const maxCost = Math.max(s.baseline_cost_usd, s.total_estimated_cost_usd, 0.0001);
    $("d-baseline").style.width = `${(s.baseline_cost_usd / maxCost) * 100}%`;
    $("d-with").style.width = `${(s.total_estimated_cost_usd / maxCost) * 100}%`;
    $("d-baseline-val").textContent = `$${s.baseline_cost_usd.toFixed(4)}`;
    $("d-with-val").textContent = `$${s.total_estimated_cost_usd.toFixed(4)}`;

    const maxFb = Math.max(s.feedback_good, s.feedback_poor, 1);
    $("d-good").style.width = `${(s.feedback_good / maxFb) * 100}%`;
    $("d-poor").style.width = `${(s.feedback_poor / maxFb) * 100}%`;
    $("d-good-val").textContent = s.feedback_good;
    $("d-poor-val").textContent = s.feedback_poor;

    $("d-history").querySelector("tbody").innerHTML = s.recent_requests.map((r) => `
      <tr>
        <td>${escapeHtml(r.timestamp)}</td>
        <td title="${escapeHtml(r.query)}">${escapeHtml(r.query.slice(0, 42))}${r.query.length > 42 ? "…" : ""}</td>
        <td>${escapeHtml(r.task_type)}</td>
        <td class="mono">${r.complexity.toFixed(2)}</td>
        <td>${escapeHtml(r.selected_model)}</td>
        <td class="mono">${r.latency_ms.toFixed(0)} ms</td>
        <td class="mono">$${r.estimated_cost_usd.toFixed(6)}</td>
        <td class="${r.success ? "ok" : "bad"}">${r.success ? "✓" : "✗"}</td>
      </tr>`).join("");

    $("dash-loading").classList.add("hidden");
    $("dash").classList.remove("hidden");
  } catch (err) {
    $("dash-loading").textContent = "Failed to load analytics: " + err.message;
  }
}