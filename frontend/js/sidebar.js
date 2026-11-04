/**
 * Smart LLM Switcher — Sidebar Component Controller
 * Implements Apple Human Interface Guidelines & macOS Big Sur / Sonoma design
 *
 * Responsibilities:
 * - Collapsible Apple icon rail & fluid spring motion transitions
 * - Mobile responsive drawer overlay with translucent backdrop blur
 * - Multi-session conversation list rendering & instant search filtering
 * - Session inline renaming and safe deletion
 * - System-level keyboard shortcuts (Cmd/Ctrl+B, Cmd/Ctrl+N, Cmd/Ctrl+,, Cmd/Ctrl+K, '/', Esc)
 */

// Module-level registry for active callbacks and manager reference
let _activeSessionManager = null;
let _onNewChatCallback = null;
let _onSwitchSessionCallback = null;
let _onToggleThemeCallback = null;
let _onOpenSettingsCallback = null;
let _keyboardShortcutsInitialized = false;

/**
 * Checks whether the current viewport is in mobile drawer range (<= 768px).
 * @returns {boolean}
 */
export const isMobile = () => typeof window !== "undefined" && window.innerWidth <= 768;

/**
 * Escapes unsafe characters for secure DOM rendering.
 * @param {string} str - Raw string.
 * @returns {string} Escaped HTML string.
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
 * Helper to get element by ID.
 * @param {string} id - Element ID.
 * @returns {HTMLElement|null}
 */
function $(id) {
  return document.getElementById(id);
}

/**
 * Initializes sidebar controls, event bindings, and keyboard shortcuts.
 *
 * @param {Object} [sessionManager] - The SessionManager instance.
 * @param {Function} [onNewChat] - Callback triggered when starting a new chat.
 * @param {Function} [onSwitchSession] - Callback triggered when switching sessions (sessionId, session).
 * @param {Function} [onToggleTheme] - Callback triggered when toggling dark/light theme.
 * @param {Function} [onOpenSettings] - Callback triggered when opening settings modal.
 */
