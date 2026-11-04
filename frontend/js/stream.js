/**
 * @file stream.js
 * @description Context-Aware Smart LLM Switcher - Streaming Transport & SSE Parsing Engine.
 * 
 * Engineered with Apple Design Interruptibility & High-Resilience Network Principles:
 * - Fluid direct control: instant abort response (0 latency) via AbortController/AbortSignal.
 * - Robust Server-Sent Events (SSE) stream decoding with multibyte UTF-8 buffer accumulation.
 * - Typed telemetry dispatch: analyzer -> routing -> reasoning_delta -> delta -> done -> error.
 * - Real-time pipeline status tracking (connecting, analyzing, routing, streaming, completed).
 * - Automatic graceful degradation: seamless fallback to unary `/api/chat` if SSE stream fails or is unsupported.
 * - Clean teardown of network handles, stream readers, and buffers upon interruption.
 */

/**
 * Resolves the active apiFetch implementation with credentials and settings headers.
 * Safely looks up window.apiFetch, globalThis.apiFetch, or provisions a resilient fallback.
 * 
 * @private
 * @returns {(url: string, options?: RequestInit) => Promise<Response>}
 */
function getTransportFetch() {
  if (typeof window !== "undefined" && typeof window.apiFetch === "function") {
    return window.apiFetch;
  }
  if (typeof globalThis !== "undefined" && typeof globalThis.apiFetch === "function") {
    return globalThis.apiFetch;
  }

  // Resilient fallback fetcher
  return async (url, options = {}) => {
    let headers = {
      "Content-Type": "application/json",
      "Accept": "text/event-stream, application/json, text/plain, */*",
    };

    if (typeof window !== "undefined" && window.SettingsManager?.getHeaders) {
      try {
        const customHeaders = await window.SettingsManager.getHeaders();
        headers = { ...headers, ...customHeaders };
      } catch (e) {
        console.warn("[stream.js] Failed to retrieve settings headers:", e);
      }
    }

    const mergedHeaders = { ...headers, ...(options.headers || {}) };
    return fetch(url, { ...options, headers: mergedHeaders });
  };
}

/**
 * Dispatches a single parsed SSE message payload to the appropriate callback handler.
 * Tracks stream state to prevent duplicate twin-emissions (e.g. content_delta + delta).
 * 
 * @private
 * @param {string|null} eventType - The SSE event name (from 'event:' line or payload.event/payload.type)
 * @param {any} data - Parsed event payload or raw string
 * @param {Object} callbacks - Callback dispatch registry
 * @param {Function} [callbacks.onAnalyzer]
 * @param {Function} [callbacks.onRouting]
 * @param {Function} [callbacks.onReasoningDelta]
 * @param {Function} [callbacks.onDelta]
 * @param {Function} [callbacks.onDone]
 * @param {Function} [callbacks.onError]
 * @param {Function} [callbacks.onPipelineStatus]
 * @param {Object} [state={}] - Internal stream state for deduplication and pipeline status
 */
