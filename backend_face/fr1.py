# fr1.py
# -*- coding: utf-8 -*-
"""
Webcam / RTSP face detection (InsightFace SCRFD) + recognition (face_recognition).
Configured for long-distance detection:
  - INSIGHT_DET_SIZE bumped to (1280, 1280) — detects much smaller faces
  - HOG face location model replaced with CNN for better long-distance results
  - Embedding cache keyed by mtime so new training images are picked up instantly
"""

import os
import glob
import time
from typing import List, Tuple, Optional

import cv2
import numpy as np
import face_recognition

try:
    from insightface.app import FaceAnalysis
except Exception as e:
    raise ImportError("insightface is required. Install with: pip install insightface") from e

# ─────────────────────── Configuration ─────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
CAMERA_INDEX = 0

TOLERANCE            = 0.48   # tighter threshold → fewer false positives
FRAME_DISPLAY_SCALE  = 1.0

# ── Long-distance settings ──────────────────────────────────────────────────
#   Larger det_size = InsightFace processes the image at higher resolution
#   → detects smaller faces (people farther away from the camera).
#   (640,640) is default; (1280,1280) detects roughly 4× smaller faces.
INSIGHT_CTX      = 0               # -1=CPU, 0=GPU
INSIGHT_DET_SIZE = (1280, 1280)    # ← CHANGED from (640,640) for long-distance

# Minimum face pixel size to accept (long-distance people have small boxes)
MIN_FACE_PX = 20   # ← was 50-60; now accepts faces 10 m+ away

IGNORE_FOLDERS = {
    "gallery", "auth", "camera_management",
    "temp_bulk", "__pycache__", ".ipynb_checkpoints"
}
# ───────────────────────────────────────────────────────────────────────────


def load_known_faces(data_dir: str,
                     company_id: Optional[str] = None
                     ) -> Tuple[List[np.ndarray], List[str]]:
    """
    Load (and cache) 128-d face embeddings from the gallery directory.

    Uses a per-company pickle cache keyed by image mtime, so:
      - First run: computes all embeddings (slow)
      - Subsequent runs: cache hit (fast)
      - New / modified images: automatically recomputed
    """
    import pickle

    known_encodings: List[np.ndarray] = []
    known_names:     List[str]        = []

    company_id_to_use = company_id or "default"
    cache_name  = f"embeddings_cache_{company_id_to_use}.pkl"
    cache_path  = os.path.join(data_dir, cache_name)
    cache: dict = {}

    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                cache = pickle.load(f)
            print(f"[INFO] Loaded {len(cache)} entries from cache ({company_id_to_use})")
        except Exception as e:
            print(f"[WARN] Cache load failed, rebuilding: {e}")
            cache = {}

    if not os.path.isdir(data_dir):
        raise ValueError(f"Data directory does not exist: {data_dir}")

    gallery_dir = os.path.join(data_dir, "gallery", company_id_to_use)
    if not os.path.exists(gallery_dir):
        print(f"[WARN] Gallery not found for company '{company_id_to_use}': {gallery_dir}")
        return [], []

    person_dirs = [
        d for d in sorted(os.listdir(gallery_dir))
        if os.path.isdir(os.path.join(gallery_dir, d)) and d not in IGNORE_FOLDERS
    ]
    print(f"[INFO] {len(person_dirs)} person(s) in {gallery_dir}")

    current_files: set = set()
    new_computations   = 0

    for person in person_dirs:
        files = [
            f for f in glob.glob(os.path.join(gallery_dir, person, "*"))
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp"))
        ]
        if not files:
            continue

        for img_path in files:
            current_files.add(img_path)
            try:
                mtime = os.path.getmtime(img_path)

                # Cache hit
                if img_path in cache and cache[img_path]["mtime"] == mtime:
                    for enc in cache[img_path]["encodings"]:
                        known_encodings.append(enc)
                        known_names.append(person)
                    continue

                # Cache miss — compute encoding
                probe = cv2.imread(img_path)
                if probe is None or probe.size == 0:
                    cache.pop(img_path, None)
                    print(f"[WARN] Invalid image file {img_path} — skipping")
                    continue

                img = face_recognition.load_image_file(img_path)

                # Try HOG first (fast); fall back to CNN for long-distance/small faces
                locations = face_recognition.face_locations(img, model="hog")
                if not locations:
                    locations = face_recognition.face_locations(img, model="cnn")
                if not locations:
                    print(f"[WARN] No face in {img_path} — skipping")
                    continue

                encs = face_recognition.face_encodings(
                    img,
                    known_face_locations=locations,
                    num_jitters=2,    # 2 jitters for better embedding quality
                    model='large'     # must match face_pipeline.py
                )
                if not encs:
                    print(f"[WARN] Could not encode {img_path}")
                    continue

                for enc in encs:
                    known_encodings.append(enc)
                    known_names.append(person)

                cache[img_path] = {"mtime": mtime, "encodings": encs, "name": person}
                new_computations += 1
                print(f"[INFO] Encoded {img_path} -> {person}")

            except Exception as e:
                print(f"[ERROR] Failed on {img_path}: {e}")

    # Purge deleted files from cache
    deleted = [p for p in cache if p not in current_files]
    for p in deleted:
        del cache[p]
    if deleted:
        print(f"[INFO] Purged {len(deleted)} stale cache entries")

    if new_computations or deleted:
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(cache, f)
            print(f"[INFO] Saved cache ({len(cache)} entries)")
        except Exception as e:
            print(f"[ERROR] Could not save cache: {e}")

    print(f"[INFO] Total encodings: {len(known_encodings)} | New: {new_computations}")
    return known_encodings, known_names


