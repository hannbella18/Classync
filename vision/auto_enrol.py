# project/vision/auto_enrol.py
# ------------------------------------------------------------
# ArcFace ONNX embedder with automatic NHWC/NCHW handling.
# Falls back to a simple 1024-D "cheap" embedding if ONNX fails.
# ------------------------------------------------------------

from __future__ import annotations
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional, Tuple, List

import cv2
import numpy as np

try:
    import onnxruntime as ort  # type: ignore
except Exception:
    ort = None  # We'll handle gracefully


# ---------- utils ----------

def l2_normalize(v: np.ndarray, eps: float = 1e-9) -> np.ndarray:
    n = np.linalg.norm(v) + eps
    return (v / n).astype(np.float32)


def cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float32)
    b = b.astype(np.float32)
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))


# ---------- Embedders ----------

@dataclass
class EmbedResult:
    emb: np.ndarray
    ok: bool
    error: Optional[str] = None


class CheapEmbedder:
    """Very fast CPU-only 1024-D embedding as a last-resort fallback."""
    emb_dim: int = 1024
    name: str = "CHEAP"

    def __init__(self) -> None:
        pass

    def embed(self, face_bgr: np.ndarray) -> EmbedResult:
        try:
            # convert to grayscale, fixed 32x32 -> 1024 dims
            g = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
            g = (g - g.mean()) / (g.std() + 1e-6)
            emb = g.flatten()
            emb = l2_normalize(emb)
            return EmbedResult(emb=emb, ok=True)
        except Exception as e:
            return EmbedResult(emb=np.zeros((self.emb_dim,), np.float32), ok=False, error=str(e))


class ArcFaceONNX:
    """
    ArcFace ONNX embedder.
    Automatically detects input layout:
      - NCHW: (1, 3, 112, 112)
      - NHWC: (1, 112, 112, 3)
    """
    name: str = "ArcFace"
    emb_dim: int = 512

    def __init__(self, model_path: str, providers: Optional[List[str]] = None) -> None:
        if ort is None:
            raise RuntimeError("onnxruntime not available")
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"arcface.onnx not found at: {model_path}")

        self.model_path = model_path
        self.providers = providers or ["CPUExecutionProvider"]

        # Create session
        sess_opt = ort.SessionOptions()
        sess_opt.log_severity_level = 3  # reduce verbosity
        self.sess = ort.InferenceSession(self.model_path, sess_options=sess_opt, providers=self.providers)

        # IO names
        inp = self.sess.get_inputs()[0]
        out = self.sess.get_outputs()[0]
        self.inp_name = inp.name
        self.out_name = out.name

        # Infer layout from shape if possible
        shape = list(inp.shape)  # could include None
        self.expects_nhwc = False  # default -> NCHW

        def _as_int(x):
            try:
                return int(x)
            except Exception:
                return None

        if len(shape) == 4:
            d1 = _as_int(shape[1])
            d3 = _as_int(shape[3])
            # If second dim looks like 112 and last like 3 -> NHWC
            if d1 == 112 and d3 == 3:
                self.expects_nhwc = True

        print(f"[auto_enrol] ONNX input shape={shape}, expects_nhwc={self.expects_nhwc}")

        # Quick forward with a dummy image to validate
        dummy = np.zeros((112, 112, 3), np.float32)
        blob = self._pack_input(dummy)
        _ = self.sess.run([self.out_name], {self.inp_name: blob})

    @staticmethod
    def _preprocess(face_bgr: np.ndarray) -> np.ndarray:
        # ArcFace common preprocess
        face_rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
        img = cv2.resize(face_rgb, (112, 112), interpolation=cv2.INTER_LINEAR).astype(np.float32)
        img = (img - 127.5) / 128.0
        return img

    def _pack_input(self, img_rgb_112: np.ndarray) -> np.ndarray:
        if self.expects_nhwc:
            # (1, 112, 112, 3)
            return img_rgb_112[None, ...]
        else:
            # (1, 3, 112, 112)
            return np.transpose(img_rgb_112, (2, 0, 1))[None, ...]

    def embed(self, face_bgr: np.ndarray) -> EmbedResult:
        try:
            img = self._preprocess(face_bgr)
            blob = self._pack_input(img)
            emb = self.sess.run([self.out_name], {self.inp_name: blob})[0]
            emb = emb.reshape(-1).astype(np.float32)
            emb = l2_normalize(emb)
            return EmbedResult(emb=emb, ok=True)
        except Exception as e:
            return EmbedResult(emb=np.zeros((self.emb_dim,), np.float32), ok=False, error=str(e))


# ---------- Factory ----------

class EmbedFactory:
    """
    Try to create ArcFace ONNX embedder; if anything fails, use CheapEmbedder.
    """
    def __init__(self, models_dir: str = None):
        self.models_dir = models_dir or os.path.join(os.path.dirname(__file__), "models")
        self.model_path = os.path.join(self.models_dir, "arcface.onnx")
        self.impl_name = ""
        self.emb_dim = 0

        self.impl = self._try_make_arcface()
        if self.impl is None:
            print("[auto_enrol] arcface.onnx not found or failed; using CHEAP embedding.")
            self.impl = CheapEmbedder()
            self.impl_name = self.impl.name
            self.emb_dim = self.impl.emb_dim
        else:
            self.impl_name = self.impl.name
            self.emb_dim = getattr(self.impl, "emb_dim", 512)

        print(f"[auto_enrol] Using {self.impl_name} emb_dim={self.emb_dim}")

    def _try_make_arcface(self) -> Optional[ArcFaceONNX]:
        try:
            if ort is None:
                raise RuntimeError("onnxruntime not installed")
            if not os.path.isfile(self.model_path):
                raise FileNotFoundError(self.model_path)
            return ArcFaceONNX(self.model_path, providers=["CPUExecutionProvider"])
        except Exception as e:
            print(f"[auto_enrol] ONNX init failed; reason: {e}")
            return None

    # Public API
    def embed(self, face_bgr: np.ndarray) -> EmbedResult:
        return self.impl.embed(face_bgr)

# --- Backwards compatibility helpers ---

_factory = EmbedFactory()

USE_CHEAP = (_factory.impl_name == "CHEAP")

def face_embedding_bgr(face_bgr):
    """Drop-in replacement for old API"""
    res = _factory.embed(face_bgr)
    return res.emb if res.ok else None

# ---------- Quick manual test (optional) ----------

if __name__ == "__main__":
    """
    Manual camera smoke test. Press ESC to quit.
    Shows which embedder is active and embeds the center crop.
    """
    factory = EmbedFactory()
    print("[ok] Camera opening…")
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("[err] Cannot open camera")
        sys.exit(1)

    font = cv2.FONT_HERSHEY_SIMPLEX
    color = (40, 200, 40)

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        h, w = frame.shape[:2]
        size = min(h, w)
        y0 = (h - size) // 2
        x0 = (w - size) // 2
        face = frame[y0:y0 + size, x0:x0 + size]

        res = factory.embed(face)
        label = f"{factory.impl_name} emb_dim={factory.emb_dim}"
        if not res.ok:
            label = f"ERROR -> {label}"

        cv2.rectangle(frame, (x0, y0), (x0 + size, y0 + size), (0, 255, 255), 2)
        cv2.putText(frame, label, (12, 28), font, 0.7, color, 2, cv2.LINE_AA)
        cv2.imshow("auto_enrol test", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == 27:  # ESC
            break

    cap.release()
    cv2.destroyAllWindows()
    print("[i] Closed.")
