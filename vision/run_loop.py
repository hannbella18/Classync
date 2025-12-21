# project/vision/run_loop.py
# ------------------------------------------------------------
# Smart Presence loop (Balanced + per-student state):
#   - YOLOv8 Awake/Drowsy via detector.Detector.predict_states()
#   - Haar face detect for ID pipeline (lightweight CPU)
#   - Centroid tracker + ArcFace embeddings + 5-frame confirm enrol
#   - Global frame stride + per-track embed throttle
#   - Per-student state: "Student_001 | Awake 0.78"
#   - Backend /api/sighting includes state + state_score
# ESC to quit
# ------------------------------------------------------------

from __future__ import annotations
import os
import cv2
import json
import time
import math
import uuid
import numpy as np
import requests
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from collections import defaultdict, deque, Counter

# ======= Balanced preset knobs =======
CAM_INDEX = int(os.getenv("CAM_INDEX", "1"))
SIM_THRESHOLD = 0.45
EVENT_COOLDOWN_S = 10
AUTO_ENROL = True
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:5001")
RECOG_ON  = 0.48   # need >= this to accept a new ID
RECOG_OFF = 0.40   # drop ID only if similarity falls below this
VOTE_WINDOW = 7    # recent frames to vote on
VOTE_NEED   = 4    # min votes for the winner name
LABEL_STICKY_MS = 900   # keep last known label for ~0.9s if a new frame says UNKNOWN
SEND_TO_BACKEND = True
COURSE_ID = "CS101"
CAMERA_ID = "LAPTOP_CAM"

# Stabilizer (7-frame confirm) knobs
ENROL_MIN_HITS = 7  # harder to auto-enrol noise
ENROL_MAX_GAP_MS = 1200
ENROL_IOU_THR = 0.20
ENROL_UNK_SIM_LOCK = 0.80
ENROL_COOLDOWN_MS  = 6000  # avoid back-to-back new IDs on the same track
AUTO_ENROL_SIM_MAX = 0.55  # only auto-enrol if best existing sim < this
DUPLICATE_SIM      = 0.62  # treat as existing (no new student) if best sim >= this

# Performance knobs (Balanced)
CAP_WIDTH = 640
CAP_HEIGHT = 480
TARGET_FPS = 30
FRAME_STRIDE = 2                 # process every 2nd frame globally
EMBED_EVERY_N_FRAMES = 3         # per track, compute embedding every 3 processed frames
YOLO_EVERY_N_FRAMES = 2          # run YOLO every 2 processed frames
DRAW_TTL_MS = 800   # how long to keep a box/label if we skip frames (ms)

# Matching YOLO -> tracked face
IOU_MATCH_THR = 0.30             # IoU threshold to attach state to a track

# =====================================

VISION_DIR = Path(__file__).resolve().parent
DATA_DIR = VISION_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
GALLERY_JSON = DATA_DIR / "gallery.json"

# ---- modules (your files) ----
from auto_enrol import EmbedFactory            # ArcFace embedder
from detector import Detector                  # YOLOv8 Awake/Drowsy

# -------------- tiny utils --------------
def l2_normalize(v: np.ndarray, eps: float = 1e-9) -> np.ndarray:
    return (v / (np.linalg.norm(v) + eps)).astype(np.float32)

def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

