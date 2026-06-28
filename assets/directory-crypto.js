(function () {
  "use strict";

  const COOKIE_NAME = "jfks_directory_key";
  const KEY_PREFIX = "JFKSKEY:v1:";

  function readCookie(name) {
    const entries = document.cookie ? document.cookie.split(";") : [];
    for (const entry of entries) {
      const [k, ...v] = entry.trim().split("=");
      if (k === name) {
        return decodeURIComponent(v.join("="));
      }
    }
    return "";
  }

  function writeCookie(name, value, days) {
    const expires = new Date(Date.now() + days * 24 * 60 * 60 * 1000).toUTCString();
    document.cookie = `${name}=${encodeURIComponent(value)}; expires=${expires}; path=/; SameSite=Lax`;
  }

  function stripPrefix(keyText) {
    const str = String(keyText || "").trim();
    if (str.startsWith(KEY_PREFIX)) {
      return str.slice(KEY_PREFIX.length);
    }
    return str;
  }

  function normalizeKeyInput(keyText) {
    const compact = stripPrefix(keyText).replace(/\s+/g, "");
    if (!compact) return "";

    const base64 = compact.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    try {
      const binary = atob(padded);
      if (binary.length !== 16) return "";
      return compact;
    } catch (error) {
      return "";
    }
  }

  function keyToBytes(normalizedKey) {
    const base64 = normalizedKey.replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const binary = atob(padded);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      out[i] = binary.charCodeAt(i);
    }
    return out;
  }

  function bytesFromBase64(base64Text) {
    const base64 = String(base64Text || "").replace(/-/g, "+").replace(/_/g, "/");
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4);
    const binary = atob(padded);
    const out = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      out[i] = binary.charCodeAt(i);
    }
    return out;
  }

  async function decryptEnvelope(envelope, normalizedKey) {
    const keyBytes = keyToBytes(normalizedKey);
    const cryptoKey = await crypto.subtle.importKey(
      "raw",
      keyBytes,
      { name: "AES-GCM" },
      false,
      ["decrypt"]
    );

    const iv = bytesFromBase64(envelope.nonce);
    const ciphertext = bytesFromBase64(envelope.ciphertext);

    const decrypted = await crypto.subtle.decrypt(
      { name: "AES-GCM", iv },
      cryptoKey,
      ciphertext
    );

    const text = new TextDecoder().decode(new Uint8Array(decrypted));
    return JSON.parse(text);
  }

  async function fetchJson(path) {
    const response = await fetch(path, { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Failed to fetch ${path}: ${response.status}`);
    }
    return response.json();
  }

  async function fetchDirectoryData(paths, normalizedKey) {
    let lastError = null;

    for (const path of paths) {
      try {
        const payload = await fetchJson(path);

        const isEnvelope = payload && typeof payload === "object" && payload.nonce && payload.ciphertext;
        if (isEnvelope) {
          if (!normalizedKey) {
            throw new Error("Missing decryption key. Please unlock first.");
          }
          return await decryptEnvelope(payload, normalizedKey);
        }

        return payload;
      } catch (error) {
        lastError = error;
      }
    }

    throw lastError || new Error("No data source could be loaded.");
  }

  function getUrlParams() {
    return new URLSearchParams(window.location.search);
  }

  function upsertKeyFromUrl() {
    const params = getUrlParams();
    const maybeKey = params.get("key") || "";
    const normalized = normalizeKeyInput(maybeKey);

    if (!normalized) {
      return "";
    }

    writeCookie(COOKIE_NAME, normalized, 3650);
    params.delete("key");
    const nextQuery = params.toString();
    const nextUrl = nextQuery ? `${window.location.pathname}?${nextQuery}` : window.location.pathname;
    window.history.replaceState({}, "", nextUrl);

    return normalized;
  }

  function getCookieKey() {
    const normalized = normalizeKeyInput(readCookie(COOKIE_NAME));
    return normalized || "";
  }

  function setCookieKey(keyText) {
    const normalized = normalizeKeyInput(keyText);
    if (!normalized) {
      throw new Error("Invalid key format. Expected a 128-bit key.");
    }
    writeCookie(COOKIE_NAME, normalized, 3650);
    return normalized;
  }

  function formattedKey(normalized) {
    return `${KEY_PREFIX}${normalized}`;
  }

  function startQrScanner(videoEl, onDecoded, onError) {
    if (!("BarcodeDetector" in window)) {
      onError(new Error("QR scan not supported in this browser. Use Chrome/Edge or manual key input."));
      return null;
    }

    let stop = false;
    let detector = null;
    let stream = null;

    const tick = async () => {
      if (stop || !detector || !videoEl || videoEl.readyState < 2) {
        if (!stop) requestAnimationFrame(tick);
        return;
      }

      try {
        const results = await detector.detect(videoEl);
        if (results && results.length > 0) {
          const value = results[0].rawValue || "";
          if (value) {
            stop = true;
            onDecoded(value);
            return;
          }
        }
      } catch (error) {
        onError(error);
      }

      if (!stop) requestAnimationFrame(tick);
    };

    (async () => {
      try {
        detector = new BarcodeDetector({ formats: ["qr_code"] });
        stream = await navigator.mediaDevices.getUserMedia({
          video: { facingMode: "environment" },
          audio: false
        });
        videoEl.srcObject = stream;
        await videoEl.play();
        requestAnimationFrame(tick);
      } catch (error) {
        onError(error);
      }
    })();

    return function stopScanner() {
      stop = true;
      if (videoEl) {
        videoEl.pause();
        videoEl.srcObject = null;
      }
      if (stream) {
        stream.getTracks().forEach((track) => track.stop());
      }
    };
  }

  window.DirectoryCrypto = {
    KEY_PREFIX,
    normalizeKeyInput,
    fetchDirectoryData,
    upsertKeyFromUrl,
    getCookieKey,
    setCookieKey,
    formattedKey,
    startQrScanner
  };
})();
