from __future__ import annotations

import logging
import os
import threading
from collections import deque
from pathlib import Path
from typing import Dict, Optional

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class LivenessEngine:
    """Presentation-attack gate with optional ONNX PAD model and temporal fallback.

    A configured or explicitly required PAD model is fail-closed: if the model file is
    missing, cannot load, or inference fails, attendance is rejected. Without a configured
    PAD model, the temporal/texture score remains advisory unless FRS_LIVENESS_REQUIRED=1.
    """

    def __init__(self) -> None:
        self.model_path = os.getenv("FRS_LIVENESS_MODEL_PATH", "").strip()
        self.required = os.getenv("FRS_LIVENESS_REQUIRED", "auto").strip().lower()
        self.threshold = float(os.getenv("FRS_LIVENESS_THRESHOLD", "0.65"))
        self.real_class_index = int(os.getenv("FRS_LIVENESS_REAL_CLASS_INDEX", "1"))
        self._session = None
        self._input_name: Optional[str] = None
        self._output_name: Optional[str] = None
        self._input_size = (80, 80)
        self._lock = threading.RLock()
        self._error: Optional[str] = None

    @property
    def model_available(self) -> bool:
        return bool(self.model_path and Path(self.model_path).is_file() and self._ensure_session())

    @property
    def fail_closed(self) -> bool:
        if self.required in {"1", "true", "yes", "required"}:
            return True
        if self.required in {"0", "false", "no", "off"}:
            return False
        # auto: once a PAD model is configured the customer is declaring it part of the
        # attendance trust boundary, so missing/broken inference must not silently downgrade.
        return bool(self.model_path)

    def _ensure_session(self) -> bool:
        if self._session is not None:
            return True
        if self._error:
            return False
        if not self.model_path or not Path(self.model_path).is_file():
            return False
        with self._lock:
            if self._session is not None:
                return True
            try:
                import onnxruntime as ort
                providers = list(ort.get_available_providers())
                selected = (["CUDAExecutionProvider"] if "CUDAExecutionProvider" in providers else []) + ["CPUExecutionProvider"]
                self._session = ort.InferenceSession(self.model_path, providers=selected)
                inp = self._session.get_inputs()[0]
                out = self._session.get_outputs()[0]
                self._input_name = inp.name
                self._output_name = out.name
                shape = inp.shape
                if len(shape) == 4:
                    h = shape[2] if isinstance(shape[2], int) and shape[2] > 0 else 80
                    w = shape[3] if isinstance(shape[3], int) and shape[3] > 0 else 80
                    self._input_size = (int(w), int(h))
                logger.info("Liveness PAD model ready: %s", Path(self.model_path).name)
                return True
            except Exception as exc:
                self._error = str(exc)
                logger.error("Liveness model failed to load: %s", exc)
                return False

    @staticmethod
    def _softmax(values: np.ndarray) -> np.ndarray:
        values = values - np.max(values)
        exp = np.exp(values)
        return exp / max(float(np.sum(exp)), 1e-8)

    def _model_score(self, crop_bgr: np.ndarray) -> Optional[float]:
        if not self.model_available:
            return None
        width, height = self._input_size
        image = cv2.resize(crop_bgr, (width, height), interpolation=cv2.INTER_LINEAR)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        image = (image - 0.5) / 0.5
        tensor = np.transpose(image, (2, 0, 1))[None, ...]
        try:
            raw = np.asarray(self._session.run([self._output_name], {self._input_name: tensor})[0], dtype=np.float32).reshape(-1)
            if raw.size == 1:
                return float(1.0 / (1.0 + np.exp(-raw[0])))
            probs = self._softmax(raw)
            index = min(max(self.real_class_index, 0), probs.size - 1)
            return float(probs[index])
        except Exception as exc:
            logger.warning("Liveness inference failed: %s", exc)
            return None

    @staticmethod
    def _heuristic_score(track: Dict, crop_bgr: np.ndarray) -> float:
        gray = cv2.cvtColor(cv2.resize(crop_bgr, (64, 64)), cv2.COLOR_BGR2GRAY)
        gray_f = gray.astype(np.float32) / 255.0
        previous = track.get("_liveness_prev")
        motion = 0.0
        if isinstance(previous, np.ndarray) and previous.shape == gray_f.shape:
            motion = float(np.mean(np.abs(gray_f - previous)))
        track["_liveness_prev"] = gray_f

        texture = min(float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 220.0, 1.0)
        dynamic = min(float(np.std(gray)) / 60.0, 1.0)
        motion_score = float(np.clip((motion - 0.004) / 0.05, 0.0, 1.0))
        return float(np.clip(texture * 0.42 + dynamic * 0.28 + motion_score * 0.30, 0.0, 1.0))

    def evaluate(self, track: Dict, crop_bgr: np.ndarray) -> Dict[str, object]:
        required = self.fail_closed
        if crop_bgr is None or crop_bgr.size == 0:
            return {"score": 0.0, "passed": not required, "mode": "invalid", "required": required, "model_available": self.model_available}

        model_available = self.model_available
        if required and self.model_path and not model_available:
            return {
                "score": 0.0,
                "instant_score": 0.0,
                "passed": False,
                "mode": "model-unavailable",
                "required": True,
                "model_available": False,
            }

        model_score = self._model_score(crop_bgr)
        if required and self.model_path and model_score is None:
            return {
                "score": 0.0,
                "instant_score": 0.0,
                "passed": False,
                "mode": "model-inference-failed",
                "required": True,
                "model_available": model_available,
            }

        heuristic = self._heuristic_score(track, crop_bgr)
        mode = "onnx-pad" if model_score is not None else "temporal-heuristic"
        score = float(model_score if model_score is not None else heuristic)
        history = track.get("liveness_history")
        if not isinstance(history, deque):
            history = deque(maxlen=5)
            track["liveness_history"] = history
        history.append(score)
        stable_score = float(np.mean(list(history)[-3:])) if history else score
        enough_samples = len(history) >= (2 if model_score is not None else 3)
        if required:
            passed = bool(enough_samples and stable_score >= self.threshold)
        else:
            passed = True
        return {
            "score": stable_score,
            "instant_score": score,
            "passed": passed,
            "mode": mode,
            "required": required,
            "model_available": model_available,
        }


_engine = LivenessEngine()


def get_liveness_engine() -> LivenessEngine:
    return _engine
