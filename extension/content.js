// content.js
// Classync – capture frames from Google Meet (or fallback webcam) and send to backend

console.log("[Classync] content.js loaded");

// ================= CONFIG =================
const CAPTURE_INTERVAL_MS = 1000;   // how often to grab a frame
const JPEG_QUALITY = 0.5;           // jpeg quality (lower = faster)
const IDENT_EVERY_MS = 2500;        // how often to call /api/identify
const INFER_EVERY_MS = 1000;        // how often to call /api/infer
// Stop re-identifying once already identified (only re-check occasionally)
const REIDENTIFY_EVERY_MS = 300_000; // 5 minute

const DROWSY_ALERT_INTERVAL_MS = 30_000; // min 30s between beeps
const DROWSY_ALERT_THRESHOLD = 0.70;     // confidence required to alert

// Persist join-click intent across Meet SPA navigation
const AUTOSTART_KEY = "classync_autostart_ts";

// Persist course id across pages (join -> meet)
const COURSE_KEY = "classync_course_id";

// Send verified only once per session (per student)
const VERIFIED_SENT = new Set();

// ================= STATE =================
let captureTimer = null;
let videoSource = null;
let fallbackVideo = null;
let canvas = null;
let ctx = null;

let started = false;
let IDENT = { id: null, name: null };

let inflightIdentify = false;
let inflightInfer = false;
let lastIdentifyAt = 0;
let lastInferAt = 0;

let CURRENT_SESSION_ID = null;

// course_id detected (dynamic)
let CURRENT_COURSE_ID = null;

// overlay state
let idleSeconds = 0;
let idleTimer = null;
let lastIdleReportedSeconds = 0;
let lastStateShown = "—";
let activityHandlerAttached = false;

// AUTO-START/STOP state
let pendingAutoStart = false;
let lastJoinClickAt = 0;
let inCallPollTimer = null;
let lastInCall = false;

// Audio unlock (Chrome requires user gesture for sound)
let audioUnlocked = false;
let sharedAudioCtx = null;

let identifiedAtMs = 0;
// Student-side drowsy alert settings
let lastStudentAlertAt = 0;
// ================= HELPERS =================
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

function storageSetCourseId(courseId) {
  const cid = (courseId || "").trim();
  if (!cid) return;

  CURRENT_COURSE_ID = cid;

  try { localStorage.setItem(COURSE_KEY, cid); } catch (e) {}
  try { sessionStorage.setItem(COURSE_KEY, cid); } catch (e) {}

  // best: keep across domains using chrome.storage
  try {
    if (chrome?.storage?.local) {
      chrome.storage.local.set({ [COURSE_KEY]: cid });
    }
  } catch (e) {}
}

function parseCourseIdFromJoinUrl(urlStr) {
  try {
    const u = new URL(urlStr);
    // example: http://hannbella-classync.hf.space/join/CSC4400
    const parts = (u.pathname || "").split("/").filter(Boolean);
    const joinIdx = parts.indexOf("join");
    if (joinIdx !== -1 && parts[joinIdx + 1]) {
      return decodeURIComponent(parts[joinIdx + 1]).trim();
    }
  } catch (e) {}
  return null;
}

function getCourseIdFromStoragesSync() {
  // try local/session first (same domain only)
  try {
    const a = sessionStorage.getItem(COURSE_KEY);
    if (a) return a.trim();
  } catch (e) {}
  try {
    const b = localStorage.getItem(COURSE_KEY);
    if (b) return b.trim();
  } catch (e) {}
  return null;
}

function getCourseIdFromChromeStorage() {
  return new Promise((resolve) => {
    try {
      if (!chrome?.storage?.local) return resolve(null);
      chrome.storage.local.get([COURSE_KEY], (res) => {
        const v = res?.[COURSE_KEY];
        resolve(v ? String(v).trim() : null);
      });
    } catch (e) {
      resolve(null);
    }
  });
}

