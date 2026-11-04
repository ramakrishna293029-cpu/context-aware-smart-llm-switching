/**
 * Context-Aware Smart LLM Switcher - Core Utilities
 * Chunk 13: DOM selection, sanitization, markdown rendering, KaTeX math typesetting,
 * auto-scroll management, code clipboard delegation, instant pointer-down feedback,
 * and Apple critically damped spring toast notifications.
 *
 * Implements Apple Design spring physics, fluid interactions, and Claude Design precision.
 */

/**
 * Fast DOM element lookup by ID or element passthrough.
 * @param {string|HTMLElement} id - Element ID (with or without leading '#') or element instance.
 * @returns {HTMLElement|null}
 */
const $ = (id) => {
  if (!id) return null;
  if (typeof id !== "string") return id;
  const cleanId = id.startsWith("#") ? id.slice(1) : id;
  return document.getElementById(cleanId);
};

/**
 * Fast DOM query selector returning all matching elements.
 * @param {string} sel - CSS selector.
 * @param {ParentNode} [parent=document] - Optional parent scope.
 * @returns {NodeListOf<Element>}
 */
const $$ = (sel, parent = document) => {
  if (!sel) return [];
  const root = parent || document;
  return root.querySelectorAll(sel);
};

/**
 * Safely escapes HTML special characters to prevent XSS.
 * @param {unknown} str - Input value.
 * @returns {string} Escaped string.
 */
function escapeHtml(str) {
  if (str === null || str === undefined) return "";
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#039;");
}

/**
 * Parses and renders Markdown text into sanitized HTML.
 * Includes custom code block chrome with language badges and copy buttons.
 * Sanitizes with DOMPurify while preserving SVG icons and secure attributes.
 *
 * @param {string} text - Raw Markdown text.
 * @returns {string} Sanitized HTML string.
 */
function formatMarkdown(text) {
  if (!text) return "";
  try {
    const markedLib = typeof marked !== "undefined"
      ? marked
      : (typeof window !== "undefined" && window.marked ? window.marked : null);

    if (markedLib) {
      const renderer = new markedLib.Renderer();

      renderer.code = function (codeOrToken, infoString) {
        let code = codeOrToken;
        let lang = infoString;
        if (typeof codeOrToken === "object" && codeOrToken !== null) {
          code = codeOrToken.text || "";
          lang = codeOrToken.lang || "";
        }
        const language = (lang || "code").trim();
        return `<div class="code-block-wrap">
          <div class="code-block-header">
            <span class="code-lang-tag">${escapeHtml(language)}</span>
            <button type="button" class="btn-copy-code" title="Copy code" aria-label="Copy code">
              <svg class="icon-sym" aria-hidden="true"><use href="#i-copy"/></svg>
              <span>Copy</span>
            </button>
          </div>
          <pre class="code-block-pre"><code class="language-${escapeHtml(language)}">${escapeHtml(code)}</code></pre>
        </div>`;
      };

      markedLib.setOptions({
        renderer: renderer,
        gfm: true,
        breaks: true,
      });

      const rawHtml = markedLib.parse(text);

      const purifyLib = typeof DOMPurify !== "undefined"
        ? DOMPurify
        : (typeof window !== "undefined" && window.DOMPurify ? window.DOMPurify : null);

      if (purifyLib && typeof purifyLib.sanitize === "function") {
        return purifyLib.sanitize(rawHtml, {
          ADD_TAGS: ["use", "svg", "button", "span", "pre", "code"],
          ADD_ATTR: ["href", "target", "class", "style", "aria-label", "aria-hidden", "title", "type"],
        });
      }
      return rawHtml;
    }
  } catch (e) {
    console.warn("Markdown parsing failed, applying graceful degradation:", e);
  }
  // Graceful degradation: escape HTML and preserve line breaks
  return escapeHtml(text).replace(/\n/g, "<br>");
}

/**
 * Typesets LaTeX mathematical formulas within the given container element using KaTeX.
 * Supports inline ($...$, \(...\)) and display ($$...$$, \[...\]) math delimiters.
 *
 * @param {HTMLElement} elem - Container element with mathematical expressions.
 */
