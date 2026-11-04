/**
 * Context-Aware Smart LLM Switcher — Topology Controller
 * Apple HIG & Claude Standard: Live 6-Tier Routing Ribbon & Collapsible Drawer
 * Manages LinUCB Bandit Router telemetry, tier activation, and dynamic escalation states.
 */

// Safe DOM query helpers
const $ = (id) => document.getElementById(id);
const $$ = (selector) => document.querySelectorAll(selector);

/**
 * Maps any tier identifier string into normalized tier key 'tier_1' ... 'tier_6'.
 * @param {string|number} tier - Raw tier string or number
 * @returns {string} Normalized tier key ('tier_1' - 'tier_6')
 */
export function normalizeTierKey(tier) {
  if (!tier) return "tier_1";
  const s = String(tier).trim().toLowerCase();

  if (s === "1" || s.includes("tier_1") || s.includes("tier 1") || s.includes("flash-lite")) {
    return "tier_1";
  }
  if (s === "5" || s.includes("tier_5") || s.includes("tier 5") || s.includes("120b") || s.includes("reasoning")) {
    return "tier_5";
  }
  if (s === "2" || s.includes("tier_2") || s.includes("tier 2") || (!s.includes("120b") && s.includes("20b"))) {
    return "tier_2";
  }
  if (s === "3" || s.includes("tier_3") || s.includes("tier 3") || s.includes("3.6")) {
    return "tier_3";
  }
  if (s === "4" || s.includes("tier_4") || s.includes("tier 4") || s.includes("qwen") || s.includes("coding")) {
    return "tier_4";
  }
  if (s === "6" || s.includes("tier_6") || s.includes("tier 6") || s.includes("3.8") || s.includes("high capability") || s.includes("powerful")) {
    return "tier_6";
  }

  // Fallback pattern matching digits 1-6
  const match = s.match(/[1-6]/);
  if (match) {
    return `tier_${match[0]}`;
  }

  return "tier_1";
}

/**
 * Returns user-facing descriptive display title for a given tier.
 * @param {string|number} tier - Tier key or raw string
 * @returns {string} Human-readable tier label
 */
export function formatTierDisplay(tier) {
  const norm = normalizeTierKey(tier);
  switch (norm) {
    case "tier_1":
      return "Tier 1: Gemini 3.5 Flash-Lite (Fast / Routine)";
    case "tier_2":
      return "Tier 2: Groq GPT-OSS 20B (Fast General)";
    case "tier_3":
      return "Tier 3: Gemini 3.6 Flash (Balanced Workhorse)";
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
 * Initializes the collapsible architecture drawer toggle.
 * Handles expanding/collapsing with fluid spring height transition and toggle arrow rotation.
 */
export function setupRibbonToggle() {
  const toggleBtn = $("ribbon-toggle-btn");
  const drawer = $("ribbon-drawer");
  const arrow = $("ribbon-toggle-arrow");

  if (!toggleBtn || !drawer) return;

  // Sync initial accessibility state
  const isCurrentlyCollapsed = drawer.classList.contains("collapsed");
  toggleBtn.setAttribute("aria-expanded", String(!isCurrentlyCollapsed));
  if (arrow) {
    arrow.textContent = "▾";
    arrow.style.transform = isCurrentlyCollapsed ? "rotate(0deg)" : "rotate(180deg)";
    arrow.style.transition = "transform 0.28s cubic-bezier(0.16, 1, 0.3, 1)";
  }

  const handleToggle = () => {
    drawer.classList.toggle("collapsed");
    const isCollapsed = drawer.classList.contains("collapsed");
    toggleBtn.setAttribute("aria-expanded", String(!isCollapsed));

    if (arrow) {
      arrow.style.transform = isCollapsed ? "rotate(0deg)" : "rotate(180deg)";
    }
  };

  toggleBtn.addEventListener("click", handleToggle);

  // Keyboard accessibility
  toggleBtn.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      handleToggle();
    }
  });
}

/**
 * Resets all topology ribbon elements to clean idle state.
 */
export function resetPipelineRibbon() {
  // Reset LinUCB analyzer node
  const analyzerNode = $("pnode-analyzer");
  if (analyzerNode) {
    analyzerNode.className = "topology-node analyzer";
    const stateEl = $("pnode-analyzer-state");
    if (stateEl) {
      stateEl.textContent = "Router";
    }
  }

  // Reset dynamic flow connector
  const connector = $("pipeline-flow-connector");
  if (connector) {
    connector.classList.remove("flowing");
  }

  // Clear active/escalated states on all tier nodes
  const tierNodes = $$(".rnode-tier, .topology-tier-node");
  tierNodes.forEach((node) => {
    node.classList.remove("active-tier", "escalated-tier");
  });

  // Reset status indicator dot
  const statusDot = $("pipeline-status-dot");
  if (statusDot) {
    statusDot.className = "status-indicator-dot";
  }

  // Reset status message
  const statusMsg = $("pipeline-status-msg");
  if (statusMsg) {
    statusMsg.textContent = "LinUCB Contextual Router Active · 6 Model Arms Online";
  }

  // Hide escalation indicator pill
  const escPill = $("pipeline-escalation-pill");
  if (escPill) {
    escPill.classList.add("hidden");
  }
}

