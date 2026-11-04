/**
 * @file session.js
 * @description Context-Aware Smart LLM Switcher - Session Management Module.
 * Provides multi-session conversation persistence, active session tracking,
 * message logging with automatic contextual titling, and history extraction for LLM routing.
 *
 * Designed with Apple Human Interface principles:
 * - Deterministic, zero-latency state transitions.
 * - Resilient fallback states and graceful storage degradation.
 * - Reactive change notification hooks for fluid UI updates.
 */

class SessionManager {
  static SESSIONS_KEY = "smart_llm_sessions";
  static ACTIVE_KEY = "smart_llm_active_session";

  /**
   * Initializes the session manager, loading existing sessions or bootstrapping a fresh one.
   */
  constructor() {
    /** @type {Array<Object>} */
    this.sessions = [];
    /** @type {string|null} */
    this.activeSessionId = null;
    /** @type {Set<Function>} */
    this._listeners = new Set();

    this.load();
  }

  /**
   * Safely reads sessions and activeSessionId from localStorage.
   * Self-heals corrupted states or empty storage by provisioning an initial session.
   */
  load() {
    try {
      const storage = this._getStorage();
      const raw = storage ? storage.getItem(SessionManager.SESSIONS_KEY) : null;
      this.sessions = raw ? JSON.parse(raw) : [];
      this.activeSessionId = storage ? storage.getItem(SessionManager.ACTIVE_KEY) : null;

      if (!Array.isArray(this.sessions)) {
        this.sessions = [];
      }

      if (this.sessions.length === 0) {
        this.createSession("New Conversation", true);
      } else if (!this.activeSessionId || !this.sessions.some(s => s.id === this.activeSessionId)) {
        this.activeSessionId = this.sessions[0].id;
        this.persistActiveId();
      }
    } catch (e) {
      console.warn("[SessionManager] Failed to load sessions from localStorage:", e);
      this.sessions = [];
      this.createSession("New Conversation", true);
    }
  }

  /**
   * Persists current sessions list and active session ID to localStorage.
   */
  save() {
    try {
      const storage = this._getStorage();
      if (storage) {
        storage.setItem(SessionManager.SESSIONS_KEY, JSON.stringify(this.sessions));
        this.persistActiveId();
      }
    } catch (e) {
      console.error("[SessionManager] Failed to save sessions to localStorage:", e);
    }
  }

  /**
   * Persists the active session ID to localStorage.
   */
  persistActiveId() {
    try {
      const storage = this._getStorage();
      if (storage && this.activeSessionId) {
        storage.setItem(SessionManager.ACTIVE_KEY, this.activeSessionId);
      }
    } catch (e) {
      console.warn("[SessionManager] Failed to persist activeSessionId:", e);
    }
  }

  /**
   * Returns all conversation sessions.
   * @returns {Array<Object>}
   */
  getAll() {
    return this.sessions;
  }

  /**
   * Retrieves the currently active session object, falling back to the first available session.
   * @returns {Object|null}
   */
  getActive() {
    if (!this.sessions || this.sessions.length === 0) {
      return null;
    }
    return this.sessions.find(s => s.id === this.activeSessionId) || this.sessions[0];
  }

  /**
   * Alias for getActive for API compatibility across modules.
   * @returns {Object|null}
   */
  getActiveSession() {
    return this.getActive();
  }

  /**
   * Alias for switchSession for API compatibility across modules.
   * @param {string} id
   * @returns {boolean}
   */
  setActiveSession(id) {
    return this.switchSession(id);
  }

  /**
   * Retrieves a session by its unique ID.
   * @param {string} id
   * @returns {Object|null}
   */
  getSessionById(id) {
    if (!id || !this.sessions) return null;
    return this.sessions.find(s => s.id === id) || null;
  }

  /**
   * Creates a new conversation session, prepends it to the list, and persists the update.
   * @param {string} [title="New Conversation"]
   * @param {boolean} [activate=true]
   * @returns {Object} The created session
   */
  createSession(title = "New Conversation", activate = true) {
    const rand = Math.random().toString(36).substring(2, 8);
    const cleanTitle = (typeof title === "string" && title.trim()) ? title.trim() : "New Conversation";

    const newSession = {
      id: `sess_${Date.now()}_${rand}`,
      title: cleanTitle,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      messages: [],
    };

    this.sessions.unshift(newSession);

    if (activate || !this.activeSessionId) {
      this.activeSessionId = newSession.id;
    }

    this.save();
    this._notify("create", { session: newSession });
    return newSession;
  }

  /**
   * Switches the active session to the provided session ID.
   * @param {string} id
   * @returns {boolean} True if switch succeeded, false if session not found.
   */
  switchSession(id) {
    if (this.sessions.some(s => s.id === id)) {
      this.activeSessionId = id;
      this.persistActiveId();
      this._notify("switch", { session: this.getActive() });
      return true;
    }
    return false;
  }

