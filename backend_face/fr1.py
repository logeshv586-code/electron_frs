# fr1.py
# -*- coding: utf-8 -*-
"""
Webcam face detection (InsightFace SCRFD) + recognition (face_recognition).
Replaces face_recognition's detector with insightface for better tiny/long-distance faces.
"""

import os
import glob
import time
from typing import List, Tuple, Optional

import cv2
import numpy as np
import face_recognition

# InsightFace import
try:
    from insightface.app import FaceAnalysis
except Exception as e:
    raise ImportError("insightface is required for detection. Install with: pip install insightface") from e

# ----------------- Configuration -----------------
DATA_DIR = os.path.join(os.path.dirname(__file__), "data")   # keep your dataset path
CAMERA_INDEX = 0
# Keep this for face_recognition's matching - only used for encoding & distance threshold
TOLERANCE = 0.5
# Resize factor for display / speed (detection runs on original frame; you can reduce for speed)
FRAME_DISPLAY_SCALE = 1.0

# InsightFace detection settings
INSIGHT_CTX = 0                 # -1 = CPU; 0 = GPU if you have onnxruntime-gpu & CUDA
INSIGHT_DET_SIZE = (640, 640)   # detector input size (increase to e.g. (1024,1024) for tiny faces)

# Folders to ignore when loading known faces
IGNORE_FOLDERS = {
    "gallery", 
    "auth", 
    "camera_management", 
    "temp_bulk", 
    "__pycache__", 
    ".ipynb_checkpoints"
}
# --------------------------------------------------


