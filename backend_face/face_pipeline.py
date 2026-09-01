# -*- coding: utf-8 -*-
"""Production live face detection + conservative dlib recognition.

Design goal: false acceptance is more harmful than an Unknown result for attendance.
SCRFD/InsightFace is used for multi-face detection; enrollment/live identity uses the
same dlib 128-D template bank generated during registration. Identity is released only
after temporal confirmation on one track and one physical face cannot share an identity
with another face in the same frame.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import Counter, defaultdict, deque
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import face_recognition
import numpy as np
from insightface.app import FaceAnalysis

from save_face import record_face_event, save_face_image

logger = logging.getLogger(__name__)

# Detection remains aggressive; recognition/attendance are intentionally stricter.
DETECTION_MIN_FACE_PX = int(os.getenv("FACE_DETECTION_MIN_PX", "20"))
DEFAULT_RECOGNITION_MIN_PX = int(os.getenv("FACE_RECOGNITION_MIN_PX", "56"))
DEFAULT_ATTENDANCE_MIN_PX = int(os.getenv("FACE_ATTENDANCE_MIN_PX", "72"))
DEFAULT_DISTANCE_THRESHOLD = float(os.getenv("FACE_MATCH_DISTANCE", "0.46"))
DEFAULT_DISTANT_THRESHOLD = float(os.getenv("FACE_DISTANT_MATCH_DISTANCE", "0.42"))
DEFAULT_MATCH_MARGIN = float(os.getenv("FACE_MATCH_MARGIN", "0.04"))
DEFAULT_CONFIRM_FRAMES = int(os.getenv("FACE_CONFIRM_FRAMES", "3"))
DEFAULT_CONFIRM_WINDOW = int(os.getenv("FACE_CONFIRM_WINDOW", "5"))
MAX_TRACK_AGE_SECONDS = float(os.getenv("FACE_TRACK_MAX_AGE_SECONDS", "1.25"))
MAX_TRACK_AGE_FRAMES = int(os.getenv("FACE_TRACK_MAX_AGE_FRAMES", "30"))
EVENT_INTERVAL_SECONDS = float(os.getenv("FACE_EVENT_INTERVAL_SECONDS", "5"))
KNOWN_IMAGE_INTERVAL_SECONDS = float(os.getenv("FACE_KNOWN_IMAGE_INTERVAL_SECONDS", "60"))
UNKNOWN_IMAGE_INTERVAL_SECONDS = float(os.getenv("FACE_UNKNOWN_IMAGE_INTERVAL_SECONDS", "60"))
EMBEDDING_CACHE_SECONDS = int(os.getenv("FACE_EMBEDDING_CACHE_SECONDS", "300"))

face_apps: Dict[int, Any] = {}
face_app = None
available_gpus: List[int] = []
runtime_profile: Dict[str, Any] = {
    "device": "uninitialized",
    "ctx": -1,
    "det_size": None,
    "process_every_n": 4,
    "providers": [],
}

data_directory = ""
company_embeddings: Dict[str, Dict[str, Any]] = {}
embedding_lock = threading.RLock()
person_tracking: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)
track_id_counter: Dict[str, int] = defaultdict(int)
tracking_lock = threading.RLock()
_frame_counters: Dict[str, int] = defaultdict(int)


def _settings(company_id: str) -> Dict[str, Any]:
    try:
        from auth.storage import get_settings
        return get_settings(company_id).get("recognition", {})
    except Exception:
        return {}


def _apply_clahe(bgr: np.ndarray) -> np.ndarray:
    try:
        lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        return cv2.cvtColor(cv2.merge([clahe.apply(l), a, b]), cv2.COLOR_LAB2BGR)
    except Exception:
        return bgr


def _available_onnx_providers() -> List[str]:
    try:
        import onnxruntime as ort
        return list(ort.get_available_providers())
    except Exception:
        return []


def check_gpu_availability() -> List[int]:
    providers = _available_onnx_providers()
    if "CUDAExecutionProvider" not in providers:
        return []
    try:
        import subprocess
        result = subprocess.run(["nvidia-smi", "--list-gpus"], capture_output=True, text=True, timeout=5)
        count = len([line for line in result.stdout.splitlines() if line.strip()])
        return list(range(count))
    except Exception:
        return [0]


def _parse_det_size(value: Optional[str], default: Tuple[int, int]) -> Tuple[int, int]:
    if not value:
        return default
    try:
        parts = [int(p) for p in value.lower().replace("x", ",").replace(" ", "").split(",") if p]
        if len(parts) == 1:
            parts *= 2
        if len(parts) >= 2 and min(parts[:2]) >= 320:
            return int(parts[0]), int(parts[1])
    except Exception:
        pass
    return default


def _select_runtime(ctx: int, requested_det_size: Tuple[int, int]) -> Dict[str, Any]:
    providers = _available_onnx_providers()
    gpus = check_gpu_availability()
    if gpus and (ctx >= 0 or ctx == -1):
        selected = ctx if ctx in gpus else gpus[0]
        return {
            "device": "gpu",
            "ctx": selected,
            "det_size": _parse_det_size(os.getenv("FACE_DET_SIZE_GPU"), requested_det_size),
            "process_every_n": max(1, int(os.getenv("FACE_PROCESS_EVERY_N_GPU", "2"))),
            "providers": providers,
            "gpu_ids": gpus,
        }
    cpu_default = (min(requested_det_size[0], 640), min(requested_det_size[1], 640))
    return {
        "device": "cpu",
        "ctx": -1,
        "det_size": _parse_det_size(os.getenv("FACE_DET_SIZE_CPU"), cpu_default),
        "process_every_n": max(1, int(os.getenv("FACE_PROCESS_EVERY_N_CPU", "5"))),
        "providers": providers,
        "gpu_ids": [],
    }


def _new_face_analysis(device: str):
    providers = ["CUDAExecutionProvider", "CPUExecutionProvider"] if device == "gpu" else ["CPUExecutionProvider"]
    try:
        return FaceAnalysis(allowed_modules=["detection"], providers=providers)
    except TypeError:
        return FaceAnalysis(allowed_modules=["detection"])


def init(data_dir: str, ctx: int = -1, det_size: Tuple[int, int] = (640, 640), use_dual_gpu: bool = True) -> None:
    global face_app, data_directory
    data_directory = data_dir
    selected = _select_runtime(ctx, det_size)
    runtime_profile.clear(); runtime_profile.update(selected)
    face_apps.clear(); available_gpus.clear()

    def make_app(ctx_id: int, device: str):
        app = _new_face_analysis(device)
        app.prepare(ctx_id=ctx_id, det_size=selected["det_size"])
        return app

    if use_dual_gpu and selected["device"] == "gpu":
        for gpu_id in selected.get("gpu_ids", [])[:2]:
            try:
                app = make_app(gpu_id, "gpu")
                face_apps[gpu_id] = app
                available_gpus.append(gpu_id)
            except Exception as exc:
                logger.warning("InsightFace GPU %s init failed: %s", gpu_id, exc)
        if face_apps:
            face_app = face_apps[available_gpus[0]]
            logger.info("Face detector ready on GPU(s) %s at %s", available_gpus, selected["det_size"])
            return

    try:
        face_app = make_app(selected["ctx"], selected["device"])
    except Exception:
        runtime_profile.update({"device": "cpu", "ctx": -1, "det_size": (640, 640), "process_every_n": 5})
        face_app = _new_face_analysis("cpu")
        face_app.prepare(ctx_id=-1, det_size=(640, 640))
    logger.info("Face detector ready: %s", runtime_profile)


def get_runtime_profile() -> Dict[str, Any]:
    return dict(runtime_profile)


def clear_company_embeddings_cache(company_id: str) -> None:
    with embedding_lock:
        company_embeddings.pop(str(company_id or "default"), None)


def load_company_embeddings(company_id: str) -> Dict[str, Any]:
    company_id = str(company_id or "default")
    with embedding_lock:
        cached = company_embeddings.get(company_id)
        if cached and time.time() - cached["loaded_at"] < EMBEDDING_CACHE_SECONDS:
            return cached
    try:
        from recognition.arcface import get_arcface_engine
        from recognition.backfill import backfill_arcface_gallery
        from recognition.vector_store import load_arcface_bank
        arcface = get_arcface_engine()
        if arcface.available:
            arc_bank = load_arcface_bank(company_id)
            if arc_bank.get("matrix") is None or arc_bank["matrix"].shape[0] == 0:
                backfill_arcface_gallery(data_directory, company_id)
                arc_bank = load_arcface_bank(company_id)
            if arc_bank.get("matrix") is not None and arc_bank["matrix"].shape[0] > 0:
                entry = {
                    "matrix": arc_bank["matrix"],
                    "names": list(arc_bank.get("names") or []),
                    "person_indices": arc_bank.get("person_indices") or {},
                    "loaded_at": time.time(),
                    "model": "arcface-512",
                }
                with embedding_lock:
                    company_embeddings[company_id] = entry
                return entry
    except Exception as exc:
        logger.warning("ArcFace bank unavailable for %s; using dlib fallback: %s", company_id, exc)

    try:
        from fr1 import load_known_faces
        encodings, names = load_known_faces(data_directory, company_id=company_id)
        matrix = np.asarray(encodings, dtype=np.float64)
        if matrix.size == 0:
            matrix = np.empty((0, 128), dtype=np.float64)
        elif matrix.ndim == 1:
            matrix = matrix.reshape(1, -1)
        person_indices: Dict[str, np.ndarray] = {}
        if names:
            names_arr = np.asarray(names, dtype=object)
            for name in sorted(set(names)):
                person_indices[name] = np.flatnonzero(names_arr == name)
        entry = {
            "matrix": matrix,
            "names": list(names),
            "person_indices": person_indices,
            "loaded_at": time.time(),
        }
        with embedding_lock:
            company_embeddings[company_id] = entry
        return entry
    except Exception as exc:
        logger.error("Failed loading face templates for %s: %s", company_id, exc)
        return {"matrix": np.empty((0, 128)), "names": [], "person_indices": {}, "loaded_at": 0.0}


def _get_face_app(stream_id: Optional[str]):
    if face_apps and available_gpus:
        return face_apps[available_gpus[hash(stream_id or "default") % len(available_gpus)]]
    return face_app


def _iou(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    if x2 <= x1 or y2 <= y1:
        return 0.0
    inter = (x2 - x1) * (y2 - y1)
    area_a = max(1, (a[2] - a[0]) * (a[3] - a[1]))
    area_b = max(1, (b[2] - b[0]) * (b[3] - b[1]))
    return inter / float(area_a + area_b - inter)


def _center_distance(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    ax, ay = (a[0] + a[2]) / 2.0, (a[1] + a[3]) / 2.0
    bx, by = (b[0] + b[2]) / 2.0, (b[1] + b[3]) / 2.0
    return float(np.hypot(ax - bx, ay - by))


def _box_size(box: Tuple[int, int, int, int]) -> Tuple[int, int]:
    return max(0, box[2] - box[0]), max(0, box[3] - box[1])


def _dedupe_boxes(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted(items, key=lambda d: (float(d.get("det_conf") or 0), _box_size(d["bbox"])[0] * _box_size(d["bbox"])[1]), reverse=True)
    kept = []
    for item in ordered:
        if any(_iou(item["bbox"], other["bbox"]) >= 0.55 for other in kept):
            continue
        kept.append(item)
    return kept


def _assign_tracks(stream_id: str, detections: List[Dict[str, Any]], frame_count: int, now: float) -> None:
    tracks = person_tracking[stream_id]
    stale = [tid for tid, t in tracks.items() if now - t.get("last_seen", 0) > MAX_TRACK_AGE_SECONDS or frame_count - t.get("frame_count", 0) > MAX_TRACK_AGE_FRAMES]
    for tid in stale:
        tracks.pop(tid, None)

    pairs = []
    for di, detection in enumerate(detections):
        box = detection["bbox"]
        fw, fh = _box_size(box)
        max_dim = max(fw, fh, 1)
        for tid, track in tracks.items():
            tbox = track.get("bbox")
            if not tbox:
                continue
            iou = _iou(box, tbox)
            center = _center_distance(box, tbox)
            proximity = max(0.0, 1.0 - center / max(max_dim * 1.5, 1.0))
            score = iou * 0.72 + proximity * 0.28
            if iou >= 0.10 or center <= max_dim * 0.65:
                pairs.append((score, di, tid))
    assigned_d, assigned_t = set(), set()
    for score, di, tid in sorted(pairs, reverse=True):
        if di in assigned_d or tid in assigned_t or score < 0.20:
            continue
        detections[di]["track_id"] = tid
        assigned_d.add(di); assigned_t.add(tid)

    for detection in detections:
        if "track_id" not in detection:
            track_id_counter[stream_id] += 1
            detection["track_id"] = track_id_counter[stream_id]
        tid = detection["track_id"]
        track = tracks.get(tid)
        if track is None:
            track = {
                "bbox": detection["bbox"],
                "last_seen": now,
                "frame_count": frame_count,
                "seen_count": 0,
                "history": deque(maxlen=max(DEFAULT_CONFIRM_WINDOW, 8)),
                "confirmed_name": None,
                "confirmed_at": None,
                "conflict_streak": 0,
                "last_event_at": 0.0,
                "last_image_at": 0.0,
                "last_unknown_at": 0.0,
                "best_quality": 0.0,
                "unknown_cluster_id": None,
            }
            tracks[tid] = track
        track["bbox"] = detection["bbox"]
        track["last_seen"] = now
        track["frame_count"] = frame_count
        track["seen_count"] = int(track.get("seen_count", 0)) + 1
        detection["track"] = track


def _quality(crop: np.ndarray, det_conf: float, face_px: int) -> float:
    if crop is None or crop.size == 0:
        return 0.0
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    sharpness = min(float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 450.0, 1.0)
    mean = float(np.mean(gray))
    exposure = 1.0 - min(abs(mean - 128.0) / 128.0, 1.0)
    size_score = min(face_px / 120.0, 1.0)
    return float(np.clip(sharpness * 0.42 + exposure * 0.18 + size_score * 0.22 + np.clip(det_conf, 0, 1) * 0.18, 0, 1))


def _crop(frame: np.ndarray, bbox: Tuple[int, int, int, int], padding: float = 0.12) -> Tuple[np.ndarray, Tuple[int, int, int, int]]:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = bbox
    fw, fh = max(1, x2 - x1), max(1, y2 - y1)
    px, py = int(fw * padding), int(fh * padding)
    cx1, cy1 = max(0, x1 - px), max(0, y1 - py)
    cx2, cy2 = min(w, x2 + px), min(h, y2 + py)
    image = frame[cy1:cy2, cx1:cx2].copy()
    location = (y1 - cy1, x2 - cx1, y2 - cy1, x1 - cx1)
    return image, location


def _encode_variants(frame: np.ndarray, bbox: Tuple[int, int, int, int], min_side: int) -> List[np.ndarray]:
    if min_side < DEFAULT_RECOGNITION_MIN_PX:
        return []
    variants = []
    paddings = (0.08, 0.20) if min_side < 90 else (0.10,)
    for padding in paddings:
        crop, loc = _crop(frame, bbox, padding)
        if crop.size == 0:
            continue
        target = 150 if min_side < 80 else 128
        top, right, bottom, left = loc
        face_short = max(1, min(right - left, bottom - top))
        if face_short < target:
            scale = min(target / face_short, 3.0)
            crop = cv2.resize(crop, (max(1, int(crop.shape[1] * scale)), max(1, int(crop.shape[0] * scale))), interpolation=cv2.INTER_LANCZOS4)
            loc = tuple(int(v * scale) for v in loc)
        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        try:
            enc = face_recognition.face_encodings(rgb, known_face_locations=[loc], num_jitters=1, model="large")
            if enc:
                variants.append(enc[0].astype(np.float64))
        except Exception:
            continue
    return variants


def _thresholds(company_id: str, min_side: int) -> Tuple[float, float, int, int, float, float, int, int]:
    cfg = _settings(company_id)
    recognition_min = int(cfg.get("min_recognition_face_px", DEFAULT_RECOGNITION_MIN_PX))
    attendance_min = int(cfg.get("min_attendance_face_px", DEFAULT_ATTENDANCE_MIN_PX))
    base = float(cfg.get("known_distance_threshold", DEFAULT_DISTANCE_THRESHOLD))
    distant = float(cfg.get("distant_distance_threshold", DEFAULT_DISTANT_THRESHOLD))
    # Smaller faces must pass a LOWER distance (stricter), never a looser one.
    threshold = distant if min_side < 90 else base
    margin = float(cfg.get("match_margin", DEFAULT_MATCH_MARGIN))
    min_quality = float(cfg.get("min_quality", 0.18))
    attendance_quality = float(cfg.get("min_attendance_quality", 0.24))
    confirm = max(2, int(cfg.get("confirmation_frames", DEFAULT_CONFIRM_FRAMES)))
    window = max(confirm, int(cfg.get("confirmation_window", DEFAULT_CONFIRM_WINDOW)))
    return threshold, margin, recognition_min, attendance_min, min_quality, attendance_quality, confirm, window


def _match(embeddings: List[np.ndarray], bank: Dict[str, Any], company_id: str, min_side: int) -> Dict[str, Any]:
    matrix = bank.get("matrix")
    names = bank.get("names") or []
    if not embeddings or matrix is None or len(names) == 0 or matrix.shape[0] == 0:
        return {"name": None, "distance": None, "confidence": 0.0, "embedding": embeddings[0] if embeddings else None, "margin": 0.0, "hits": 0}

    if matrix.shape[1] == 512:
        try:
            from recognition.vector_store import match_arcface_embeddings
            return match_arcface_embeddings(embeddings, company_id, min_side)
        except Exception as exc:
            logger.warning("ArcFace vector search failed for %s: %s", company_id, exc)
            return {"name": None, "distance": None, "confidence": 0.0, "embedding": embeddings[0], "margin": 0.0, "hits": 0}

    threshold, required_margin, *_ = _thresholds(company_id, min_side)
    indices = bank.get("person_indices") or {}
    best_result = None
    for embedding in embeddings:
        if matrix.shape[1] != embedding.shape[0]:
            continue
        distances = np.linalg.norm(matrix - embedding.reshape(1, -1), axis=1)
        people = []
        for person, idx in indices.items():
            person_distances = np.sort(distances[idx])
            if person_distances.size == 0:
                continue
            minimum = float(person_distances[0])
            hits = int(np.sum(person_distances <= threshold))
            top_count = min(2, person_distances.size)
            score_distance = float(np.mean(person_distances[:top_count]))
            people.append((score_distance, minimum, person, hits, int(person_distances.size)))
        if not people:
            continue
        people.sort(key=lambda x: (x[0], x[1]))
        score_distance, minimum, person, hits, template_count = people[0]
        second_score = people[1][0] if len(people) > 1 else 1.0
        margin = float(second_score - score_distance)

        required_hits = 2 if template_count >= 3 else 1
        # A person with only one enrollment template receives an extra strict penalty.
        effective_threshold = threshold - 0.02 if template_count == 1 else threshold
        accepted = minimum <= effective_threshold and hits >= required_hits and (len(people) == 1 or margin >= required_margin)
        result = {
            "name": person if accepted else None,
            "distance": minimum,
            "score_distance": score_distance,
            "confidence": float(np.clip(1.0 - minimum, 0.0, 1.0)),
            "embedding": embedding,
            "margin": margin,
            "hits": hits,
            "threshold": effective_threshold,
        }
        if accepted and (best_result is None or minimum < best_result["distance"]):
            best_result = result
        elif best_result is None:
            best_result = result
    return best_result or {"name": None, "distance": None, "confidence": 0.0, "embedding": embeddings[0] if embeddings else None, "margin": 0.0, "hits": 0}


def _update_identity(track: Dict[str, Any], match: Dict[str, Any], quality: float, company_id: str, min_side: int) -> None:
    threshold, margin_req, _, _, min_quality, _, confirm_frames, window = _thresholds(company_id, min_side)
    history: deque = track["history"]
    # Resize history if tenant settings changed.
    if history.maxlen != window:
        history = deque(list(history)[-window:], maxlen=window)
        track["history"] = history

    candidate = match.get("name") if quality >= min_quality else None
    history.append(candidate)
    confirmed = track.get("confirmed_name")

    if confirmed:
        if candidate and candidate != confirmed and match.get("distance") is not None and match.get("margin", 0) >= margin_req:
            track["conflict_streak"] = int(track.get("conflict_streak", 0)) + 1
        elif candidate == confirmed:
            track["conflict_streak"] = 0
        # Revoke a label after two strong contradictory observations. This prevents
        # a tracker ID swap in a crowd from carrying the previous person's name.
        if track.get("conflict_streak", 0) >= 2:
            track["confirmed_name"] = None
            track["confirmed_at"] = None
            track["history"].clear()
            track["history"].append(candidate)
            track["conflict_streak"] = 0
        return

    counts = Counter(name for name in history if name)
    if not counts:
        return
    name, count = counts.most_common(1)[0]
    if count >= confirm_frames:
        # Competing identities inside the confirmation window make the track ambiguous.
        competitors = sum(v for k, v in counts.items() if k != name)
        if competitors <= 1:
            track["confirmed_name"] = name
            track["confirmed_at"] = time.time()
            track["conflict_streak"] = 0


def _display_name(person_key: str, company_id: str) -> str:
    try:
        from db.repository import get_person
        person = get_person(company_id, person_key)
        return (person or {}).get("name") or person_key.replace("_", " ").title()
    except Exception:
        return person_key.replace("_", " ").title()


def _best_crop(stream_id: Optional[str], track_id: int, frame: np.ndarray, bbox: Tuple[int, int, int, int]) -> np.ndarray:
    if stream_id:
        try:
            from camera_management.streaming import get_stream_manager
            manager = get_stream_manager()
            manager.register_track_frame(stream_id, track_id, frame, bbox)
            crop = manager.get_best_crop_for_track(stream_id, track_id)
            if crop is not None and crop.size:
                return crop
        except Exception:
            pass
    crop, _ = _crop(frame, bbox, 0.35)
    return crop


def process_frame(
    frame_bgr: np.ndarray,
    force_process: bool = False,
    stream_id: Optional[str] = None,
    company_id: Optional[str] = None,
) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    detector = _get_face_app(stream_id)
    if detector is None:
        raise RuntimeError("Face pipeline not initialized")
    if frame_bgr is None or frame_bgr.size == 0:
        return frame_bgr, []

    company_id = str(company_id or "default")
    bank = load_company_embeddings(company_id)
    stream_key = str(stream_id or "default")
    now = time.time()
    _frame_counters[stream_key] += 1
    frame_count = _frame_counters[stream_key]

    enhanced = _apply_clahe(frame_bgr)
    try:
        faces = detector.get(enhanced)
    except Exception as exc:
        logger.error("Face detector failed for %s: %s", stream_key, exc)
        return frame_bgr, []

    h, w = frame_bgr.shape[:2]
    raw = []
    for face in faces:
        try:
            x1, y1, x2, y2 = [int(v) for v in face.bbox[:4]]
        except Exception:
            continue
        x1, x2 = max(0, min(w - 1, x1)), max(1, min(w, x2))
        y1, y2 = max(0, min(h - 1, y1)), max(1, min(h, y2))
        fw, fh = x2 - x1, y2 - y1
        if fw < DETECTION_MIN_FACE_PX or fh < DETECTION_MIN_FACE_PX:
            continue
        kps = getattr(face, "kps", None)
        raw.append({
            "bbox": (x1, y1, x2, y2),
            "det_conf": float(getattr(face, "det_score", 0.0) or getattr(face, "score", 0.0) or 0.0),
            "kps": np.asarray(kps, dtype=np.float32).reshape(-1, 2).tolist() if kps is not None else None,
        })
    raw = _dedupe_boxes(raw)

    with tracking_lock:
        _assign_tracks(stream_key, raw, frame_count, now)

    results = []
    for detection in raw:
        bbox = detection["bbox"]
        fw, fh = _box_size(bbox)
        min_side = min(fw, fh)
        face_crop = frame_bgr[bbox[1]:bbox[3], bbox[0]:bbox[2]]
        quality = _quality(face_crop, detection["det_conf"], min_side)
        threshold, margin_req, recognition_min, attendance_min, min_quality, attendance_quality, confirm_frames, window = _thresholds(company_id, min_side)

        embeddings = []
        if min_side >= recognition_min:
            try:
                from recognition.arcface import get_arcface_engine
                arcface = get_arcface_engine()
                if arcface.available:
                    arc_embedding = arcface.embed_frame(frame_bgr, bbox, detection.get("kps"))
                    if arc_embedding is not None:
                        embeddings = [arc_embedding.astype(np.float64)]
            except Exception as exc:
                logger.debug("ArcFace live embedding fallback: %s", exc)
            if not embeddings:
                embeddings = _encode_variants(frame_bgr, bbox, min_side)
        match = _match(embeddings, bank, company_id, min_side)
        track = detection["track"]
        with tracking_lock:
            _update_identity(track, match, quality, company_id, min_side)
            confirmed = track.get("confirmed_name")

        try:
            from recognition.liveness import get_liveness_engine
            liveness = get_liveness_engine().evaluate(track, face_crop)
        except Exception:
            liveness = {"score": 0.0, "passed": True, "mode": "unavailable", "required": False}

        stream_info = {}
        if stream_id:
            try:
                from camera_management.streaming import get_stream_manager
                stream_info = get_stream_manager().get_stream_info(stream_id) or {}
            except Exception:
                stream_info = {}
        try:
            from tracking.direction import has_virtual_line, update_track_direction
            event_direction = update_track_direction(track, bbox, frame_bgr.shape, stream_info)
            crossing_required = bool(
                str(stream_info.get("camera_role") or "BIDIRECTIONAL").upper() == "BIDIRECTIONAL"
                and str(stream_info.get("direction") or "AUTO").upper() == "AUTO"
                and has_virtual_line(stream_info)
            )
        except Exception:
            event_direction = str(stream_info.get("direction") or "AUTO").upper()
            crossing_required = False

        current_match_is_confirmed = bool(confirmed and match.get("name") == confirmed)
        attendance_eligible = bool(
            current_match_is_confirmed
            and min_side >= attendance_min
            and quality >= attendance_quality
            and detection["det_conf"] >= 0.55
            and bool(liveness.get("passed", True))
            and event_direction != "NONE"
            and (not crossing_required or event_direction in {"IN", "OUT"})
        )
        results.append({
            "name": confirmed or "Unknown",
            "display_name": _display_name(confirmed, company_id) if confirmed else "Unknown",
            "candidate": match.get("name"),
            "conf": float(match.get("confidence") or detection["det_conf"]),
            "distance": match.get("distance"),
            "margin": float(match.get("margin") or 0.0),
            "quality": quality,
            "bbox": bbox,
            "track_id": detection["track_id"],
            "track": track,
            "embedding": match.get("embedding") if match.get("embedding") is not None else (embeddings[0] if embeddings else None),
            "face_size_px": (fw, fh),
            "attendance_eligible": attendance_eligible,
            "current_match_is_confirmed": current_match_is_confirmed,
            "det_conf": detection["det_conf"],
            "liveness_score": float(liveness.get("score") or 0.0),
            "liveness_passed": bool(liveness.get("passed", True)),
            "liveness_mode": liveness.get("mode"),
            "event_direction": event_direction,
            "model_version": match.get("model_version") or ("arcface-512" if embeddings and embeddings[0].shape[0] == 512 else "dlib-128-consensus-v2"),
        })

    # One physical identity may appear at most once in one frame. If two distinct
    # boxes resolve to the same employee, only the strongest observation keeps the
    # identity; the other remains Unknown until subsequent frames disambiguate it.
    by_name: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in results:
        if item["name"] != "Unknown":
            by_name[item["name"]].append(item)
    for name, items in by_name.items():
        if len(items) <= 1:
            continue
        items.sort(key=lambda x: (
            1 if x["current_match_is_confirmed"] else 0,
            -(x["distance"] if x["distance"] is not None else 9.0),
            x["quality"],
        ), reverse=True)
        for loser in items[1:]:
            loser["identity_conflict"] = True
            loser["name"] = "Unknown"
            loser["display_name"] = "Unknown"
            loser["attendance_eligible"] = False

    # Persist DB observations independently from JPEG retention. JPEG is evidence;
    # recognition_events/attendance_sessions are authoritative history.
    for item in results:
        track = item["track"]
        track_id = item["track_id"]
        bbox = item["bbox"]
        if item["name"] != "Unknown" and item["current_match_is_confirmed"]:
            if now - float(track.get("last_event_at", 0.0)) >= EVENT_INTERVAL_SECONDS:
                image_path = None
                should_image = (
                    track.get("last_image_at", 0.0) == 0.0
                    or now - float(track.get("last_image_at", 0.0)) >= KNOWN_IMAGE_INTERVAL_SECONDS
                    or item["quality"] > float(track.get("best_quality", 0.0)) + 0.10
                )
                if should_image:
                    crop = _best_crop(stream_id, track_id, frame_bgr, bbox)
                    saved = save_face_image(
                        face_crop_bgr=crop,
                        label=item["name"],
                        confidence=item["conf"],
                        min_interval=0,
                        source="stream",
                        camera_name=stream_id,
                        company_id=company_id,
                        identity_key=f"{item['name']}:{track_id}",
                    )
                    if saved:
                        image_path = str(saved)
                        track["last_image_at"] = now
                        track["best_quality"] = max(float(track.get("best_quality", 0.0)), item["quality"])
                try:
                    camera_name = stream_id
                    if stream_id:
                        from camera_management.streaming import get_stream_manager
                        info = get_stream_manager().get_stream_info(stream_id) or {}
                        camera_name = info.get("camera_name") or stream_id
                    record_face_event(
                        company_id=company_id,
                        label=item["name"],
                        display_name=item["display_name"],
                        embedding=item["embedding"],
                        confidence=item["conf"],
                        distance=item["distance"],
                        quality=item["quality"],
                        face_size=item["face_size_px"],
                        camera_name=camera_name,
                        image_path=image_path,
                        attendance_eligible=item["attendance_eligible"],
                        direction_override=item.get("event_direction"),
                        model_version=item.get("model_version"),
                    )
                    track["last_event_at"] = now
                except Exception as exc:
                    logger.error("Could not persist recognition event: %s", exc)
        else:
            # Do not immediately save a known employee as Unknown while the first
            # confirmation frames are accumulating. Save only stable unknown tracks.
            known_votes = sum(1 for value in track.get("history", []) if value)
            stable_unknown = int(track.get("seen_count", 0)) >= 3 and known_votes == 0
            embedding = item.get("embedding")
            if stable_unknown and embedding is not None and item["quality"] >= 0.16 and item["det_conf"] >= 0.60:
                if now - float(track.get("last_unknown_at", 0.0)) >= UNKNOWN_IMAGE_INTERVAL_SECONDS:
                    try:
                        from db.repository import cluster_unknown
                        cfg = _settings(company_id)
                        cluster_key = track.get("unknown_cluster_id") or cluster_unknown(
                            company_id,
                            embedding,
                            quality=item["quality"],
                            threshold=float(cfg.get("unknown_cluster_similarity", 0.88)),
                        )
                        track["unknown_cluster_id"] = cluster_key
                        crop = _best_crop(stream_id, track_id, frame_bgr, bbox)
                        camera_name = stream_id
                        if stream_id:
                            from camera_management.streaming import get_stream_manager
                            info = get_stream_manager().get_stream_info(stream_id) or {}
                            camera_name = info.get("camera_name") or stream_id
                        saved = save_face_image(
                            face_crop_bgr=crop,
                            label="Unknown",
                            confidence=item["det_conf"],
                            min_interval=0,
                            source="stream",
                            camera_name=camera_name,
                            company_id=company_id,
                            identity_key=f"unknown:{track_id}",
                            unknown_cluster_id=cluster_key,
                        )
                        record_face_event(
                            company_id=company_id,
                            label="Unknown",
                            display_name="Unknown",
                            embedding=embedding,
                            confidence=item["det_conf"],
                            distance=None,
                            quality=item["quality"],
                            face_size=item["face_size_px"],
                            camera_name=camera_name,
                            image_path=str(saved) if saved else None,
                            attendance_eligible=False,
                            unknown_cluster_id=cluster_key,
                            direction_override=item.get("event_direction"),
                            model_version=item.get("model_version"),
                        )
                        track["last_unknown_at"] = now
                    except Exception as exc:
                        logger.error("Could not persist unknown face: %s", exc)

    public = []
    for item in results:
        public.append({
            "name": item["display_name"] if item["name"] != "Unknown" else "Unknown",
            "person_key": item["name"] if item["name"] != "Unknown" else None,
            "conf": item["conf"],
            "bbox": item["bbox"],
            "track_id": item["track_id"],
            "face_size_px": item["face_size_px"],
            "quality": item["quality"],
            "is_confirmed": item["name"] != "Unknown",
            "is_verifying": item["name"] == "Unknown" and bool(item.get("candidate")),
            "attendance_eligible": item["attendance_eligible"],
            "identity_conflict": bool(item.get("identity_conflict")),
            "liveness_score": item.get("liveness_score"),
            "liveness_passed": item.get("liveness_passed"),
            "liveness_mode": item.get("liveness_mode"),
            "direction": item.get("event_direction"),
            "model_version": item.get("model_version"),
        })
    return frame_bgr, public


def render_bounding_boxes(frame: np.ndarray, detections: List[Dict[str, Any]], show_bounding_box: bool = True) -> np.ndarray:
    if not show_bounding_box or frame is None or not detections:
        return frame
    output = frame.copy()
    for detection in detections:
        box = detection.get("bbox")
        if not box:
            continue
        x1, y1, x2, y2 = [int(v) for v in box]
        confirmed = bool(detection.get("is_confirmed"))
        verifying = bool(detection.get("is_verifying"))
        if confirmed:
            color = (35, 160, 85)
            label = detection.get("name") or "Recognized"
        elif verifying:
            color = (0, 155, 220)
            label = "Verifying"
        else:
            color = (70, 95, 220)
            label = "Unknown"
        cv2.rectangle(output, (x1, y1), (x2, y2), color, 2)
        font_scale = max(0.45, min(0.75, output.shape[1] / 1400.0))
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, 1)
        ty = max(0, y1 - th - 8)
        cv2.rectangle(output, (x1, ty), (x1 + tw + 10, y1), color, -1)
        cv2.putText(output, label, (x1 + 5, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), 1, cv2.LINE_AA)
    return output
