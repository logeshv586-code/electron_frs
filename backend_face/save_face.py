from __future__ import annotations

import logging
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Sequence, Tuple

import cv2
import numpy as np

from db.repository import (
    cluster_unknown,
    get_camera_context,
    record_recognition_event,
)

logger = logging.getLogger(__name__)

BACKEND_FACE_DIR = Path(__file__).resolve().parent
BASE_DIR = BACKEND_FACE_DIR / "captured_faces"
KNOWN_DIRNAME = "known"
UNKNOWN_DIRNAME = "unknown"
DEFAULT_MIN_SAVE_INTERVAL_SECONDS = float(os.getenv("FACE_IMAGE_SAVE_INTERVAL", "30"))
MIN_KNOWN_SAVE_CONFIDENCE = float(os.getenv("FACE_MIN_KNOWN_SAVE_CONFIDENCE", "0.55"))
MIN_UNKNOWN_DETECTION_CONFIDENCE = float(os.getenv("FACE_MIN_UNKNOWN_DET_CONFIDENCE", "0.60"))

_last_saved_time: Dict[str, float] = {}
_lock = threading.Lock()
_filename_safe_re = re.compile(r"[^\w\-_.]")


def sanitize_label(label: Optional[str]) -> str:
    value = (label or "unknown").strip().lower().replace(" ", "_")
    value = _filename_safe_re.sub("", value)
    return value or "unknown"


def ensure_dirs_for_label(
    label: str,
    camera_name: Optional[str] = None,
    company_id: Optional[str] = None,
    unknown_cluster_id: Optional[str] = None,
) -> Path:
    label_s = sanitize_label(label)
    cam = sanitize_label(camera_name or "default")
    comp = sanitize_label(company_id or "default")
    if label_s == "unknown":
        cluster = sanitize_label(unknown_cluster_id or "unclustered")
        path = BASE_DIR / UNKNOWN_DIRNAME / comp / cam / cluster
    else:
        path = BASE_DIR / KNOWN_DIRNAME / comp / cam / label_s
    path.mkdir(parents=True, exist_ok=True)
    return path


def _timestamp_filename(label: str) -> str:
    return f"{sanitize_label(label)}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.jpg"


def _bbox_to_ltrb(bbox: Tuple, frame_shape: Tuple[int, ...]) -> Tuple[int, int, int, int]:
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = [float(v) for v in bbox]
    if all(0 <= v <= 1 for v in (x1, y1, x2, y2)):
        left = int(x1 * w); top = int(y1 * h)
        right = int((x1 + x2) * w); bottom = int((y1 + y2) * h)
    elif x2 > 0 and y2 > 0 and x1 + x2 <= w and y1 + y2 <= h and not (x2 > x1 and y2 > y1):
        left, top, right, bottom = int(x1), int(y1), int(x1 + x2), int(y1 + y2)
    else:
        left, top, right, bottom = int(x1), int(y1), int(x2), int(y2)
    return (
        max(0, min(w - 1, left)),
        max(0, min(h - 1, top)),
        max(1, min(w, right)),
        max(1, min(h, bottom)),
    )


def _prepare_crop(face_crop_bgr: np.ndarray, target_width: int = 384, max_upscale: float = 3.0) -> np.ndarray:
    image = face_crop_bgr.copy()
    h, w = image.shape[:2]
    min_side = min(h, w)
    if min_side < target_width:
        scale = min(target_width / max(min_side, 1), max_upscale)
        if scale > 1.05:
            image = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4)
    try:
        from recognition.evidence_quality import enhance_for_review
        image = enhance_for_review(image)
    except Exception:
        pass
    return image