def prepare_insightface(ctx: int = INSIGHT_CTX,
                        det_size: Tuple[int, int] = INSIGHT_DET_SIZE) -> FaceAnalysis:
    """Prepare InsightFace detector for long-distance use."""
    try:
        import onnxruntime as ort
        print("[INFO] ONNX providers:", ort.get_available_providers())
    except Exception:
        pass

    app = FaceAnalysis(allowed_modules=['detection'])
    app.prepare(ctx_id=ctx, det_size=det_size)
    print(f"[INFO] InsightFace ready | ctx={ctx} | det_size={det_size}")
    return app


def recognize_frame_insight(frame_bgr: np.ndarray,
                             app: FaceAnalysis,
                             known_encodings: List[np.ndarray],
                             known_names: List[str]) -> np.ndarray:
    """
    Run long-distance detection + recognition on a single frame.
    Upscales small face crops before encoding for better accuracy.
    """
    if frame_bgr is None:
        return frame_bgr

    orig_h, orig_w = frame_bgr.shape[:2]

    # CLAHE to help with dim / far-away cameras
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = cv2.cvtColor(cv2.merge([clahe.apply(l), a, b]), cv2.COLOR_LAB2BGR)

    faces = app.get(enhanced)

    for f in faces:
        try:
            x1, y1, x2, y2 = map(int, f.bbox)
        except Exception:
            bx = f.bbox
            if len(bx) < 4:
                continue
            x1, y1, x2, y2 = int(bx[0]), int(bx[1]), int(bx[2]), int(bx[3])

        x1 = max(0, min(orig_w - 1, x1))
        x2 = max(0, min(orig_w - 1, x2))
        y1 = max(0, min(orig_h - 1, y1))
        y2 = max(0, min(orig_h - 1, y2))

        fw, fh = x2 - x1, y2 - y1
        if fw < MIN_FACE_PX or fh < MIN_FACE_PX:
            continue

        # Crop and upscale small faces before encoding
        crop_bgr = frame_bgr[y1:y2, x1:x2]
        target   = 112
        short    = min(fw, fh)
        if short < target:
            scale    = target / short
            crop_bgr = cv2.resize(
                crop_bgr,
                (max(target, int(fw * scale)), max(target, int(fh * scale))),
                interpolation=cv2.INTER_LANCZOS4
            )

        crop_rgb  = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2RGB)
        ch, cw    = crop_rgb.shape[:2]
        crop_loc  = [(0, cw - 1, ch - 1, 0)]

        try:
            encs = face_recognition.face_encodings(
                crop_rgb,
                known_face_locations=crop_loc,
                num_jitters=1,
                model='large'
            )
        except Exception:
            encs = []

        name = "Unknown"
        dist = None

        if encs and known_encodings:
            dists    = face_recognition.face_distance(known_encodings, encs[0])
            best_idx = int(np.argmin(dists))
            best_d   = float(dists[best_idx])
            dist     = best_d
            if best_d <= TOLERANCE:
                name = known_names[best_idx]

        color = (0, 255, 0) if name != "Unknown" else (0, 0, 255)
        cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), color, 2)

        conf    = getattr(f, "det_score", None) or getattr(f, "score", None)
        parts   = [name]
        if dist  is not None: parts.append(f"d={dist:.2f}")
        if conf  is not None: parts.append(f"det={conf:.2f}")
        parts.append(f"{fw}x{fh}px")   # show face size for distance debugging

        label   = " | ".join(parts)
        label_y = y1 - 10 if y1 - 10 > 10 else y2 + 20
        cv2.putText(frame_bgr, label, (x1, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (255, 255, 255), 2, cv2.LINE_AA)

    return frame_bgr


def main():
    print("[INFO] Loading known faces ...")
    known_encodings, known_names = load_known_faces(DATA_DIR)
    if not known_encodings:
        print("[ERROR] No known faces found. Add images to data/gallery/<company>/<name>/")
        return

    app = prepare_insightface(ctx=INSIGHT_CTX, det_size=INSIGHT_DET_SIZE)

    print(f"[INFO] Opening camera {CAMERA_INDEX} ...")
    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"[ERROR] Cannot open camera {CAMERA_INDEX}")
        return

    # High resolution capture for maximum long-distance detection
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
    cap.set(cv2.CAP_PROP_FPS, 30)

    print("[INFO] Press 'q' to quit.")
    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            annotated = recognize_frame_insight(frame, app, known_encodings, known_names)

            if FRAME_DISPLAY_SCALE != 1.0:
                annotated = cv2.resize(annotated, (0, 0), fx=FRAME_DISPLAY_SCALE, fy=FRAME_DISPLAY_SCALE)

            cv2.imshow("Long-Distance Face Recognition | press Q to quit", annotated)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted")
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
