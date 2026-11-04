/**
 * Context-Aware Smart LLM Switcher - Secure Storage & Transport Layer
 * 
 * Apple Design & Security Engineering Principles:
 * - Fluid, zero-latency local persistence with asynchronous WebCrypto AES-GCM 256-bit encryption.
 * - Per-operation 96-bit (12-byte) cryptographically secure initialization vectors (IVs).
 * - Graceful degradation & plaintext migration fallback for non-secure contexts.
 * - In-memory synchronous cache for instantaneous zero-latency read access.
 * - Defensive header sanitation and strict typing.
 */

// Helper: Chunked Base64 encoding to prevent stack overflow on large buffers
function bytesToBase64(bytes) {
  let binary = "";
  const len = bytes.byteLength;
  const chunkSize = 8192;
  for (let i = 0; i < len; i += chunkSize) {
    const chunk = bytes.subarray(i, Math.min(i + chunkSize, len));
    binary += String.fromCharCode.apply(null, chunk);
  }
  return btoa(binary);
}

// Helper: Base64 to Uint8Array decoding
function base64ToBytes(b64) {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

/**
 * SettingsManager handles encrypted persistence of API keys, custom endpoints,
 * model tier overrides, and preferences in localStorage using WebCrypto AES-GCM.
 */
class SettingsManager {
  static STORAGE_KEY = "smart_llm_settings";
  static CRYPTO_KEY_NAME = "smart_llm_settings_v1";
  static _cryptoKey = null;
  static _cryptoKeyPromise = null;
  static _cachedSettings = null;

  /**
   * Returns complete canonical schema and default values.
   */
  static getDefaults() {
    return {
      apiKeys: {
        gemini: "",
        groq: "",
        openrouter: "",
        openai: "",
        custom: "",
      },
      customEndpoints: {
        custom: "",
      },
      providerModels: {
        geminiTier1: "gemini-3.5-flash-lite",
        geminiTier3: "gemini-3.6-flash",
        geminiTier6: "gemini-3.8-flash",
        groqTier2: "openai/gpt-oss-20b",
        groqTier4: "qwen/qwen3.8-27b",
        groqTier5: "openai/gpt-oss-120b",
        custom: "",
      },
      preferences: {
        theme: "dark",
        strategy: "balanced",
      },
    };
  }

  /**
   * Synchronously returns cached settings if already loaded, or defaults.
   * Enables zero-latency UI reads without waiting on WebCrypto async decipher.
   * @returns {Object}
   */
  static getCached() {
    if (this._cachedSettings) {
      return JSON.parse(JSON.stringify(this._cachedSettings));
    }
    return this.getDefaults();
  }

  /**
   * Lazily loads or creates the AES-GCM 256-bit CryptoKey.
   * Key material is stored base64-encoded in localStorage under CRYPTO_KEY_NAME.
   * @private
   */
  static async _getCryptoKey() {
    if (this._cryptoKey) return this._cryptoKey;
    if (this._cryptoKeyPromise) return this._cryptoKeyPromise;

    this._cryptoKeyPromise = (async () => {
      try {
        const cryptoObj = typeof window !== "undefined"
          ? (window.crypto || window.msCrypto)
          : (typeof crypto !== "undefined" ? crypto : null);

        if (!cryptoObj || !cryptoObj.subtle) {
          console.warn("[SettingsManager] WebCrypto subtle API unavailable; falling back to plaintext-safe mode.");
          return null;
        }

        let rawB64 = null;
        if (typeof localStorage !== "undefined") {
          rawB64 = localStorage.getItem(this.CRYPTO_KEY_NAME);
        }

        let raw;
        if (rawB64) {
          raw = base64ToBytes(rawB64);
        } else {
          raw = new Uint8Array(32); // 256 bits
          cryptoObj.getRandomValues(raw);
          if (typeof localStorage !== "undefined") {
            localStorage.setItem(this.CRYPTO_KEY_NAME, bytesToBase64(raw));
          }
        }

        this._cryptoKey = await cryptoObj.subtle.importKey(
          "raw",
          raw,
          "AES-GCM",
          false,
          ["encrypt", "decrypt"]
        );
        return this._cryptoKey;
      } catch (err) {
        console.warn("[SettingsManager] WebCrypto key generation failed; falling back to plaintext:", err);
        return null;
      } finally {
        this._cryptoKeyPromise = null;
      }
    })();

    return this._cryptoKeyPromise;
  }

  /**
   * Encrypts arbitrary serializable objects into AES-GCM base64 format.
   * Format: IV (12 bytes / 96 bits) + Ciphertext + Auth Tag.
   * @private
   */
  static async _encrypt(obj) {
    try {
      const key = await this._getCryptoKey();
      if (!key) return null;

      const cryptoObj = typeof window !== "undefined"
        ? (window.crypto || window.msCrypto)
        : (typeof crypto !== "undefined" ? crypto : null);
      if (!cryptoObj || !cryptoObj.subtle) return null;

      const iv = new Uint8Array(12); // Recommended 96-bit IV for AES-GCM
      cryptoObj.getRandomValues(iv);

      const encoded = new TextEncoder().encode(JSON.stringify(obj));
      const ciphertext = await cryptoObj.subtle.encrypt(
        { name: "AES-GCM", iv },
        key,
        encoded
      );

      const combined = new Uint8Array(iv.length + ciphertext.byteLength);
      combined.set(iv, 0);
      combined.set(new Uint8Array(ciphertext), iv.length);

      return bytesToBase64(combined);
    } catch (err) {
      console.warn("[SettingsManager] Encryption failed; falling back to unencrypted storage:", err);
      return null;
    }
  }

  /**
   * Decrypts AES-GCM base64 payload.
   * @private
   */
  static async _decrypt(b64) {
    try {
      const key = await this._getCryptoKey();
      if (!key) return null;

      const cryptoObj = typeof window !== "undefined"
        ? (window.crypto || window.msCrypto)
        : (typeof crypto !== "undefined" ? crypto : null);
      if (!cryptoObj || !cryptoObj.subtle) return null;

      const blob = base64ToBytes(b64);
      // AES-GCM has 12-byte IV + 16-byte authentication tag = 28 bytes minimum
      if (blob.length < 28) return null;

      const iv = blob.slice(0, 12);
      const ciphertext = blob.slice(12);

      const decrypted = await cryptoObj.subtle.decrypt(
        { name: "AES-GCM", iv },
        key,
        ciphertext
      );

      return JSON.parse(new TextDecoder().decode(decrypted));
    } catch (err) {
      console.warn("[SettingsManager] Decryption failed:", err);
      return null;
    }
  }

  /**
   * Deeply merges stored settings with defaults to guarantee all expected fields exist.
   * @private
   */
  static _merge(parsed) {
    const defaults = this.getDefaults();
    return {
      apiKeys: { ...defaults.apiKeys, ...(parsed?.apiKeys || {}) },
      customEndpoints: { ...defaults.customEndpoints, ...(parsed?.customEndpoints || {}) },
      providerModels: { ...defaults.providerModels, ...(parsed?.providerModels || {}) },
      preferences: { ...defaults.preferences, ...(parsed?.preferences || {}) },
    };
  }

  /**
   * Loads settings from localStorage. Decrypts if encrypted (`enc:` prefix),
   * seamlessly upgrades legacy plaintext storage, and merges with defaults.
   * @returns {Promise<Object>} Safe merged settings object
   */
  static async load() {
    try {
      if (typeof localStorage === "undefined") {
        this._cachedSettings = this.getDefaults();
        return this.getDefaults();
      }

      const raw = localStorage.getItem(this.STORAGE_KEY);
      if (!raw) {
        this._cachedSettings = this.getDefaults();
        return this.getDefaults();
      }

      if (raw.startsWith("enc:")) {
        const decrypted = await this._decrypt(raw.slice(4));
        const merged = decrypted ? this._merge(decrypted) : this.getDefaults();
        this._cachedSettings = merged;
        return merged;
      }

      // Legacy plaintext migration path: parse, merge, and save encrypted
      const legacy = JSON.parse(raw);
      const merged = this._merge(legacy);
      this._cachedSettings = merged;
      await this.save(merged);
      return merged;
    } catch (err) {
      console.warn("[SettingsManager] Failed to load settings from storage; returning defaults:", err);
      this._cachedSettings = this.getDefaults();
      return this.getDefaults();
    }
  }

  /**
   * Encrypts and writes settings object to localStorage.
   * @param {Object} settings 
   * @returns {Promise<Object>} The persisted settings object
   */
  static async save(settings) {
    try {
      const merged = this._merge(settings);
      this._cachedSettings = merged;

      if (typeof localStorage === "undefined") return merged;

      const enc = await this._encrypt(merged);
      if (enc) {
        localStorage.setItem(this.STORAGE_KEY, "enc:" + enc);
      } else {
        localStorage.setItem(this.STORAGE_KEY, JSON.stringify(merged));
      }
      return merged;
    } catch (err) {
      console.error("[SettingsManager] Failed to save settings to storage:", err);
      return this._merge(settings);
    }
  }

  /**
   * Clears configured API keys and custom endpoints while preserving user preferences and model tier selections.
   */
  static async clearKeys() {
    const settings = await this.load();
    const defaults = this.getDefaults();
    settings.apiKeys = { ...defaults.apiKeys };
    settings.customEndpoints = { ...defaults.customEndpoints };
    await this.save(settings);
    return settings;
  }

  /**
   * Generates authentication and routing headers for engine calls.
   * @returns {Promise<Record<string, string>>}
   */
  static async getHeaders() {
    const settings = await this.load();
    const headers = { "Content-Type": "application/json" };

    const keys = settings.apiKeys || {};
    if (keys.gemini?.trim()) headers["X-Gemini-Key"] = keys.gemini.trim();
    if (keys.groq?.trim()) headers["X-Groq-Key"] = keys.groq.trim();
    if (keys.openrouter?.trim()) headers["X-OpenRouter-Key"] = keys.openrouter.trim();
    if (keys.openai?.trim()) headers["X-OpenAI-Key"] = keys.openai.trim();
    if (keys.custom?.trim()) headers["X-Custom-Key"] = keys.custom.trim();

    const customUrl = (settings.customEndpoints?.custom || "").trim();
    if (customUrl) {
      headers["X-Custom-Base-URL"] = customUrl;
      headers["X-Custom-Endpoint"] = customUrl;
    }

    const providerModels = settings.providerModels || {};
    if (providerModels.custom?.trim()) {
      headers["X-Custom-Model"] = providerModels.custom.trim();
    }
    if (providerModels.geminiTier1?.trim()) {
      headers["X-Gemini-Tier1-Model"] = providerModels.geminiTier1.trim();
    }
    if (providerModels.groqTier2?.trim()) {
      headers["X-Groq-Tier2-Model"] = providerModels.groqTier2.trim();
    }
    if (providerModels.geminiTier3?.trim()) {
      headers["X-Gemini-Tier3-Model"] = providerModels.geminiTier3.trim();
    }
    if (providerModels.groqTier4?.trim()) {
      headers["X-Groq-Tier4-Model"] = providerModels.groqTier4.trim();
    }
    if (providerModels.groqTier5?.trim()) {
      headers["X-Groq-Tier5-Model"] = providerModels.groqTier5.trim();
    }
    if (providerModels.geminiTier6?.trim()) {
      headers["X-Gemini-Tier6-Model"] = providerModels.geminiTier6.trim();
    }

    return headers;
  }
}

/**
 * Centralized API Fetch Helper
 * Injects stored API keys and custom endpoints into outgoing requests.
 * Safely handles FormData/Blob uploads, case-insensitive headers, and signal passthrough.
 * 
 * @param {string|URL} url - Request target URL
 * @param {RequestInit} [options={}] - Standard Fetch options
 * @returns {Promise<Response>}
 */
async function apiFetch(url, options = {}) {
  const defaultHeaders = await SettingsManager.getHeaders();
  
  // Normalize incoming headers from options case-insensitively
  const customHeaders = {};
  if (options.headers) {
    if (typeof Headers !== "undefined" && options.headers instanceof Headers) {
      options.headers.forEach((value, key) => {
        customHeaders[key] = value;
      });
    } else if (Array.isArray(options.headers)) {
      for (const [key, value] of options.headers) {
        customHeaders[key] = value;
      }
    } else if (typeof options.headers === "object") {
      Object.assign(customHeaders, options.headers);
    }
  }

  const mergedHeaders = { ...defaultHeaders };

  // Apply custom headers, overriding default headers with case normalization
  for (const [key, value] of Object.entries(customHeaders)) {
    const lowerKey = key.toLowerCase();
    // Remove existing matching keys with different casing
    for (const existingKey of Object.keys(mergedHeaders)) {
      if (existingKey.toLowerCase() === lowerKey && existingKey !== key) {
        delete mergedHeaders[existingKey];
      }
    }
    mergedHeaders[key] = value;
  }

  // If payload is FormData or Blob, avoid overriding multipart boundary
  const isFormOrBlob =
    (typeof FormData !== "undefined" && options.body instanceof FormData) ||
    (typeof Blob !== "undefined" && options.body instanceof Blob);

  if (isFormOrBlob) {
    const hasExplicitContentType = Object.keys(customHeaders).some(
      (k) => k.toLowerCase() === "content-type"
    );
    if (!hasExplicitContentType) {
      for (const k of Object.keys(mergedHeaders)) {
        if (k.toLowerCase() === "content-type") {
          delete mergedHeaders[k];
        }
      }
    }
  }

  return fetch(url, { ...options, headers: mergedHeaders });
}

// Global browser window attachment for non-bundled scripts / vanilla script tags
if (typeof window !== "undefined") {
  window.SettingsManager = SettingsManager;
  window.apiFetch = apiFetch;
}
if (typeof globalThis !== "undefined") {
  globalThis.SettingsManager = SettingsManager;
  globalThis.apiFetch = apiFetch;
}

export { SettingsManager, apiFetch };
export default SettingsManager;
