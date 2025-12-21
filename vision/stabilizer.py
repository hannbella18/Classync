from collections import deque
import time
import math

def cosine_sim(a, b, eps=1e-8):
    # a, b are 1D lists/np arrays
    dot = sum(x*y for x, y in zip(a, b))
    na  = math.sqrt(sum(x*x for x in a)) + eps
    nb  = math.sqrt(sum(y*y for y in b)) + eps
    return dot / (na * nb)

def iou_xywh(a, b):
    # a, b: (x, y, w, h)
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh

    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih   = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter    = iw * ih
    area_a   = aw * ah
    area_b   = bw * bh
    union    = area_a + area_b - inter + 1e-8
    return inter / union

class PendingEnroll:
    """Holds consecutive 'unknown' hits for one face until confirmed."""
    def __init__(self, min_hits=5, max_gap_ms=1200, iou_thr=0.20, unk_sim_lock=0.80):
        self.min_hits   = min_hits        # need this many frames in a row
        self.max_gap_ms = max_gap_ms      # allow short gaps (blinks/occlusion)
        self.iou_thr    = iou_thr         # require some box stability
        self.unk_sim_lock = unk_sim_lock  # ensure it's the same 'unknown' face
        self.reset()

    def reset(self):
        self.hits = 0
        self.last_ts_ms = 0
        self.last_bbox = None
        self.embeds = deque(maxlen=16)

    def step(self, now_ms, bbox_xywh, emb):
        """Return True when we should enroll, else False (keep buffering)."""
        same_target = True
        if self.last_bbox is not None:
            if iou_xywh(self.last_bbox, bbox_xywh) < self.iou_thr:
                same_target = False

        if self.embeds:
            # keep lock to the same unknown via embedding similarity
            if cosine_sim(self.embeds[-1], emb) < self.unk_sim_lock:
                same_target = False

        if self.last_ts_ms and (now_ms - self.last_ts_ms) > self.max_gap_ms:
            same_target = False

        if not same_target:
            # face jumped/changed: reset streak to this new one
            self.reset()

        # buffer this frame
        self.embeds.append(emb)
        self.hits += 1
        self.last_ts_ms = now_ms
        self.last_bbox = bbox_xywh

        return self.hits >= self.min_hits

    def averaged_embedding(self):
        if not self.embeds:
            return None
        d = len(self.embeds[0])
        avg = [0.0]*d
        for e in self.embeds:
            for i, v in enumerate(e):
                avg[i] += v
        return [v/len(self.embeds) for v in avg]