function dispatchSseEvent(eventType, data, callbacks, state = {}) {
  const {
    onAnalyzer,
    onRouting,
    onReasoningDelta,
    onDelta,
    onDone,
    onError,
    onPipelineStatus,
  } = callbacks;

  // Handle standard SSE [DONE] stream termination marker
  if (data === "[DONE]" || (typeof data === "string" && data.trim() === "[DONE]")) {
    if (typeof onPipelineStatus === "function") {
      onPipelineStatus("completed", { done: true });
    }
    if (typeof onDone === "function") {
      onDone({ done: true, stream_completed: true });
    }
    return;
  }

  // Determine normalized event type
  let type = eventType;
  if (!type && typeof data === "object" && data !== null) {
    type = data.event || data.type || "message";
  }

  switch (type) {
    case "analyzer": {
      const info = (typeof data === "object" && data !== null)
        ? (data.info || data.data || data)
        : data;
      if (typeof onPipelineStatus === "function") {
        onPipelineStatus("analyzing", info);
      }
      if (typeof onAnalyzer === "function") {
        onAnalyzer(info);
      }
      break;
    }

    case "routing": {
      const routeData = (typeof data === "object" && data !== null)
        ? (data.data || data)
        : data;
      if (typeof onPipelineStatus === "function") {
        onPipelineStatus("routing", routeData);
      }
      if (typeof onRouting === "function") {
        onRouting(routeData);
      }
      break;
    }

    case "status":
    case "pipeline_status": {
      if (typeof onPipelineStatus === "function") {
        const statusName = typeof data === "string" ? data : (data.status || data.phase || "status");
        onPipelineStatus(statusName, data);
      }
      break;
    }

    case "reasoning_delta":
    case "reasoning": {
      let chunk = "";
      if (typeof data === "string") {
        chunk = data;
      } else if (typeof data === "object" && data !== null) {
        chunk = data.text ?? data.delta ?? (data.data && (data.data.text ?? data.data.delta)) ?? "";
      }
      if (chunk) {
        if (!state.hasEmittedReasoning) {
          state.hasEmittedReasoning = true;
          if (typeof onPipelineStatus === "function") {
            onPipelineStatus("reasoning", { chunk });
          }
        }
        if (typeof onReasoningDelta === "function") {
          onReasoningDelta(chunk);
        }
      }
      break;
    }

    // Handles both "delta" and "content_delta" with twin-event deduplication
    case "delta":
    case "content_delta": {
      let chunk = "";
      if (typeof data === "string") {
        chunk = data;
      } else if (typeof data === "object" && data !== null) {
        chunk = data.text ?? data.delta ?? (data.data && (data.data.text ?? data.data.delta)) ?? "";
      }

      if (chunk) {
        const now = Date.now();
        const isTwinOfRecent =
          state.lastDeltaText === chunk &&
          state.lastDeltaType !== type &&
          now - (state.lastDeltaTime || 0) < 60;

        if (!isTwinOfRecent) {
          state.lastDeltaText = chunk;
          state.lastDeltaType = type;
          state.lastDeltaTime = now;

          if (!state.hasEmittedDelta) {
            state.hasEmittedDelta = true;
            if (typeof onPipelineStatus === "function") {
              onPipelineStatus("streaming", { chunk });
            }
          }

          if (typeof onDelta === "function") {
            onDelta(chunk);
          }
        }
      }
      break;
    }

    case "done": {
      const doneData = (typeof data === "object" && data !== null)
        ? (data.data || data)
        : data;
      if (typeof onPipelineStatus === "function") {
        onPipelineStatus("completed", doneData);
      }
      if (typeof onDone === "function") {
        onDone(doneData);
      }
      break;
    }

    case "error": {
      let message = "Unknown streaming error occurred";
      if (typeof data === "string") {
        message = data;
      } else if (typeof data === "object" && data !== null) {
        message = data.detail || data.message || (data.data && (data.data.detail || data.data.message)) || JSON.stringify(data);
      }
      if (typeof onPipelineStatus === "function") {
        onPipelineStatus("error", { message });
      }
      if (typeof onError === "function") {
        onError(message);
      }
      break;
    }

    default: {
      // Unhandled or custom event type
      if (typeof data === "object" && data !== null) {
        if (data.detail && typeof onError === "function") {
          onError(data.detail);
        } else if ((data.text || data.delta) && typeof onDelta === "function") {
          onDelta(data.text || data.delta);
        }
      }
      break;
    }
  }
}

/**
 * Parses raw SSE chunk blocks and dispatches typed events.
 * Handles multiline data, comments (: ping), and event-type headers.
 * 
 * @param {string} block - Contiguous SSE message block separated by double newline
 * @param {Object} callbacks - Callback hooks
 * @param {Object} [state={}] - Stream state tracker
 */
