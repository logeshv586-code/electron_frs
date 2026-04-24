# face_pipeline.py
# -*- coding: utf-8 -*-
"""
Long-distance face detection + recognition pipeline.
Uses InsightFace (SCRFD) with:
  - CLAHE contrast enhancement for low-light/far cameras
  - Elevated det_size (1280x1280) for resolving small/distant faces
  - Face upscaling (Lanczos4 + unsharp mask) before encoding
  - MIN_FACE_PX = 20 to accept distant detections
  - Tracking persistence so labels don't flicker
"""

import cv2
import numpy as np
import face_recognition
from insightface.app import FaceAnalysis
from typing import List, Tuple, Dict, Any, Optional
from collections import defaultdict
import threading
import os
import time
import logging
from save_face import save_face_image

logger = logging.getLogger(__name__)

# ─────────────────────── Tuning constants ──────────────────────────────────
TOLERANCE = 0.50          # base face_recognition distance threshold
LONG_RANGE_TOLERANCE = 0.58
LONG_RANGE_FACE_PX = 72
VERY_LONG_RANGE_FACE_PX = 42
MATCH_MARGIN = 0.025
MIN_SAVE_INTERVAL = 5.0   # seconds between saves for same label
UNKNOWN_MIN_SAVE_INTERVAL = 12.0

# ── Long-distance detection ─────────────────────────────────────────────────
#   The primary long-distance mechanism is the elevated det_size=(1280,1280)
#   passed to InsightFace at init time. This alone ~4× the effective resolution.
#   MIN_FACE_PX is lowered so small/distant detections are not filtered out.
MIN_FACE_PX = 20          # absolute minimum face size in pixels (was 50–60)

#   Upscale small face crops to this size before encoding (improves accuracy)
ENCODING_MIN_SIZE = 128   # px; insightface & dlib work best >=112
ENCODING_MAX_SIZE = 224   # don't upscale beyond this to stay fast

# ── Tracking ────────────────────────────────────────────────────────────────
IOU_THRESHOLD        = 0.22
MAX_TRACK_AGE_FRAMES = 12
MAX_TRACK_AGE_SECONDS = 0.75
BEST_QUALITY_RESET_SECONDS = 30.0
# ───────────────────────────────────────────────────────────────────────────

# Singletons / shared state
face_apps: Dict[int, Any] = {}
face_app   = None
available_gpus: List[int] = []
runtime_profile: Dict[str, Any] = {
    "device": "uninitialized",
    "ctx": -1,
    "det_size": None,
    "process_every_n": 4,
    "providers": [],
}

company_embeddings: Dict[str, Dict[str, Any]] = {}
embedding_lock = threading.Lock()
data_directory: str = ""

person_tracking: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)
track_id_counter: Dict[str, int] = defaultdict(int)
tracking_lock = threading.Lock()

best_face_quality: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(dict)

# ═══════════════════════════════════════════════════════════════════════════
#   UTILITY HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _apply_clahe(bgr: np.ndarray) -> np.ndarray:
    """Contrast Limited Adaptive Histogram Equalisation – helps dull/far cameras."""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    lab = cv2.merge([clahe.apply(l), a, b])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def _upscale_for_encoding(crop_bgr: np.ndarray) -> np.ndarray:
    """
    Upscale a small face crop to at least ENCODING_MIN_SIZE so that
    face_recognition produces a reliable 128-d embedding.
    Uses Lanczos4 (sharpest interpolation for upscaling).
    """
    h, w = crop_bgr.shape[:2]
    short = min(h, w)
    if short >= ENCODING_MIN_SIZE:
        return crop_bgr                         # already large enough

    scale     = ENCODING_MIN_SIZE / short
    # Cap to ENCODING_MAX_SIZE
    if short * scale > ENCODING_MAX_SIZE:
        scale = ENCODING_MAX_SIZE / short
    new_w     = max(int(w * scale), ENCODING_MIN_SIZE)
    new_h     = max(int(h * scale), ENCODING_MIN_SIZE)
    upscaled  = cv2.resize(crop_bgr, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
    # Gentle unsharp-mask after upscaling to recover edge definition
    blurred   = cv2.GaussianBlur(upscaled, (0, 0), sigmaX=1.0)
    upscaled  = cv2.addWeighted(upscaled, 1.5, blurred, -0.5, 0)
    return upscaled


def _enhance_for_encoding(crop_bgr: np.ndarray) -> np.ndarray:
    if crop_bgr is None or crop_bgr.size == 0:
        return crop_bgr
    try:
        enhanced = _apply_clahe(crop_bgr)
        blurred = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=0.8)
        return cv2.addWeighted(enhanced, 1.35, blurred, -0.35, 0)
    except Exception:
        return crop_bgr


