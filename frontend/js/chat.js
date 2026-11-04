/**
 * @file chat.js
 * @description Context-Aware Smart LLM Switcher - Chat & Telemetry Viewport Module.
 * Implements Apple Design fluid spring physics, Claude Design precision data visualization,
 * and high-density Generative UI for intelligent LLM routing.
 *
 * Provides:
 * - Active session message timeline rendering with zero-state Welcome Hero.
 * - Right-aligned user prompt bubbles with OLED dark contrast & specular elevation.
 * - Left-aligned assistant cards with instant agentic telemetry HUD:
 *     * Tier badge with tier-specific pill colors (T1 emerald -> T6 rose, self, escalated)
 *     * Roundtrip & TTFT latency indicator
 *     * Cost in micro-dollars and USD with micro-dollar hover tooltip
 *     * Real-time routing confidence score
 *     * Token count (Prompt + Completion)
 *     * Savings percentage pill
 * - Collapsible reasoning/thinking accordion for Chain-of-Thought models (live streaming & static).
 * - Interactive expandable Decision Reasoning Drawer:
 *     * 3 Micro-meters (Complexity, Reasoning, Coding)
 *     * Stage Latency Waterfall (LinUCB zero-overhead telemetry)
 *     * LinUCB Contextual Bandit Telemetry strip & candidate scoreboard table
 *     * Routing rationale quote box
 * - Markdown code block chrome with macOS window controls, language badge, copy button, and syntax styling.
 * - User feedback thumbs up/down buttons wired to `/api/feedback` to train LinUCB rewards.
 */

// Helper: safe DOM selector
const $ = (id) => (typeof document !== "undefined" ? document.getElementById(id) : null);

/**
 * Escapes HTML characters to prevent XSS.
 * @param {string} str 
 * @returns {string}
 */
export function escapeHtml(str) {
  if (!str) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Normalizes any tier identifier string into a canonical 'tier_1' through 'tier_6' key.
 * @param {string} tier 
 * @returns {string}
 */
export function normalizeTierKey(tier) {
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
 * Parses markdown text into sanitized HTML with custom window chrome code blocks and copy triggers.
 * @param {string} text 
 * @returns {string}
 */
export function formatMarkdown(text) {
  if (!text) return "";
  try {
    if (typeof marked !== "undefined") {
      const renderer = new marked.Renderer();
      renderer.code = function (code, lang) {
        const language = (lang || "code").trim();
        let codeHtml = escapeHtml(code);

        // Highlight syntax if hljs is present in window
        if (typeof hljs !== "undefined" && language && language !== "code" && hljs.getLanguage && hljs.getLanguage(language)) {
          try {
            codeHtml = hljs.highlight(code, { language }).value;
          } catch (_) {}
        }

        return `<div class="code-block-wrap">
          <div class="code-block-header">
            <div class="code-header-left">
              <span class="window-dot red" title="Close"></span>
              <span class="window-dot yellow" title="Minimize"></span>
              <span class="window-dot green" title="Maximize"></span>
              <span class="code-lang-tag">${escapeHtml(language)}</span>
            </div>
            <button type="button" class="btn-copy-code" title="Copy code snippet">
              <svg class="icon-sym" aria-hidden="true"><use href="#i-copy"/></svg>
              <span>Copy</span>
            </button>
          </div>
          <pre class="code-block-pre"><code class="language-${escapeHtml(language)}">${codeHtml}</code></pre>
        </div>`;
      };

      marked.setOptions({
        renderer: renderer,
        gfm: true,
        breaks: true,
      });

      const rawHtml = marked.parse(text);
      if (typeof DOMPurify !== "undefined") {
        return DOMPurify.sanitize(rawHtml, {
          ADD_TAGS: ["use", "svg", "details", "summary"],
          ADD_ATTR: ["href", "target", "open"],
        });
      }
      return rawHtml;
    }
  } catch (e) {
    console.warn("[chat.js] Markdown parsing failed:", e);
  }
  return escapeHtml(text);
}

/**
 * Renders LaTeX mathematical formulas inside an element via KaTeX auto-render.
 * @param {HTMLElement} elem 
 */
export function _renderMathInElement(elem) {
  if (!elem) return;
  try {
    if (typeof renderMathInElement === "function") {
      renderMathInElement(elem, {
        delimiters: [
          { left: "$$", right: "$$", display: true },
          { left: "$", right: "$", display: false },
          { left: "\\[", right: "\\]", display: true },
          { left: "\\(", right: "\\)", display: false },
        ],
        throwOnError: false,
      });
    }
  } catch (e) {
    console.warn("[chat.js] KaTeX render failed:", e);
  }
}

/**
 * Smoothly scrolls the messages container to the bottom unless the user has manually scrolled up.
 * @param {HTMLElement} container 
 */
export function smoothScrollToBottom(container) {
  if (!container) return;
  const threshold = 48;
  const distFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
  if (distFromBottom > threshold) {
    if (typeof window !== "undefined") window.isUserScrolledUp = true;
    return;
  }
  if (typeof window !== "undefined") window.isUserScrolledUp = false;
  if (typeof container.scrollTo === "function") {
    container.scrollTo({
      top: container.scrollHeight,
      behavior: "smooth",
    });
  } else {
    container.scrollTop = container.scrollHeight;
  }
}

/**
 * Displays a non-intrusive ephemeral toast notification.
 * @param {string} message 
 * @param {"info"|"success"|"error"} type 
 */
export function showToast(message, type = "info") {
  if (typeof document === "undefined") return;
  let container = $("toast-container") || document.querySelector(".toast-container");
  if (!container) {
    container = document.createElement("div");
    container.id = "toast-container";
    container.className = "toast-container";
    document.body.appendChild(container);
  }

  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.setAttribute("role", "status");
  toast.setAttribute("aria-live", "polite");
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateY(10px)";
    toast.style.transition = "all 0.2s cubic-bezier(0.16, 1, 0.3, 1)";
    setTimeout(() => toast.remove(), 200);
  }, 2800);
}

