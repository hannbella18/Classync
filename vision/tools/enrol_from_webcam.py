# project/vision/tools/enrol_from_webcam.py
from __future__ import annotations
import os, json, time, cv2, numpy as np
from pathlib import Path
from auto_enrol import EmbedFactory

GALLERY_DIR = Path(__file__).resolve().parents[1] / "data"
GALLERY_DIR.mkdir(parents=True, exist_ok=True)
GALLERY_JSON = GALLERY_DIR / "gallery.json"

def load_gallery():
    if GALLERY_JSON.exists():
        with open(GALLERY_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    return {"students": []}  # [{name:str, emb:[...]}]

def save_gallery(data):
    with open(GALLERY_JSON, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def main():
    factory = EmbedFactory()
    print(f"[enrol] Using {factory.impl_name} emb_dim={factory.emb_dim}")

    cap = cv2.VideoCapture(1)  # change to 1 if needed
    if not cap.isOpened():
        print("[err] Cannot open camera"); return

    print("[enrol] Press SPACE to capture a face, ESC to quit.")
    while True:
        ok, frame = cap.read()
        if not ok: break

        # simple center crop as a face (good enough for enrolment)
        h, w = frame.shape[:2]
        size = min(h, w)
        y0 = (h - size) // 2; x0 = (w - size) // 2
        face = frame[y0:y0+size, x0:x0+size]
        vis = frame.copy()
        cv2.rectangle(vis, (x0,y0), (x0+size,y0+size), (0,255,255), 2)
        cv2.putText(vis, "SPACE: capture | ESC: quit", (10,30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,0), 2)
        cv2.imshow("enrol_from_webcam", vis)

        k = cv2.waitKey(1) & 0xFF
        if k == 27:
            break
        if k == 32:  # SPACE
            res = factory.embed(face)
            if not res.ok:
                print("[enrol] embed failed"); continue
            name = input("Enter student name: ").strip()
            if not name:
                print("[enrol] skipped (empty name)"); continue
            g = load_gallery()
            g["students"].append({"name": name, "emb": [float(x) for x in res.emb.tolist()]})
            save_gallery(g)
            print(f"[enrol] saved: {name} (total {len(g['students'])})")

    cap.release()
    cv2.destroyAllWindows()
    print("[enrol] done.")

if __name__ == "__main__":
    main()