  /**
   * Removes a session by ID. If active session was deleted, activates the next available session.
   * If all sessions are removed, automatically spawns a fresh "New Conversation".
   * @param {string} id
   */
  deleteSession(id) {
    this.sessions = this.sessions.filter(s => s.id !== id);

    if (this.sessions.length === 0) {
      this.createSession("New Conversation", true);
    } else if (this.activeSessionId === id) {
      this.activeSessionId = this.sessions[0].id;
      this.persistActiveId();
    }

    this.save();
    this._notify("delete", { id, activeSession: this.getActive() });
  }

  /**
   * Renames an existing session and updates its timestamp.
   * @param {string} id
   * @param {string} newTitle
   * @returns {boolean}
   */
  renameSession(id, newTitle) {
    const s = this.sessions.find(item => item.id === id);
    if (s && typeof newTitle === "string" && newTitle.trim()) {
      s.title = newTitle.trim();
      s.updatedAt = Date.now();
      this.save();
      this._notify("rename", { session: s });
      return true;
    }
    return false;
  }

  /**
   * Clears all existing sessions and initializes a fresh active conversation.
   * @returns {Object} The new active session.
   */
  clearAll() {
    this.sessions = [];
    const freshSession = this.createSession("New Conversation", true);
    this.save();
    this._notify("clear", { session: freshSession });
    return freshSession;
  }

  /**
   * Clears message history for a specific session (defaults to active session).
   * @param {string} [id=null]
   * @returns {Object|null}
   */
  clearMessages(id = null) {
    const session = id ? this.getSessionById(id) : this.getActive();
    if (!session) return null;

    session.messages = [];
    session.updatedAt = Date.now();
    this.save();
    this._notify("clearMessages", { session });
    return session;
  }

  /**
   * Generates a concise, context-aware session title from a user prompt.
   * Strips conversational filler and formats cleanly.
   * @param {string} prompt
   * @param {number} [maxLength=36]
   * @returns {string}
   */
  static generateContextualTitle(prompt, maxLength = 36) {
    if (!prompt || typeof prompt !== "string") return "New Conversation";

    // Clean whitespace and linebreaks
    let clean = prompt
      .trim()
      .replace(/[\r\n\t]+/g, " ")
      .replace(/\s+/g, " ");

    if (!clean) return "New Conversation";

    // Repeatedly strip conversational request phrasing to find core intent
    let changed = true;
    while (changed) {
      changed = false;
      const stripped = clean.replace(
        /^(?:please|can\s+you|could\s+you|would\s+you|help\s+me(?:\s+to)?|i\s+want\s+to|how\s+(?:do|can|to)|what\s+is(?:\s+the)?|tell\s+me\s+about|explain(?:\s+to\s+me)?(?:\s+how)?|write(?:\s+me)?(?:\s+a|\s+an)?|create(?:\s+a|\s+an)?|generate(?:\s+a|\s+an)?|code(?:\s+a|\s+an)?)\s+/i,
        ""
      );
      if (stripped !== clean && stripped.length >= 3) {
        clean = stripped;
        changed = true;
      }
    }

    clean = clean.trim();
    if (!clean) clean = prompt.trim();

    // Capitalize first character
    clean = clean.charAt(0).toUpperCase() + clean.slice(1);

    if (clean.length > maxLength) {
      return clean.substring(0, maxLength).trimEnd() + "...";
    }
    return clean;
  }

  /**
   * Contextually auto-names a session from a prompt.
   * @param {string} sessionId
   * @param {string} prompt
   * @returns {boolean}
   */
  autoNameSession(sessionId, prompt) {
    const session = this.getSessionById(sessionId);
    if (!session) return false;
    const title = SessionManager.generateContextualTitle(prompt);
    session.title = title;
    session.updatedAt = Date.now();
    this.save();
    this._notify("rename", { session });
    return true;
  }

