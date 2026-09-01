from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional, Sequence, Tuple

import cv2
import numpy as np

logger = logging.getLogger(__name__)

_ARCFACE_TEMPLATE = np.asarray(
    [
        [38.2946, 51.6963],
        [73.5318, 51.5014],
        [56.0252, 71.7366],
        [41.5493, 92.3655],
        [70.7299, 92.2041],
    ],
    dtype=np.float32,
)


class ArcFaceEngine:
    """Lazy ArcFace-compatible 512-D ONNX inference.

    The application intentionally does not download recognition model weights. A customer
    deployment must provide a model whose commercial licence permits that deployment and
    set FRS_ARCFACE_MODEL_PATH. When no model is configured the hardened dlib path remains
    available.
    """

    def __init__(self) -> None:
        self.model_path = os.getenv("FRS_ARCFACE_MODEL_PATH", "").strip()
        self._session = None
        self._input_name: Optional[str] = None
        self._output_name: Optional[str] = None
        self._input_size = (112, 112)
        self._lock = threading.RLock()
        self._load_error: Optional[str] = None

    @property
    def available(self) -> bool:
        return bool(self.model_path and Path(self.model_path).is_file() and self._ensure_session())

    @property
    def model_version(self) -> str:
        if not self.model_path:
            return "arcface-512-unconfigured"
        return f"arcface-512:{Path(self.model_path).stem}"

    def _ensure_session(self) -> bool:
        if self._session is not None:
            return True
        if self._load_error:
            return False
        if not self.model_path or not Path(self.model_path).is_file():
            return False
        with self._lock:
            if self._session is not None:
                return True
            try:
                import onnxruntime as ort

                providers = list(ort.get_available_providers())
                preferred = []
                if "CUDAExecutionProvider" in providers:
                    preferred.append("CUDAExecutionProvider")
                preferred.append("CPUExecutionProvider")
                self._session = ort.InferenceSession(self.model_path, providers=preferred)
                input_meta = self._session.get_inputs()[0]
                output_meta = self._session.get_outputs()[0]
                self._input_name = input_meta.name
                self._output_name = output_meta.name
                shape = input_meta.shape
                if len(shape) == 4:
                    height = shape[2] if isinstance(shape[2], int) and shape[2] > 0 else 112
                    width = shape[3] if isinstance(shape[3], int) and shape[3] > 0 else 112
                    self._input_size = (int(width), int(height))
                logger.info("ArcFace recognizer ready: %s providers=%s", self.model_version, self._session.get_providers())
                return True
            except Exception as exc:
                self._load_error = str(exc)
                logger.error("ArcFace model could not be loaded: %s", exc)
                return False

    @staticmethod
    def _normalize_kps(kps: Optional[Sequence[Sequence[float]]]) -> Optional[np.ndarray]:
        if kps is None:
            return None
        try:
            value = np.asarray(kps, dtype=np.float32).reshape(-1, 2)
            return value if value.shape[0] >= 5 else None
        except Exception:
            return None

    def _aligned_crop(
        self,
        frame_bgr: np.ndarray,
        bbox: Tuple[int, int, int, int],
        kps: Optional[Sequence[Sequence[float]]] = None,
    ) -> Optional[np.ndarray]:
        if frame_bgr is None or frame_bgr.size == 0:
            return None
        width, height = self._input_size
        points = self._normalize_kps(kps)
        if points is not None and width == 112 and height == 112:
            try:
                matrix, _ = cv2.estimateAffinePartial2D(points[:5], _ARCFACE_TEMPLATE, method=cv2.LMEDS)
                if matrix is not None:
                    return cv2.warpAffine(frame_bgr, matrix, (112, 112), borderValue=0)
            except Exception:
                pass

        h, w = frame_bgr.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        fw, fh = max(1, x2 - x1), max(1, y2 - y1)
        px, py = int(fw * 0.18), int(fh * 0.18)
        x1, y1 = max(0, x1 - px), max(0, y1 - py)
        x2, y2 = min(w, x2 + px), min(h, y2 + py)
        crop = frame_bgr[y1:y2, x1:x2]
        if crop.size == 0:
            return None
        return cv2.resize(crop, (width, height), interpolation=cv2.INTER_LINEAR)

    def embed_frame(
        self,
        frame_bgr: np.ndarray,
        bbox: Tuple[int, int, int, int],
        kps: Optional[Sequence[Sequence[float]]] = None,
    ) -> Optional[np.ndarray]:
        if not self.available:
            return None
        crop = self._aligned_crop(frame_bgr, bbox, kps)
        return self.embed_crop(crop) if crop is not None else None

    def embed_crop(self, crop_bgr: Optional[np.ndarray]) -> Optional[np.ndarray]:
        if crop_bgr is None or crop_bgr.size == 0 or not self.available:
            return None
        width, height = self._input_size
        image = cv2.resize(crop_bgr, (width, height), interpolation=cv2.INTER_LINEAR)
        image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB).astype(np.float32)
        image = (image - 127.5) / 128.0
        tensor = np.transpose(image, (2, 0, 1))[None, ...]
        try:
            output = self._session.run([self._output_name], {self._input_name: tensor})[0]
            vector = np.asarray(output, dtype=np.float32).reshape(-1)
            if vector.size != 512 or not np.all(np.isfinite(vector)):
                logger.error("ArcFace model returned invalid embedding dimension %s", vector.size)
                return None
            norm = float(np.linalg.norm(vector))
            if norm <= 1e-8:
                return None
            return vector / norm
        except Exception as exc:
            logger.warning("ArcFace inference failed: %s", exc)
            return None


_engine = ArcFaceEngine()


def get_arcface_engine() -> ArcFaceEngine:
    return _engine