def _crop_with_location(
    frame: np.ndarray,
    bbox: Tuple[int, int, int, int],
    padding: float,
) -> Tuple[Optional[np.ndarray], Optional[Tuple[int, int, int, int]]]:
    if frame is None or frame.size == 0:
        return None, None

    H, W = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    fw, fh = max(1, x2 - x1), max(1, y2 - y1)
    px, py = int(fw * padding), int(fh * padding)
    cx1, cy1 = max(0, x1 - px), max(0, y1 - py)
    cx2, cy2 = min(W, x2 + px), min(H, y2 + py)
    if cx2 <= cx1 or cy2 <= cy1:
        return None, None

    crop = frame[cy1:cy2, cx1:cx2].copy()
    loc = (y1 - cy1, x2 - cx1, y2 - cy1, x1 - cx1)
    return crop, loc


def _scale_crop_and_location(
    crop_bgr: np.ndarray,
    loc: Tuple[int, int, int, int],
    face_target_px: int,
) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    top, right, bottom, left = loc
    face_w = max(1, right - left)
    face_h = max(1, bottom - top)
    short = min(face_w, face_h)
    if short >= face_target_px:
        return crop_bgr, loc

    scale = face_target_px / float(short)
    if short * scale > ENCODING_MAX_SIZE:
        scale = ENCODING_MAX_SIZE / float(short)

    h, w = crop_bgr.shape[:2]
    new_w = max(1, int(w * scale))
    new_h = max(1, int(h * scale))
    upscaled = cv2.resize(crop_bgr, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
    blurred = cv2.GaussianBlur(upscaled, (0, 0), sigmaX=1.0)
    upscaled = cv2.addWeighted(upscaled, 1.5, blurred, -0.5, 0)
    scaled_loc = (
        int(top * scale),
        int(right * scale),
        int(bottom * scale),
        int(left * scale),
    )
    return upscaled, scaled_loc


def _encode_face_variants(
    frame_bgr: np.ndarray,
    bbox: Tuple[int, int, int, int],
    min_side: int,
) -> List[np.ndarray]:
    """
    Try a few aligned crops for distant faces. Far boxes are often a little
    tight or soft, so a single full-crop descriptor can miss a known person.
    """
    encodings: List[np.ndarray] = []
    paddings = (0.0, 0.18, 0.34) if min_side < LONG_RANGE_FACE_PX else (0.0, 0.18)
    target = 160 if min_side < VERY_LONG_RANGE_FACE_PX else ENCODING_MIN_SIZE

    for padding in paddings:
        crop, loc = _crop_with_location(frame_bgr, bbox, padding)
        if crop is None or loc is None or crop.size == 0:
            continue

        variants = [crop]
        if min_side < LONG_RANGE_FACE_PX:
            variants.append(_enhance_for_encoding(crop))

        for variant in variants:
            prepared, prepared_loc = _scale_crop_and_location(variant, loc, target)
            rgb = cv2.cvtColor(prepared, cv2.COLOR_BGR2RGB)
            try:
                encs = face_recognition.face_encodings(
                    rgb,
                    known_face_locations=[prepared_loc],
                    num_jitters=1,
                    model='large'
                )
                if encs:
                    encodings.extend(encs)
            except Exception:
                continue

    return encodings


def _threshold_for_face_size(min_side: int, det_conf: float) -> float:
    if min_side < VERY_LONG_RANGE_FACE_PX:
        return LONG_RANGE_TOLERANCE if det_conf >= 0.55 else 0.54
    if min_side < LONG_RANGE_FACE_PX:
        return 0.56 if det_conf >= 0.50 else 0.53
    return TOLERANCE


def _match_known_face(
    candidate_encodings: List[np.ndarray],
    known_enc: List[np.ndarray],
    known_names: List[str],
    min_side: int,
    det_conf: float,
) -> Tuple[str, float, Optional[np.ndarray], Optional[float]]:
    if not candidate_encodings or len(known_enc) == 0:
        return "Unknown", det_conf, None, None

    threshold = _threshold_for_face_size(min_side, det_conf)
    best: Optional[Dict[str, Any]] = None

    for enc in candidate_encodings:
        distances = face_recognition.face_distance(known_enc, enc)
        if len(distances) == 0:
            continue

        sorted_idx = np.argsort(distances)
        best_idx = int(sorted_idx[0])
        best_name = known_names[best_idx]
        best_dist = float(distances[best_idx])
        if best_dist > threshold:
            continue

        per_name: Dict[str, Dict[str, float]] = {}
        for idx, dist in enumerate(distances):
            dist_f = float(dist)
            person = known_names[idx]
            entry = per_name.setdefault(person, {"min": dist_f, "votes": 0})
            entry["min"] = min(entry["min"], dist_f)
            if dist_f <= threshold + 0.02:
                entry["votes"] += 1

        same_person_images = known_names.count(best_name)
        required_votes = 1 if same_person_images <= 1 else 2
        if len(set(known_names)) == 1:
            required_votes = 1

        other_mins = [
            item["min"] for person, item in per_name.items()
            if person != best_name
        ]
        second_best = min(other_mins) if other_mins else 1.0
        margin = second_best - best_dist

        if per_name[best_name]["votes"] < required_votes:
            continue
        if other_mins and margin < MATCH_MARGIN and best_dist > TOLERANCE:
            continue

        score = (threshold - best_dist) + min(per_name[best_name]["votes"], 5) * 0.015 + max(margin, 0) * 0.2
        if best is None or score > best["score"]:
            best = {
                "name": best_name,
                "conf": max(0.0, 1.0 - best_dist),
                "encoding": enc,
                "distance": best_dist,
                "score": score,
                "votes": per_name[best_name]["votes"],
                "threshold": threshold,
            }

    if best is None:
        return "Unknown", det_conf, None, None

    logger.debug(
        "[MATCH] %s | dist=%.3f | thr=%.2f | votes=%s | conf=%.2f | size=%spx",
        best["name"], best["distance"], best["threshold"], best["votes"], best["conf"], min_side
    )
    return best["name"], best["conf"], best["encoding"], best["distance"]


def _calculate_iou(b1: Tuple, b2: Tuple) -> float:
    x1 = max(b1[0], b2[0]); y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2]); y2 = min(b1[3], b2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    a1    = (b1[2] - b1[0]) * (b1[3] - b1[1])
    a2    = (b2[2] - b2[0]) * (b2[3] - b2[1])
    return inter / (a1 + a2 - inter + 1e-6)


def _bbox_area(b: Tuple) -> float:
    return max(0, b[2] - b[0]) * max(0, b[3] - b[1])


def _overlap_ratio(b1: Tuple, b2: Tuple) -> float:
    x1 = max(b1[0], b2[0]); y1 = max(b1[1], b2[1])
    x2 = min(b1[2], b2[2]); y2 = min(b1[3], b2[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    return inter / (min(_bbox_area(b1), _bbox_area(b2)) + 1e-6)


def _center_distance(b1: Tuple, b2: Tuple) -> float:
    c1x = (b1[0] + b1[2]) * 0.5
    c1y = (b1[1] + b1[3]) * 0.5
    c2x = (b2[0] + b2[2]) * 0.5
    c2y = (b2[1] + b2[3]) * 0.5
    return float(np.hypot(c1x - c2x, c1y - c2y))


def _is_same_face_box(b1: Tuple, b2: Tuple) -> bool:
    max_dim = max(
        b1[2] - b1[0],
        b1[3] - b1[1],
        b2[2] - b2[0],
        b2[3] - b2[1],
        1,
    )
    return (
        _calculate_iou(b1, b2) >= IOU_THRESHOLD
        or _overlap_ratio(b1, b2) >= 0.42
        or _center_distance(b1, b2) <= max_dim * 0.55
    )


def _dedupe_detections(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    def score(item: Dict[str, Any]) -> Tuple[int, float, float]:
        bbox = item.get("bbox") or (0, 0, 0, 0)
        is_known = 1 if item.get("name") != "Unknown" else 0
        return (is_known, float(item.get("conf") or 0), _bbox_area(bbox))

    kept: List[Dict[str, Any]] = []
    for det in sorted(items, key=score, reverse=True):
        bbox = det.get("bbox")
        if bbox is None:
            continue
        if any(_is_same_face_box(bbox, k.get("bbox")) for k in kept if k.get("bbox")):
            continue
        kept.append(det)
    return kept


def _calculate_face_quality(crop_bgr: np.ndarray, det_conf: float = 0.0) -> float:
    """Score 0–1: sharpness × size × confidence."""
    if crop_bgr is None or crop_bgr.size == 0:
        return 0.0
    h, w  = crop_bgr.shape[:2]
    gray  = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    sharp = min(cv2.Laplacian(gray, cv2.CV_64F).var() / 500.0, 1.0)
    size  = min((h * w) / 40000.0, 1.0)
    conf  = float(np.clip(det_conf, 0, 1))
    return float(np.clip(sharp * 0.5 + size * 0.25 + conf * 0.25, 0, 1))


def _extract_face_crop(frame: np.ndarray, bbox: Tuple, padding: float = 0.3) -> Optional[np.ndarray]:
    if frame is None or frame.size == 0:
        return None
    H, W  = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    pw    = int((x2 - x1) * padding)
    ph    = int((y2 - y1) * padding)
    crop  = frame[max(0, y1 - ph):min(H, y2 + ph),
                  max(0, x1 - pw):min(W, x2 + pw)].copy()
    if crop.size == 0 or crop.shape[0] < MIN_FACE_PX or crop.shape[1] < MIN_FACE_PX:
        return None
    return crop


def _parse_det_size(value: Optional[str], default: Tuple[int, int]) -> Tuple[int, int]:
    if not value:
        return default
    try:
        cleaned = value.lower().replace("x", ",").replace(" ", "")
        parts = [int(p) for p in cleaned.split(",") if p]
        if len(parts) == 1:
            parts = [parts[0], parts[0]]
        if len(parts) >= 2 and parts[0] >= 320 and parts[1] >= 320:
            return (parts[0], parts[1])
    except Exception:
        pass
    logger.warning(f"Invalid det_size value '{value}', using {default}")
    return default


def _env_int(name: str, default: int, min_value: int = 1, max_value: int = 30) -> int:
    try:
        value = int(os.getenv(name, str(default)))
        return max(min_value, min(max_value, value))
    except Exception:
        return default


def _available_onnx_providers() -> List[str]:
    try:
        import onnxruntime as ort
        return list(ort.get_available_providers())
    except Exception:
        return []


def get_runtime_profile() -> Dict[str, Any]:
    """Return the current CPU/GPU tuning profile for stream workers."""
    return dict(runtime_profile)


# ═══════════════════════════════════════════════════════════════════════════
#   INITIALISATION
# ═══════════════════════════════════════════════════════════════════════════

def check_gpu_availability() -> List[int]:
    available = []
    providers = _available_onnx_providers()
    if 'CUDAExecutionProvider' not in providers:
        logger.info(f"CUDAExecutionProvider unavailable. ONNX providers: {providers or 'unknown'}")
        return available

    try:
        import subprocess
        res = subprocess.run(['nvidia-smi', '--list-gpus'],
                             capture_output=True, text=True, timeout=5)
        count = len([l for l in res.stdout.strip().split('\n') if l.strip()])
        available = list(range(count))
        logger.info(f"Detected {count} CUDA GPU(s)")
    except Exception:
        available = [0]
    return available


def _select_runtime(ctx: int, requested_det_size: Tuple[int, int]) -> Dict[str, Any]:
    providers = _available_onnx_providers()
    cuda_available = 'CUDAExecutionProvider' in providers
    gpu_ids = check_gpu_availability() if cuda_available else []
    wants_gpu = ctx >= 0
    auto_gpu = ctx == -1 and bool(gpu_ids)

    if (wants_gpu or auto_gpu) and gpu_ids:
        selected_ctx = ctx if wants_gpu else gpu_ids[0]
        if selected_ctx not in gpu_ids:
            selected_ctx = gpu_ids[0]
        gpu_det_size = _parse_det_size(os.getenv("FACE_DET_SIZE_GPU"), requested_det_size)
        return {
            "device": "gpu",
            "ctx": selected_ctx,
            "det_size": gpu_det_size,
            "process_every_n": _env_int("FACE_PROCESS_EVERY_N_GPU", 2, 1, 10),
            "providers": providers,
            "gpu_ids": gpu_ids,
        }

    cpu_default = (
        min(int(requested_det_size[0]), 640),
        min(int(requested_det_size[1]), 640),
    )
    cpu_det_size = _parse_det_size(os.getenv("FACE_DET_SIZE_CPU"), cpu_default)
    return {
        "device": "cpu",
        "ctx": -1,
        "det_size": cpu_det_size,
        "process_every_n": _env_int("FACE_PROCESS_EVERY_N_CPU", 5, 1, 30),
        "providers": providers,
        "gpu_ids": [],
    }


def _new_face_analysis(device: str):
    providers = ['CUDAExecutionProvider', 'CPUExecutionProvider'] if device == "gpu" else ['CPUExecutionProvider']
    try:
        return FaceAnalysis(allowed_modules=['detection'], providers=providers)
    except TypeError:
        return FaceAnalysis(allowed_modules=['detection'])


def init(data_dir: str,
         ctx: int = -1,
         det_size: Tuple[int, int] = (640, 640),
         use_dual_gpu: bool = True) -> None:
    """
    Initialise the face pipeline.

    For long-distance detection, pass a larger det_size such as (1280, 1280).
    This alone ~quadruples the effective resolution InsightFace uses.
    """
    global face_app, face_apps, available_gpus, data_directory, runtime_profile
    data_directory = data_dir

    try:
        from fr1 import load_known_faces  # noqa: F401 – just validate importability
    except Exception as e:
        raise ImportError("Cannot import load_known_faces from fr1.py") from e

    with embedding_lock:
        company_embeddings["_global"] = {"encodings": [], "names": [], "last_loaded": time.time()}

    face_apps.clear()
    available_gpus.clear()
    selected = _select_runtime(ctx, det_size)
    runtime_profile.update(selected)
    logger.info(
        "Face runtime selected: device=%s ctx=%s det_size=%s process_every_n=%s providers=%s",
        selected["device"],
        selected["ctx"],
        selected["det_size"],
        selected["process_every_n"],
        selected.get("providers") or "unknown",
    )

    def _make_app(ctx_id: int, device: str) -> Optional[Any]:
        try:
            app = _new_face_analysis(device)
            app.prepare(ctx_id=ctx_id, det_size=selected["det_size"])
            label = f"GPU {ctx_id}" if device == "gpu" else "CPU"
            logger.info(f"InsightFace ready on {label}, det_size={selected['det_size']}")
            return app
        except Exception as e:
            logger.warning(f"Failed to initialise InsightFace on {device} ctx={ctx_id}: {e}")
            return None

    if use_dual_gpu and selected["device"] == "gpu":
        for gpu_id in selected.get("gpu_ids", [])[:2]:
            app = _make_app(gpu_id, "gpu")
            if app:
                face_apps[gpu_id] = app
                available_gpus.append(gpu_id)
        if face_apps:
            globals()['face_app'] = face_apps[available_gpus[0]]
            return
        selected["device"] = "cpu"
        selected["ctx"] = -1
        selected["det_size"] = _parse_det_size(os.getenv("FACE_DET_SIZE_CPU"), (640, 640))
        selected["process_every_n"] = _env_int("FACE_PROCESS_EVERY_N_CPU", 5, 1, 30)
        runtime_profile.update(selected)

    app = _make_app(selected["ctx"], selected["device"])
    if app is None:
        logger.info("Falling back to CPU for InsightFace")
        runtime_profile.update({
            "device": "cpu",
            "ctx": -1,
            "det_size": _parse_det_size(os.getenv("FACE_DET_SIZE_CPU"), (640, 640)),
            "process_every_n": _env_int("FACE_PROCESS_EVERY_N_CPU", 5, 1, 30),
            "providers": selected.get("providers", []),
        })
        app = _new_face_analysis("cpu")
        app.prepare(ctx_id=-1, det_size=runtime_profile["det_size"])
    globals()['face_app'] = app
    if runtime_profile["device"] == "gpu":
        face_apps[runtime_profile["ctx"]] = app
        available_gpus.append(runtime_profile["ctx"])


# ═══════════════════════════════════════════════════════════════════════════
#   EMBEDDING MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════

def clear_company_embeddings_cache(company_id: str) -> None:
    with embedding_lock:
        company_embeddings.pop(company_id, None)
        logger.info(f"Cleared embedding cache for company {company_id}")


def load_company_embeddings(company_id: str) -> Dict[str, Any]:
    global data_directory
    with embedding_lock:
        cached = company_embeddings.get(company_id)
        if cached and time.time() - cached["last_loaded"] < 300:
            return cached
    try:
        from fr1 import load_known_faces
        encs, names = load_known_faces(data_directory, company_id=company_id)
        entry = {"encodings": encs, "names": names, "last_loaded": time.time()}
        with embedding_lock:
            company_embeddings[company_id] = entry
        return entry
    except Exception as e:
        logger.error(f"Failed to load embeddings for {company_id}: {e}")
        return {"encodings": [], "names": [], "last_loaded": 0}


def _get_face_app_for_stream(stream_id: Optional[str] = None):
    if not face_apps:
        return globals().get('face_app')
    if stream_id and available_gpus:
        return face_apps[available_gpus[hash(stream_id) % len(available_gpus)]]
    return face_apps[available_gpus[0]] if available_gpus else globals().get('face_app')


# ═══════════════════════════════════════════════════════════════════════════
#   TRACKING HELPERS
# ═══════════════════════════════════════════════════════════════════════════

def _match_detection_to_track(bbox: Tuple, tracks: Dict) -> Optional[int]:
    best_score, best_id = 0.0, None
    for tid, info in tracks.items():
        tb = info.get('bbox')
        if tb is None:
            continue
        iou = _calculate_iou(bbox, tb)
        overlap = _overlap_ratio(bbox, tb)
        same_face = _is_same_face_box(bbox, tb)
        score = max(iou, overlap * 0.9)
        if same_face and score > best_score:
            best_score, best_id = score, tid
    return best_id


def _cleanup_old_tracks(stream_id: str, frame_count: int, now: float):
    tracks = person_tracking.get(stream_id, {})
    stale  = [tid for tid, t in tracks.items()
               if (frame_count - t.get('frame_count', 0)) > MAX_TRACK_AGE_FRAMES
               or (now - t.get('last_seen', 0)) > MAX_TRACK_AGE_SECONDS]
    for tid in stale:
        del tracks[tid]


# ═══════════════════════════════════════════════════════════════════════════
#   MAIN PROCESS FRAME  (long-distance aware, single-pass for speed)
# ═══════════════════════════════════════════════════════════════════════════

def process_frame(frame_bgr: np.ndarray,
                  force_process: bool = False,
                  stream_id: Optional[str] = None,
                  company_id: Optional[str] = None
                  ) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """
    Detect + recognise faces.  Returns (original_frame, detections).

    Long-distance strategy (fast single-pass)
    ------------------------------------------
    1. Apply CLAHE contrast enhancement to the full frame
    2. Run InsightFace SCRFD once at det_size=(1280,1280) — this already
       quadruples effective resolution vs the old (640,640)
    3. Accept faces down to MIN_FACE_PX (20 px)
    4. Upscale small crops via Lanczos4 + unsharp mask before encoding
    5. Encode with dlib large model, consensus vote matching
    6. Track + persist labels across frames
    """
    global person_tracking, track_id_counter

    cur_face_app = _get_face_app_for_stream(stream_id)
    if cur_face_app is None:
        raise RuntimeError("Face pipeline not initialised. Call init() first.")
    if frame_bgr is None:
        return frame_bgr, []

    # ── Per-stream init ──────────────────────────────────────────────────
    if stream_id:
        person_tracking.setdefault(stream_id, {})
        track_id_counter.setdefault(stream_id, 0)

    # ── Resolve company / embeddings ─────────────────────────────────────
    if company_id is None and stream_id:
        try:
            from camera_management.streaming import get_stream_manager
            info = get_stream_manager().get_stream_info(stream_id)
            if info:
                company_id = info.get('company_id')
        except Exception:
            pass
    if not company_id or str(company_id).strip() in ("", "None"):
        company_id = "default"

    emb = load_company_embeddings(str(company_id))
    known_enc   = emb.get("encodings", [])
    known_names = emb.get("names", [])

    # ── Frame counter / periodic track cleanup ───────────────────────────
    now = time.time()
    _fc_key = f"{stream_id}_fc"
    if not hasattr(process_frame, '_fc'):
        process_frame._fc = {}
    process_frame._fc[_fc_key] = process_frame._fc.get(_fc_key, 0) + 1
    cur_fc = process_frame._fc[_fc_key]

    if stream_id and cur_fc % 10 == 0:
        with tracking_lock:
            _cleanup_old_tracks(stream_id, cur_fc, now)

    # ────────────────────────────────────────────────────────────────────
    #  STEP 1 – Single-pass detection with CLAHE enhancement
    #  The elevated det_size=(1280,1280) already handles long-distance.
    # ────────────────────────────────────────────────────────────────────
    orig_h, orig_w = frame_bgr.shape[:2]

    # Apply CLAHE to boost contrast for outdoor/far cameras
    enhanced = _apply_clahe(frame_bgr)

    t0 = time.time()
    faces = cur_face_app.get(enhanced)
    det_time = time.time() - t0

    if len(faces) > 0:
        logger.debug(f"[DETECT] {len(faces)} faces | {det_time:.3f}s | stream={stream_id}")

    tracks = person_tracking.get(stream_id, {}) if stream_id else {}
    detections: List[Dict[str, Any]] = []

    for f in faces:
        # ── Parse bbox ───────────────────────────────────────────────────
        try:
            bx1, by1, bx2, by2 = map(int, f.bbox[:4])
        except Exception:
            bbox_raw = getattr(f, 'bbox', None)
            if bbox_raw is None or len(bbox_raw) < 4:
                continue
            bx1, by1, bx2, by2 = int(bbox_raw[0]), int(bbox_raw[1]), int(bbox_raw[2]), int(bbox_raw[3])

        det_conf = float(getattr(f, 'det_score', 0) or getattr(f, 'score', 0) or 0)

        # Clamp to frame
        x1 = max(0, min(orig_w - 1, bx1))
        y1 = max(0, min(orig_h - 1, by1))
        x2 = max(0, min(orig_w - 1, bx2))
        y2 = max(0, min(orig_h - 1, by2))

        fw, fh = x2 - x1, y2 - y1

        # ── Accept faces down to MIN_FACE_PX (long-distance) ────────────
        if fw < MIN_FACE_PX or fh < MIN_FACE_PX:
            continue

        current_bbox = (x1, y1, x2, y2)

        # ── Crop + upscale for encoding ──────────────────────────────────
        face_crop_bgr = frame_bgr[y1:y2, x1:x2]
        if face_crop_bgr.size == 0:
            continue

        min_side = min(fw, fh)
        candidate_encodings = (
            _encode_face_variants(frame_bgr, current_bbox, min_side)
            if len(known_enc) > 0 else []
        )

        # ── Encoding ─────────────────────────────────────────────────────
        # ── Track matching ───────────────────────────────────────────────
        matched_tid    = None
        persisted_name = None
        if stream_id and tracks:
            with tracking_lock:
                matched_tid = _match_detection_to_track(current_bbox, tracks)
                if matched_tid is not None:
                    persisted_name = tracks[matched_tid].get('name')

        name = persisted_name if (persisted_name and persisted_name != "Unknown") else "Unknown"
        conf = 0.0
        face_encoding = None

        # ── Recognition ──────────────────────────────────────────────────
        matched_name, matched_conf, matched_encoding, _ = _match_known_face(
            candidate_encodings,
            known_enc,
            known_names,
            min_side,
            det_conf,
        )
        if matched_name != "Unknown":
            name = matched_name
            conf = matched_conf
            face_encoding = matched_encoding
        else:
            conf = det_conf

        # ── Update tracking ───────────────────────────────────────────────
        if stream_id:
            with tracking_lock:
                if matched_tid is None:
                    track_id_counter[stream_id] += 1
                    matched_tid = track_id_counter[stream_id]
                    tracks[matched_tid] = {
                        'name': name, 'bbox': current_bbox,
                        'last_seen': now, 'frame_count': cur_fc,
                        'encoding': face_encoding
                    }
                else:
                    t = tracks[matched_tid]
                    t['bbox']       = current_bbox
                    t['last_seen']  = now
                    t['frame_count'] = cur_fc
                    if t['name'] == "Unknown" and name != "Unknown":
                        t['name'] = name
                    if face_encoding is not None:
                        t['encoding'] = face_encoding

        # ── Save decision (quality-gated) ─────────────────────────────────
        quality      = _calculate_face_quality(face_crop_bgr, det_conf)
        person_key   = f"{name}_{matched_tid}" if name != "Unknown" else f"Unknown_{matched_tid}"
        should_save  = False
        save_interval = UNKNOWN_MIN_SAVE_INTERVAL if name == "Unknown" else MIN_SAVE_INTERVAL
        eligible_save = True

        if name == "Unknown" and (
            min_side < MIN_FACE_PX
            or det_conf < 0.45
            or (quality < 0.12 and det_conf < 0.80)
        ):
            eligible_save = False
        elif name != "Unknown" and (
            min_side < MIN_FACE_PX
            or (quality < 0.12 and det_conf < 0.55)
        ):
            eligible_save = False

        if eligible_save and stream_id:
            with tracking_lock:
                rec = best_face_quality[stream_id].get(person_key)
                if rec is None:
                    should_save = True
                    best_face_quality[stream_id][person_key] = {'quality': quality, 'timestamp': now}
                elif now - rec['timestamp'] > BEST_QUALITY_RESET_SECONDS:
                    should_save = True
                    best_face_quality[stream_id][person_key] = {'quality': quality, 'timestamp': now}
                elif quality > rec['quality'] + 0.08:
                    should_save = True
                    best_face_quality[stream_id][person_key] = {'quality': quality, 'timestamp': now}
        elif eligible_save:
            should_save = True

        if should_save:
            # Use padded crop for saving (head + shoulders)
            best_frame = None
            if stream_id:
                try:
                    from camera_management.streaming import get_stream_manager
                    best_frame = get_stream_manager().get_best_frame_for_bbox(stream_id, current_bbox)
                except Exception:
                    best_frame = None

            save_frame = best_frame if best_frame is not None else frame_bgr
            padded = _extract_face_crop(save_frame, current_bbox, padding=0.32)
            if padded is None:
                padded = face_crop_bgr
            padded_copy = padded.copy()

            camera_name_to_save  = stream_id or "default"
            company_id_to_save   = None
            if stream_id:
                try:
                    from camera_management.streaming import get_stream_manager
                    info = get_stream_manager().get_stream_info(stream_id)
                    if info:
                        camera_name_to_save = info.get('camera_name', camera_name_to_save)
                        company_id_to_save  = info.get('company_id')
                except Exception:
                    pass

            def _save_async():
                try:
                    save_face_image(
                        face_crop_bgr=padded_copy,
                        label=name,
                        confidence=conf,
                        min_interval=save_interval,
                        source="stream",
                        jpeg_quality=95,
                        target_width=224,
                        max_upscale=4.0,
                        camera_name=camera_name_to_save,
                        company_id=company_id_to_save,
                        identity_key=person_key,
                    )
                except Exception as e:
                    logger.error(f"Error saving face async: {e}")

            threading.Thread(target=_save_async, daemon=True).start()

        detections.append({
            "name": name,
            "conf": conf,
            "bbox": current_bbox,
            "face_size_px": (fw, fh),   # useful for debugging distance
        })

    # ── Return active tracked persons (persistence for UI) ────────────────
    if stream_id:
        active = []
        with tracking_lock:
            for tid, t in person_tracking.get(stream_id, {}).items():
                if now - t.get('last_seen', 0) < MAX_TRACK_AGE_SECONDS:
                    t_bbox = t.get('bbox')
                    active.append({
                        "name": t.get('name', 'Unknown'),
                        "conf": 0.95 if t.get('name') != "Unknown" else 0.5,
                        "bbox": t_bbox,
                        "track_id": tid,
                        "is_persisted": (now - t.get('last_seen', 0)) > 0.1,
                        "face_size_px": (
                            t_bbox[2] - t_bbox[0],
                            t_bbox[3] - t_bbox[1]
                        ) if t_bbox else (0, 0),
                    })
        return frame_bgr, _dedupe_detections(active)

    return frame_bgr, _dedupe_detections(detections)


# ═══════════════════════════════════════════════════════════════════════════
#   BOUNDING BOX RENDERER
# ═══════════════════════════════════════════════════════════════════════════

def render_bounding_boxes(frame: np.ndarray,
                           detections: List[Dict[str, Any]],
                           show_bounding_box: bool = True) -> np.ndarray:
    """
    Draw bounding boxes.  Purely cosmetic – does not affect detection/saving.
    Shows face size for unknown faces (useful for verifying long-distance detections).
    """
    if not show_bounding_box or not detections:
        return frame

    detections = _dedupe_detections(detections)
    show_size = os.getenv("SHOW_FACE_SIZE_LABEL", "0").lower() in ("1", "true", "yes")
    annotated = frame.copy()
    h, w      = annotated.shape[:2]
    font_scale = max(0.5, min(1.0, w / 900.0))
    thick      = max(2, int(font_scale * 2))
    box_thick  = max(2, int(font_scale * 2.5))

    for det in detections:
        name  = det.get("name", "Unknown")
        bbox  = det.get("bbox")
        if bbox is None:
            continue
        x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        color  = (0, 255, 0) if name != "Unknown" else (0, 0, 255)

        # ── Box ──────────────────────────────────────────────────────────
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, box_thick)

        # ── Label ────────────────────────────────────────────────────────
        label = name
        fx, fy = det.get("face_size_px", (0, 0))
        if show_size and fx > 0 and fy > 0:
            if name == "Unknown":
                label = f"Unknown ({fx}x{fy}px)"
            else:
                label = f"{name} ({fx}x{fy}px)"

        (lw, lh), base = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thick)
        ly = max(0, y1 - lh - base - 8)
        cv2.rectangle(annotated, (x1, ly), (x1 + lw + 8, ly + lh + base + 8), color, cv2.FILLED)
        cv2.putText(annotated, label, (x1 + 4, ly + lh + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale,
                    (255, 255, 255), thick, cv2.LINE_AA)

    return annotated