def save_face_image(
    face_crop_bgr: Optional[np.ndarray] = None,
    frame_bgr: Optional[np.ndarray] = None,
    bbox: Optional[Tuple] = None,
    label: Optional[str] = None,
    confidence: Optional[float] = None,
    min_interval: float = DEFAULT_MIN_SAVE_INTERVAL_SECONDS,
    source: str = "stream",
    expand_factor: float = 0.35,
    target_width: Optional[int] = 384,
    max_upscale: float = 3.0,
    jpeg_quality: int = 96,
    stream_id: Optional[str] = None,
    prefer_png: bool = False,
    camera_name: Optional[str] = None,
    company_id: Optional[str] = None,
    identity_key: Optional[str] = None,
    unknown_cluster_id: Optional[str] = None,
):
    if face_crop_bgr is None and (frame_bgr is None or bbox is None):
        return None

    label_s = sanitize_label(label)
    confidence = float(confidence or 0.0)
    if label_s == "unknown":
        if confidence < MIN_UNKNOWN_DETECTION_CONFIDENCE:
            return None
    elif confidence < MIN_KNOWN_SAVE_CONFIDENCE:
        return None

    comp = sanitize_label(company_id or "default")
    cam = sanitize_label(camera_name or "default")
    identity = sanitize_label(identity_key or unknown_cluster_id or label_s)
    cooldown_key = f"{comp}:{cam}:{label_s}:{identity}"
    now = time.time()
    with _lock:
        if min_interval > 0 and now - _last_saved_time.get(cooldown_key, 0.0) < min_interval:
            return None
        _last_saved_time[cooldown_key] = now

    try:
        if face_crop_bgr is None and frame_bgr is not None and bbox is not None:
            left, top, right, bottom = _bbox_to_ltrb(bbox, frame_bgr.shape)
            fw, fh = max(1, right - left), max(1, bottom - top)
            pad_x, pad_y = int(fw * expand_factor), int(fh * expand_factor)
            h, w = frame_bgr.shape[:2]
            face_crop_bgr = frame_bgr[
                max(0, top - pad_y):min(h, bottom + pad_y),
                max(0, left - pad_x):min(w, right + pad_x),
            ].copy()

        if face_crop_bgr is None or face_crop_bgr.size == 0:
            return None
        if min(face_crop_bgr.shape[:2]) < 10:
            return None

        prepared = _prepare_crop(face_crop_bgr, int(target_width or 320), float(max_upscale))
        target_dir = ensure_dirs_for_label(
            label_s,
            camera_name=camera_name,
            company_id=company_id,
            unknown_cluster_id=unknown_cluster_id,
        )
        filename = _timestamp_filename(label_s if label_s != "unknown" else (unknown_cluster_id or "unknown"))
        path = target_dir / filename
        if not cv2.imwrite(str(path), prepared, [cv2.IMWRITE_JPEG_QUALITY, int(jpeg_quality)]):
            return None
        try:
            from storage.evidence_store import get_evidence_store
            stored = get_evidence_store().store_file(path)
            return stored if stored != str(path) else path
        except Exception as exc:
            logger.warning("Evidence object-store mirror failed; keeping local file: %s", exc)
            return path
    except Exception as exc:
        logger.error("Failed saving face evidence: %s", exc)
        return None


def record_face_event(
    *,
    company_id: str,
    label: str,
    display_name: Optional[str],
    embedding: Optional[Sequence[float]],
    confidence: float,
    distance: Optional[float],
    quality: float,
    face_size: Tuple[int, int],
    camera_name: Optional[str],
    camera_id: Optional[int] = None,
    image_path: Optional[str] = None,
    source: str = "stream",
    attendance_eligible: bool = False,
    unknown_cluster_id: Optional[str] = None,
    captured_at=None,
    direction_override: Optional[str] = None,
    model_version: Optional[str] = None,
) -> dict:
    company_id = str(company_id or "default")
    camera = get_camera_context(camera_name, company_id, camera_id)
    label_s = sanitize_label(label)

    if label_s == "unknown" and not unknown_cluster_id and embedding is not None:
        unknown_cluster_id = cluster_unknown(
            company_id,
            embedding,
            quality=float(quality),
            image_path=image_path,
            captured_at=captured_at,
        )

    identity = unknown_cluster_id or label_s
    resolved_camera = camera.get("name") or camera_name or "default"
    try:
        from cache.redis_cache import get_event_cache
        event_cache = get_event_cache()
        timestamp = captured_at.timestamp() if hasattr(captured_at, "timestamp") else None
        if not event_cache.claim(
            company_id,
            identity,
            resolved_camera,
            ttl_seconds=int(os.getenv("FRS_DISTRIBUTED_EVENT_TTL", "5")),
            timestamp=timestamp,
        ):
            return {"deduplicated": True, "company_id": company_id, "identity": identity}
    except Exception:
        event_cache = None

    event_type = "unknown" if label_s == "unknown" else "known"
    from auth.storage import get_settings
    attendance_settings = get_settings(company_id).get("attendance", {})
    event = record_recognition_event(
        company_id=company_id,
        person_key=None if event_type == "unknown" else label_s,
        display_name=display_name if event_type == "known" else "Unknown",
        event_type=event_type,
        camera_id=camera.get("id"),
        camera_name=resolved_camera,
        location=camera.get("location") or camera_name,
        camera_role=camera.get("camera_role") or "BIDIRECTIONAL",
        direction=(direction_override or camera.get("direction") or "AUTO"),
        captured_at=captured_at,
        confidence=float(confidence),
        distance=distance,
        quality=float(quality),
        face_size=face_size,
        image_path=image_path,
        source=source,
        model_version=model_version or ("arcface-512" if embedding is not None and len(embedding) == 512 else "dlib-128-consensus-v2"),
        attendance_eligible=bool(attendance_eligible and event_type == "known"),
        unknown_cluster_id=unknown_cluster_id,
        shift_start=attendance_settings.get("shift_start"),
        shift_end=attendance_settings.get("shift_end"),
    )
    if event_cache is not None:
        try:
            event_cache.publish(company_id, event)
        except Exception:
            pass
    return event
