// content.js
// Classync – capture frames from Google Meet (or fallback webcam) and send to backend

console.log("[Classync] content.js loaded");

// ================= CONFIG =================
const CAPTURE_INTERVAL_MS = 3000;   // how often to grab a frame
const JPEG_QUALITY = 0.6;           // jpeg quality (lower = faster)
const IDENT_EVERY_MS = 5000;        // how often to call /api/identify
const INFER_EVERY_MS = 3000;        // how often to call /api/infer

// Student-side drowsy alert settings
let lastStudentAlertAt = 0;
const DROWSY_ALERT_INTERVAL_MS = 30_000; // minimum 30s between beeps
const DROWSY_ALERT_THRESHOLD = 0.70;     // confidence required to alert

// ================= STATE =================
let captureTimer = null;
let videoSource = null;      // <video> we are capturing from
let fallbackVideo = null;    // hidden webcam video
let canvas = null;
let ctx = null;

let started = false;
let IDENT = { id: null, name: null };

let inflightIdentify = false;
let inflightInfer = false;
let lastIdentifyAt = 0;
let lastInferAt = 0;

let CURRENT_SESSION_ID = null;

// overlay state
let idleSeconds = 0;
let idleTimer = null;
let lastIdleReportedSeconds = 0;
let lastStateShown = "—";

// track user activity so Idle = time since last activity
let activityHandlerAttached = false;

// ================= HELPERS: TALK TO BACKGROUND =================

// For JSON APIs: /api/auto/session_from_meet, /stop, /api/events, etc.
function apiJson(path, method = "GET", bodyObj = null) {
  return new Promise((resolve) => {
    if (!chrome || !chrome.runtime || !chrome.runtime.sendMessage) {
      console.warn("[Classync] chrome.runtime not available");
      return resolve({ ok: false, status: 0, error: "chrome.runtime not available", data: null });
    }

    chrome.runtime.sendMessage(
      {
        type: "API_FETCH",
        path,
        method,
        headers: bodyObj ? { "Content-Type": "application/json" } : undefined,
        body: bodyObj ? JSON.stringify(bodyObj) : undefined,
      },
      (resp) => {
        if (chrome.runtime.lastError) {
          console.warn("[Classync] API_FETCH error:", chrome.runtime.lastError.message);
          return resolve({ ok: false, status: 0, error: chrome.runtime.lastError.message, data: null });
        }
        if (!resp) return resolve({ ok: false, status: 0, error: "no response from background", data: null });

        let data = null;
        try {
          data = resp.body ? JSON.parse(resp.body) : null;
        } catch (e) {
          console.warn("[Classync] apiJson parse error:", e, resp.body);
        }

        resolve({ ok: !!resp.ok, status: resp.status ?? 0, error: resp.error, data });
      }
    );
  });
}

// For JPEG APIs: /api/identify and /api/infer
function apiJpeg(path, blob) {
  return new Promise((resolve) => {
    if (!chrome || !chrome.runtime || !chrome.runtime.sendMessage) {
      console.warn("[Classync] chrome.runtime not available");
      return resolve({ ok: false, error: "chrome.runtime not available" });
    }

    const reader = new FileReader();
    reader.onloadend = () => {
      const dataUrl = reader.result; // "data:image/jpeg;base64,..."
      chrome.runtime.sendMessage(
        { type: "API_JPEG", path, dataUrl, cameraId: "MEET_TAB" },
        (resp) => {
          if (chrome.runtime.lastError) {
            console.warn("[Classync] API_JPEG error:", chrome.runtime.lastError.message);
            return resolve({ ok: false, error: chrome.runtime.lastError.message });
          }
          resolve(resp || { ok: false, error: "no response from background" });
        }
      );
    };
    reader.readAsDataURL(blob);
  });
}