function parseSseBlock(block, callbacks, state = {}) {
  const trimmed = block.trim();
  if (!trimmed) return;

  const lines = trimmed.split(/\r?\n/);
  let eventType = null;
  let dataLines = [];

  for (const line of lines) {
    const trimmedLine = line.trim();
    if (!trimmedLine || trimmedLine.startsWith(":")) {
      // Comment or keep-alive heartbeat line
      continue;
    }

    if (trimmedLine.startsWith("event:")) {
      eventType = trimmedLine.slice(6).trim();
    } else if (trimmedLine.startsWith("data:")) {
      // Slice after "data:" and strip single optional leading space per SSE spec
      let dataContent = trimmedLine.slice(5);
      if (dataContent.startsWith(" ")) {
        dataContent = dataContent.slice(1);
      }
      dataLines.push(dataContent);
    }
  }

  if (dataLines.length === 0) return;

  const rawData = dataLines.join("\n");
  if (rawData.trim() === "[DONE]") {
    dispatchSseEvent("done", { done: true }, callbacks, state);
    return;
  }

  let parsedJson = null;
  try {
    parsedJson = JSON.parse(rawData);
  } catch {
    // Plaintext payload fallback
    parsedJson = rawData;
  }

  dispatchSseEvent(eventType, parsedJson, callbacks, state);
}

/**
 * Graceful fallback to unary POST `/api/chat` when SSE stream fails or is unsupported.
 * Emulates the same lifecycle callbacks to keep the client UI state completely synchronized.
 * 
 * @private
 * @param {Object} payload - Chat request payload { query, history, strategy, ... }
 * @param {AbortSignal} [signal] - Optional abort signal
 * @param {Object} callbacks - Callback hooks
 * @returns {Promise<Object>} Unary response JSON
 */
async function executeUnaryFallback(payload, signal, callbacks) {
  const { onAnalyzer, onRouting, onDelta, onDone, onError, onPipelineStatus } = callbacks;

  if (signal?.aborted) {
    throw new DOMException("The operation was aborted", "AbortError");
  }

  if (typeof onPipelineStatus === "function") {
    onPipelineStatus("fallback", { phase: "unary_initiation" });
  }

  const transportFetch = getTransportFetch();
  const resp = await transportFetch("/api/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Accept": "application/json",
    },
    body: JSON.stringify(payload),
    signal,
  });

  if (!resp.ok) {
    const errorData = await resp.json().catch(() => ({}));
    const errorMessage = errorData.detail || errorData.message || `Unary fallback HTTP ${resp.status}`;
    if (typeof onPipelineStatus === "function") {
      onPipelineStatus("error", { message: errorMessage });
    }
    if (typeof onError === "function") {
      onError(errorMessage);
    }
    throw new Error(errorMessage);
  }

  const data = await resp.json();

  // Emulate lifecycle events from unary payload
  const analyzerInfo = data.analyzer || {
    task_type: data.task_type || "general",
    complexity_score: data.complexity_score ?? 0.5,
    target_tier: data.tier || "tier_1",
    reasoning: data.reasoning || "Direct unary execution",
    confidence: data.confidence ?? 1.0,
  };
  if (typeof onPipelineStatus === "function") {
    onPipelineStatus("analyzing", analyzerInfo);
  }
  if (typeof onAnalyzer === "function") {
    onAnalyzer(analyzerInfo);
  }

  const routeInfo = {
    target_tier: data.tier || data.target_tier || data.model?.tier || "tier_1",
    target_model: data.model?.model_id || data.model_id || data.selected_model || "fallback-model",
    target_name: data.model?.model_name || data.model_name || data.model?.name || data.model_id || "Fallback Model",
    provider: data.provider || data.model?.provider || "gateway",
    cost_usd: data.total_cost_usd ?? data.cost_usd ?? 0.0,
    latency_ms: data.total_latency_ms ?? data.latency_ms ?? 0.0,
  };
  if (typeof onPipelineStatus === "function") {
    onPipelineStatus("routing", routeInfo);
  }
  if (typeof onRouting === "function") {
    onRouting(routeInfo);
  }

  if (data.response) {
    if (typeof onPipelineStatus === "function") {
      onPipelineStatus("streaming", { response: data.response });
    }
    if (typeof onDelta === "function") {
      onDelta(data.response);
    }
  }

  if (typeof onPipelineStatus === "function") {
    onPipelineStatus("completed", data);
  }
  if (typeof onDone === "function") {
    onDone(data);
  }

  return data;
}