def load_known_faces(data_dir: str, company_id: Optional[str] = None) -> Tuple[List[np.ndarray], List[str]]:
    import pickle
    
    known_encodings: List[np.ndarray] = []
    known_names: List[str] = []
    
    # Use company-specific cache file
    cache_name = f"embeddings_cache_{company_id}.pkl" if company_id else "embeddings_cache.pkl"
    cache_path = os.path.join(data_dir, cache_name)
    cache = {}
    
    # Load existing cache if available
    if os.path.exists(cache_path):
        try:
            with open(cache_path, "rb") as f:
                cache = pickle.load(f)
            print(f"[INFO] Loaded {len(cache)} entries from embeddings cache ({company_id or 'global'})")
        except Exception as e:
            print(f"[WARN] Failed to load cache, starting fresh: {e}")
            cache = {}

    if not os.path.isdir(data_dir):
        raise ValueError(f"Data directory does not exist: {data_dir}")

    # Determine which directories to scan
    # If company_id is provided, we scan data/gallery/<company_id>/*
    # Otherwise we scan the base data directory (for backward compatibility)
    scan_dir = data_dir
    if company_id:
        gallery_dir = os.path.join(data_dir, "gallery", company_id)
        if os.path.exists(gallery_dir):
            scan_dir = gallery_dir
        else:
            print(f"[WARN] Gallery directory for company {company_id} not found: {gallery_dir}")
            return [], []

    # Filter out system folders and non-directories
    person_dirs = [
        d for d in sorted(os.listdir(scan_dir)) 
        if os.path.isdir(os.path.join(scan_dir, d)) and d not in IGNORE_FOLDERS
    ]
    print(f"[INFO] Found {len(person_dirs)} person folders in {scan_dir}")

    current_files = set()
    new_computations = 0

    for person in person_dirs:
        person_path = os.path.join(scan_dir, person)
        pattern = os.path.join(person_path, "*")
        files = [f for f in glob.glob(pattern) if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp", ".webp"))]
        if not files:
            continue

        for img_path in files:
            current_files.add(img_path)
            try:
                mtime = os.path.getmtime(img_path)
                
                # Check cache
                if img_path in cache and cache[img_path]["mtime"] == mtime:
                    # Valid cache hit
                    for enc in cache[img_path]["encodings"]:
                        known_encodings.append(enc)
                        known_names.append(person)
                    continue

                # Cache miss or file modified - compute encoding
                img = face_recognition.load_image_file(img_path)
                # Using 'large' model for better accuracy as requested in face_pipeline
                locations = face_recognition.face_locations(img, model="hog")
                if not locations:
                    # try cnn if hog fails and we have GPU? 
                    # but hog is safer for general loading
                    print(f"[WARN] No face found in {img_path} - skipping image")
                    continue
                
                encs = face_recognition.face_encodings(img, known_face_locations=locations, num_jitters=1, model='large')
                if not encs:
                    print(f"[WARN] Could not encode face in {img_path} - skipping")
                    continue
                
                # Update lists and cache
                for enc in encs:
                    known_encodings.append(enc)
                    known_names.append(person)
                
                cache[img_path] = {
                    "mtime": mtime,
                    "encodings": encs,
                    "name": person
                }
                new_computations += 1
                print(f"[INFO] Computed new encoding for {img_path} -> {person}")
                
            except Exception as e:
                print(f"[ERROR] Failed to process {img_path}: {e}")

    # Cleanup deleted files from cache
    files_to_remove = [p for p in cache.keys() if p not in current_files]
    if files_to_remove:
        for p in files_to_remove:
            del cache[p]
        print(f"[INFO] Removed {len(files_to_remove)} deleted files from cache")

    # Save cache to disk if things changed
    if new_computations > 0 or files_to_remove:
        try:
            with open(cache_path, "wb") as f:
                pickle.dump(cache, f)
            print(f"[INFO] Saved updated cache with {len(cache)} entries")
        except Exception as e:
            print(f"[ERROR] Failed to save cache: {e}")

    print(f"[INFO] Total encodings loaded: {len(known_encodings)} (Computed: {new_computations})")
    return known_encodings, known_names


def prepare_insightface(ctx: int = -1, det_size: Tuple[int, int] = (640, 640)) -> FaceAnalysis:
    """Prepare InsightFace FaceAnalysis detector (detection only)."""
    # print available providers (optional)
    try:
        import onnxruntime as ort
        print("[INFO] ONNX providers:", ort.get_available_providers())
    except Exception:
        print("[INFO] onnxruntime not available to query providers (ok if CPU).")

    app = FaceAnalysis(allowed_modules=['detection'])
    app.prepare(ctx_id=ctx, det_size=det_size)
    print("[INFO] InsightFace detector ready. ctx:", ctx, "det_size:", det_size)
    return app


def recognize_frame_insight(frame_bgr: np.ndarray,
                            app: FaceAnalysis,
                            known_encodings: List[np.ndarray],
                            known_names: List[str]) -> np.ndarray:
    """
    Use InsightFace to detect faces on the BGR frame, then use face_recognition to encode the cropped faces
    and match against known_encodings/names.
    Returns annotated BGR frame.
    """
    if frame_bgr is None:
        return frame_bgr

    original_h, original_w = frame_bgr.shape[:2]

    # Run InsightFace detection (it expects BGR or RGB; it handles numpy arrays)
    faces = app.get(frame_bgr)  # returns list of Face objects with .bbox and .det_score

    for f in faces:
        # InsightFace bbox order: [x1, y1, x2, y2]
        try:
            x1, y1, x2, y2 = map(int, f.bbox)
        except Exception:
            # fallback if bbox shape unexpected
            bx = f.bbox
            if len(bx) >= 4:
                x1, y1, x2, y2 = int(bx[0]), int(bx[1]), int(bx[2]), int(bx[3])
            else:
                continue

        # clamp to image bounds
        x1 = max(0, min(original_w - 1, x1))
        x2 = max(0, min(original_w - 1, x2))
        y1 = max(0, min(original_h - 1, y1))
        y2 = max(0, min(original_h - 1, y2))

        # Skip tiny boxes
        if (x2 - x1) < 20 or (y2 - y1) < 20:
            continue

        # Crop face from original BGR frame
        face_crop_bgr = frame_bgr[y1:y2, x1:x2]
        # Convert to RGB for face_recognition
        face_crop_rgb = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2RGB)

        # Prepare face_location for cropped image: top,right,bottom,left (relative to crop)
        h_crop, w_crop = face_crop_rgb.shape[:2]
        crop_location = [(0, w_crop - 1, h_crop - 1, 0)]

        # Compute encoding on the crop (fast because we pass location relative to the crop)
        try:
            encs = face_recognition.face_encodings(face_crop_rgb, known_face_locations=crop_location, num_jitters=0)
        except Exception as e:
            encs = []

        name = "Unknown"
        distance = None

        if encs:
            enc = encs[0]
            if known_encodings:
                distances = face_recognition.face_distance(known_encodings, enc)
                best_idx = int(np.argmin(distances))
                best_distance = float(distances[best_idx])
                distance = best_distance
                if best_distance <= TOLERANCE:
                    name = known_names[best_idx]
                else:
                    name = "Unknown"
        else:
            # no encoding obtained (rare) — keep unknown
            pass

        # Draw rectangle and label on the original frame
        cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (0, 255, 0), 2)
        conf = getattr(f, "det_score", None) or getattr(f, "score", None)
        label_parts = []
        if name:
            label_parts.append(name)
        if distance is not None:
            label_parts.append(f"{distance:.2f}")
        if conf is not None:
            label_parts.append(f"det:{conf:.2f}")
        label = " | ".join(label_parts) if label_parts else "Unknown"
        label_y = y1 - 10 if y1 - 10 > 10 else y1 + 10
        cv2.putText(frame_bgr, label, (x1, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)

    return frame_bgr


def main():
    print("[INFO] Loading known faces...")
    known_encodings, known_names = load_known_faces(DATA_DIR)

    if not known_encodings:
        print("[ERROR] No known face encodings found. Ensure your data folder is correct and has face images.")
        return

    # Prepare InsightFace detector
    app = prepare_insightface(ctx=INSIGHT_CTX, det_size=INSIGHT_DET_SIZE)

    print("[INFO] Starting camera...")
    cap = cv2.VideoCapture(CAMERA_INDEX, cv2.CAP_DSHOW)
    if not cap.isOpened():
        print(f"[ERROR] Unable to open camera index {CAMERA_INDEX}")
        return

    time.sleep(0.5)
    print("[INFO] Press 'q' to quit.")

    try:
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                print("[WARN] Failed to read frame from camera")
                time.sleep(0.01)
                continue

            # Optionally resize for display speed - detection runs on original frame
            display_frame = frame.copy()
            if FRAME_DISPLAY_SCALE != 1.0:
                display_frame = cv2.resize(display_frame, (0, 0), fx=FRAME_DISPLAY_SCALE, fy=FRAME_DISPLAY_SCALE)

            annotated = recognize_frame_insight(frame, app, known_encodings, known_names)

            # For display, apply scaling if needed
            disp = annotated
            if FRAME_DISPLAY_SCALE != 1.0:
                disp = cv2.resize(annotated, (0, 0), fx=FRAME_DISPLAY_SCALE, fy=FRAME_DISPLAY_SCALE)

            cv2.imshow("Face Recognition (InsightFace detector) - press 'q' to quit", disp)

            # Quit on 'q'
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")

    finally:
        cap.release()
        cv2.destroyAllWindows()
        print("[INFO] Camera closed. Bye.")


if __name__ == "__main__":
    main()