function _renderMathInElement(elem) {
  if (!elem) return;
  try {
    const renderFn = typeof renderMathInElement === "function"
      ? renderMathInElement
      : (typeof window !== "undefined" && typeof window.renderMathInElement === "function" ? window.renderMathInElement : null);

    if (typeof renderFn === "function") {
      renderFn(elem, {
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
    console.warn("KaTeX render failed:", e);
  }
}

/**
 * Smoothly scrolls a scrollable container to its bottom edge.
 * Respects user scroll position (skips if the user is scrolled up reading).
 *
 * @param {HTMLElement} container - Scrollable DOM container.
 * @param {boolean} [isUserScrolledUp=false] - Whether the user has scrolled away from the bottom.
 */
function smoothScrollToBottom(container, isUserScrolledUp = false) {
  const scrolledUp = Boolean(
    isUserScrolledUp ||
    (typeof window !== "undefined" && window.isUserScrolledUp === true)
  );
  if (!container || scrolledUp) return;

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
 * Fallback clipboard copy using a temporary textarea element for legacy or constrained contexts.
 * @private
 * @param {string} text - Text to copy.
 * @param {() => void} [onSuccess] - Optional success callback.
 * @param {() => void} [onError] - Optional error callback.
 * @returns {boolean} Whether execCommand succeeded.
 */
function _copyFallback(text, onSuccess, onError) {
  if (typeof document === "undefined") return false;
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.top = "0";
  ta.style.left = "-9999px";
  ta.style.opacity = "0";
  ta.setAttribute("aria-hidden", "true");
  document.body.appendChild(ta);
  ta.focus();
  ta.select();

  let ok = false;
  try {
    ok = document.execCommand("copy");
  } catch (_) {
    ok = false;
  }
  document.body.removeChild(ta);

  if (ok) {
    if (typeof onSuccess === "function") onSuccess();
  } else {
    if (typeof onError === "function") onError();
  }
  return ok;
}

/**
 * Universal clipboard copy with modern Navigator API and legacy textarea fallback.
 * @param {string} text - Plain text to copy to the system clipboard.
 * @returns {Promise<boolean>} True if copied successfully.
 */
async function copyToClipboard(text) {
  if (!text) return false;
  if (typeof navigator !== "undefined" && navigator.clipboard && typeof navigator.clipboard.writeText === "function") {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      return _copyFallback(text);
    }
  }
  return _copyFallback(text);
}

/**
 * Initializes global click event delegation for `.btn-copy-code` buttons.
 * Supports clipboard writeText API with resilient legacy textarea fallback.
 * Provides micro-interaction feedback and toast confirmation.
 */
let _codeCopyHandlerInitialized = false;
function setupCodeCopyHandler() {
  if (typeof document === "undefined" || _codeCopyHandlerInitialized) return;
  _codeCopyHandlerInitialized = true;

  document.addEventListener("click", async (e) => {
    const copyBtn = e.target.closest(".btn-copy-code");
    if (!copyBtn) return;

    const wrap = copyBtn.closest(".code-block-wrap");
    const codeElem = wrap ? wrap.querySelector("code") : null;
    const textToCopy = codeElem ? (codeElem.innerText || codeElem.textContent || "") : "";
    if (!textToCopy) return;

    const success = await copyToClipboard(textToCopy);

    if (success) {
      const span = copyBtn.querySelector("span");
      const prevText = span ? span.textContent : "Copy";
      if (span) span.textContent = "Copied!";
      copyBtn.classList.add("copied");

      setTimeout(() => {
        if (span) span.textContent = prevText || "Copy";
        copyBtn.classList.remove("copied");
      }, 1800);

      showToast("Code copied to clipboard", "success");
    } else {
      showToast("Failed to copy code", "error");
    }
  });
}

/**
 * Displays a non-intrusive toast notification in `#toast-container`.
 * Incorporates Apple critically damped spring entrance/exit physics and semantic visual accents.
 *
 * @param {string} message - Notification text.
 * @param {"info"|"success"|"error"|"warning"} [type="info"] - Toast semantic variant.
 */
function showToast(message, type = "info") {
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

  // Semantic border accent token mapping
  const borderAccents = {
    success: "var(--accent-green, #10b981)",
    error: "var(--accent-red, #ef4444)",
    warning: "var(--accent-amber, #f59e0b)",
    info: "var(--accent-blue, #6366f1)",
  };
  if (borderAccents[type]) {
    toast.style.borderLeft = `3px solid ${borderAccents[type]}`;
  }

  // Apple critically damped spring entrance setup
  toast.style.opacity = "0";
  toast.style.transform = "translateY(-10px) scale(0.96)";
  toast.style.transition = "opacity 0.22s cubic-bezier(0.16, 1, 0.3, 1), transform 0.22s cubic-bezier(0.16, 1, 0.3, 1)";

  container.appendChild(toast);

  // Trigger spring entrance animation on next animation frame
  requestAnimationFrame(() => {
    toast.style.opacity = "1";
    toast.style.transform = "translateY(0) scale(1)";
  });

  // Dismiss helper with critically damped exit spring
  let dismissed = false;
  const dismissToast = () => {
    if (dismissed) return;
    dismissed = true;
    toast.style.opacity = "0";
    toast.style.transform = "translateY(8px) scale(0.95)";
    toast.style.transition = "opacity 0.2s cubic-bezier(0.16, 1, 0.3, 1), transform 0.2s cubic-bezier(0.16, 1, 0.3, 1)";
    setTimeout(() => {
      if (toast.parentNode) {
        toast.parentNode.removeChild(toast);
      }
    }, 200);
  };

  // Auto-dismiss after 2800ms
  const autoDismissTimer = setTimeout(dismissToast, 2800);

  // Dismiss on click for instant user control
  toast.addEventListener("click", () => {
    clearTimeout(autoDismissTimer);
    dismissToast();
  });
}

/**
 * Attaches Apple-style instant zero-latency feedback on pointerdown to an interactive element.
 * Applies immediate tactile depression (scale 0.96) on pointerdown and springs back smoothly
 * on pointerup/pointercancel/pointerleave with a critically damped spring.
 * 
 * @param {HTMLElement} el - Element to attach spring tactile feedback to.
 */
function attachPointerDownFeedback(el) {
  if (!el || typeof el.addEventListener !== "function") return;

  const onPointerDown = () => {
    el.style.transition = "transform 0.08s ease-out";
    el.style.transform = "scale(0.96)";
  };

  const onPointerUp = () => {
    el.style.transition = "transform 0.28s cubic-bezier(0.16, 1, 0.3, 1)";
    el.style.transform = "";
  };

  el.addEventListener("pointerdown", onPointerDown);
  el.addEventListener("pointerup", onPointerUp);
  el.addEventListener("pointercancel", onPointerUp);
  el.addEventListener("pointerleave", onPointerUp);
}

/**
 * Initializes global instant pointer-down spring feedback for all interactive buttons and pills.
 * Enables zero-latency tactile response matching native iOS / macOS controls.
 * 
 * @param {ParentNode} [root=document] - Root container to bind listeners.
 */
let _pointerFeedbackInitialized = false;
function initPointerFeedback(root = document) {
  if (typeof document === "undefined" || _pointerFeedbackInitialized) return;
  _pointerFeedbackInitialized = true;

  const targetSelector = "button, [role='button'], .btn, .pill, .tab-btn, .clickable-pill, .btn-copy-code";

  root.addEventListener("pointerdown", (e) => {
    const target = e.target.closest(targetSelector);
    if (!target) return;

    target.style.transition = "transform 0.08s cubic-bezier(0.2, 0, 0, 1)";
    target.style.transform = "scale(0.96)";

    const restore = () => {
      target.style.transition = "transform 0.28s cubic-bezier(0.16, 1, 0.3, 1)";
      target.style.transform = "";
      window.removeEventListener("pointerup", restore);
      window.removeEventListener("pointercancel", restore);
    };

    window.addEventListener("pointerup", restore, { once: true });
    window.addEventListener("pointercancel", restore, { once: true });
  }, { passive: true });
}

// Auto-initialize code copy delegation and pointer feedback on document ready
if (typeof document !== "undefined") {
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => {
      setupCodeCopyHandler();
      initPointerFeedback();
    });
  } else {
    setupCodeCopyHandler();
    initPointerFeedback();
  }
}

// Universal browser window bindings
if (typeof window !== "undefined") {
  window.$ = $;
  window.$$ = $$;
  window.escapeHtml = escapeHtml;
  window.formatMarkdown = formatMarkdown;
  window._renderMathInElement = _renderMathInElement;
  window.smoothScrollToBottom = smoothScrollToBottom;
  window.copyToClipboard = copyToClipboard;
  window.setupCodeCopyHandler = setupCodeCopyHandler;
  window.showToast = showToast;
  window.attachPointerDownFeedback = attachPointerDownFeedback;
  window.initPointerFeedback = initPointerFeedback;
}
if (typeof globalThis !== "undefined") {
  globalThis.$ = $;
  globalThis.$$ = $$;
  globalThis.escapeHtml = escapeHtml;
  globalThis.formatMarkdown = formatMarkdown;
  globalThis._renderMathInElement = _renderMathInElement;
  globalThis.smoothScrollToBottom = smoothScrollToBottom;
  globalThis.copyToClipboard = copyToClipboard;
  globalThis.setupCodeCopyHandler = setupCodeCopyHandler;
  globalThis.showToast = showToast;
  globalThis.attachPointerDownFeedback = attachPointerDownFeedback;
  globalThis.initPointerFeedback = initPointerFeedback;
}

export {
  $,
  $$,
  escapeHtml,
  formatMarkdown,
  _renderMathInElement,
  smoothScrollToBottom,
  copyToClipboard,
  setupCodeCopyHandler,
  showToast,
  attachPointerDownFeedback,
  initPointerFeedback,
};