/**
 * Transitions topology ribbon into active analyzing/evaluating state.
 */
export function updatePipelineToAnalyzing() {
  resetPipelineRibbon();

  // Set analyzer node to analyzing pulse
  const analyzerNode = $("pnode-analyzer");
  if (analyzerNode) {
    analyzerNode.classList.add("analyzing");
    const stateEl = $("pnode-analyzer-state");
    if (stateEl) {
      stateEl.textContent = "TF-IDF + LinUCB Scoring...";
    }
  }

  // Activate SVG connector flow
  const connector = $("pipeline-flow-connector");
  if (connector) {
    connector.classList.add("flowing");
  }

  // Pulse status dot
  const statusDot = $("pipeline-status-dot");
  if (statusDot) {
    statusDot.className = "status-indicator-dot analyzing";
  }

  // Telemetry status message
  const statusMsg = $("pipeline-status-msg");
  if (statusMsg) {
    statusMsg.textContent = "LinUCB Contextual Bandit evaluating candidate arms...";
  }
}

/**
 * Updates topology ribbon with feature extraction & analyzer evaluation results.
 * @param {Object} info - Routing analysis metadata
 * @param {string} [info.answer_mode] - 'self' or 'route'
 * @param {string} [info.target_tier] - Recommended tier key
 * @param {string} [info.required_capability] - Capability tier key
 * @param {string} [info.task_type] - Task classification (e.g. Coding, STEM, General)
 * @param {string|number} [info.complexity] - Complexity label or score
 */
export function updatePipelineAnalyzerResult(info = {}) {
  const analyzerNode = $("pnode-analyzer");
  const isSelf = info.answer_mode === "self";

  if (analyzerNode) {
    analyzerNode.classList.remove("analyzing");
    const stateEl = $("pnode-analyzer-state");
    if (stateEl) {
      stateEl.textContent = isSelf
        ? "Self-Answer"
        : `${info.task_type || "General"} · ${info.complexity || "Med"}`;
    }
  }

  const targetTier = normalizeTierKey(info.target_tier || info.required_capability);
  if (targetTier && !isSelf) {
    const tierCard = $(`pnode-${targetTier}`);
    if (tierCard) {
      tierCard.classList.add("active-tier");
    }
  }

  const statusMsg = $("pipeline-status-msg");
  if (statusMsg) {
    statusMsg.textContent = isSelf
      ? "Resolved in Zero-Latency Self-Answer Mode"
      : `LinUCB Routed: ${(info.task_type || "General").toUpperCase()} ➔ ${formatTierDisplay(targetTier)}`;
  }
}

/**
 * Updates topology ribbon when route is selected.
 * @param {Object} route - Route descriptor
 * @param {string} [route.target_tier] - Selected tier
 * @param {string} [route.target_name] - Selected model name
 * @param {string} [route.target_model] - Alternative model identifier
 */
export function updatePipelineRouting(route = {}) {
  const tierNodes = $$(".rnode-tier, .topology-tier-node");
  tierNodes.forEach((node) => node.classList.remove("active-tier"));

  const tierKey = normalizeTierKey(route.target_tier);
  if (tierKey) {
    const card = $(`pnode-${tierKey}`);
    if (card) {
      card.classList.add("active-tier");
    }
  }

  const connector = $("pipeline-flow-connector");
  if (connector) {
    connector.classList.remove("flowing");
  }

  const statusDot = $("pipeline-status-dot");
  if (statusDot) {
    statusDot.className = "status-indicator-dot active";
  }

  const statusMsg = $("pipeline-status-msg");
  if (statusMsg) {
    const modelName = route.target_name || route.target_model || "Model";
    statusMsg.textContent = `Routed to ${modelName} (${route.target_tier || tierKey.toUpperCase()})`;
  }
}

/**
 * Updates topology ribbon with final completed execution outcome.
 * Highlights served tier, applies escalation indicators if triggered,
 * and displays latency in milliseconds and cost in USD.
 * @param {Object} outcome - Execution outcome metadata
 * @param {boolean} [outcome.escalation_used] - Whether escalation triggered
 * @param {boolean} [outcome.escalated] - Alternative escalation flag
 * @param {string} [outcome.escalated_tier] - Escalation target tier
 * @param {string} [outcome.original_tier] - Initial tier before escalation
 * @param {Object} [outcome.model] - Model details
 * @param {string} [outcome.selected_model] - Model name fallback
 * @param {number} [outcome.total_latency_ms] - Total latency in ms
 * @param {number} [outcome.latency_ms] - Fallback latency
 * @param {number} [outcome.total_cost_usd] - Total cost in USD
 * @param {number} [outcome.estimated_cost_usd] - Fallback cost
 */
