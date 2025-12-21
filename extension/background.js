// background.js - MV3 service worker for Classync
// Proxies all network calls to the Flask backend so content.js
// doesn't hit CORS / private network rules.

try {
  importScripts("config.js");
} catch (e) {
  console.warn("[Classync] config load failed:", e);
}

const NGROK_HDR = { "ngrok-skip-browser-warning": "1" };

// Decide which base URL to use (API_BASE from config.js or localhost)
async function getApiBase() {
  // Always use the URL from config.js
  if (typeof self.API_BASE === "string" && self.API_BASE.trim()) {
    return self.API_BASE.trim().replace(/\/+$/, "");
  }
  return "https://hannbella-classync.hf.space";
}

let RESOLVED_API_BASE = null;

async function apiFetch(path, options = {}) {
  if (!RESOLVED_API_BASE) {
    RESOLVED_API_BASE = await getApiBase();
  }
  const url = RESOLVED_API_BASE.replace(/\/+$/, "") + path;
  const headers = {
    ...(options.headers || {}),
    ...NGROK_HDR,
  };
  const method = options.method || "GET";
  const body = options.body;

  return fetch(url, { method, headers, body });
}

// ----------------- Message router -----------------
chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return;

  // 1) Generic JSON proxy (used by ensureSessionId, /stop, /api/events, etc.)
  if (msg.type === "API_FETCH") {
    apiFetch(msg.path, {
      method: msg.method || "GET",
      headers: msg.headers,
      body: msg.body,
    })
      .then(async (res) => {
        const text = await res.text();
        sendResponse({
          ok: res.ok,
          status: res.status,
          body: text,
        });
      })
      .catch((err) => {
        console.error("[Classync] API_FETCH error in background:", err);
        sendResponse({
          ok: false,
          status: 0,
          error: String(err),
          body: "",
        });
      });
    return true; // keep the message channel open
  }

  // 2) JPEG proxy (used by /api/identify and /api/infer)
  if (msg.type === "API_JPEG") {
    (async () => {
      try {
        // msg.dataUrl is a "data:image/jpeg;base64,...." string
        const response = await fetch(msg.dataUrl);
        const blob = await response.blob();

        const fd = new FormData();
        fd.append("frame", blob, "frame.jpg");
        fd.append("camera_id", msg.cameraId || "MEET_TAB");

        const res = await apiFetch(msg.path || "/api/identify", {
          method: "POST",
          body: fd,
        });

        const text = await res.text();
        let data;
        try {
          data = text ? JSON.parse(text) : null;
        } catch (e) {
          console.warn("[Classync] API_JPEG JSON parse error:", e, text);
          data = { raw: text };
        }
        if (data && typeof data === "object" && !("ok" in data)) {
          data.ok = res.ok;
        }
        sendResponse(data);
      } catch (err) {
        console.error("[Classync] API_JPEG error in background:", err);
        sendResponse({ ok: false, error: String(err) });
      }
    })();
    return true; // keep the message channel open
  }
});