/**
 * Attaches clipboard copy functionality to code blocks within an element.
 * @param {HTMLElement} scopeElem 
 */
function attachCodeBlockCopyHandlers(scopeElem) {
  if (!scopeElem) return;
  const copyButtons = scopeElem.querySelectorAll(".btn-copy-code");
  copyButtons.forEach((btn) => {
    btn.addEventListener("click", (e) => {
      e.stopPropagation();
      const wrap = btn.closest(".code-block-wrap");
      const codeElem = wrap ? wrap.querySelector("code") : null;
      const textToCopy = codeElem ? (codeElem.innerText || codeElem.textContent) : "";
      if (!textToCopy) return;

      const setSuccess = () => {
        const span = btn.querySelector("span");
        if (span) span.textContent = "Copied!";
        btn.classList.add("copied");
        setTimeout(() => {
          if (span) span.textContent = "Copy";
          btn.classList.remove("copied");
        }, 1800);
        showToast("Code copied to clipboard", "success");
      };

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(textToCopy).then(setSuccess).catch(() => {
          fallbackClipboardCopy(textToCopy, setSuccess);
        });
      } else {
        fallbackClipboardCopy(textToCopy, setSuccess);
      }
    });
  });
}

/**
 * Fallback copy using hidden textarea for legacy or restricted contexts.
 * @param {string} text 
 * @param {Function} onSuccess 
 */
function fallbackClipboardCopy(text, onSuccess) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand("copy");
    if (typeof onSuccess === "function") onSuccess();
  } catch (_) {
    showToast("Failed to copy text", "error");
  }
  document.body.removeChild(ta);
}

/**
 * Updates the context turn counter badge in the interface.
 * @param {Object} session 
 */
function updateContextCounter(session) {
  const active = session || (typeof window !== "undefined" && window.sessionManager ? window.sessionManager.getActive() : null);
  const count = active && Array.isArray(active.messages) ? active.messages.length : 0;
  const badge = $("context-turn-count");
  if (badge) {
    badge.textContent = count.toString();
  }
}

/**
 * Renders all messages for the active conversation session.
 * Displays the zero-state Welcome Hero when the active session is empty.
 *
 * @param {Object} [sessionMgr=null] - SessionManager instance
 */
export function renderActiveSessionMessages(sessionMgr = null) {
  const container = $("chat-messages");
  if (!container) return;

  const mgr = sessionMgr || (typeof window !== "undefined" ? window.sessionManager : null);
  const active = mgr ? mgr.getActive() : null;

  if (typeof window !== "undefined" && typeof window.updateActiveSessionHeader === "function") {
    window.updateActiveSessionHeader();
  }
  updateContextCounter(active);

  // Zero-State: Welcome Hero with Architectural Routing Scenarios
  if (!active || !Array.isArray(active.messages) || active.messages.length === 0) {
    container.innerHTML = `
      <div class="welcome-hero" id="welcome-hero">
        <div class="welcome-eyebrow-badge">
          <span class="badge-dot"></span>
          <span>✦ Intelligent LLM Router</span>
        </div>
        <h2 class="welcome-title">Where intelligence meets cost efficiency.</h2>
        <p class="welcome-subtitle">
          Autonomous multi-model routing across 6 specialized tiers. Queries are evaluated by a Contextual Bandit router to select the optimal model for speed, intelligence, and price.
        </p>

        <div class="welcome-prompts-grid" id="welcome-quick-chips">
          
          <!-- SCENARIO CARD 1: T1 ROUTINE DIRECTIVE -->
          <button type="button" class="welcome-prompt-card quick-chip-card" data-query="Summarize the primary benefits of semantic caching in 2 bullet points.">
            <div class="welcome-prompt-header">
              <span class="welcome-prompt-icon">⚡</span>
              <span class="welcome-prompt-title">Fast Caching</span>
              <span class="node-tier-pill t1" style="margin-left:auto; font-size:10.5px; padding:2px 7px; border-radius:9999px; background:rgba(16,185,129,0.12); color:#10B981; border:1px solid rgba(16,185,129,0.25); font-family:var(--font-mono, monospace);">Tier 1</span>
            </div>
            <div class="welcome-prompt-desc" style="font-size:12.5px; color:var(--text-secondary); line-height:1.45; margin-top:4px;">
              Summarize the primary benefits of semantic caching in 2 bullet points.
            </div>
          </button>

          <!-- SCENARIO CARD 2: T3 BALANCED SYNTHESIS -->
          <button type="button" class="welcome-prompt-card quick-chip-card" data-query="Compare relational databases and document stores for high-throughput write workloads.">
            <div class="welcome-prompt-header">
              <span class="welcome-prompt-icon">⚖️</span>
              <span class="welcome-prompt-title">Database Workloads</span>
              <span class="node-tier-pill t3" style="margin-left:auto; font-size:10.5px; padding:2px 7px; border-radius:9999px; background:rgba(56,189,248,0.12); color:#38BDF8; border:1px solid rgba(56,189,248,0.25); font-family:var(--font-mono, monospace);">Tier 3</span>
            </div>
            <div class="welcome-prompt-desc" style="font-size:12.5px; color:var(--text-secondary); line-height:1.45; margin-top:4px;">
              Compare relational databases and document stores for high-throughput write workloads.
            </div>
          </button>

          <!-- SCENARIO CARD 3: T4 CODING SPECIALIST -->
          <button type="button" class="welcome-prompt-card quick-chip-card" data-query="Write a thread-safe Python implementation of an LRU Cache with TTL expiration.">
            <div class="welcome-prompt-header">
              <span class="welcome-prompt-icon">🐍</span>
              <span class="welcome-prompt-title">Thread-Safe LRU</span>
              <span class="node-tier-pill t4" style="margin-left:auto; font-size:10.5px; padding:2px 7px; border-radius:9999px; background:rgba(139,92,246,0.12); color:#A78BFA; border:1px solid rgba(139,92,246,0.25); font-family:var(--font-mono, monospace);">Tier 4</span>
            </div>
            <div class="welcome-prompt-desc" style="font-size:12.5px; color:var(--text-secondary); line-height:1.45; margin-top:4px;">
              Write a thread-safe Python implementation of an LRU Cache with TTL expiration.
            </div>
          </button>

          <!-- SCENARIO CARD 4: T5 DEEP REASONING -->
          <button type="button" class="welcome-prompt-card quick-chip-card" data-query="Prove that the square root of 2 is irrational and analyze its algebraic implications.">
            <div class="welcome-prompt-header">
              <span class="welcome-prompt-icon">📐</span>
              <span class="welcome-prompt-title">Mathematical Proof</span>
              <span class="node-tier-pill t5" style="margin-left:auto; font-size:10.5px; padding:2px 7px; border-radius:9999px; background:rgba(245,158,11,0.12); color:#FBBF24; border:1px solid rgba(245,158,11,0.25); font-family:var(--font-mono, monospace);">Tier 5</span>
            </div>
            <div class="welcome-prompt-desc" style="font-size:12.5px; color:var(--text-secondary); line-height:1.45; margin-top:4px;">
              Prove that the square root of 2 is irrational and analyze its algebraic implications.
            </div>
          </button>
        </div>
      </div>
    `;

    // Attach click listeners to quick chip cards
    container.querySelectorAll(".quick-chip-card, .welcome-prompt-card").forEach((chip) => {
      chip.addEventListener("click", () => {
        const query = chip.dataset.query;
        const input = $("query-input");
        if (input && query) {
          input.value = query;
          input.style.height = "auto";
          input.style.height = Math.min(input.scrollHeight, 180) + "px";
          input.focus();
          const form = $("composer-form");
          if (form) {
            if (typeof form.requestSubmit === "function") {
              form.requestSubmit();
            } else {
              form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
            }
          }
        }
      });
    });
    return;
  }

  // Populate active conversation turns
  container.innerHTML = "";
  active.messages.forEach((msg) => {
    if (msg.role === "user") {
      appendUserMessageToUI(msg.content, false);
    } else if (msg.role === "assistant") {
      appendAssistantResponseToUI(msg.meta?.query || "", msg.content, msg.meta || {}, false);
    }
  });

  smoothScrollToBottom(container);
}

