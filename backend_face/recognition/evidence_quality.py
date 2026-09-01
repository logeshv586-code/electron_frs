from __future__ import annotations

import math
from typing import Tuple

import cv2
import numpy as np


def evidence_score(crop: np.ndarray, bbox: Tuple[int, int, int, int]) -> float:
    """Score a track crop for evidence selection without inventing image detail.

    The score strongly prefers native face pixels and focus. This means a distant blurry
    frame is retained only until a later, larger/sharper view of the same track arrives.
    """
    if crop is None or crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    mean = float(np.mean(gray))
    exposure = max(0.0, 1.0 - abs(mean - 128.0) / 128.0)
    contrast = min(float(np.std(gray)) / 55.0, 1.0)
    x1, y1, x2, y2 = [int(v) for v in bbox]
    face_w, face_h = max(1, x2 - x1), max(1, y2 - y1)
    native_face_pixels = math.sqrt(float(face_w * face_h))
    size_weight = min(native_face_pixels / 140.0, 1.0)
    focus_weight = min(sharpness / 450.0, 1.0)
    # Multiplying focus by size makes a genuinely detailed crop beat an upscaled blur.
    return float((focus_weight * 0.50 + size_weight * 0.30 + exposure * 0.12 + contrast * 0.08) * (0.65 + 0.35 * size_weight))


def enhance_for_review(image: np.ndarray) -> np.ndarray:
    """Mild review enhancement only; never used to create recognition embeddings."""
    if image is None or image.size == 0:
        return image
    output = image.copy()
    try:
        output = cv2.bilateralFilter(output, 5, 28, 28)
        lab = cv2.cvtColor(output, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        l = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(l)
        output = cv2.cvtColor(cv2.merge([l, a, b]), cv2.COLOR_LAB2BGR)
        blur = cv2.GaussianBlur(output, (0, 0), 1.0)
        output = cv2.addWeighted(output, 1.12, blur, -0.12, 0)
    except Exception:
        return image
    return output