// ========= Engagement events helper (idle, tab-away) =========
async function sendEngagementEvent(eventType, valueObj) {
  if (!started) return;

  const sid = await ensureSessionId();
  if (!sid) return;

  await apiJson("/api/events", "POST", {
    course_id: "CSC4400",
    camera_id: "MEET_TAB",
    student_id: IDENT.id || null,
    name: IDENT.name || IDENT.id || "Unknown",
    ts: Math.floor(Date.now() / 1000),
    session_id: sid,
    type: eventType,
    value: valueObj || null,
  });
}

// ========= Student drowsy alert (local beep) =========
function playStudentAlert() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) {
      console.warn("[Classync] No AudioContext available for alert");
      return;
    }

    const ctxA = new AudioCtx();
    const osc = ctxA.createOscillator();
    const gain = ctxA.createGain();

    osc.type = "sine";
    osc.frequency.value = 880; // high beep

    const now = ctxA.currentTime;
    gain.gain.setValueAtTime(0.001, now);
    gain.gain.exponentialRampToValueAtTime(0.2, now + 0.02);
    gain.gain.exponentialRampToValueAtTime(0.001, now + 0.4);

    osc.connect(gain);
    gain.connect(ctxA.destination);

    osc.start(now);
    osc.stop(now + 0.45);
  } catch (e) {
    console.warn("[Classync] student alert sound failed:", e);
  }
}

function maybeAlertStudent(state, score) {
  const now = Date.now();

  if (
    state === "Drowsy" &&
    typeof score === "number" &&
    score >= DROWSY_ALERT_THRESHOLD &&
    now - lastStudentAlertAt >= DROWSY_ALERT_INTERVAL_MS
  ) {
    lastStudentAlertAt = now;
    console.log("[Classync] triggering student drowsy alert", score);
    playStudentAlert();
  }
}

// ================= UI OVERLAY =================

function logOverlayLine(text) {
  const log = document.getElementById("mm-log");
  if (!log) return;

  const line = document.createElement("div");
  const ts = new Date();
  const timeStr = ts.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  line.textContent = `[${timeStr}] ${text}`;
  log.prepend(line);

  while (log.children.length > 30) log.removeChild(log.lastChild);
}

function setNameIdLabel(text) {
  const span = document.getElementById("mm-name");
  if (span) span.textContent = text;
}

function setIdleLabel(sec) {
  const span = document.getElementById("mm-idle");
  if (span) span.textContent = `${sec}s`;
}

function setTabStatus(status) {
  const span = document.getElementById("mm-tab");
  if (span) span.textContent = status;
}

function setStateLabel(state) {
  const span = document.getElementById("mm-state");
  if (span) span.textContent = state;
}

function resetIdleTimer() {
  if (!started) return;
  idleSeconds = 0;
  lastIdleReportedSeconds = 0;
  setIdleLabel(idleSeconds);
}

function handleUserActivity() {
  resetIdleTimer();
}

function setOverlayRunning(running) {
  const startBtn = document.getElementById("mm-start");
  const stopBtn = document.getElementById("mm-stop");
  if (!startBtn || !stopBtn) return;

  if (running) {
    startBtn.disabled = true;
    stopBtn.disabled = false;
  } else {
    startBtn.disabled = false;
    stopBtn.disabled = true;
    setStateLabel("—");
  }
}