/**
 * Appends a user prompt message bubble to the chat container.
 *
 * @param {string} content - Raw user query text
 * @param {boolean} [shouldScroll=true] - Whether to smooth scroll to bottom
 */
export function appendUserMessageToUI(content, shouldScroll = true) {
  const container = $("chat-messages");
  if (!container) return;

  const welcomeHero = $("welcome-hero");
  if (welcomeHero) {
    welcomeHero.remove();
  }

  const msgEl = document.createElement("div");
  msgEl.className = "chat-msg user";
  msgEl.innerHTML = `<div class="user-bubble">${escapeHtml(content)}</div>`;
  container.appendChild(msgEl);

  if (shouldScroll) {
    smoothScrollToBottom(container);
  }
}

/**
 * Creates and mounts a live streaming card placeholder with an Apple fluid pulse dot.
 * Returns an interface for streaming token updates, live reasoning deltas, analyzer telemetry, and finalization.
 *
 * @param {string} [initialQuery=""] - Original user prompt
 * @returns {Object} Streaming controller object
 */
export function createStreamingPlaceholder(initialQuery = "") {
  const container = $("chat-messages");
  const cardId = "stream_" + Date.now() + "_" + Math.random().toString(36).substring(2, 6);

  const msgEl = document.createElement("div");
  msgEl.className = "chat-msg assistant";
  msgEl.id = cardId;

  msgEl.innerHTML = `
    <div class="msg-avatar">
      <svg class="icon-sym" aria-hidden="true"><use href="#i-node-switch"/></svg>
    </div>
    <div class="msg-content-wrap">
      <div class="assistant-card">
        
        <!-- Live Monospace Streaming Trace -->
        <div class="agentic-trace-stream" id="${cardId}_trace">
          <span class="trace-pulse-dot"></span>
          <span class="trace-text" id="${cardId}_tracetext">Routing via Gemini 3.5 Flash-Lite · Evaluating prompt complexity...</span>
        </div>

        <!-- Hidden compatibility hooks -->
        <span id="${cardId}_tier" style="display:none;"></span>
        <span id="${cardId}_model" style="display:none;"></span>
        <span id="${cardId}_lat" style="display:none;"></span>

        <div class="msg-text-body" id="${cardId}_body">
          <span style="color:var(--text-muted);font-style:italic;">Routing query across calibrated model tiers...</span>
        </div>

      </div>
    </div>
  `;

  if (container) {
    container.appendChild(msgEl);
    smoothScrollToBottom(container);
  }

  const bodyEl = $(`${cardId}_body`);
  let currentText = "";
  let currentReasoning = "";
  let reasoningStartTime = 0;
  let routingMeta = {};
  let userPrompt = initialQuery;

  const finishCoT = () => {
    const thoughtAccordion = $(`${cardId}_thought`);
    if (thoughtAccordion && thoughtAccordion.classList.contains("streaming")) {
      const elapsedSec = reasoningStartTime > 0 ? ((Date.now() - reasoningStartTime) / 1000).toFixed(1) : "0.5";
      const status = thoughtAccordion.querySelector(".thought-status");
      const badge = thoughtAccordion.querySelector(".thought-badge");
      if (status) status.textContent = `Thought for ${elapsedSec}s`;
      if (badge) badge.textContent = "CoT Completed";
      thoughtAccordion.classList.remove("streaming");
    }
  };

  return {
    card: msgEl,
    element: msgEl,
    contentBody: bodyEl,
    setQuery: (q) => {
      userPrompt = q;
    },
    updateAnalyzer: (info) => {
      if (info) routingMeta.analyzer = info;
      const isSelf = info && info.answer_mode === "self";
      const tracetext = $(`${cardId}_tracetext`);
      if (tracetext) {
        if (isSelf) {
          tracetext.textContent = "[⚡ SELF-ANSWER] Gemini 3.5 Flash-Lite · Direct single-pass resolution";
        } else {
          const tierNorm = normalizeTierKey(info?.target_tier || info?.required_capability || "tier_1").toUpperCase();
          const compScore = (info?.complexity_score ?? 0.5).toFixed(2);
          const task = (info?.task_type || "general").toUpperCase();
          tracetext.textContent = `Routing via Gemini 3.5 Flash-Lite → Escalated to ${tierNorm} · Complexity ${compScore} · ${task}`;
        }
      }
    },
    updateRouting: (route) => {
      if (route) routingMeta = { ...routingMeta, ...route };
      const tracetext = $(`${cardId}_tracetext`);
      if (tracetext && route) {
        const tierNorm = normalizeTierKey(route.target_tier || "tier_1").toUpperCase();
        const modelName = route.target_name || route.target_model || "Target Model";
        tracetext.textContent = `Routing via Gemini 3.5 Flash-Lite → Switched to ${tierNorm} (${modelName}) · Streaming response...`;
      }
    },
    appendReasoningDelta: (reasoning) => {
      if (!reasoning) return;
      if (reasoningStartTime === 0) {
        reasoningStartTime = Date.now();
      }
      currentReasoning = reasoning;
      let thoughtAccordion = $(`${cardId}_thought`);
      const body = $(`${cardId}_body`);
      if (!thoughtAccordion && body) {
        thoughtAccordion = document.createElement("details");
        thoughtAccordion.className = "thought-accordion streaming";
        thoughtAccordion.id = `${cardId}_thought`;
        thoughtAccordion.open = true;
        thoughtAccordion.innerHTML = `
          <summary class="thought-header">
            <div class="thought-header-left">
              <span class="thought-icon-pulse">🧠</span>
              <span class="thought-title">Chain-of-Thought Reasoning</span>
              <span class="thought-badge">Live Reasoning</span>
            </div>
            <span class="thought-status">Generating thoughts...</span>
          </summary>
          <div class="thought-body" id="${cardId}_thought_body"></div>
        `;
        body.parentNode.insertBefore(thoughtAccordion, body);
      }
      const thoughtBody = $(`${cardId}_thought_body`);
      if (thoughtBody) {
        thoughtBody.innerHTML = formatMarkdown(reasoning);
        _renderMathInElement(thoughtBody);
        attachCodeBlockCopyHandlers(thoughtBody);
      }
      if (container) smoothScrollToBottom(container);
    },
    startResponse: () => {
      finishCoT();
      const body = $(`${cardId}_body`);
      if (body) body.innerHTML = '<span class="typing-cursor"></span>';
    },
    appendDelta: (text) => {
      finishCoT();
      currentText = text;
      const body = $(`${cardId}_body`);
      if (body) {
        body.innerHTML = formatMarkdown(text) + '<span class="typing-cursor"></span>';
        _renderMathInElement(body);
        attachCodeBlockCopyHandlers(body);
      }
      if (container) smoothScrollToBottom(container);
    },
    finalize: (finalData) => {
      finishCoT();
      const merged = { ...(routingMeta || {}), ...(finalData || {}) };
      if (!merged.reasoning && currentReasoning) {
        merged.reasoning = currentReasoning;
      }
      const finalCard = buildAssistantCardElement(userPrompt, currentText, merged);
      if (msgEl.parentNode) {
        msgEl.replaceWith(finalCard);
      } else if (container) {
        container.appendChild(finalCard);
      }
      if (container) smoothScrollToBottom(container);
      return finalCard;
    },
    showError: (err) => {
      finishCoT();
      const body = $(`${cardId}_body`);
      if (body) {
        body.innerHTML = `
          <div style="padding:10px 14px;background:rgba(244,63,94,0.08);border:1px solid rgba(244,63,94,0.25);border-radius:8px;color:var(--signal-rose, #F43F5E);font-size:13px;display:flex;align-items:center;gap:8px;">
            <span>⚠️</span>
            <span>${escapeHtml(err || "Stream connection failed")}</span>
          </div>`;
      }
    },
    showStoppedState: (text) => {
      finishCoT();
      const body = $(`${cardId}_body`);
      if (body && text) {
        body.innerHTML = formatMarkdown(text) + `
          <div class="generation-stopped-notice">
            <svg class="icon-sym" aria-hidden="true"><use href="#i-stop"/></svg>
            <span>Generation stopped by user</span>
          </div>`;
        _renderMathInElement(body);
        attachCodeBlockCopyHandlers(body);
      }
      const tracetext = $(`${cardId}_tracetext`);
      if (tracetext) {
        tracetext.textContent = "Generation halted by user";
      }
    },
  };
}

