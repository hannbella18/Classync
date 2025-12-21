# vision/tracker.py
import math

class CentroidTracker:
    def __init__(self, max_dist=50):
        self.max_dist = max_dist
        self.next_id = 1
        self.objects = {}  # id -> (cx, cy)

    def update(self, detections):
        # detections: list[(x1,y1,x2,y2)]
        centers = [((x1+x2)/2, (y1+y2)/2) for x1,y1,x2,y2 in detections]
        assigned = {}
        used = set()

        for oid, (ox, oy) in list(self.objects.items()):
            best_j, best_d = None, 1e9
            for j,(cx,cy) in enumerate(centers):
                if j in used: continue
                d = math.hypot(cx-ox, cy-oy)
                if d < best_d:
                    best_d, best_j = d, j
            if best_j is not None and best_d < self.max_dist:
                assigned[oid] = detections[best_j]
                used.add(best_j)
                self.objects[oid] = centers[best_j]
            else:
                # lost: keep for a bit or drop; we drop for simplicity
                self.objects.pop(oid, None)

        for j, det in enumerate(detections):
            if j in used: continue
            oid = self.next_id; self.next_id += 1
            self.objects[oid] = centers[j]
            assigned[oid] = det

        return assigned  # dict track_id -> bbox