/**
 * Executes a streaming chat request to the Context-Aware Smart LLM Switcher backend.
 * 
 * Supports both function call patterns:
 * 1. Positional arguments: executeStreamingChat(payload, signal, onAnalyzer, onRouting, onReasoningDelta, onDelta, onDone, onError, onPipelineStatus)
 * 2. Options object: executeStreamingChat(payload, { signal, onAnalyzer, onRouting, onReasoningDelta, onDelta, onDone, onError, onPipelineStatus })
 * 
 * Capabilities:
 * - Server-Sent Events (SSE) via POST `/api/chat/stream`.
 * - Multi-chunk UTF-8 buffer accumulation and line-frame boundary detection.
 * - Fluid user interruptibility via AbortSignal (cancelling reader immediately with zero leaks).
 * - Automatic seamless degradation to unary `/api/chat` if streaming is unavailable or fails before emission.
 * - Complete telemetry and pipeline status dispatching.
 * 
 * @param {Object} payload - The chat request body
 * @param {AbortSignal|Object} [signalOrOptions] - AbortSignal or options dictionary
 * @param {Function} [onAnalyzer] - Callback fired when analyzer completes: (info) => void
 * @param {Function} [onRouting] - Callback fired when model routing completes: (route) => void
 * @param {Function} [onReasoningDelta] - Callback fired on thought/reasoning token: (chunk) => void
 * @param {Function} [onDelta] - Callback fired on content token delta: (chunk) => void
 * @param {Function} [onDone] - Callback fired when response generation completes: (doneData) => void
 * @param {Function} [onError] - Callback fired on stream or pipeline error: (message) => void
 * @param {Function} [onPipelineStatus] - Callback fired on pipeline state change: (status, details) => void
 * @returns {Promise<void>} Resolves when the stream finishes or unary fallback completes
 */