/**
 * Builds the complete assistant response card element with:
 * - One-Line Agentic Telemetry Bar (Tier, model, latency, tokens, cost, confidence score, savings pill, trace toggle)
 * - Collapsible reasoning/thinking accordion for Chain-of-Thought models
 * - Expandable Decision Reasoning Drawer (3 micro-meters, stage latency waterfall, LinUCB stats & scoreboard, quote box)
 * - Markdown answer typography with copyable code blocks & KaTeX math formulas
 * - Action footer (copy, inspector, feedback thumbs wired to /api/feedback)
 *
 * @param {string} query - Original user prompt
 * @param {string} text - Final assistant response markdown text
 * @param {Object} [data={}] - Response telemetry data
 * @returns {HTMLElement} Assistant message element
 */
export function buildAssistantCardElement(query, text, data = {}) {
  const msgEl = document.createElement("div");
  msgEl.className = "chat-msg assistant";
  const drawerId = "drawer_" + (data.request_id || Date.now() + "_" + Math.random().toString(36).substring(2, 6));

  const analyzer = data.analyzer || {};
  const model = data.model || {};

  const isSelf = Boolean(data.answer_mode === "self" || analyzer.answer_mode === "self");
  const taskType = analyzer.task_type || data.task_type || "general";
  const complexity = analyzer.complexity || data.complexity || "medium";
  const complexityScore = analyzer.complexity_score ?? data.complexity_score ?? 0.5;
  const servedTierNorm = normalizeTierKey(data.tier || model.tier || analyzer.required_capability || "tier_1");
  const targetModelName = model.model_name || model.model_id || data.selected_model || "Gemini Flash";
  const shortModel = (targetModelName || "").split(" ")[0].replace(/^[a-z0-9_-]+\//i, "");
  const routingReason = data.routing_reason || analyzer.reason || model.reason || "Cost-optimal model selection";

  const isEscalated = Boolean(data.escalation_used || data.escalated);

  const costNumber = data.total_cost_usd != null ? data.total_cost_usd : (data.estimated_cost_usd || 0.0);
  const costStr = `$${costNumber.toFixed(6)}`;
  const microDollars = (costNumber * 1000000).toFixed(1);
  const latencyNumber = data.total_latency_ms != null ? data.total_latency_ms : (data.latency_ms || 0.0);
  const ttftNumber = Number(data.ttft_ms || 0);

  const inTok = data.input_tokens != null ? data.input_tokens : (data.usage?.prompt_tokens ?? (isSelf ? 120 : 380));
  const outTok = data.output_tokens != null ? data.output_tokens : (data.usage?.completion_tokens ?? (isSelf ? 85 : 420));
  const savingsPct = data.savings_percent != null && data.savings_percent > 0 ? `${data.savings_percent.toFixed(1)}%` : null;

  // Candidate Factor Analysis
  const selectedCandidate = Array.isArray(data.candidates) ? data.candidates.find((c) => c.selected) : null;
  const reasoningScore = selectedCandidate?.factors?.reasoning_compatibility != null
    ? selectedCandidate.factors.reasoning_compatibility
    : (analyzer.reasoning_required ? 0.95 : (complexityScore > 0.6 ? 0.80 : 0.25));
  const codingScore = selectedCandidate?.factors?.coding_compatibility != null
    ? selectedCandidate.factors.coding_compatibility
    : (taskType === "coding" || analyzer.coding_required ? 0.95 : 0.15);

  const pComp = Math.min(100, Math.max(5, Math.round(complexityScore * 100)));
  const pReason = Math.min(100, Math.max(5, Math.round(reasoningScore * 100)));
  const pCode = Math.min(100, Math.max(5, Math.round(codingScore * 100)));

  // Routing Confidence calculation
  let confidenceVal = 0.94;
  if (typeof data.confidence === "number") {
    confidenceVal = data.confidence;
  } else if (selectedCandidate && typeof selectedCandidate.total === "number") {
    confidenceVal = Math.min(0.99, Math.max(0.60, selectedCandidate.total));
  } else if (data.bandit_score != null) {
    confidenceVal = Math.min(0.99, Math.max(0.60, data.bandit_score));
  } else if (data.expected_reward != null) {
    confidenceVal = Math.min(0.99, Math.max(0.60, data.expected_reward));
  } else if (data.uncertainty != null) {
    confidenceVal = Math.min(0.99, Math.max(0.60, 1.0 - Math.min(0.35, data.uncertainty)));
  } else {
    confidenceVal = Number((0.90 + (1.0 - complexityScore) * 0.08).toFixed(2));
  }
  const confPercent = Math.round(confidenceVal * 100);

  // Stage Latency Waterfall (LinUCB Architecture)
  const routerLat = Number(data.routing_latency_ms || 1.2);
  const prepLat = ttftNumber > 0 ? Math.max(5, ttftNumber - routerLat) : (isSelf ? 0.5 : 25);
  const genLat = isSelf ? 0 : Math.max(10, Number(data.latency_ms || Math.max(0, latencyNumber - routerLat - prepLat)));
  const verifLat = Number(data.verification_latency_ms || 0.5);

  const totalStages = Math.max(1, routerLat + prepLat + genLat + verifLat);
  const pRouter = Math.max(2, (routerLat / totalStages) * 100).toFixed(1);
  const pPrep = Math.max(2, (prepLat / totalStages) * 100).toFixed(1);
  const pGen = Math.max(5, (genLat / totalStages) * 100).toFixed(1);
  const pVerif = Math.max(1, (verifLat / totalStages) * 100).toFixed(1);

  // LinUCB Contextual Bandit Telemetry Strip & Candidate Arm Scoreboard
  const banditScore = data.bandit_score != null ? data.bandit_score : null;
  const expReward = data.expected_reward != null ? data.expected_reward : null;
  const uncertainty = data.uncertainty != null ? data.uncertainty : null;
  const rewardVal = data.reward != null ? data.reward : null;
  const scoresObj = data.scores || {};
  const scoreEntries = Object.entries(scoresObj);

  let linucbScoreboardRows = "";
  if (scoreEntries.length > 0) {
    scoreEntries.sort((a, b) => (b[1].ucb_score || 0) - (a[1].ucb_score || 0));
    const selectedArmId = data.selected_model || data.model?.model_id || "";
    linucbScoreboardRows = scoreEntries
      .map(([armId, s]) => {
        const isWinner = armId === selectedArmId || data.model?.model_id === armId || data.model?.endpoint_model === armId;
        return `
          <tr class="${isWinner ? "selected" : ""}">
            <td><strong>${escapeHtml(armId)}</strong></td>
            <td style="color:#38BDF8; font-weight:600;">${s.ucb_score != null ? s.ucb_score.toFixed(4) : "—"}</td>
            <td style="color:#34D399;">${s.expected_reward != null ? s.expected_reward.toFixed(4) : "—"}</td>
            <td style="color:#FBBF24;">${s.uncertainty != null ? s.uncertainty.toFixed(4) : "—"}</td>
            <td>${s.pull_count != null ? s.pull_count : 0}</td>
            <td>${isWinner ? '<span class="status-pill status-pill-active" style="background:rgba(56,189,248,0.2); color:#38BDF8; padding:2px 6px; border-radius:9999px; font-size:10px;">✓ Selected</span>' : '<span style="color:var(--text-muted);">—</span>'}</td>
          </tr>
        `;
      })
      .join("");
  }

  // Tier Badge Class & Label
  const tierClass = isSelf ? "self" : isEscalated ? "escalated" : servedTierNorm.replace("_", "-");
  const tierBadgeLabel = isSelf ? "SELF" : isEscalated ? "⚡ ESCALATED" : servedTierNorm.replace("_", " ").toUpperCase();

  // Chain-of-Thought Reasoning content check
  const reasoningContent = data.reasoning || data.thinking || data.reasoning_content || data.thought || data.meta?.reasoning || "";
  const hasReasoning = Boolean(reasoningContent && reasoningContent.trim().length > 0);

  // Existing user feedback status
  const existingFeedback = data.feedback != null ? Number(data.feedback) : null;

  // Construct Assistant Card DOM
  msgEl.innerHTML = `
    <div class="msg-avatar">
      <svg class="icon-sym" aria-hidden="true"><use href="#i-node-switch"/></svg>
    </div>
    <div class="msg-content-wrap">
      <div class="assistant-card">
        
        <!-- One-Line Agentic Telemetry HUD -->
        <div class="agentic-telemetry-bar" data-action="toggle-drawer" data-target="${drawerId}">
          <div class="telemetry-bar-left">
            <span class="telemetry-badge-tier ${tierClass}">
              ${tierBadgeLabel}
            </span>
            <span class="routing-model-name">${escapeHtml(shortModel)}</span>
            <span class="telemetry-sep">·</span>
            <span class="telemetry-stat" title="Roundtrip Latency: ${latencyNumber.toFixed(1)}ms · TTFT: ${ttftNumber}ms">${Math.round(latencyNumber)}ms</span>
            <span class="telemetry-sep">·</span>
            <span class="telemetry-stat" title="Prompt: ${inTok} tok · Output: ${outTok} tok">${inTok + outTok} tok</span>
            <span class="telemetry-sep">·</span>
            <span class="telemetry-stat telemetry-cost" title="${microDollars} µ$ micro-dollars (${costStr})">${costStr}</span>
            <span class="telemetry-sep">·</span>
            <span class="telemetry-stat telemetry-conf" title="Routing Confidence: ${confidenceVal.toFixed(4)}">${confPercent}% conf</span>
            ${savingsPct ? `<span class="savings-pill">+${savingsPct}</span>` : ""}
          </div>
          <button type="button" class="btn-inspect-drawer" data-action="toggle-drawer" data-target="${drawerId}" title="Inspect Decision Trace">
            <span>Trace</span>
            <span class="drawer-arrow">▾</span>
          </button>
        </div>

        <!-- Expandable Decision Reasoning Drawer -->
        <div class="routing-drawer" id="${drawerId}">
          <div class="routing-drawer-content hidden" id="${drawerId}_content">
            
            <!-- 3 Horizontal Micro-Meters -->
            <div class="drawer-meters-row">
              <div class="micro-meter">
                <div class="meter-head">
                  <span>Complexity</span>
                  <span class="mono">${complexityScore.toFixed(2)} (${complexity.toUpperCase()})</span>
                </div>
                <div class="meter-bar">
                  <div class="meter-fill ${complexityScore > 0.7 ? "amber" : "indigo"}" style="width: ${pComp}%;"></div>
                </div>
              </div>

              <div class="micro-meter">
                <div class="meter-head">
                  <span>Reasoning</span>
                  <span class="mono">${reasoningScore.toFixed(2)}</span>
                </div>
                <div class="meter-bar">
                  <div class="meter-fill indigo" style="width: ${pReason}%;"></div>
                </div>
              </div>

              <div class="micro-meter">
                <div class="meter-head">
                  <span>Coding</span>
                  <span class="mono">${codingScore.toFixed(2)}</span>
                </div>
                <div class="meter-bar">
                  <div class="meter-fill emerald" style="width: ${pCode}%;"></div>
                </div>
              </div>
            </div>

            <!-- Stage Latency Waterfall (LinUCB Architecture) -->
            <div class="waterfall-section">
              <div class="waterfall-header">Stage Latency Waterfall</div>
              <div class="waterfall-bar">
                <div class="wf-seg router" style="width: ${pRouter}%;" title="LinUCB Routing: ${routerLat.toFixed(1)}ms"></div>
                <div class="wf-seg prep" style="width: ${pPrep}%;" title="TTFT / Prep: ${Math.round(prepLat)}ms">${Math.round(prepLat)}ms</div>
                <div class="wf-seg generation" style="width: ${pGen}%;" title="Generation: ${Math.round(genLat)}ms">${Math.round(genLat)}ms</div>
                <div class="wf-seg verification" style="width: ${pVerif}%;" title="Verification: ${verifLat.toFixed(1)}ms"></div>
              </div>
              <div class="waterfall-legend">
                <span style="color:#8B5CF6;">⚡ LinUCB Routing: ${routerLat.toFixed(1)}ms</span>
                <span style="color:#94A3B8;">⏱ Prep: ${Math.round(prepLat)}ms</span>
                <span style="color:var(--signal-indigo, #6366F1);">💬 Gen: ${Math.round(genLat)}ms</span>
                <span style="color:var(--signal-emerald, #30D158);">✓ Verif: ${verifLat.toFixed(1)}ms</span>
              </div>
            </div>

            <!-- LinUCB Contextual Bandit Telemetry Box -->
            <div class="linucb-drawer-box">
              <div class="linucb-drawer-head">
                <div class="linucb-drawer-title">
                  ⚡ LinUCB Contextual Bandit Routing
                </div>
                <div class="linucb-arm-selected">
                  Selected Arm: <strong>${escapeHtml(data.selected_model || targetModelName)}</strong>
                </div>
              </div>

              <!-- 4-Stat Metric Strip -->
              <div class="linucb-strip-grid">
                <div class="linucb-stat-card">
                  <div class="linucb-stat-label">UCB Score</div>
                  <div class="linucb-stat-val" style="color:#38BDF8;">
                    ${banditScore != null ? banditScore.toFixed(4) : selectedCandidate ? selectedCandidate.total?.toFixed(4) ?? "—" : "—"}
                  </div>
                </div>
                <div class="linucb-stat-card">
                  <div class="linucb-stat-label">Exploitation (θ̂ᵀx)</div>
                  <div class="linucb-stat-val" style="color:#34D399;">
                    ${expReward != null ? expReward.toFixed(4) : "—"}
                  </div>
                </div>
                <div class="linucb-stat-card">
                  <div class="linucb-stat-label">Exploration (α·σ)</div>
                  <div class="linucb-stat-val" style="color:#FBBF24;">
                    ${uncertainty != null ? uncertainty.toFixed(4) : "—"}
                  </div>
                </div>
                <div class="linucb-stat-card">
                  <div class="linucb-stat-label">Reward (R)</div>
                  <div class="linucb-stat-val" style="color:${rewardVal != null && rewardVal >= 0 ? "#4ADE80" : "#F87171"};">
                    ${rewardVal != null ? (rewardVal >= 0 ? "+" : "") + rewardVal.toFixed(4) : "—"}
                  </div>
                </div>
              </div>

              <!-- Candidate Arm Scoreboard Table -->
              ${linucbScoreboardRows ? `
                <div class="waterfall-header" style="margin-bottom:6px; font-size:10.5px;">LinUCB Candidate Arm Scoreboard</div>
                <div class="scoreboard-table-wrap">
                  <table class="scoreboard-table">
                    <thead>
                      <tr>
                        <th>Arm / Model ID</th>
                        <th>UCB Score</th>
                        <th>Exploitation (θ̂ᵀx)</th>
                        <th>Exploration (α·σ)</th>
                        <th>Pulls</th>
                        <th>Status</th>
                      </tr>
                    </thead>
                    <tbody>${linucbScoreboardRows}</tbody>
                  </table>
                </div>
              ` : ""}
            </div>

            <!-- Decision Rationale Quote Box -->
            <div class="drawer-rationale-quote">
              <span class="rationale-label">ROUTING RATIONALE</span>
              "${escapeHtml(routingReason)}"
            </div>

          </div>
        </div>

        <!-- Collapsible Reasoning / Thinking Accordion (Chain-of-Thought Models) -->
        ${hasReasoning ? `
          <details class="thought-accordion">
            <summary class="thought-header">
              <div class="thought-header-left">
                <span class="thought-icon">🧠</span>
                <span class="thought-title">Chain-of-Thought Reasoning</span>
                <span class="thought-badge">${escapeHtml(shortModel)} CoT</span>
              </div>
              <span class="thought-meta">${Math.round(reasoningContent.length / 4)} tokens · Expand to view</span>
            </summary>
            <div class="thought-body">
              ${formatMarkdown(reasoningContent)}
            </div>
          </details>
        ` : ""}

        <!-- Assistant Markdown Answer -->
        <div class="msg-text-body">
          ${formatMarkdown(text)}
        </div>

        <!-- Telemetry Actions Bar -->
        <div class="telemetry-footer">
          <div class="telemetry-actions">
            <button type="button" class="btn-icon-action" data-action="copy-message" data-text="${escapeHtml(text)}" title="Copy Response">
              <svg class="icon-sym" aria-hidden="true"><use href="#i-copy"/></svg>
              <span>Copy Answer</span>
            </button>
            ${data.request_id ? `
              <button type="button" class="btn-icon-action" data-action="open-inspector" data-id="${data.request_id}" title="Inspect Full Telemetry">
                <svg class="icon-sym" aria-hidden="true"><use href="#i-search"/></svg>
                <span>Inspect</span>
              </button>
              <button 
                type="button" 
                class="btn-icon-action btn-thumb-up ${existingFeedback === 1 ? "active-feedback thumb-up" : ""}" 
                data-action="feedback" 
                data-id="${data.request_id}" 
                data-rating="1" 
                title="Helpful Response (+1.0 LinUCB Reward)"
              >
                <svg class="icon-sym" aria-hidden="true"><use href="#i-thumb-up"/></svg>
              </button>
              <button 
                type="button" 
                class="btn-icon-action btn-thumb-down ${existingFeedback === -1 ? "active-feedback thumb-down" : ""}" 
                data-action="feedback" 
                data-id="${data.request_id}" 
                data-rating="-1" 
                title="Poor Response (-1.0 LinUCB Penalty)"
              >
                <svg class="icon-sym" aria-hidden="true"><use href="#i-thumb-down"/></svg>
              </button>
            ` : ""}
          </div>
        </div>

      </div>
    </div>
  `;

  // Drawer Toggle Handlers (Handles clicking anywhere on telemetry bar or inspect button)
  const drawerContent = msgEl.querySelector(`#${drawerId}_content`);
  const arrow = msgEl.querySelector(".drawer-arrow");

  msgEl.querySelectorAll(`[data-target="${drawerId}"]`).forEach((toggleTarget) => {
    toggleTarget.addEventListener("click", (e) => {
      // Don't toggle if clicking an inner interactive button that isn't the toggle target
      if (
        e.target.closest("button") &&
        e.target.closest("button") !== toggleTarget &&
        !toggleTarget.classList.contains("btn-inspect-drawer")
      ) {
        return;
      }
      if (!drawerContent) return;
      const isHidden = drawerContent.classList.toggle("hidden");
      if (arrow) {
        arrow.textContent = isHidden ? "▾" : "▴";
        arrow.classList.toggle("open", !isHidden);
      }
    });
  });

  // Action Button Handlers (Copy, Feedback, Inspector)
  msgEl.querySelectorAll("[data-action]").forEach((btn) => {
    const act = btn.dataset.action;
    if (act === "copy-message") {
      btn.addEventListener("click", () => {
        const textToCopy = btn.dataset.text || text;
        const setCopied = () => {
          const span = btn.querySelector("span");
          if (span) span.textContent = "Copied!";
          setTimeout(() => {
            if (span) span.textContent = "Copy Answer";
          }, 1800);
          showToast("Answer copied to clipboard", "success");
        };

        if (navigator.clipboard && navigator.clipboard.writeText) {
          navigator.clipboard.writeText(textToCopy).then(setCopied).catch(() => {
            fallbackClipboardCopy(textToCopy, setCopied);
          });
        } else {
          fallbackClipboardCopy(textToCopy, setCopied);
        }
      });
    } else if (act === "open-inspector") {
      btn.addEventListener("click", () => {
        if (typeof window !== "undefined" && typeof window.openInspectorModal === "function") {
          window.openInspectorModal(btn.dataset.id);
        } else {
          showToast(`Inspector for #${btn.dataset.id}`, "info");
        }
      });
    } else if (act === "feedback") {
      btn.addEventListener("click", async () => {
        const reqId = parseInt(btn.dataset.id, 10);
        const rating = parseInt(btn.dataset.rating, 10);

        try {
          const fetchFn = typeof window !== "undefined" && typeof window.apiFetch === "function" ? window.apiFetch : fetch;
          const resp = await fetchFn("/api/feedback", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ request_id: reqId, rating: rating }),
          });

          if (resp && resp.ok) {
            // Update UI state for buttons
            const parent = btn.closest(".telemetry-actions");
            if (parent) {
              parent.querySelectorAll("[data-action='feedback']").forEach((b) => {
                b.classList.remove("active-feedback", "thumb-up", "thumb-down");
              });
            }
            btn.classList.add("active-feedback", rating === 1 ? "thumb-up" : "thumb-down");

            // Persist feedback to active session in sessionManager
            if (typeof window !== "undefined" && window.sessionManager) {
              const active = window.sessionManager.getActive();
              if (active && Array.isArray(active.messages)) {
                const targetMsg = active.messages.find((m) => m.meta && m.meta.request_id === reqId);
                if (targetMsg) {
                  targetMsg.meta.feedback = rating;
                  window.sessionManager.save();
                }
              }
            }

            const rewardMsg = rating === 1 ? "+1.0 reward trained to LinUCB arm" : "-1.0 penalty applied to LinUCB arm";
            showToast(`Feedback recorded (${rewardMsg})`, "success");
          } else {
            showToast("Failed to record feedback", "error");
          }
        } catch (e) {
          console.error("[chat.js] Feedback error:", e);
          showToast("Feedback network error", "error");
        }
      });
    }
  });

  // Attach code copy handlers for any code block inside the response
  attachCodeBlockCopyHandlers(msgEl);

  // KaTeX rendering for math blocks in answer and reasoning
  const textBody = msgEl.querySelector(".msg-text-body");
  if (textBody) {
    _renderMathInElement(textBody);
  }
  const thoughtBody = msgEl.querySelector(".thought-body");
  if (thoughtBody) {
    _renderMathInElement(thoughtBody);
  }

  return msgEl;
}