  /**
   * Appends a message to the active session with deduplication and auto-titling.
   * Prevents rapid duplicate insertions within 1500ms or matching message_id.
   * 
   * @param {"user"|"assistant"|"system"} role
   * @param {string} content
   * @param {Object} [meta={}]
   * @returns {Object|null} The appended or existing message object.
   */
  addMessage(role, content, meta = {}) {
    let active = this.getActive();
    if (!active) {
      active = this.createSession("New Conversation", true);
    }

    if (!Array.isArray(active.messages)) {
      active.messages = [];
    }

    const normRole = role || "user";
    const strContent = content != null ? String(content) : "";
    const cleanMeta = (meta && typeof meta === "object") ? { ...meta } : {};
    const now = Date.now();

    // Deduplication check 1: explicit message_id or request_id match
    const messageId = cleanMeta.message_id || cleanMeta.id || cleanMeta.request_id;
    if (messageId) {
      const existing = active.messages.find(m => {
        const mId = m.meta?.message_id || m.meta?.id || m.meta?.request_id;
        return mId && mId === messageId;
      });
      if (existing) {
        existing.content = strContent;
        existing.meta = { ...existing.meta, ...cleanMeta };
        existing.updatedAt = now;
        active.updatedAt = now;
        this.save();
        this._notify("message", { session: active, message: existing });
        return existing;
      }
    }

    // Deduplication check 2: rapid duplicate submission debounce (same role and content within 1500ms)
    const lastMsg = active.messages[active.messages.length - 1];
    if (
      lastMsg &&
      lastMsg.role === normRole &&
      lastMsg.content === strContent &&
      Math.abs(now - (lastMsg.timestamp || 0)) < 1500
    ) {
      return lastMsg;
    }

    const message = {
      role: normRole,
      content: strContent,
      timestamp: now,
      meta: cleanMeta,
    };

    active.messages.push(message);
    active.updatedAt = now;

    // Auto-title if first user prompt or default placeholder
    if (normRole === "user" && (active.title === "New Conversation" || active.messages.length <= 2)) {
      active.title = SessionManager.generateContextualTitle(strContent);
    }

    this.save();
    this._notify("message", { session: active, message });
    return message;
  }

  /**
   * Prunes duplicate messages in a session based on message_id or consecutive identical content.
   * @param {string} [sessionId=null] - Defaults to active session.
   * @returns {number} Count of removed duplicates.
   */
  deduplicateMessages(sessionId = null) {
    const session = sessionId ? this.getSessionById(sessionId) : this.getActive();
    if (!session || !Array.isArray(session.messages)) return 0;

    const seenIds = new Set();
    const deduped = [];
    let removedCount = 0;

    for (let i = 0; i < session.messages.length; i++) {
      const msg = session.messages[i];
      const mId = msg.meta?.message_id || msg.meta?.id || msg.meta?.request_id;

      if (mId) {
        if (seenIds.has(mId)) {
          removedCount++;
          continue;
        }
        seenIds.add(mId);
      }

      // Check consecutive duplicate content
      const prev = deduped[deduped.length - 1];
      if (prev && prev.role === msg.role && prev.content === msg.content) {
        removedCount++;
        continue;
      }

      deduped.push(msg);
    }

    if (removedCount > 0) {
      session.messages = deduped;
      session.updatedAt = Date.now();
      this.save();
      this._notify("update", { session });
    }

    return removedCount;
  }

  /**
   * Exports a conversation session as a formatted JSON or Markdown string.
   * 
   * @param {string} [id=null] - Session ID (defaults to active session)
   * @param {"json"|"markdown"|"md"} [format="json"] - Export format
   * @returns {string}
   */
  exportSession(id = null, format = "json") {
    const session = id ? this.getSessionById(id) : this.getActive();
    if (!session) return "";

    const normFormat = (format || "json").toLowerCase();

    if (normFormat === "markdown" || normFormat === "md") {
      const createdStr = new Date(session.createdAt || Date.now()).toISOString();
      const updatedStr = new Date(session.updatedAt || Date.now()).toISOString();
      
      let md = `# ${session.title || "Conversation"}\n\n`;
      md += `> **Created:** ${createdStr} | **Updated:** ${updatedStr} | **ID:** \`${session.id}\`\n\n---\n\n`;

      for (const msg of session.messages || []) {
        const roleLabel = (msg.role || "user").toUpperCase();
        const timeLabel = new Date(msg.timestamp || Date.now()).toLocaleTimeString();
        const modelLabel = msg.meta?.model_name || msg.meta?.target_model || "";
        const metaStr = modelLabel ? ` (${modelLabel})` : "";

        md += `### ${roleLabel}${metaStr} - *${timeLabel}*\n\n`;
        if (msg.meta?.reasoning) {
          md += `> **Reasoning:**\n> ${msg.meta.reasoning.replace(/\n/g, "\n> ")}\n\n`;
        }
        md += `${msg.content || ""}\n\n---\n\n`;
      }
      return md;
    }

    return JSON.stringify(session, null, 2);
  }

  /**
   * Exports all conversation sessions as a JSON backup bundle.
   * @returns {string} Pretty-printed JSON
   */
  exportAll() {
    const bundle = {
      version: 1,
      exportedAt: new Date().toISOString(),
      activeSessionId: this.activeSessionId,
      sessions: this.sessions,
    };
    return JSON.stringify(bundle, null, 2);
  }