async function executeStreamingChat(
  payload,
  signalOrOptions,
  onAnalyzer,
  onRouting,
  onReasoningDelta,
  onDelta,
  onDone,
  onError,
  onPipelineStatus
) {
  let signal;
  let cbAnalyzer;
  let cbRouting;
  let cbReasoningDelta;
  let cbDelta;
  let cbDone;
  let cbError;
  let cbPipelineStatus;

  // Detect whether caller used options-object pattern or positional arguments
  const isOptionsObj =
    signalOrOptions &&
    typeof signalOrOptions === "object" &&
    !(typeof AbortSignal !== "undefined" && signalOrOptions instanceof AbortSignal) &&
    !("aborted" in signalOrOptions);

  if (isOptionsObj) {
    signal = signalOrOptions.signal;
    cbAnalyzer = signalOrOptions.onAnalyzer;
    cbRouting = signalOrOptions.onRouting;
    cbReasoningDelta = signalOrOptions.onReasoningDelta;
    cbDelta = signalOrOptions.onDelta;
    cbDone = signalOrOptions.onDone;
    cbError = signalOrOptions.onError;
    cbPipelineStatus = signalOrOptions.onPipelineStatus;
  } else {
    signal = signalOrOptions;
    cbAnalyzer = onAnalyzer;
    cbRouting = onRouting;
    cbReasoningDelta = onReasoningDelta;
    cbDelta = onDelta;
    cbDone = onDone;
    cbError = onError;
    cbPipelineStatus = onPipelineStatus;
  }

  // Direct check for pre-aborted signal
  if (signal?.aborted) {
    throw new DOMException("The operation was aborted", "AbortError");
  }

  const callbacks = {
    onAnalyzer: cbAnalyzer,
    onRouting: cbRouting,
    onReasoningDelta: cbReasoningDelta,
    onDelta: cbDelta,
    onDone: cbDone,
    onError: cbError,
    onPipelineStatus: cbPipelineStatus,
  };

  if (typeof cbPipelineStatus === "function") {
    cbPipelineStatus("connecting", { endpoint: "/api/chat/stream" });
  }

  const transportFetch = getTransportFetch();
  let streamResponse = null;
  let receivedAnyDeltas = false;
  const streamState = {
    lastDeltaText: null,
    lastDeltaType: null,
    lastDeltaTime: 0,
    hasEmittedDelta: false,
    hasEmittedReasoning: false,
  };

  // Track deltas to prevent fallback duplication once streaming has commenced
  const wrappedOnDelta = (chunk) => {
    receivedAnyDeltas = true;
    if (typeof cbDelta === "function") {
      cbDelta(chunk);
    }
  };
  const activeCallbacks = { ...callbacks, onDelta: wrappedOnDelta };

  try {
    streamResponse = await transportFetch("/api/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Accept": "text/event-stream",
      },
      body: JSON.stringify(payload),
      signal,
    });
  } catch (fetchErr) {
    // If the request was aborted by the user, immediately honor cancellation without fallback
    if (fetchErr.name === "AbortError" || signal?.aborted) {
      throw fetchErr;
    }

    console.warn("[stream.js] SSE fetch failed, initiating unary fallback:", fetchErr);
    await executeUnaryFallback(payload, signal, callbacks);
    return;
  }

  // If streaming endpoint returned error status or missing readable body, trigger unary fallback
  if (!streamResponse || !streamResponse.ok || !streamResponse.body) {
    let errDetail = `HTTP ${streamResponse?.status || "Unknown"}`;
    try {
      const errJson = await streamResponse.json();
      errDetail = errJson.detail || errJson.message || errDetail;
    } catch {
      // Non-JSON error body
    }

    console.warn(`[stream.js] SSE stream unavailable (${errDetail}), attempting unary fallback...`);
    await executeUnaryFallback(payload, signal, callbacks);
    return;
  }

  // Stream reader initialization with UTF-8 decoding
  const reader = streamResponse.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  // Attach immediate abort listener to cancel reader directly with Apple-style direct response
  let abortListener = null;
  if (signal) {
    abortListener = () => {
      try {
        reader.cancel().catch(() => {});
      } catch (_) {}
    };
    signal.addEventListener("abort", abortListener, { once: true });
  }

  try {
    while (true) {
      if (signal?.aborted) {
        throw new DOMException("The operation was aborted", "AbortError");
      }

      const { done, value } = await reader.read();
      if (done) {
        break;
      }

      // Stream decode with buffer accumulation
      buffer += decoder.decode(value, { stream: true });

      // Split on standard SSE double newline delimiters (\r\n\r\n or \n\n)
      const blocks = buffer.split(/\r?\n\r?\n/);
      // The last element is either empty (if trailing delimiter) or a partial SSE block
      buffer = blocks.pop() || "";

      for (const block of blocks) {
        if (signal?.aborted) {
          throw new DOMException("The operation was aborted", "AbortError");
        }
        parseSseBlock(block, activeCallbacks, streamState);
      }
    }

    // Flush any remaining buffer if reader finished with trailing content
    if (buffer.trim()) {
      parseSseBlock(buffer, activeCallbacks, streamState);
    }
  } catch (streamErr) {
    // Cleanly propagate user aborts
    if (streamErr.name === "AbortError" || signal?.aborted) {
      throw streamErr;
    }

    // If an error occurred before any deltas were rendered, attempt unary fallback
    if (!receivedAnyDeltas) {
      console.warn("[stream.js] Stream broke before deltas received, falling back to unary /api/chat:", streamErr);
      await executeUnaryFallback(payload, signal, callbacks);
      return;
    }

    // If stream broke mid-generation, report error to UI
    const errMessage = streamErr.message || "Streaming connection terminated unexpectedly";
    console.error("[stream.js] Streaming error during token emission:", streamErr);
    if (typeof cbError === "function") {
      cbError(errMessage);
    }
    throw streamErr;
  } finally {
    // Teardown abort listener and reader locks
    if (signal && abortListener) {
      signal.removeEventListener("abort", abortListener);
    }
    try {
      reader.releaseLock();
    } catch (_) {}
  }
}

// Expose on global window and globalThis for script-tag compatibility
if (typeof window !== "undefined") {
  window.executeStreamingChat = executeStreamingChat;
  window.parseSseBlock = parseSseBlock;
  window.executeUnaryFallback = executeUnaryFallback;
}
if (typeof globalThis !== "undefined") {
  globalThis.executeStreamingChat = executeStreamingChat;
  globalThis.parseSseBlock = parseSseBlock;
  globalThis.executeUnaryFallback = executeUnaryFallback;
}

// Export for modern ES module bundlers and imports
export { executeStreamingChat, parseSseBlock, executeUnaryFallback };
export default executeStreamingChat;