export function setupSidebarControls(
  sessionManager,
  onNewChat,
  onSwitchSession,
  onToggleTheme,
  onOpenSettings
) {
  _activeSessionManager = sessionManager || (typeof window !== "undefined" ? window.sessionManager : null);
  _onNewChatCallback = onNewChat;
  _onSwitchSessionCallback = onSwitchSession;
  _onToggleThemeCallback = onToggleTheme;
  _onOpenSettingsCallback = onOpenSettings;

  const sidebar = $("sidebar");
  const sidebarBackdrop = $("sidebar-backdrop");
  const collapseBtn = $("sidebar-collapse-btn");
  const openBtn = $("sidebar-open-btn");
  const newChatBtn = $("new-chat-btn");
  const themeToggleBtn = $("theme-toggle-btn");
  const openSettingsBtn = $("open-settings-btn");
  const clearAllBtn = $("clear-all-sessions-btn");
  const searchInput = $("session-search-input");
  const clearSearchBtn = $("clear-search-btn");

  // 1. New Conversation Button
  if (newChatBtn) {
    newChatBtn.addEventListener("click", () => {
      handleNewConversation();
    });
  }

  // 2. Sidebar Collapse / Expand (Desktop Icon Rail)
  if (collapseBtn) {
    collapseBtn.addEventListener("click", () => {
      toggleSidebarCollapse();
    });
  }

  // 3. Sidebar Open Button (Mobile Drawer & Collapsed Desktop Header)
  if (openBtn) {
    openBtn.addEventListener("click", () => {
      handleSidebarOpenToggle();
    });
  }

  // 4. Mobile Backdrop Dismissal
  if (sidebarBackdrop) {
    sidebarBackdrop.addEventListener("click", () => {
      closeMobileDrawer();
    });
  }

  // 4b. Apple 1:1 Direct Manipulation Touch Swipe to Dismiss Drawer on Mobile
  if (sidebar) {
    let touchStartX = 0;
    let touchStartY = 0;
    let isSwiping = false;

    sidebar.addEventListener(
      "touchstart",
      (e) => {
        if (!isMobile() || !sidebar.classList.contains("mobile-open")) return;
        const touch = e.touches[0];
        touchStartX = touch.clientX;
        touchStartY = touch.clientY;
        isSwiping = false;
      },
      { passive: true }
    );

    sidebar.addEventListener(
      "touchmove",
      (e) => {
        if (!isMobile() || !sidebar.classList.contains("mobile-open")) return;
        const touch = e.touches[0];
        const deltaX = touch.clientX - touchStartX;
        const deltaY = touch.clientY - touchStartY;

        // If predominantly horizontal drag to the left
        if (deltaX < -8 && Math.abs(deltaX) > Math.abs(deltaY)) {
          isSwiping = true;
          sidebar.style.transform = `translateX(${deltaX}px)`;
        }
      },
      { passive: true }
    );

    sidebar.addEventListener(
      "touchend",
      (e) => {
        if (!isMobile() || !isSwiping) return;
        isSwiping = false;
        const touch = e.changedTouches[0];
        const deltaX = touch.clientX - touchStartX;
        sidebar.style.transform = "";

        // Dismiss if dragged left past 50px threshold
        if (deltaX < -50) {
          closeMobileDrawer();
        }
      },
      { passive: true }
    );
  }

  // 5. Theme Toggle Button
  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
      handleThemeToggle();
    });
  }

  // 6. Settings Button
  if (openSettingsBtn) {
    openSettingsBtn.addEventListener("click", () => {
      handleOpenSettings();
    });
  }

  // 7. Clear All Sessions
  if (clearAllBtn) {
    clearAllBtn.addEventListener("click", () => {
      handleClearAllSessions();
    });
  }

  // 8. Session Search Filter
  if (searchInput) {
    searchInput.addEventListener("input", () => {
      const q = (searchInput.value || "").trim().toLowerCase();
      if (q.length > 0) {
        clearSearchBtn?.classList.remove("hidden");
      } else {
        clearSearchBtn?.classList.add("hidden");
      }
      renderSidebarSessions(_activeSessionManager, q);
    });
  }

  if (clearSearchBtn) {
    clearSearchBtn.addEventListener("click", () => {
      if (searchInput) searchInput.value = "";
      clearSearchBtn.classList.add("hidden");
      renderSidebarSessions(_activeSessionManager, "");
      searchInput?.focus();
    });
  }

  // 9. Navigation View Items — Close Mobile Drawer on Navigation
  const navItems = document.querySelectorAll(".sidebar-nav-item");
  navItems.forEach((item) => {
    item.addEventListener("click", () => {
      if (isMobile()) {
        closeMobileDrawer();
      }
    });
  });

  // 10. Global Apple HIG Keyboard Shortcuts
  if (!_keyboardShortcutsInitialized) {
    setupKeyboardShortcuts(
      handleNewConversation,
      handleOpenSettings,
      () => $("query-input")?.focus()
    );
    _keyboardShortcutsInitialized = true;
  }
}

/**
 * Handles new conversation creation with fallback routing.
 */
export function handleNewConversation() {
  if (typeof _onNewChatCallback === "function") {
    _onNewChatCallback();
    return;
  }

  const manager = _activeSessionManager || (typeof window !== "undefined" ? window.sessionManager : null);
  if (manager && typeof manager.createSession === "function") {
    manager.createSession("New Conversation", true);
    renderSidebarSessions(manager);
    if (typeof window !== "undefined" && typeof window.renderActiveSessionMessages === "function") {
      window.renderActiveSessionMessages();
    }
    if (typeof window !== "undefined" && typeof window.switchView === "function") {
      window.switchView("chat");
    }
  }

  // Close mobile drawer if open
  if (isMobile()) {
    closeMobileDrawer();
  }

  // Focus input
  const queryInput = $("query-input");
  if (queryInput) {
    queryInput.focus();
  }
}

/**
 * Toggles desktop collapsed icon rail state.
 */
export function toggleSidebarCollapse() {
  const sidebar = $("sidebar");
  if (!sidebar) return;

  sidebar.classList.toggle("collapsed");
  const isCollapsed = sidebar.classList.contains("collapsed");
  const collapseBtn = $("sidebar-collapse-btn");

  if (collapseBtn) {
    collapseBtn.setAttribute("aria-expanded", isCollapsed ? "false" : "true");
    collapseBtn.setAttribute(
      "title",
      isCollapsed ? "Expand Sidebar [Ctrl+B]" : "Collapse Sidebar [Ctrl+B]"
    );
  }
}

/**
 * Handles opening/toggling the sidebar depending on screen size.
 */
