# project/vision/test_auto_enrol.py
# Camera smoke test for ArcFace ONNX (with NHWC/NCHW auto-detect)
# Press ESC to quit.

from __future__ import annotations
import sys
import cv2
import numpy as np

from auto_enrol import EmbedFactory

def main() -> int:
    # Build the embedder (ArcFace if model loads, else CHEAP)
    factory = EmbedFactory()
    print(f"[test] Using {factory.impl_name} emb_dim={factory.emb_dim}")

    cap = cv2.VideoCapture(1)
    if not cap.isOpened():
        print("[err] Cannot open camera")
        return 2

    font = cv2.FONT_HERSHEY_SIMPLEX
    green = (40, 200, 40)

    print("[ok] Camera opened. Press ESC to quit.")
    while True:
        ok, frame = cap.read()
        if not ok or frame is None:
            print("[err] Failed to read frame")
            break

        # take a center square crop as the 'face'
        h, w = frame.shape[:2]
        size = min(h, w)
        y0 = (h - size) // 2
        x0 = (w - size) // 2
        face = frame[y0:y0 + size, x0:x0 + size]

        # run embedding (just to exercise the pipeline)
        res = factory.embed(face)

        # draw UI
        label = f"{factory.impl_name} emb_dim={factory.emb_dim}"
        if not res.ok:
            label = f"ERR -> {label}"
        cv2.rectangle(frame, (x0, y0), (x0 + size, y0 + size), (0, 255, 255), 2)
        cv2.putText(frame, label, (12, 28), font, 0.7, green, 2, cv2.LINE_AA)

        cv2.imshow("auto_enrol test", frame)
        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            break

    cap.release()
    cv2.destroyAllWindows()
    print("[i] Closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
