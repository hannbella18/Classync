# project/vision/detector.py
import os
import numpy as np
import cv2
import onnxruntime as ort
from pathlib import Path

class Detector:
    def __init__(self, weights=None, base_conf=0.25, imgsz=512):
        # 1. FIXED PATHING: Tell the server exactly where the file is
        # Relative paths like ".." often fail in Hugging Face Docker environments
        if weights is None:
            # Check the standard Hugging Face root directory first
            hf_path = Path("/code/awake_drowsy.onnx")
            # Fallback to local project structure
            local_path = Path(__file__).resolve().parent.parent / "awake_drowsy.onnx"
            
            if hf_path.exists():
                default_w = str(hf_path)
            else:
                default_w = str(local_path)
        
        self.weights = weights or default_w
        
        if not os.path.isfile(self.weights):
            raise FileNotFoundError(
                f"AI Model file NOT FOUND at: {self.weights}. "
                "Please ensure awake_drowsy.onnx is in the root folder."
            )

        # 2. FIXED PROVIDER: Use OpenVINO for stability and speed on cloud CPUs
        # This matches your requirements.txt switch to onnxruntime-openvino
        try:
            self.session = ort.InferenceSession(
                self.weights, 
                providers=['OpenVINOExecutionProvider', 'CPUExecutionProvider']
            )
        except Exception as e:
            print(f"[Detector] OpenVINO init failed, falling back to CPU: {e}")
            self.session = ort.InferenceSession(self.weights, providers=['CPUExecutionProvider'])

        self.input_name = self.session.get_inputs()[0].name
        self.base_conf = base_conf
        self.imgsz = imgsz
        
        # Sensitivity settings
        self.th = {"Awake": 0.50, "Drowsy": 0.60}

    def predict_state(self, frame):
        """Finds the best detection and returns (label, score)."""
        dets = self.predict_states(frame)
        if not dets:
            return None, None
        best = max(dets, key=lambda d: d["score"])
        return best["label"], best["score"]

    def predict_states(self, frame):
        """Processes frame via ONNX and returns Awake/Drowsy detections."""
        # A. Pre-processing
        h, w = frame.shape[:2]
        img = cv2.resize(frame, (self.imgsz, self.imgsz))
        img = img.transpose((2, 0, 1)).astype(np.float32) / 255.0
        img = np.expand_dims(img, axis=0)

        # B. Run Inference
        outputs = self.session.run(None, {self.input_name: img})

        # C. Post-processing for YOLOv8
        # [batch, 4 + classes, 8400] -> [8400, 4 + classes]
        predictions = np.squeeze(outputs[0]).T
        
        out = []
        # 🔍 Detect number of classes from output (YOLOv8 format: 4 + num_classes)
        num_classes = predictions.shape[1] - 4
        print("[Detector] detected num_classes:", num_classes)

        # ✅ Your system expects EXACTLY 2 classes: Awake, Drowsy
        if num_classes != 2:
            raise RuntimeError(
                f"[Detector] WRONG MODEL: This ONNX outputs {num_classes} classes. "
                "Classync drowsiness expects a 2-class model [Awake, Drowsy]. "
                "Your yolov8n.onnx is likely the default COCO model. "
                "Export your trained awake/drowsy YOLOv8 model to ONNX and replace yolov8n.onnx."
            )

        class_names = ["Awake", "Drowsy"]

        for i in range(len(predictions)):
            row = predictions[i]
            scores = row[4:]
            class_id = int(np.argmax(scores))
            confidence = float(scores[class_id])
            
            if confidence > self.base_conf:
                label = class_names[class_id] if class_id < len(class_names) else "Unknown"
                
                if confidence >= self.th.get(label, self.base_conf):
                    x, y, w_box, h_box = row[:4]
                    x1 = int((x - w_box/2) * (w / self.imgsz))
                    y1 = int((y - h_box/2) * (h / self.imgsz))
                    x2 = int((x + w_box/2) * (w / self.imgsz))
                    y2 = int((y + h_box/2) * (h / self.imgsz))
                    
                    out.append({
                        "label": label,
                        "score": float(confidence),
                        "xyxy": (x1, y1, x2, y2)
                    })
        
        return out