export function handleSidebarOpenToggle() {
  const sidebar = $("sidebar");
  const backdrop = $("sidebar-backdrop");
  if (!sidebar) return;

  if (!isMobile()) {
    // Desktop: uncollapse icon rail
    sidebar.classList.remove("collapsed");
  } else {
    // Mobile: toggle slide-out drawer
    sidebar.classList.toggle("mobile-open");
    backdrop?.classList.toggle("active");
  }
}

/**
 * Closes mobile sidebar drawer and dismisses backdrop.
 */
export function closeMobileDrawer() {
  const sidebar = $("sidebar");
  const backdrop = $("sidebar-backdrop");
  sidebar?.classList.remove("mobile-open");
  backdrop?.classList.remove("active");
}

/**
 * Handles theme toggle dispatching.
 */
function handleThemeToggle() {
  if (typeof _onToggleThemeCallback === "function") {
    _onToggleThemeCallback();
    return;
  }

  if (typeof window !== "undefined" && typeof window.toggleTheme === "function") {
    window.toggleTheme();
    return;
  }

  // Standalone fallback theme toggle
  const html = document.documentElement;
  const current = html.getAttribute("data-theme") || "dark";
  const next = current === "dark" ? "light" : "dark";
  html.setAttribute("data-theme", next);
  try {
    localStorage.setItem("smart_llm_theme", next);
  } catch (e) {
    // Ignore localStorage errors
  }

  const themeText = $("theme-text");
  if (themeText) {
    themeText.textContent = next === "dark" ? "Dark Mode" : "Light Mode";
  }
}

/**
 * Handles settings modal dispatching.
 */
function handleOpenSettings() {
  if (typeof _onOpenSettingsCallback === "function") {
    _onOpenSettingsCallback();
    return;
  }

  if (typeof window !== "undefined" && typeof window.openSettingsModal === "function") {
    window.openSettingsModal();
    return;
  }

  const settingsModal = $("settings-modal");
  if (settingsModal) {
    settingsModal.classList.remove("hidden");
  }
}

/**
 * Handles clear all conversations request with confirmation.
 */
function handleClearAllSessions() {
  const confirmed = window.confirm(
    "Are you sure you want to delete all saved conversations? This action cannot be undone."
  );
  if (!confirmed) return;

  const manager = _activeSessionManager || (typeof window !== "undefined" ? window.sessionManager : null);
  if (manager && typeof manager.clearAll === "function") {
    manager.clearAll();
  }

  renderSidebarSessions(manager);

  if (typeof window !== "undefined" && typeof window.renderActiveSessionMessages === "function") {
    window.renderActiveSessionMessages();
  }

  if (typeof window !== "undefined" && typeof window.showToast === "function") {
    window.showToast("All conversations cleared", "info");
  }
}

/**
 * Renders the session items in the sidebar list.
 *
 * @param {Object} [sessionManager] - The session manager instance.
 * @param {string} [filterQuery=""] - Optional search query to filter conversation titles.
 */