async function ensureCourseId() {
  if (CURRENT_COURSE_ID) return CURRENT_COURSE_ID;

  // 1) if extension is running on join page, parse it and store it
  const fromJoin = parseCourseIdFromJoinUrl(location.href);
  if (fromJoin) {
    storageSetCourseId(fromJoin);
    return fromJoin;
  }

  // 2) try session/local (domain-scoped)
  const fromLocal = getCourseIdFromStoragesSync();
  if (fromLocal) {
    CURRENT_COURSE_ID = fromLocal;
    return fromLocal;
  }

  // 3) try chrome.storage.local (cross-domain)
  const fromChrome = await getCourseIdFromChromeStorage();
  if (fromChrome) {
    CURRENT_COURSE_ID = fromChrome;
    return fromChrome;
  }

  // 4) last resort: ask once
  const guessed = window.prompt("Enter class code (e.g. CSC4400):", "");
  if (guessed && guessed.trim()) {
    storageSetCourseId(guessed.trim());
    return guessed.trim();
  }

  return null;
}

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

// ================= OVERLAY UI =================
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

  // Header
  const row1 = document.createElement("div");
  row1.className = "mm-row";
  row1.style.justifyContent = "space-between";

  const title = document.createElement("div");
  title.style.fontWeight = "600";
  title.style.fontSize = "13px";
  
  // Create a clickable span for the label
  const labelSpan = document.createElement("span");
  labelSpan.textContent = "Name / ID: ";
  labelSpan.style.cursor = "pointer";
  labelSpan.title = "Click to reset Class ID";
  
  // Add click listener to reset ID
  labelSpan.onclick = () => {
      const newId = prompt("Enter new Class ID:", CURRENT_COURSE_ID || "");
      if (newId && newId.trim() !== "") {
          storageSetCourseId(newId.trim());
          location.reload(); // Reload to apply the new ID
      }
  };
  
  title.appendChild(labelSpan);

  const nameSpan = document.createElement("span");
  nameSpan.id = "mm-name";

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

  // Buttons
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

  const logBox = document.createElement("div");
  logBox.id = "mm-log";

  card.appendChild(row1);
  card.appendChild(row2);
  card.appendChild(statusRow);
  card.appendChild(logBox);

  root.appendChild(card);
  document.body.appendChild(root);

  // Manual fallback controls
  startBtn.addEventListener("click", () => { unlockAudioOnce(); if (!started) startCapture(); });
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

// ================= AUDIO (BEEP) =================
function unlockAudioOnce() {
  if (audioUnlocked) return;

  const AudioCtx = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtx) return;

  try {
    sharedAudioCtx = sharedAudioCtx || new AudioCtx();
    if (sharedAudioCtx.state === "suspended") sharedAudioCtx.resume();
    audioUnlocked = true;
    console.log("[Classync] Audio unlocked");
    logOverlayLine("Audio unlocked (alerts enabled).");
  } catch (e) {
    console.warn("[Classync] unlockAudioOnce failed:", e);
  }
}

function playStudentAlert() {
  try {
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (!AudioCtx) return;

    const ctxA = sharedAudioCtx || new AudioCtx();
    sharedAudioCtx = ctxA;

    if (ctxA.state === "suspended") ctxA.resume();

    const osc = ctxA.createOscillator();
    const gain = ctxA.createGain();

    osc.type = "sine";
    osc.frequency.value = 880;

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
    unlockAudioOnce();
    playStudentAlert();
  }
}