def xyxy_to_xywh(b: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = b
    return (x1, y1, max(0, x2 - x1), max(0, y2 - y1))

def iou_xywh(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ax2, ay2 = ax + aw, ay + ah
    bx2, by2 = bx + bw, by + bh
    ix1, iy1 = max(ax, bx), max(ay, by)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    union = aw * ah + bw * bh - inter + 1e-8
    return inter / union

def iou_xyxy(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    ua = max(0, ax2-ax1) * max(0, ay2-ay1) + max(0, bx2-bx1) * max(0, by2-by1) - inter + 1e-8
    return inter / ua

def expand_crop_xyxy(img, x1, y1, x2, y2, margin=0.15):
    """Expand a crop by a % margin, keep inside image bounds."""
    h, w = img.shape[:2]
    bw, bh = x2 - x1, y2 - y1
    dx, dy = int(bw * margin), int(bh * margin)
    nx1 = max(0, x1 - dx)
    ny1 = max(0, y1 - dy)
    nx2 = min(w, x2 + dx)
    ny2 = min(h, y2 + dy)
    return nx1, ny1, nx2, ny2

def merge_embedding_into(gallery, name, new_emb, alpha=0.15):
    # gallery in your current {"students":[{"name","emb","id"}]} format
    new_emb = np.asarray(new_emb, dtype=np.float32)
    for s in gallery.get("students", []):
        if s.get("name") == name:
            old = np.asarray(s["emb"], dtype=np.float32)
            merged = (1.0 - alpha) * old + alpha * new_emb
            # L2 normalize to keep scale consistent
            merged = merged / (np.linalg.norm(merged) + 1e-9)
            s["emb"] = merged.tolist()
            save_gallery(gallery)
            break

# -------------- gallery I/O --------------
def load_gallery() -> Dict:
    if GALLERY_JSON.exists():
        with open(GALLERY_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {"students": []}

def save_gallery(g: Dict) -> None:
    with open(GALLERY_JSON, "w", encoding="utf-8") as f:
        json.dump(g, f, indent=2)

def next_student_name(g: Dict) -> str:
    taken = {s["name"] for s in g["students"]}
    i = 1
    while True:
        cand = f"Student_{i:03d}"
        if cand not in taken:
            return cand
        i += 1

def best_match(emb: np.ndarray, g: Dict) -> Tuple[str, float, Optional[int]]:
    """
    Standard best match that applies SIM_THRESHOLD.
    Returns (name, similarity, index). If no match passes, returns ("UNKNOWN", best_score, None).
    """
    best_s = -1.0
    best_i = None
    best_name = "UNKNOWN"
    for i, s in enumerate(g["students"]):
        v = np.asarray(s["emb"], dtype=np.float32)
        s_ = cosine_sim(emb, v)
        if s_ > best_s:
            best_s, best_i, best_name = s_, i, s["name"]
    if best_s >= SIM_THRESHOLD:
        return best_name, best_s, best_i
    return "UNKNOWN", best_s, None

def best_match_raw(emb: np.ndarray, g: Dict) -> Tuple[Optional[int], Optional[str], float]:
    """Return (idx, name, best_sim) WITHOUT applying SIM_THRESHOLD (for de-dup guard)."""
    best_s = -1.0
    best_i = None
    best_name = None
    q = emb.astype(np.float32)
    q = q / (np.linalg.norm(q) + 1e-9)
    for i, s in enumerate(g.get("students", [])):
        v = np.asarray(s["emb"], dtype=np.float32)
        v = v / (np.linalg.norm(v) + 1e-9)
        s_ = float(np.dot(q, v))
        if s_ > best_s:
            best_s, best_i, best_name = s_, i, s.get("name")
    return best_i, best_name, best_s

# -------------- simple centroid tracker --------------
class CentroidTracker:
    def __init__(self, max_dist: float = 60.0, ttl: int = 30):
        self.max_dist = max_dist
        self.ttl = ttl
        self.next_id = 1
        self.objects: Dict[int, Tuple[int, int, int, int]] = {}
        self.centroids: Dict[int, Tuple[float, float]] = {}
        self.age: Dict[int, int] = {}

    @staticmethod
    def _centroid(b: Tuple[int, int, int, int]) -> Tuple[float, float]:
        x1, y1, x2, y2 = b
        return (0.5 * (x1 + x2), 0.5 * (y1 + y2))

    def update(self, boxes: List[Tuple[int, int, int, int]]) -> Dict[int, Tuple[int, int, int, int]]:
        if len(self.objects) == 0:
            for b in boxes:
                self.objects[self.next_id] = b
                self.centroids[self.next_id] = self._centroid(b)
                self.age[self.next_id] = self.ttl
                self.next_id += 1
            return dict(self.objects)

        # decay age + drop stale
        for k in list(self.age.keys()):
            self.age[k] -= 1
            if self.age[k] <= 0:
                self.objects.pop(k, None)
                self.centroids.pop(k, None)
                self.age.pop(k, None)

        # greedy nearest-centroid match
        unmatched = set(range(len(boxes)))
        assigned: Dict[int, Tuple[int, int, int, int]] = {}
        for obj_id, c in list(self.centroids.items()):
            best_j, best_d = None, 1e9
            for j in unmatched:
                cj = self._centroid(boxes[j])
                d = math.hypot(cj[0] - c[0], cj[1] - c[1])
                if d < best_d:
                    best_d, best_j = d, j
            if best_j is not None and best_d <= self.max_dist:
                b = boxes[best_j]
                assigned[obj_id] = b
                self.objects[obj_id] = b
                self.centroids[obj_id] = self._centroid(b)
                self.age[obj_id] = self.ttl
                unmatched.remove(best_j)

        # new tracks
        for j in unmatched:
            b = boxes[j]
            obj_id = self.next_id
            self.next_id += 1
            self.objects[obj_id] = b
            self.centroids[obj_id] = self._centroid(b)
            self.age[obj_id] = self.ttl
            assigned[obj_id] = b

        return assigned

# -------------- stabilizer (5-frame confirm) --------------
class PendingEnroll:
    def __init__(self, min_hits=ENROL_MIN_HITS, max_gap_ms=ENROL_MAX_GAP_MS,
                 iou_thr=ENROL_IOU_THR, unk_sim_lock=ENROL_UNK_SIM_LOCK):
        self.min_hits = min_hits
        self.max_gap_ms = max_gap_ms
        self.iou_thr = iou_thr
        self.unk_sim_lock = unk_sim_lock
        self.embeds: deque[np.ndarray] = deque(maxlen=16)
        self.last_ts_ms: int = 0
        self.last_xywh: Optional[Tuple[int, int, int, int]] = None
        self.hits: int = 0

    def reset(self):
        self.embeds.clear()
        self.last_ts_ms = 0
        self.last_xywh = None
        self.hits = 0

    def step(self, now_ms: int, xywh: Tuple[int, int, int, int], emb: np.ndarray) -> bool:
        same_target = True
        if self.last_xywh is not None and iou_xywh(self.last_xywh, xywh) < self.iou_thr:
            same_target = False
        if self.embeds:
            if cosine_sim(self.embeds[-1], emb) < self.unk_sim_lock:
                same_target = False
        if self.last_ts_ms and (now_ms - self.last_ts_ms) > self.max_gap_ms:
            same_target = False
        if not same_target:
            self.reset()
        self.embeds.append(emb)
        self.hits += 1
        self.last_ts_ms = now_ms
        self.last_xywh = xywh
        return self.hits >= self.min_hits

    def averaged_embedding(self) -> Optional[np.ndarray]:
        if not self.embeds:
            return None
        arr = np.stack(list(self.embeds), axis=0)
        avg = arr.mean(axis=0)
        return l2_normalize(avg.astype(np.float32))

# -------------- backend posting (state-aware) --------------
def post_sighting(
    name: str,
    score: float,
    bbox: Tuple[int, int, int, int],
    ts: float,
    state: Optional[str] = None,
    state_score: float = 0.0,
    student_id: str = ""
):
    if not SEND_TO_BACKEND:
        return
    try:
        payload = {
            "course_id": COURSE_ID,
            "camera_id": CAMERA_ID,
            "name": name,
            "student_id": student_id,  # <-- NEW
            "score": score,
            "bbox": {"x": bbox[0], "y": bbox[1], "w": bbox[2] - bbox[0], "h": bbox[3] - bbox[1]},
            "ts": ts,
        }
        if state is not None:
            payload["state"] = state
            payload["state_score"] = state_score

        # endpoint unified to /api/events
        r = requests.post(f"{BACKEND_URL}/api/events", json=payload, timeout=2.0)
        if r.status_code != 200:
            print(f"[post] non-200 {r.status_code}: {r.text[:160]}")

    except Exception as e:
        print(f"[post] failed: {e}")

# -------------- main loop --------------
def main():
    factory = EmbedFactory()
    print(f"[run] Using {factory.impl_name} emb_dim={factory.emb_dim}")

    # YOLOv8 Awake/Drowsy
    yolo = Detector()  # imgsz preset inside detector.py

    # Haar for face boxes (ID pipeline)
    cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if cascade.empty():
        print("[err] haarcascade not found"); return

    gallery = load_gallery()
    print(f"[run] loaded students: {len(gallery['students'])}")
    # Build a name->id map for quick lookup when posting events
    name_to_id = {s.get("name"): (s.get("id") or "") for s in gallery.get("students", [])}

    tracker = CentroidTracker(max_dist=60, ttl=30)
    last_event: Dict[str, float] = {}

    # per-track stabilizers + throttles
    pending_by_tid: Dict[int, PendingEnroll] = defaultdict(PendingEnroll)
    per_track_frame_i: Dict[int, int] = defaultdict(int)
    last_label_by_tid: Dict[int, str] = {}
    last_score_by_tid: Dict[int, float] = {}
    recent_matches_by_tid: Dict[int, deque] = defaultdict(lambda: deque(maxlen=VOTE_WINDOW))  # (name, sim)
    last_label_ts_by_tid: Dict[int, float] = {}   # tid -> last time we had a known label (ms)

    # YOLO cache: all detections this cadence
    last_yolo_dets: List[Dict] = []  # {'label','score','xyxy'}
    state_by_tid: Dict[int, Tuple[str, float, float]] = {}  # tid -> (label, score, ts)

    cap = cv2.VideoCapture(CAM_INDEX)
    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
    cap.set(cv2.CAP_PROP_FPS, TARGET_FPS)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, CAP_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, CAP_HEIGHT)

    if not cap.isOpened():
        print(f"[err] Cannot open camera index {CAM_INDEX}")
        return

    font = cv2.FONT_HERSHEY_SIMPLEX
    print("[ok] Camera opened. ESC to quit.")
    global_frame_i = 0

    draw_cache = {}  # tid -> {'bbox':(x1,y1,x2,y2), 'text':str, 'color':(B,G,R), 'ts':ms}

    def draw_overlays(frame):
        now_ms = int(time.time() * 1000)
        stale = []
        for tid, d in draw_cache.items():
            if now_ms - d['ts'] > DRAW_TTL_MS:
                stale.append(tid)
                continue
            x1, y1, x2, y2 = d['bbox']
            cv2.rectangle(frame, (x1, y1), (x2, y2), d['color'], 2)
            cv2.putText(frame, d['text'], (x1, max(20, y1 - 10)),
                        font, 0.6, d['color'], 2, cv2.LINE_AA)
        for tid in stale:
            draw_cache.pop(tid, None)

    while True:
        ok, frame = cap.read()
        if not ok:
            break
        frame = cv2.flip(frame, 1)
        global_frame_i += 1

        # --- YOLO cadence: get ALL Awake/Drowsy detections (with boxes)
        if global_frame_i % YOLO_EVERY_N_FRAMES == 0:
            # returns list of dicts: {'label','score','xyxy'}
            last_yolo_dets = yolo.predict_states(frame)

        # ---- Frame stride: skip heavy ID work on alternate frames
        if global_frame_i % FRAME_STRIDE != 0:
            draw_overlays(frame)   # draw cached boxes/labels even on skipped frames
            cv2.imshow("smart presence", frame)
            if (cv2.waitKey(1) & 0xFF) == 27:
                break
            continue

        # --- ID pipeline (Haar -> tracker -> embedding throttle -> enrol)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = cascade.detectMultiScale(gray, scaleFactor=1.2, minNeighbors=5, minSize=(70, 70))
        boxes = [(int(x), int(y), int(x + w), int(y + h)) for (x, y, w, h) in faces]

        assigned = tracker.update(boxes)

        for tid, (x1, y1, x2, y2) in assigned.items():
            if x2 <= x1 or y2 <= y1:
                continue

            # Per-track embed throttle
            per_track_frame_i[tid] += 1
            do_embed = (per_track_frame_i[tid] % EMBED_EVERY_N_FRAMES == 0)

            label_to_draw = last_label_by_tid.get(tid, "…")
            score_to_draw = last_score_by_tid.get(tid, 0.0)

            if do_embed:
                # expand crop slightly for more stable embeddings
                ex1, ey1, ex2, ey2 = expand_crop_xyxy(frame, x1, y1, x2, y2, margin=0.15)
                crop = frame[ey1:ey2, ex1:ex2]

                # (optional) resize to 112x112 if your EmbedFactory doesn't do it internally
                # crop = cv2.resize(crop, (112, 112), interpolation=cv2.INTER_LINEAR)

                res = factory.embed(crop)
                if res.ok:
                    emb = res.emb  # EmbedFactory already handles model preproc
                    now = time.time()
                    now_ms = int(now * 1000)
                    xywh = xyxy_to_xywh((x1, y1, x2, y2))

                    # 1) get both thresholded and raw matches
                    cand_name, cand_sim, _ = best_match(emb, gallery)         # uses SIM_THRESHOLD (for display)
                    raw_idx,  raw_name,  raw_sim  = best_match_raw(emb, gallery)  # ignores SIM_THRESHOLD (for de-dup)

                    # 2) push to vote window (keep UNKNOWN too)
                    recent_matches_by_tid[tid].append((cand_name, cand_sim))

                    # compute majority vote over named candidates only
                    names = [n for n, s in recent_matches_by_tid[tid] if n != "UNKNOWN"]
                    winner, winner_count = (None, 0)
                    if names:
                        counts = Counter(names)
                        winner, winner_count = counts.most_common(1)[0]

                    # average sim for the winner over the window
                    avg_sim_winner = 0.0
                    if winner:
                        sims = [s for n, s in recent_matches_by_tid[tid] if n == winner]
                        avg_sim_winner = sum(sims) / max(1, len(sims))

                    # previous label (if any)
                    prev_label = last_label_by_tid.get(tid, "")
                    prev_known = ("Unknown" not in prev_label) and (prev_label != "…")
                    prev_sim   = last_score_by_tid.get(tid, 0.0)

                    # --- Hysteresis + vote decision ---
                    decided_name = None
                    decided_sim  = 0.0

                    # Case 1: we have a clear winner with enough votes & confidence
                    if winner and winner_count >= VOTE_NEED and avg_sim_winner >= RECOG_ON:
                        decided_name = winner
                        decided_sim  = avg_sim_winner
                        last_label_ts_by_tid[tid] = now_ms

                    # Case 2: keep previous known label unless confidence has really dropped
                    elif prev_known and prev_sim >= RECOG_OFF:
                        decided_name = prev_label.split()[0]  # strip sim if present
                        decided_sim  = prev_sim

                    # Case 3: no stable ID yet → duplicate guard / auto-enrol gate / sticky fallback
                    else:
                        # (a) if raw match is already high, treat as existing (NO auto-enrol) + light merge
                        if raw_idx is not None and raw_sim >= DUPLICATE_SIM:
                            decided_name = raw_name or "Unknown"
                            decided_sim  = raw_sim
                            merge_embedding_into(gallery, decided_name, emb, alpha=0.15)

                        else:
                            # (b) consider auto-enrol ONLY if clearly far from any known student
                            if raw_sim < AUTO_ENROL_SIM_MAX:
                                # quality gates (face big & sharp enough) BEFORE buffering
                                h_face, w_face = (y2 - y1), (x2 - x1)
                                ok_size = min(h_face, w_face) >= 120
                                gray_face = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                                sharp = cv2.Laplacian(gray_face, cv2.CV_64F).var()
                                ok_sharp = sharp >= 60.0  # adjust 40–80 if needed

                                if ok_size and ok_sharp:
                                    pe = pending_by_tid[tid]
                                    cv2.putText(frame, f"NEW? ({min(pe.hits+1, ENROL_MIN_HITS)}/{ENROL_MIN_HITS})",
                                                (x1, max(20, y1 - 34)), font, 0.6, (0, 170, 255), 2, cv2.LINE_AA)

                                    last_new_ms = getattr(pe, "last_new_ms", 0)
                                    if AUTO_ENROL and (now_ms - last_new_ms) >= ENROL_COOLDOWN_MS and pe.step(now_ms, xywh, emb):
                                        avg_emb = pe.averaged_embedding()
                                        if avg_emb is None or not isinstance(avg_emb, np.ndarray) or avg_emb.size == 0:
                                            avg_emb = emb.astype(np.float32)
                                        else:
                                            avg_emb = avg_emb.astype(np.float32)

                                        new_name = next_student_name(gallery)

                                        new_id = str(uuid.uuid4())
                                        gallery["students"].append({
                                            "name": new_name,
                                            "emb": [float(x) for x in avg_emb.tolist()],
                                            "id": new_id
                                        })
                                        save_gallery(gallery)
                                        name_to_id[new_name] = new_id            # <-- keep the map in sync
                                        pe.last_new_ms = now_ms
                                        print(f"[enrol] added {new_name} ({new_id})  (total {len(gallery['students'])})")

                                        decided_name = new_name
                                        decided_sim  = 1.0
                                        pe.reset()
                                    else:
                                        decided_name = "Unknown (buffering…)" if AUTO_ENROL else "Unknown"
                                        decided_sim  = 0.0
                                else:
                                    decided_name = "Unknown"
                                    decided_sim  = 0.0
                            else:
                                # (c) close to existing but not confident yet → sticky fallback then wait
                                last_ts = last_label_ts_by_tid.get(tid, 0.0)
                                if last_ts and (now_ms - last_ts) <= LABEL_STICKY_MS and prev_known:
                                    decided_name = prev_label.split()[0]
                                    decided_sim  = prev_sim
                                else:
                                    decided_name = "Unknown"
                                    decided_sim  = 0.0

                    # --- finalize label text (BUGFIX: ensure we actually set label_to_draw/score_to_draw) ---
                    if decided_name != "Unknown" and decided_name is not None:
                        label_to_draw = f"{decided_name} {decided_sim:.2f}"
                        score_to_draw = decided_sim
                    else:
                        label_to_draw = "Unknown (buffering…)" if AUTO_ENROL else "Unknown"
                        score_to_draw = 0.0

                    # remember last decision
                    last_label_by_tid[tid] = label_to_draw
                    last_score_by_tid[tid] = score_to_draw


            # --- Match best YOLO detection to this track by IoU (xyxy boxes)
            best_det = None
            best_iou = 0.0
            for det in last_yolo_dets:
                iou = iou_xyxy(det["xyxy"], (x1, y1, x2, y2))
                if iou > best_iou:
                    best_iou, best_det = iou, det
            if best_det and best_iou >= IOU_MATCH_THR:
                state_by_tid[tid] = (best_det["label"], float(best_det["score"]), time.time())

            # Compose final label with state
            draw_color = (0, 170, 255)
            base = last_label_by_tid.get(tid, label_to_draw)
            st = state_by_tid.get(tid)
            if st:
                s_label, s_score, _ = st
                if "Unknown" in base:
                    label_draw_final = f"{base} | {s_label} {s_score:.2f}"
                else:
                    base_name = base.split()[0]  # strip similarity if present
                    label_draw_final = f"{base_name} | {s_label} {s_score:.2f}"
                if "Unknown" not in base:
                    draw_color = (0, 220, 0)  # recognized
            else:
                label_draw_final = base
                if "Unknown" not in base:
                    draw_color = (0, 220, 0)

            # throttled backend event (when we have a label to show)
            now = time.time()
            key = (last_label_by_tid.get(tid, "UNKNOWN")).split()[0] # base name w/o similarity
            sid_for_post = "" if ("Unknown" in key or key == "UNKNOWN") else name_to_id.get(key, "")
            cur_state, cur_state_score = (None, 0.0)
            if tid in state_by_tid:
                cur_state, cur_state_score, _ = state_by_tid[tid]
            if now - last_event.get(key, 0) >= EVENT_COOLDOWN_S:
                last_event[key] = now
                post_sighting(
                    key if "Unknown" not in key else "UNKNOWN",
                    last_score_by_tid.get(tid, 0.0) if "Unknown" not in key else 0.0,
                    (x1, y1, x2, y2),
                    now,
                    state=cur_state,
                    state_score=cur_state_score,
                    student_id=sid_for_post                       # <-- NEW
                )

            # draw UI
            draw_cache[tid] = {
                    'bbox': (x1, y1, x2, y2),
                    'text': label_draw_final,
                    'color': draw_color,
                    'ts': int(time.time() * 1000)
                }

        head = f"{factory.impl_name} emb_dim={factory.emb_dim} known={len(gallery['students'])} thr={SIM_THRESHOLD:.2f} 640x480 stride={FRAME_STRIDE} embed/track={EMBED_EVERY_N_FRAMES} yolo/{YOLO_EVERY_N_FRAMES}"
        cv2.putText(frame, head, (12, 28), font, 0.6, (40, 200, 40), 2, cv2.LINE_AA)

        draw_overlays(frame)

        cv2.imshow("smart presence", frame)
        if (cv2.waitKey(1) & 0xFF) == 27:
            break

    cap.release()
    cv2.destroyAllWindows()
    print("[i] Closed.")

if __name__ == "__main__":
    main()