export function renderSidebarSessions(sessionManager, filterQuery = "") {
  const manager = sessionManager || _activeSessionManager || (typeof window !== "undefined" ? window.sessionManager : null);
  const listContainer = $("session-list");
  if (!listContainer) return;

  const sessions = manager
    ? typeof manager.getAll === "function"
      ? manager.getAll()
      : Array.isArray(manager.sessions)
      ? manager.sessions
      : []
    : [];

  const activeId = manager ? manager.activeSessionId : null;
  const q = (filterQuery || "").trim().toLowerCase();

  const filtered = q
    ? sessions.filter((s) => (s && s.title ? s.title.toLowerCase().includes(q) : false))
    : sessions;

  // Update session count badge
  const countBadge = $("sessions-count-badge");
  if (countBadge) {
    countBadge.textContent = filtered.length.toString();
  }

  // Empty state handling
  if (filtered.length === 0) {
    listContainer.innerHTML = `
      <div class="session-list-empty">
        <svg class="icon-sym session-list-empty-icon" aria-hidden="true"><use href="#i-chat"/></svg>
        <span>${q ? "No matching conversations" : "No conversations yet"}</span>
      </div>
    `;
    return;
  }

  // Render session list items
  listContainer.innerHTML = filtered
    .map((s) => {
      const isActive = s.id === activeId;
      const safeTitle = escapeHtml(s.title || "Untitled Conversation");
      return `
        <div class="session-item ${isActive ? "active" : ""}" data-id="${escapeHtml(s.id)}" role="button" tabindex="0" title="${safeTitle}">
          <span class="session-item-title">${safeTitle}</span>
          <div class="session-item-actions">
            <button class="btn-session-action rename" title="Rename conversation" data-action="rename" data-id="${escapeHtml(s.id)}" aria-label="Rename conversation">
              <svg class="icon-sym" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
                <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
              </svg>
            </button>
            <button class="btn-session-action delete" title="Delete conversation" data-action="delete" data-id="${escapeHtml(s.id)}" aria-label="Delete conversation">
              <svg class="icon-sym" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
                <line x1="18" y1="6" x2="6" y2="18"/>
                <line x1="6" y1="6" x2="18" y2="18"/>
              </svg>
            </button>
          </div>
        </div>
      `;
    })
    .join("");

  // Attach session item click handlers
  const itemEls = listContainer.querySelectorAll(".session-item");
  itemEls.forEach((el) => {
    el.addEventListener("click", (e) => {
      const actBtn = e.target.closest("button");
      const id = el.dataset.id;
      if (!id) return;

      // Handle action buttons
      if (actBtn) {
        e.stopPropagation();
        const action = actBtn.dataset.action;
        if (action === "delete") {
          if (manager && typeof manager.deleteSession === "function") {
            manager.deleteSession(id);
            renderSidebarSessions(manager, filterQuery);
            if (typeof window !== "undefined" && typeof window.renderActiveSessionMessages === "function") {
              window.renderActiveSessionMessages();
            }
          }
        } else if (action === "rename") {
          promptRenameSession(manager, id);
        }
        return;
      }

      // Handle session selection
      if (manager && typeof manager.switchSession === "function") {
        manager.switchSession(id);
      }

      renderSidebarSessions(manager, filterQuery);

      const targetSession = sessions.find((item) => item.id === id);

      if (typeof _onSwitchSessionCallback === "function") {
        _onSwitchSessionCallback(id, targetSession);
      } else {
        if (typeof window !== "undefined" && typeof window.renderActiveSessionMessages === "function") {
          window.renderActiveSessionMessages();
        }
        if (typeof window !== "undefined" && typeof window.switchView === "function") {
          window.switchView("chat");
        }
        const activeTitleEl = $("active-session-title");
        if (activeTitleEl && targetSession) {
          activeTitleEl.textContent = targetSession.title;
        }
      }

      if (isMobile()) {
        closeMobileDrawer();
      }
    });

    // Keyboard navigation (Enter / Space to select)
    el.addEventListener("keydown", (e) => {
      if (e.key === "Enter" || e.key === " ") {
        if (e.target.tagName !== "BUTTON") {
          e.preventDefault();
          el.click();
        }
      }
    });
  });
}

/**
 * Prompts the user to rename a session.
 *
 * @param {Object} [sessionManager] - The SessionManager instance.
 * @param {string} id - The session ID to rename.
 * @param {Function} [onRenamed] - Optional callback invoked after renaming (id, newTitle).
 */
export function promptRenameSession(sessionManager, id, onRenamed) {
  const manager = sessionManager || _activeSessionManager || (typeof window !== "undefined" ? window.sessionManager : null);
  if (!manager) return;

  const sessions = typeof manager.getAll === "function" ? manager.getAll() : manager.sessions || [];
  const session = sessions.find((s) => s.id === id);
  if (!session) return;

  const currentTitle = session.title || "New Conversation";
  const newTitle = window.prompt("Enter conversation title:", currentTitle);

  if (newTitle !== null) {
    const trimmed = newTitle.trim();
    if (trimmed.length > 0 && trimmed !== currentTitle) {
      if (typeof manager.renameSession === "function") {
        manager.renameSession(id, trimmed);
      } else {
        session.title = trimmed;
        if (typeof manager.save === "function") manager.save();
      }

      renderSidebarSessions(manager);

      // Update header title if renaming active session
      if (manager.activeSessionId === id) {
        const titleEl = $("active-session-title");
        if (titleEl) {
          titleEl.textContent = trimmed;
        }
      }

      if (typeof onRenamed === "function") {
        onRenamed(id, trimmed);
      }
    }
  }
}