function createOverlay() {
  if (document.getElementById("meet-monitor-overlay")) return;

  const root = document.createElement("div");
  root.id = "meet-monitor-overlay";

  const card = document.createElement("div");
  card.className = "mm-card";

  // Header: name / id
  const row1 = document.createElement("div");
  row1.className = "mm-row";
  row1.style.justifyContent = "space-between";

  const title = document.createElement("div");
  title.style.fontWeight = "600";
  title.style.fontSize = "13px";
  title.textContent = "Name / ID: ";

  const nameSpan = document.createElement("span");
  nameSpan.id = "mm-name";

  // animated "Detecting..."
  const detect = document.createElement("span");
  detect.id = "mm-detecting";
  detect.textContent = "Detecting";
  const dots = document.createElement("span");
  dots.className = "mm-dots";
  dots.textContent = "...";
  detect.appendChild(dots);
  nameSpan.appendChild(detect);

  title.appendChild(nameSpan);
  row1.appendChild(title);

  const spacer = document.createElement("div");
  spacer.style.width = "16px";
  row1.appendChild(spacer);

  // Row 2: buttons
  const row2 = document.createElement("div");
  row2.className = "mm-row";

  const startBtn = document.createElement("button");
  startBtn.id = "mm-start";
  startBtn.textContent = "Start";

  const stopBtn = document.createElement("button");
  stopBtn.id = "mm-stop";
  stopBtn.textContent = "Stop";
  stopBtn.disabled = true;

  const lectBtn = document.createElement("button");
  lectBtn.id = "mm-lecturer";
  lectBtn.textContent = "Lecturer";
  lectBtn.disabled = true;

  row2.appendChild(startBtn);
  row2.appendChild(stopBtn);
  row2.appendChild(lectBtn);

  // Status row
  const statusRow = document.createElement("div");
  statusRow.className = "mm-status";

  const idleSpan = document.createElement("span");
  idleSpan.innerHTML = 'Idle: <span id="mm-idle">0s</span>';

  const tabSpan = document.createElement("span");
  tabSpan.innerHTML = 'Tab: <span id="mm-tab">here</span>';

  const stateSpan = document.createElement("span");
  stateSpan.innerHTML = 'State: <span id="mm-state">—</span>';

  statusRow.appendChild(idleSpan);
  statusRow.appendChild(tabSpan);
  statusRow.appendChild(stateSpan);

  // Log area
  const logBox = document.createElement("div");
  logBox.id = "mm-log";

  card.appendChild(row1);
  card.appendChild(row2);
  card.appendChild(statusRow);
  card.appendChild(logBox);

  root.appendChild(card);
  document.body.appendChild(root);

  // Manual fallback controls
  startBtn.addEventListener("click", () => { if (!started) startCapture(); });
  stopBtn.addEventListener("click", () => { if (started) stopCapture(); });

  logOverlayLine("Overlay ready.");
}

// Track tab visibility
document.addEventListener("visibilitychange", () => {
  const visible = document.visibilityState === "visible";
  setTabStatus(visible ? "here" : "away");

  if (!started) return;
  if (visible) sendEngagementEvent("tab_back", null);
  else sendEngagementEvent("tab_away", null);
});

// ================= SESSION HELPER =================
async function ensureSessionId() {
  if (CURRENT_SESSION_ID !== null) return CURRENT_SESSION_ID;

  const resp = await apiJson("/api/auto/session_from_meet", "POST", {
    course_id: "CSC4400",
    meet_url: location.href,
    title: document.title || "",
  });

  if (!resp.ok || !resp.data || !resp.data.ok) {
    console.warn("[Classync] session_from_meet failed:", resp);
    logOverlayLine("Failed to create session.");
    return null;
  }

  CURRENT_SESSION_ID = resp.data.session_id || null;
  console.log("[Classync] Session id:", CURRENT_SESSION_ID);
  logOverlayLine(`Session id: ${CURRENT_SESSION_ID}`);
  return CURRENT_SESSION_ID;
}

// ================= VIDEO SOURCE PICKER =================
function pickMeetVideo() {
  const videos = Array.from(document.querySelectorAll("video"));
  if (!videos.length) return null;

  let best = null;
  let bestArea = 0;
  for (const v of videos) {
    const w = v.videoWidth || v.clientWidth;
    const h = v.videoHeight || v.clientHeight;
    const area = w * h;
    if (area > bestArea && w >= 200 && h >= 150) {
      best = v;
      bestArea = area;
    }
  }
  return best;
}

