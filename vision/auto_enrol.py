# project/vision/auto_enrol.py
# ------------------------------------------------------------
# ArcFace ONNX embedder with LAZY LOADING.
# This prevents the "Startup Timeout" by waiting to load the AI.
# ------------------------------------------------------------

from __future__ import annotations
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional
import cv2
import numpy as np

try:
    import onnxruntime as ort
except Exception:
    ort = None

# ---------- utils ----------

def l2_normalize(v: np.ndarray, eps: float = 1e-9) -> np.ndarray:
    n = np.linalg.norm(v) + eps
    return (v / n).astype(np.float32)

@dataclass
class EmbedResult:
    emb: np.ndarray
    ok: bool
    error: Optional[str] = None

class CheapEmbedder:
    """Fallback embedder (Fast, Low Quality)"""
    emb_dim: int = 1024
    name: str = "CHEAP"

    def embed(self, face_bgr: np.ndarray) -> EmbedResult:
        try:
            g = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2GRAY)
            g = cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
            g = (g - g.mean()) / (g.std() + 1e-6)
            emb = g.flatten()
            emb = l2_normalize(emb)
            return EmbedResult(emb=emb, ok=True)
        except Exception as e:
            return EmbedResult(emb=np.zeros((1024,), np.float32), ok=False, error=str(e))

class ArcFaceONNX:
    """Real AI Embedder (Slow to load, High Quality)"""
    name: str = "ArcFace"
    emb_dim: int = 512

    def __init__(self, model_path: str):
        if ort is None:
            raise RuntimeError("onnxruntime not installed")
        if not os.path.isfile(model_path):
            raise FileNotFoundError(f"Model not found: {model_path}")

        sess_opt = ort.SessionOptions()
        sess_opt.log_severity_level = 3
        # Load the brain
        self.sess = ort.InferenceSession(model_path, sess_options=sess_opt, providers=["CPUExecutionProvider"])

        self.inp_name = self.sess.get_inputs()[0].name
        self.out_name = self.sess.get_outputs()[0].name

        # Detect input shape
        shape = self.sess.get_inputs()[0].shape
        self.nhwc = (len(shape) == 4 and shape[1] == 112 and shape[3] == 3)

    def embed(self, face_bgr: np.ndarray) -> EmbedResult:
        try:
            face_rgb = cv2.cvtColor(face_bgr, cv2.COLOR_BGR2RGB)
            img = cv2.resize(face_rgb, (112, 112)).astype(np.float32)
            img = (img - 127.5) / 128.0

            if self.nhwc:
                blob = img[None, ...]
            else:
                blob = np.transpose(img, (2, 0, 1))[None, ...]

            emb = self.sess.run([self.out_name], {self.inp_name: blob})[0]
            emb = emb.flatten().astype(np.float32)
            return EmbedResult(emb=l2_normalize(emb), ok=True)
        except Exception as e:
            return EmbedResult(emb=np.zeros((512,), np.float32), ok=False, error=str(e))


class EmbedFactory:
    """
    The Manager. It starts empty and only loads the AI when you ask for it.
    """
    def __init__(self):
        self.impl = None # Start Empty!
        # This path looks for vision/models/arcface.onnx
        self.model_path = os.path.join(os.path.dirname(__file__), "models", "arcface.onnx")

    def get_impl(self):
        # This function runs ONLY when a student joins (not at startup)
        if self.impl is None:
            print("⏳ [LazyLoad] Loading AI Model now... (This may take a moment)")
            
            if os.path.exists(self.model_path) and ort:
                try:
                    self.impl = ArcFaceONNX(self.model_path)
                    print("✅ [LazyLoad] AI Loaded Successfully!")
                except Exception as e:
                    print(f"⚠️ [LazyLoad] ArcFace failed ({e}), using cheap mode.")
                    self.impl = CheapEmbedder()
            else:
                print(f"⚠️ [LazyLoad] Model file not found at {self.model_path}, using cheap mode.")
                self.impl = CheapEmbedder()
        
        return self.impl

    def embed(self, face_bgr: np.ndarray) -> EmbedResult:
        return self.get_impl().embed(face_bgr)

# --- GLOBAL INSTANCE ---
# This is safe now because __init__ does almost nothing.
_factory = EmbedFactory()

def face_embedding_bgr(face_bgr):
    return _factory.embed(face_bgr)