// ================= SESSION + EVENTS =================
async function ensureSessionId() {
  if (CURRENT_SESSION_ID !== null) return CURRENT_SESSION_ID;

  const courseId = await ensureCourseId();
  if (!courseId) {
    logOverlayLine("Error: no class code. Cannot create session.");
    return null;
  }

  const resp = await apiJson("/api/auto/session_from_meet", "POST", {
    course_id: courseId,         // ✅ dynamic now
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

async function sendEngagementEvent(eventType, valueObj) {
  if (!started) return;

  const courseId = await ensureCourseId();
  const sid = await ensureSessionId();
  if (!sid || !courseId) return;

  await apiJson("/api/events", "POST", {
    course_id: courseId,         // ✅ dynamic now
    camera_id: "MEET_TAB",
    student_id: IDENT.id || null,
    name: IDENT.name || IDENT.id || "Unknown",
    ts: Math.floor(Date.now() / 1000),
    session_id: sid,
    type: eventType,
    value: valueObj || null,
  });
}

// ================= VIDEO SOURCE =================
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

  // ✅ reset verified tracking safely (cannot reassign const)
  VERIFIED_SENT.clear();

  if (captureTimer) { clearInterval(captureTimer); captureTimer = null; }
  if (idleTimer) { clearInterval(idleTimer); idleTimer = null; }

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

  const TARGET = 512;
  canvas.width = TARGET;
  canvas.height = TARGET;

  const side = Math.min(vw, vh);
  const sx = (vw - side) / 2;
  const sy = (vh - side) / 2;

  ctx.drawImage(videoSource, sx, sy, side, side, 0, 0, TARGET, TARGET);
  canvas.toBlob(handleFrameBlob, "image/jpeg", JPEG_QUALITY);
}

// ================= MAIN PER-FRAME =================
async function handleFrameBlob(blob) {
  if (!blob || !started) return;

  const now = Date.now();

  // 1) IDENTIFY (only until first success, then re-check every REIDENTIFY_EVERY_MS)
  const shouldIdentify =
    (!IDENT.id) || (identifiedAtMs && (now - identifiedAtMs) >= REIDENTIFY_EVERY_MS);

    if (shouldIdentify && !inflightIdentify && now - lastIdentifyAt >= IDENT_EVERY_MS) {
    try {
      logOverlayLine("Trying face recognition…");

      const sid = CURRENT_SESSION_ID
        ? `?session_id=${encodeURIComponent(CURRENT_SESSION_ID)}`
        : "";

      const resp = await apiJpeg(`/api/identify${sid}`, blob);

      if (resp && resp.ok && resp.student_id && !resp.pending) {
        IDENT.id = resp.student_id;
        IDENT.name = resp.name || "";
        identifiedAtMs = Date.now();

        console.log("[Classync] identified:", IDENT);
        setNameIdLabel(IDENT.name || IDENT.id || "Unknown");
        logOverlayLine(`Identified as ${IDENT.name || IDENT.id || "Unknown"}.`);

        // ✅ send verified ONCE per session+student
        const sidNow = CURRENT_SESSION_ID || (await ensureSessionId());
        const courseId = await ensureCourseId();
        const key = `${sidNow}:${IDENT.id}`;

        if (sidNow && courseId && IDENT.id && !VERIFIED_SENT.has(key)) {
          VERIFIED_SENT.add(key);

          // send event type="verified" so backend can mark attendance + late logic
          await apiJson("/api/events", "POST", {
            course_id: courseId,
            camera_id: "MEET_TAB",
            student_id: IDENT.id,
            name: IDENT.name || IDENT.id,
            ts: Math.floor(Date.now() / 1000),
            session_id: sidNow,
            type: "verified",
            value: {
              method: "face_match",
              confidence: resp.score ?? null,
            },
          });

          logOverlayLine("Verified → attendance marked.");
        }
      } else {
        console.log("[Classync] identify: no match yet", resp);
        logOverlayLine("No face match yet.");
      }
    } catch (e) {
      console.warn("[Classync] identify error:", e);
      logOverlayLine("Identify error (see console).");
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

        if (typeof state === "string") {
          const s = state.trim().toLowerCase();
          if (s === "awake" || s === "alert") state = "Awake";
          else if (s.includes("drow") || s.includes("sleep") || s.includes("yawn") || s.includes("close") || s.includes("tired")) state = "Drowsy";
          else if (s === "unknown" || s === "") state = "Unknown";
          else state = state.trim();
        }

        const bbox = resp2.bbox || null;

        console.log("[Classync] infer:", state, score);

        // Student beep (local)
        maybeAlertStudent(state, score);

        // Update overlay
        const label = state === "Unknown" ? "Unknown" : `${state}`;
        if (label !== lastStateShown) {
          lastStateShown = label;
          setStateLabel(label);
          logOverlayLine(`State: ${label} (${Number(score).toFixed(3)})`);
        }

        const sid = await ensureSessionId();
        const courseId = await ensureCourseId();
        if (!sid || !courseId) return;

        await apiJson("/api/events", "POST", {
          course_id: courseId,
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

// ================= AUTO START/STOP =================
function isJoinAction(el) {
  const btn = el?.closest?.("button, div[role='button']");
  if (!btn) return false;

  const text = (btn.innerText || "").trim().toLowerCase();
  const aria = (btn.getAttribute("aria-label") || "").trim().toLowerCase();

  const keys = [
    "join now", "join", "ask to join", "request to join",
    "enter", "continue", "admit",
    "sertai", "minta untuk sertai", "mohon untuk sertai", "masuk"
  ];

  const hay = `${text} ${aria}`;
  return keys.some(k => hay.includes(k));
}

function isLeaveAction(el) {
  const btn = el?.closest?.("button, div[role='button']");
  if (!btn) return false;

  const text = (btn.innerText || "").trim().toLowerCase();
  const aria = (btn.getAttribute("aria-label") || "").trim().toLowerCase();
  const hay = `${text} ${aria}`;

  const keys = ["leave", "leave call", "hang up", "end call", "keluar", "tinggalkan", "tamat", "tamatkan"];
  return keys.some(k => hay.includes(k));
}

// In-call detection (fallback)
function detectInCall() {
  const leaveByAria = Array.from(
    document.querySelectorAll("button[aria-label], div[role='button'][aria-label]")
  ).find(el => {
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
  // A) Start when user clicks Join / Ask to join
  document.addEventListener("click", (e) => {
    if (!isJoinAction(e.target)) return;

    const now = Date.now();
    if (now - lastJoinClickAt < 1200) return;
    lastJoinClickAt = now;

    console.log("[Classync] Join button clicked -> queue auto start");
    pendingAutoStart = true;
    markAutoStartIntent();

    // unlock audio so beeps work even with auto-start
    unlockAudioOnce();

    setTimeout(() => {
      if (pendingAutoStart && !started) {
        console.log("[Classync] Auto startCapture() after join click");
        startCapture();
        pendingAutoStart = false;
      }
    }, 1500);
  }, true);

  // B) Stop immediately when user clicks Leave/End
  document.addEventListener("click", (e) => {
    if (!isLeaveAction(e.target)) return;
    console.log("[Classync] Leave clicked -> stopCapture()");
    if (started) stopCapture();
    pendingAutoStart = false;
  }, true);

  // C) Fallback poll: start once in-call is detected; stop when out-of-call
  if (inCallPollTimer) clearInterval(inCallPollTimer);

  inCallPollTimer = setInterval(() => {
    const inCall = detectInCall();

    if (inCall && (pendingAutoStart || consumeAutoStartIntent()) && !started) {
      console.log("[Classync] In-call detected after join -> auto startCapture()");
      startCapture();
      pendingAutoStart = false;
    }

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
async function init() {
  // ✅ Guard: only run overlay + capture logic on Google Meet
  if (!location.hostname.includes("meet.google.com")) {
    console.log("[Classync] Not on Meet. Skipping overlay.");
    return;
  }

  createOverlay();
  setTabStatus(document.visibilityState === "visible" ? "here" : "away");
  // Always unlock audio on the first real user gesture in Meet
  window.addEventListener("pointerdown", unlockAudioOnce, { once: true, capture: true });
  window.addEventListener("keydown", unlockAudioOnce, { once: true, capture: true });

  // Try to learn course_id early (if join page)
  const maybeJoin = parseCourseIdFromJoinUrl(location.href);
  if (maybeJoin) storageSetCourseId(maybeJoin);

  console.log("[Classync] Overlay injected.");
  const cid = await ensureCourseId();
  if (cid) logOverlayLine(`Ready. Class: ${cid}. Detection will start when you join the meeting.`);
  else logOverlayLine("Ready. Detection will start when you join the meeting.");

  setupAutoStartStop();

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