/**
 * Sets up global desktop keyboard shortcuts adhering to Apple Human Interface Guidelines:
 * - Cmd/Ctrl+B: toggle sidebar collapsed
 * - Cmd/Ctrl+N: new conversation
 * - Cmd/Ctrl+,: open settings
 * - Cmd/Ctrl+K or '/': focus composer
 * - Escape: dismiss modals and mobile drawer
 *
 * @param {Function} [onNewChat] - Callback for new chat.
 * @param {Function} [onOpenSettings] - Callback for opening settings.
 * @param {Function} [onFocusComposer] - Callback for focusing composer query input.
 */
export function setupKeyboardShortcuts(onNewChat, onOpenSettings, onFocusComposer) {
  document.addEventListener("keydown", (e) => {
    // 1. Escape: Dismiss active modals and mobile drawer
    if (e.key === "Escape") {
      let handled = false;

      // Close open modals
      const openModals = document.querySelectorAll(
        ".modal:not(.hidden), #settings-modal:not(.hidden), #inspector-modal:not(.hidden)"
      );
      if (openModals.length > 0) {
        openModals.forEach((modal) => modal.classList.add("hidden"));
        handled = true;
      }

      // Close mobile drawer if active
      const sidebar = $("sidebar");
      const backdrop = $("sidebar-backdrop");
      if (sidebar?.classList.contains("mobile-open")) {
        sidebar.classList.remove("mobile-open");
        backdrop?.classList.remove("active");
        handled = true;
      }

      if (handled) {
        e.preventDefault();
        return;
      }
    }

    const isModifier = e.metaKey || e.ctrlKey;

    // 2. Cmd/Ctrl+B: Toggle sidebar collapsed
    if (isModifier && e.key.toLowerCase() === "b") {
      e.preventDefault();
      toggleSidebarCollapse();
      return;
    }

    // 3. Cmd/Ctrl+N: New conversation
    if (isModifier && e.key.toLowerCase() === "n") {
      e.preventDefault();
      if (typeof onNewChat === "function") {
        onNewChat();
      } else {
        handleNewConversation();
      }
      return;
    }

    // 4. Cmd/Ctrl+,: Open Settings (Canonical macOS Standard)
    if (isModifier && e.key === ",") {
      e.preventDefault();
      if (typeof onOpenSettings === "function") {
        onOpenSettings();
      } else {
        handleOpenSettings();
      }
      return;
    }

    // 5. Cmd/Ctrl+K: Focus composer input
    if (isModifier && e.key.toLowerCase() === "k") {
      e.preventDefault();
      if (typeof onFocusComposer === "function") {
        onFocusComposer();
      } else {
        $("query-input")?.focus();
      }
      return;
    }

    // 6. '/': Focus composer input (only when outside input/textarea)
    if (e.key === "/" && !isModifier && !e.altKey) {
      const activeEl = document.activeElement;
      const isTyping =
        activeEl &&
        (activeEl.tagName === "INPUT" ||
          activeEl.tagName === "TEXTAREA" ||
          activeEl.isContentEditable);

      if (!isTyping) {
        e.preventDefault();
        if (typeof onFocusComposer === "function") {
          onFocusComposer();
        } else {
          $("query-input")?.focus();
        }
      }
    }
  });
}

// Window attachment for backwards compatibility with non-module scripts
if (typeof window !== "undefined") {
  window.setupSidebarControls = setupSidebarControls;
  window.renderSidebarSessions = renderSidebarSessions;
  window.promptRenameSession = promptRenameSession;
  window.setupKeyboardShortcuts = setupKeyboardShortcuts;
  window.handleNewConversation = handleNewConversation;
  window.toggleSidebarCollapse = toggleSidebarCollapse;
  window.closeMobileDrawer = closeMobileDrawer;
  window.handleSidebarOpenToggle = handleSidebarOpenToggle;
  window.isMobile = isMobile;
  window.SidebarModule = {
    setupSidebarControls,
    renderSidebarSessions,
    promptRenameSession,
    setupKeyboardShortcuts,
    handleNewConversation,
    toggleSidebarCollapse,
    closeMobileDrawer,
    handleSidebarOpenToggle,
    isMobile,
  };
}

export default {
  setupSidebarControls,
  renderSidebarSessions,
  promptRenameSession,
  setupKeyboardShortcuts,
  handleNewConversation,
  toggleSidebarCollapse,
  closeMobileDrawer,
  handleSidebarOpenToggle,
  isMobile,
};