  /**
   * Triggers a browser download of a session in JSON or Markdown format with zero memory leak.
   * 
   * @param {string} [id=null] - Session ID
   * @param {"json"|"markdown"} [format="json"] - File format
   */
  downloadSession(id = null, format = "json") {
    if (typeof document === "undefined" || typeof Blob === "undefined") return;

    const session = id ? this.getSessionById(id) : this.getActive();
    if (!session) return;

    const isMd = format === "markdown" || format === "md";
    const data = this.exportSession(session.id, isMd ? "markdown" : "json");
    const mime = isMd ? "text/markdown;charset=utf-8" : "application/json;charset=utf-8";
    const ext = isMd ? "md" : "json";

    const cleanTitle = (session.title || "conversation")
      .toLowerCase()
      .replace(/[^a-z0-9_-]+/g, "_")
      .substring(0, 30);
    const filename = `${cleanTitle}_${Date.now()}.${ext}`;

    const blob = new Blob([data], { type: mime });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.style.display = "none";
    document.body.appendChild(link);
    link.click();

    setTimeout(() => {
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
    }, 200);
  }

  /**
   * Imports sessions from a JSON bundle or array with integrity validation.
   * @param {string|Object} rawData - JSON string or parsed object
   * @param {Object} [options={}]
   * @param {boolean} [options.merge=true] - Whether to merge with existing sessions or replace
   * @returns {number} Count of successfully imported sessions
   */
  importSessions(rawData, options = {}) {
    try {
      const parsed = typeof rawData === "string" ? JSON.parse(rawData) : rawData;
      const sessionList = Array.isArray(parsed)
        ? parsed
        : (Array.isArray(parsed?.sessions) ? parsed.sessions : (parsed?.id ? [parsed] : []));

      if (sessionList.length === 0) return 0;

      const merge = options.merge !== false;
      const existingIds = new Set(this.sessions.map(s => s.id));
      let importedCount = 0;

      for (const item of sessionList) {
        if (!item || typeof item !== "object") continue;
        let id = item.id;
        if (!id || existingIds.has(id)) {
          id = `sess_${Date.now()}_${Math.random().toString(36).substring(2, 8)}`;
        }
        existingIds.add(id);

        const validatedSession = {
          id,
          title: item.title || "Imported Conversation",
          createdAt: item.createdAt || Date.now(),
          updatedAt: item.updatedAt || Date.now(),
          messages: Array.isArray(item.messages) ? item.messages : [],
        };

        if (merge) {
          this.sessions.push(validatedSession);
        } else {
          this.sessions = [validatedSession];
        }
        importedCount++;
      }

      if (importedCount > 0) {
        if (!this.activeSessionId || !this.sessions.some(s => s.id === this.activeSessionId)) {
          this.activeSessionId = this.sessions[0].id;
        }
        this.save();
        this._notify("import", { count: importedCount, sessions: this.sessions });
      }

      return importedCount;
    } catch (e) {
      console.warn("[SessionManager] Import failed:", e);
      return 0;
    }
  }

  /**
   * Slices the last `maxTurns * 2` messages formatted as `{ role, content }` pairs for API consumption.
   * @param {number} [maxTurns=10]
   * @returns {Array<{ role: string, content: string }>}
   */
  getRecentHistoryForAPI(maxTurns = 10) {
    const active = this.getActive();
    if (!active || !Array.isArray(active.messages)) return [];

    const turns = Number.isInteger(maxTurns) && maxTurns > 0 ? maxTurns : 10;
    return active.messages
      .slice(-turns * 2)
      .map(m => ({
        role: m.role,
        content: m.content,
      }));
  }

  /**
   * Subscribes a listener callback to session mutation events (create, switch, delete, rename, message, clear).
   * Returns an unsubscribe function.
   * @param {Function} listener
   * @returns {Function} Unsubscribe closure
   */
  subscribe(listener) {
    if (typeof listener === "function") {
      this._listeners.add(listener);
      return () => this._listeners.delete(listener);
    }
    return () => {};
  }

  /**
   * Notifies all registered listeners of a session mutation.
   * @private
   */
  _notify(type, data) {
    for (const listener of this._listeners) {
      try {
        listener(type, data);
      } catch (err) {
        console.warn("[SessionManager] Listener error:", err);
      }
    }
  }

  /**
   * Internal storage accessor that safely handles environments without window/localStorage.
   * @private
   */
  _getStorage() {
    try {
      if (typeof window !== "undefined" && window.localStorage) {
        return window.localStorage;
      }
      if (typeof localStorage !== "undefined") {
        return localStorage;
      }
    } catch {
      // Storage access blocked by browser privacy sandbox
    }
    return null;
  }
}

// Attach to window and globalThis for backwards compatibility with non-module scripts
if (typeof window !== "undefined") {
  window.SessionManager = SessionManager;
}
if (typeof globalThis !== "undefined") {
  globalThis.SessionManager = SessionManager;
}

export { SessionManager };
export default SessionManager;