// Fallback: webcam using getUserMedia
async function ensureFallbackCamera() {
  if (fallbackVideo && fallbackVideo.srcObject) return fallbackVideo;

  fallbackVideo = document.createElement("video");
  fallbackVideo.autoplay = true;
  fallbackVideo.muted = true;
  fallbackVideo.playsInline = true;
  fallbackVideo.style.position = "fixed";
  fallbackVideo.style.bottom = "-9999px";
  fallbackVideo.style.right = "-9999px";
  fallbackVideo.style.width = "0";
  fallbackVideo.style.height = "0";
  document.body.appendChild(fallbackVideo);

  try {
    const stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
    fallbackVideo.srcObject = stream;
    await fallbackVideo.play();
    logOverlayLine("Fallback camera active.");
    return fallbackVideo;
  } catch (err) {
    console.error("[Classync] getUserMedia error:", err);
    logOverlayLine("Error: cannot access fallback camera.");
    return null;
  }
}

// ================= CAPTURE LOOP =================
async function startCapture() {
  if (started) return;

  createOverlay();
  setOverlayRunning(true);
  started = true;

  idleSeconds = 0;
  lastIdleReportedSeconds = 0;
  setIdleLabel(idleSeconds);

  if (idleTimer) clearInterval(idleTimer);
  idleTimer = setInterval(() => {
    idleSeconds++;
    setIdleLabel(idleSeconds);

    if (!started) return;

    const delta = idleSeconds - lastIdleReportedSeconds;
    if (idleSeconds >= 10 && delta >= 10) {
      lastIdleReportedSeconds = idleSeconds;
      sendEngagementEvent("idle", { duration_s: delta });
    }
  }, 1000);

  // Track activity
  if (!activityHandlerAttached) {
    window.addEventListener("mousemove", handleUserActivity);
    window.addEventListener("keydown", handleUserActivity);
    window.addEventListener("click", handleUserActivity);
    window.addEventListener("scroll", handleUserActivity, true);
    activityHandlerAttached = true;
  }

  let vid = pickMeetVideo();
  if (!vid) {
    logOverlayLine("No Meet video yet — using fallback camera.");
    console.warn("[Classync] No Meet video found, using fallback webcam.");
    vid = await ensureFallbackCamera();
  } else {
    logOverlayLine("Using Meet video as source.");
  }

  if (!vid) {
    console.error("[Classync] No video source available for capture.");
    logOverlayLine("Error: no video source.");
    setOverlayRunning(false);
    started = false;
    if (idleTimer) { clearInterval(idleTimer); idleTimer = null; }
    return;
  }

  videoSource = vid;

  canvas = document.createElement("canvas");
  ctx = canvas.getContext("2d", { willReadFrequently: true });

  await ensureSessionId();

  captureTimer = setInterval(captureFrame, CAPTURE_INTERVAL_MS);
  console.log("[Classync] Capture started.");
  logOverlayLine("Started.");
}

function stopCapture() {
  if (!started) return;

  started = false;

  if (captureTimer) { clearInterval(captureTimer); captureTimer = null; }
  if (idleTimer) { clearInterval(idleTimer); idleTimer = null; }

  // Stop tracking activity
  if (activityHandlerAttached) {
    window.removeEventListener("mousemove", handleUserActivity);
    window.removeEventListener("keydown", handleUserActivity);
    window.removeEventListener("click", handleUserActivity);
    window.removeEventListener("scroll", handleUserActivity, true);
    activityHandlerAttached = false;
  }

  setOverlayRunning(false);
  console.log("[Classync] Capture stopped.");
  logOverlayLine("Stopped.");

  // Best-effort stop on backend
  (async () => {
    try {
      const sid = CURRENT_SESSION_ID;
      CURRENT_SESSION_ID = null;
      if (!sid) return;
      await apiJson("/stop", "POST", { session_id: sid });
    } catch (e) {
      console.warn("[Classync] stop session error:", e);
    }
  })();
}

function captureFrame() {
  if (!started || !videoSource || !canvas || !ctx) return;

  const vw = videoSource.videoWidth || videoSource.clientWidth;
  const vh = videoSource.videoHeight || videoSource.clientHeight;

  if (!vw || !vh) {
    console.warn("[Classync] Video not ready yet.");
    return;
  }

  // Downscale + center-crop to model size
  const TARGET = 512;
  canvas.width = TARGET;
  canvas.height = TARGET;

  const side = Math.min(vw, vh);
  const sx = (vw - side) / 2;
  const sy = (vh - side) / 2;

  ctx.drawImage(videoSource, sx, sy, side, side, 0, 0, TARGET, TARGET);

  canvas.toBlob(handleFrameBlob, "image/jpeg", JPEG_QUALITY);
}