/**
 * Appends a finalized assistant response card to the chat messages container.
 *
 * @param {string} query - Original user prompt
 * @param {string} text - Final assistant response markdown text
 * @param {Object} [data={}] - Response telemetry data
 * @param {boolean} [shouldScroll=true] - Whether to smooth scroll
 * @returns {HTMLElement|null} Mounted message element
 */
export function appendAssistantResponseToUI(query, text, data = {}, shouldScroll = true) {
  const container = $("chat-messages");
  if (!container) return null;
  const msgEl = buildAssistantCardElement(query, text, data);
  container.appendChild(msgEl);
  if (shouldScroll) {
    smoothScrollToBottom(container);
  }
  return msgEl;
}

// Global browser window attachment for non-module scripts / backwards compatibility
if (typeof window !== "undefined") {
  window.renderActiveSessionMessages = renderActiveSessionMessages;
  window.appendUserMessageToUI = appendUserMessageToUI;
  window.createStreamingPlaceholder = createStreamingPlaceholder;
  window.buildAssistantCardElement = buildAssistantCardElement;
  window.appendAssistantResponseToUI = appendAssistantResponseToUI;
  window.escapeHtml = escapeHtml;
  window.normalizeTierKey = normalizeTierKey;
  window.formatMarkdown = formatMarkdown;
  window._renderMathInElement = _renderMathInElement;
  window.smoothScrollToBottom = smoothScrollToBottom;
  window.showToast = showToast;

  window.ChatModule = {
    renderActiveSessionMessages,
    appendUserMessageToUI,
    createStreamingPlaceholder,
    appendAssistantResponseToUI,
    escapeHtml,
    normalizeTierKey,
    formatMarkdown,
    _renderMathInElement,
    smoothScrollToBottom,
    showToast,
  };
}