export function updatePipelineDone(outcome = {}) {
  const isEscalated = Boolean(outcome.escalation_used || outcome.escalated);
  const servedTier = normalizeTierKey(
    outcome.escalated_tier ||
    outcome.model?.tier ||
    outcome.target_tier ||
    outcome.original_tier ||
    "tier_1"
  );

  // Clear previous states
  const tierNodes = $$(".rnode-tier, .topology-tier-node");
  tierNodes.forEach((node) => node.classList.remove("active-tier", "escalated-tier"));

  // Highlight served tier
  const card = $(`pnode-${servedTier}`);
  if (card) {
    card.classList.add("active-tier");
    if (isEscalated) {
      card.classList.add("escalated-tier");
    }
  }

  // Escalation badge handling
  const escPill = $("pipeline-escalation-pill");
  const escText = $("pipeline-escalation-text");
  if (isEscalated && escPill && escText) {
    escPill.classList.remove("hidden");
    const fromLabel = formatTierDisplay(outcome.original_tier || "tier_1").split(":")[0];
    const toLabel = formatTierDisplay(outcome.escalated_tier || servedTier).split(":")[0];
    escText.textContent = `Escalated: ${fromLabel} → ${toLabel}`;
  } else if (escPill) {
    escPill.classList.add("hidden");
  }

  // Status indicator dot
  const statusDot = $("pipeline-status-dot");
  if (statusDot) {
    statusDot.className = isEscalated
      ? "status-indicator-dot escalated"
      : "status-indicator-dot";
  }

  // Status telemetry message: Served Model · Latency · Cost
  const statusMsg = $("pipeline-status-msg");
  if (statusMsg) {
    const modelName = outcome.model?.model_name ||
                      outcome.model?.model_id ||
                      outcome.selected_model ||
                      "Model";

    const costVal = outcome.total_cost_usd != null
      ? outcome.total_cost_usd
      : (outcome.estimated_cost_usd != null ? outcome.estimated_cost_usd : 0);
    const costStr = `$${Number(costVal).toFixed(6)}`;

    const latVal = outcome.total_latency_ms != null
      ? outcome.total_latency_ms
      : (outcome.latency_ms != null ? outcome.latency_ms : 0);
    const latStr = `${Math.round(latVal)}ms`;

    statusMsg.textContent = `Served: ${modelName} · ${latStr} · ${costStr}`;
  }

  // Ensure connector flow is deactivated
  const connector = $("pipeline-flow-connector");
  if (connector) {
    connector.classList.remove("flowing");
  }
}

// Grouped Topology controller API Class
export class Topology {
  static setupRibbonToggle = setupRibbonToggle;
  static normalizeTierKey = normalizeTierKey;
  static formatTierDisplay = formatTierDisplay;
  static resetPipelineRibbon = resetPipelineRibbon;
  static updatePipelineToAnalyzing = updatePipelineToAnalyzing;
  static updatePipelineAnalyzerResult = updatePipelineAnalyzerResult;
  static updatePipelineRouting = updatePipelineRouting;
  static updatePipelineDone = updatePipelineDone;

  // Instance methods for constructor / instance compatibility
  setupRibbonToggle() { return setupRibbonToggle(); }
  normalizeTierKey(tier) { return normalizeTierKey(tier); }
  formatTierDisplay(tier) { return formatTierDisplay(tier); }
  resetPipelineRibbon() { return resetPipelineRibbon(); }
  updatePipelineToAnalyzing() { return updatePipelineToAnalyzing(); }
  updatePipelineAnalyzerResult(info) { return updatePipelineAnalyzerResult(info); }
  updatePipelineRouting(route) { return updatePipelineRouting(route); }
  updatePipelineDone(outcome) { return updatePipelineDone(outcome); }
}

// Global window exposure for progressive modular migration and non-module compatibility
if (typeof window !== "undefined") {
  window.setupRibbonToggle = setupRibbonToggle;
  window.normalizeTierKey = normalizeTierKey;
  window.formatTierDisplay = formatTierDisplay;
  window.resetPipelineRibbon = resetPipelineRibbon;
  window.updatePipelineToAnalyzing = updatePipelineToAnalyzing;
  window.updatePipelineAnalyzerResult = updatePipelineAnalyzerResult;
  window.updatePipelineRouting = updatePipelineRouting;
  window.updatePipelineDone = updatePipelineDone;
  window.Topology = Topology;
  window.TopologyRouter = Topology;
}

export default Topology;