// Main per-frame logic: identify face, then infer awake/drowsy
async function handleFrameBlob(blob) {
  if (!blob || !started) return;

  const now = Date.now();

  // 1) IDENTIFY
  if (!IDENT.id && !inflightIdentify && now - lastIdentifyAt >= IDENT_EVERY_MS) {
    inflightIdentify = true;
    lastIdentifyAt = now;

    try {
      const sid = CURRENT_SESSION_ID ? `?session_id=${encodeURIComponent(CURRENT_SESSION_ID)}` : "";
      const resp = await apiJpeg(`/api/identify${sid}`, blob);

      if (resp && resp.ok && resp.student_id && !resp.pending) {
        IDENT.id = resp.student_id;
        IDENT.name = resp.name || "";
        console.log("[Classync] identified:", IDENT);
        setNameIdLabel(IDENT.name || IDENT.id || "Unknown");
        logOverlayLine(`Identified as ${IDENT.name || IDENT.id || "Unknown"}.`);
      } else {
        console.log("[Classync] identify: no match yet", resp);
      }
    } catch (e) {
      console.warn("[Classync] identify error:", e);
    } finally {
      inflightIdentify = false;
    }
  }

  // 2) INFER
  if (!inflightInfer && now - lastInferAt >= INFER_EVERY_MS) {
    inflightInfer = true;
    lastInferAt = now;

    try {
      const sid2 = CURRENT_SESSION_ID ? `?session_id=${encodeURIComponent(CURRENT_SESSION_ID)}` : "";
      const resp2 = await apiJpeg(`/api/infer${sid2}`, blob);

      if (resp2 && resp2.ok) {
        let state =
          resp2.state ??
          resp2.label ??
          resp2.class_name ??
          resp2.class ??
          "Unknown";

        let score =
          (typeof resp2.state_score === "number" ? resp2.state_score : null) ??
          (typeof resp2.score === "number" ? resp2.score : null) ??
          (typeof resp2.confidence === "number" ? resp2.confidence : null) ??
          0;

        // Normalize label
        if (typeof state === "string") {
          const s = state.trim().toLowerCase();
          if (s === "awake" || s === "alert") state = "Awake";
          else if (s.includes("drow") || s.includes("sleep") || s.includes("yawn") || s.includes("close") || s.includes("tired")) state = "Drowsy";
          else if (s === "unknown" || s === "") state = "Unknown";
          else state = state.trim();
        }

        const bbox = resp2.bbox || null;

        console.log("[Classync] infer:", state, score);

        // Student-side alert
        maybeAlertStudent(state, score);

        // Update overlay
        const label = state === "Unknown" ? "Unknown" : `${state}`;
        if (label !== lastStateShown) {
          lastStateShown = label;
          setStateLabel(label);
          logOverlayLine(`State: ${label} (${Number(score).toFixed(3)})`);
        }

        const sid = await ensureSessionId();
        await apiJson("/api/events", "POST", {
          course_id: "CSC4400",
          camera_id: "MEET_TAB",
          student_id: IDENT.id || null,
          name: IDENT.name || IDENT.id || "Unknown",
          ts: Math.floor(Date.now() / 1000),
          session_id: sid,
          state,
          state_score: score,
          bbox,
        });
      } else {
        console.warn("[Classync] infer failed:", resp2);
      }
    } catch (e) {
      console.warn("[Classync] infer error:", e);
    } finally {
      inflightInfer = false;
    }
  }
}

// ================= AUTO-START/STOP (JOIN CLICK + FALLBACK) =================

// Persist join-click intent across Meet SPA navigation
const AUTOSTART_KEY = "classync_autostart_ts";

function markAutoStartIntent() {
  try { sessionStorage.setItem(AUTOSTART_KEY, String(Date.now())); } catch (e) {}
}