if (typeof globalThis !== "undefined") {
  globalThis.renderActiveSessionMessages = renderActiveSessionMessages;
  globalThis.appendUserMessageToUI = appendUserMessageToUI;
  globalThis.createStreamingPlaceholder = createStreamingPlaceholder;
  globalThis.appendAssistantResponseToUI = appendAssistantResponseToUI;
  globalThis.escapeHtml = escapeHtml;
  globalThis.normalizeTierKey = normalizeTierKey;
  globalThis.formatMarkdown = formatMarkdown;
  globalThis._renderMathInElement = _renderMathInElement;
  globalThis.smoothScrollToBottom = smoothScrollToBottom;
  globalThis.showToast = showToast;
  globalThis.ChatModule = typeof window !== "undefined" ? window.ChatModule : {
    renderActiveSessionMessages,
    appendUserMessageToUI,
    createStreamingPlaceholder,
    appendAssistantResponseToUI,
    escapeHtml,
    normalizeTierKey,
    formatMarkdown,
    _renderMathInElement,
    smoothScrollToBottom,
    showToast,
  };
}

export default {
  renderActiveSessionMessages,
  appendUserMessageToUI,
  createStreamingPlaceholder,
  appendAssistantResponseToUI,
  escapeHtml,
  normalizeTierKey,
  formatMarkdown,
  _renderMathInElement,
  smoothScrollToBottom,
  showToast,
};