function consumeAutoStartIntent(maxAgeMs = 15_000) {
  try {
    const v = sessionStorage.getItem(AUTOSTART_KEY);
    if (!v) return false;
    const ts = parseInt(v, 10);
    const ok = Number.isFinite(ts) && (Date.now() - ts) <= maxAgeMs;
    if (ok) sessionStorage.removeItem(AUTOSTART_KEY);
    return ok;
  } catch (e) {
    return false;
  }
}

function isJoinAction(el) {
  const btn = el?.closest?.("button, div[role='button']");
  if (!btn) return false;

  const text = (btn.innerText || "").trim().toLowerCase();
  const aria = (btn.getAttribute("aria-label") || "").trim().toLowerCase();

  const keys = [
    "join now", "join", "ask to join", "request to join",
    "enter", "continue", "admit",
    // Malay common labels
    "sertai", "minta untuk sertai", "mohon untuk sertai", "masuk"
  ];

  const hay = `${text} ${aria}`;
  return keys.some(k => hay.includes(k));
}

let pendingAutoStart = false;
let lastJoinClickAt = 0;

let inCallPollTimer = null;
let lastInCall = false;

function detectInCall() {
  const leaveByAria = Array.from(document.querySelectorAll("button[aria-label], div[role='button'][aria-label]"))
    .find(el => {
      const a = (el.getAttribute("aria-label") || "").toLowerCase();
      return a.includes("leave") || a.includes("hang up") || a.includes("end call") ||
             a.includes("keluar") || a.includes("tamat") || a.includes("tinggalkan");
    });
  if (leaveByAria) return true;

  const vids = document.querySelectorAll("video");
  if (vids && vids.length >= 1) {
    const buttons = document.querySelectorAll("button, div[role='button']");
    if (buttons.length > 10) return true;
  }
  return false;
}

function setupAutoStartStop() {
  // (A) Start when user clicks Join / Ask to join
  document.addEventListener("click", (e) => {
    if (!isJoinAction(e.target)) return;

    const now = Date.now();
    if (now - lastJoinClickAt < 1200) return;
    lastJoinClickAt = now;

    console.log("[Classync] Join button clicked -> queue auto start");
    pendingAutoStart = true;
    markAutoStartIntent(); // survive Meet navigation/re-render

    // Try to start shortly after click (may still work if no navigation)
    setTimeout(() => {
      if (pendingAutoStart && !started) {
        console.log("[Classync] Auto startCapture() after join click");
        startCapture();
        pendingAutoStart = false;
      }
    }, 1500);
  }, true); // capture phase helps catch Meet internal handlers

  // (B) Fallback: start once "in-call" is detected (if join causes re-render)
  if (inCallPollTimer) clearInterval(inCallPollTimer);

  inCallPollTimer = setInterval(() => {
    const inCall = detectInCall();

    // If user clicked Join earlier and we are now in-call, start.
    if (inCall && (pendingAutoStart || consumeAutoStartIntent()) && !started) {
      console.log("[Classync] In-call detected after join -> auto startCapture()");
      startCapture();
      pendingAutoStart = false;
    }

    // Auto-stop when leaving call
    if (!inCall && lastInCall) {
      console.log("[Classync] Out-of-call detected -> auto stopCapture()");
      if (started) stopCapture();
      pendingAutoStart = false;
    }

    lastInCall = inCall;
  }, 800);

  window.addEventListener("beforeunload", () => {
    if (started) stopCapture();
  });
}

// ================= INIT =================
function init() {
  createOverlay();
  setTabStatus(document.visibilityState === "visible" ? "here" : "away");

  console.log("[Classync] Overlay injected.");
  logOverlayLine("Ready. Detection will start when you join the meeting.");

  setupAutoStartStop();

  // If Meet navigated after join click, start on page load
  if (!started && consumeAutoStartIntent()) {
    console.log("[Classync] Auto-start intent found on init -> starting");
    setTimeout(() => { if (!started) startCapture(); }, 1200);
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", init);
} else {
  init();
}
