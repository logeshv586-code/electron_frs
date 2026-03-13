import os
from pathlib import Path
import time
from datetime import datetime
import csv
import threading
import re
import cv2
import numpy as np
import face_recognition
from typing import Optional, Dict, Tuple
import asyncio
import uuid

# CONFIG - Use dynamic path based on file location
# Get the backend_face directory (parent of this file's directory)
BACKEND_FACE_DIR = Path(__file__).parent.absolute()
BASE_DIR = BACKEND_FACE_DIR / "captured_faces"
KNOWN_DIRNAME = "known"
UNKNOWN_DIRNAME = "unknown"
LOG_CSV = BASE_DIR / "capture_log.csv"
# Minimum seconds between saves for same label (to avoid duplicates)
DEFAULT_MIN_SAVE_INTERVAL_SECONDS = 8.0

# Internal state for rate-limiting and thread-safety
_last_saved_time: Dict[str, float] = {}
_lock = threading.Lock()

# sanitize label for filename and directory name
_filename_safe_re = re.compile(r"[^\w\-_.]")

def sanitize_label(label: str) -> str:
    if not label:
        return "unknown"
    label = label.strip().lower()
    label = label.replace(" ", "_")
    label = _filename_safe_re.sub("", label)
    if label == "":
        return "unknown"
    return label

def ensure_dirs_for_label(label: str, camera_name: Optional[str] = None, company_id: Optional[str] = None) -> Path:
    label_s = sanitize_label(label)
    cam = sanitize_label(camera_name) if camera_name else "default"
    comp = sanitize_label(company_id) if company_id else "default"
    
    if label_s == "unknown":
        dir_path = BASE_DIR / UNKNOWN_DIRNAME / comp / cam
    else:
        dir_path = BASE_DIR / KNOWN_DIRNAME / comp / cam / label_s
        
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path

def _current_timestamp_str() -> str:
    # e.g. 20251029_153012_123456
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

def _should_save(label: str, min_interval: float) -> bool:
    label_s = sanitize_label(label)
    now = time.time()
    with _lock:
        last = _last_saved_time.get(label_s, 0.0)
        if now - last >= min_interval:
            _last_saved_time[label_s] = now
            return True
        return False

def _append_log(row: dict):
    header = ["filename", "label", "timestamp_iso", "saved_path", "confidence", "source"]
    write_header = not LOG_CSV.exists()
    try:
        LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
        with LOG_CSV.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            if write_header:
                writer.writeheader()
            writer.writerow({k: row.get(k, "") for k in header})
    except Exception as e:
        # don't crash pipeline for logging issues; just print
        print("Failed to write capture log:", e)

def _bbox_to_ltrb(bbox: Tuple, frame_shape: Tuple) -> Tuple[int, int, int, int]:
    """
    Auto-detect bbox format and convert to (left, top, right, bottom).
    Handles: normalized coords [0..1], (x,y,w,h) in pixels, or (l,t,r,b) coords.
    Returns: (l, t, r, b) clamped to image bounds.
    """
    H, W = frame_shape[0], frame_shape[1]
    x0, x1, x2, x3 = bbox
    
    # Check if all values are normalized (0..1)
    if 0 <= x0 <= 1 and 0 <= x1 <= 1 and 0 <= x2 <= 1 and 0 <= x3 <= 1:
        # Treat as normalized (x,y,w,h)
        x = int(x0 * W)
        y = int(x1 * H)
        w = int(x2 * W)
        h = int(x3 * H)
        l, t, r, b = x, y, x + w, y + h
        return max(0, l), max(0, t), min(W, r), min(H, b)
    
    # Check if looks like (x,y,w,h) in pixels
    if x2 > 0 and x3 > 0 and (x0 + x2) <= W and (x1 + x3) <= H:
        l = int(x0)
        t = int(x1)
        r = int(x0 + x2)
        b = int(x1 + x3)
        return max(0, l), max(0, t), min(W, r), min(H, b)
    
    # Treat as (l,t,r,b) if they look like coords
    if x2 > x0 and x3 > x1 and x2 <= W and x3 <= H:
        l = int(x0)
        t = int(x1)
        r = int(x2)
        b = int(x3)
        return max(0, l), max(0, t), min(W, r), min(H, b)
    
    # Fallback: clamp and validate
    l = int(np.clip(x0, 0, W - 1))
    t = int(np.clip(x1, 0, H - 1))
    r = int(np.clip(x2, 0, W - 1))
    b = int(np.clip(x3, 0, H - 1))
    if r <= l or b <= t:
        # Fallback to small box around center
        cx, cy = W // 2, H // 2
        s = min(W, H) // 4
        return cx - s, cy - s, cx + s, cy + s
    return l, t, r, b

def apply_clahe(image: np.ndarray) -> np.ndarray:
    """Apply CLAHE (Contrast Limited Adaptive Histogram Equalization) for enhancement."""
    try:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        cl = clahe.apply(l)
        limg = cv2.merge((cl, a, b))
        enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
        return enhanced
    except Exception:
        return image

def save_face_image(
    face_crop_bgr: Optional[np.ndarray] = None,
    frame_bgr: Optional[np.ndarray] = None,
    bbox: Optional[Tuple] = None,
    label: Optional[str] = None,
    confidence: Optional[float] = None,
    min_interval: float = DEFAULT_MIN_SAVE_INTERVAL_SECONDS,
    source: str = "stream",
    expand_factor: float = 0.3,  # 30% padding around face for clean headshot
    target_width: Optional[int] = None,  # None = no forced resizing, preserve natural resolution
    max_upscale: float = 1.2,  # Minimal upscaling to preserve quality
    jpeg_quality: int = 95,
    stream_id: Optional[str] = None,  # Optional stream_id to access frame buffer for sharp capture
    prefer_png: bool = False,  # Save PNG instead of JPEG when True
    camera_name: Optional[str] = None,  # Camera/stream name for directory organization
    company_id: Optional[str] = None  # Company/tenant ID for data isolation
) -> Optional[Path]:
    """
    Robust face saving with auto-detected bbox format, smart padding, and limited upscaling.
    
    Can be called two ways:
    1. Direct crop: save_face_image(face_crop_bgr=crop, label="john", ...)
    2. Frame + bbox: save_face_image(frame_bgr=frame, bbox=(x1,y1,x2,y2), label="john", ...)
    
    Returns the saved Path or None if skipped/failed.
    """
    if face_crop_bgr is None and (frame_bgr is None or bbox is None):
        return None

    label = label or "unknown"
    label_s = sanitize_label(label)
    cam = sanitize_label(camera_name) if camera_name else "default"
    comp = sanitize_label(company_id) if company_id else "default"

    # Check face confidence before saving (must be > 70% for quality)
    if confidence is not None and confidence < 0.6:
        print(f"Skipping save: Low confidence {confidence:.2f} < 0.6 for {label_s}")
        return None

    try:
        # If bbox + frame provided, extract and expand crop
        if frame_bgr is not None and bbox is not None:
            # Try to get best (sharpest) frame from buffer if stream_id provided
            best_frame = None
            if stream_id and source == "stream":
                try:
                    from camera_management.streaming import stream_manager
                    best_frame = stream_manager._get_best_frame_from_buffer(stream_id, bbox)
                except Exception as e:
                    # Fallback to current frame if buffer access fails
                    pass
            
            # Use best frame from buffer if available, otherwise use current frame
            frame_to_use = best_frame if best_frame is not None else frame_bgr
            
            H, W = frame_to_use.shape[:2]
            l, t, r, b = _bbox_to_ltrb(bbox, frame_to_use.shape)
            w_box = r - l
            h_box = b - t
            
            if w_box <= 0 or h_box <= 0:
                return None
            
            # Expand box by expand_factor to capture more context
            ew = int(w_box * expand_factor)
            eh = int(h_box * expand_factor)
            el = l - ew
            et = t - eh
            er = r + ew
            eb = b + eh
            
            # Calculate padding if expanded box goes outside image
            pad_left = max(0, -el)
            pad_top = max(0, -et)
            pad_right = max(0, er - W)
            pad_bottom = max(0, eb - H)
            
            # Clamp coords to image bounds
            el = max(0, el)
            et = max(0, et)
            er = min(W, er)
            eb = min(H, eb)
            
            face = frame_to_use[et:eb, el:er].copy()
            if face.size == 0:
                return None
            
            # Apply padding if needed using BORDER_REFLECT for better quality
            if any((pad_left, pad_top, pad_right, pad_bottom)):
                face = cv2.copyMakeBorder(
                    face, pad_top, pad_bottom, pad_left, pad_right,
                    borderType=cv2.BORDER_REFLECT_101
                )
            
            face_crop_bgr = face

        # Basic validation: check image dimensions and content
        # NOTE: We do NOT re-run face_recognition.face_locations() here because:
        # 1. The face was already detected by InsightFace in face_pipeline.py
        # 2. Re-running face_recognition on small crops can cause segmentation faults
        # 3. The two detectors can disagree, causing valid faces to be discarded
        if face_crop_bgr is None or face_crop_bgr.size == 0:
            print(f"Skipping save: Empty face crop for {label_s}")
            return None
        if face_crop_bgr.shape[0] < 20 or face_crop_bgr.shape[1] < 20:
            print(f"Skipping save: Face crop too small ({face_crop_bgr.shape[1]}x{face_crop_bgr.shape[0]}) for {label_s}")
            return None
        # Verify the array is valid and contiguous
        if not face_crop_bgr.flags['C_CONTIGUOUS']:
            face_crop_bgr = np.ascontiguousarray(face_crop_bgr)
        
        # Ensure dtype is uint8
        if face_crop_bgr.dtype != "uint8":
            face_crop_bgr = (face_crop_bgr * 255).astype("uint8") if face_crop_bgr.max() <= 1.0 else face_crop_bgr.astype("uint8")
        
        # Preserve natural resolution - minimal processing to maintain quality
        # Only apply minimal upscaling for very small faces, and only if target_width is specified
        fh, fw = face_crop_bgr.shape[:2]
        
        # Only resize if target_width is specified AND face is very small
        if target_width is not None and fw < target_width:
            # Only upscale if face is very small (less than 50% of target)
            # This prevents quality degradation from excessive upscaling
            if fw < (target_width * 0.5):
                aspect = fw / float(fh) if fh != 0 else 1.0
                # Limit upscaling to max_upscale factor to preserve quality
                max_allowed_w = int(fw * max_upscale)
                desired_w = min(max_allowed_w, target_width)
                desired_w = max(desired_w, fw)  # never shrink
                desired_h = max(1, int(desired_w / aspect))
                if abs(desired_w - fw) > 2:
                    # Use high-quality interpolation only when necessary
                    face_crop_bgr = cv2.resize(
                        face_crop_bgr, (desired_w, desired_h),
                        interpolation=cv2.INTER_LANCZOS4
                    )
        
        # Remove aggressive image processing to preserve natural quality
        # No unsharp mask or CLAHE - these can degrade image quality
        # Save images as captured to maintain original quality
        
        # Save
        dir_path = ensure_dirs_for_label(label_s, camera_name=camera_name, company_id=company_id)
        fname = f"{label_s}_{_current_timestamp_str()}.jpg"
        save_path = dir_path / fname
        
        if prefer_png:
            save_path = save_path.with_suffix(".png")
            success = cv2.imwrite(str(save_path), face_crop_bgr, [cv2.IMWRITE_PNG_COMPRESSION, 1])
        else:
            # Try to write optimized/progressive JPEG at very high quality
            params = [cv2.IMWRITE_JPEG_QUALITY, max(1, min(100, int(jpeg_quality)))]
            try:
                params += [cv2.IMWRITE_JPEG_OPTIMIZE, 1, cv2.IMWRITE_JPEG_PROGRESSIVE, 1]
            except Exception:
                pass
            success = cv2.imwrite(str(save_path), face_crop_bgr, params)
        if not success:
            print("cv2.imwrite failed for", save_path)
            return None
        
        # Log using a universal relative POSIX path (e.g. 'captured_faces/known/...')
        try:
            univ_path = save_path.relative_to(BACKEND_FACE_DIR).as_posix()
        except ValueError:
            univ_path = save_path.as_posix()

        log_row = {
            "filename": fname,
            "label": label_s,
            "timestamp_iso": datetime.now().isoformat(),
            "saved_path": univ_path,
            "confidence": confidence if confidence is not None else "",
            "source": source,
        }
        _append_log(log_row)
        
        # Real-time WebSocket Broadcast
        try:
            from ws_manager import ws_manager
            # Determine if it's a recognition or an alert
            if label_s == "unknown":
                msg_type = "ALERT"
                payload = {
                    "id": str(uuid.uuid4()),
                    "type": "Unknown Person",
                    "time": datetime.now().strftime("%H:%M"),
                    "location": camera_name or "Camera 1",
                    "image_url": f"/api/captured/image/unknown/{comp}/{cam}/{fname}"
                }
            else:
                msg_type = "RECOGNITION"
                payload = {
                    "id": str(uuid.uuid4()),
                    "name": label.title(),
                    "time": datetime.now().strftime("%H:%M"),
                    "camera": camera_name or "Camera 1",
                    "status": "Recognized",
                    "imgColor": "bg-blue-500",
                    "image_url": f"/api/captured/image/known/{comp}/{cam}/{label_s}/{fname}"
                }
            
            # Since this might be called from a different thread, we use a helper or try/except loop
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    loop.create_task(ws_manager.broadcast({"type": msg_type, "payload": payload}, company_id or "default"))
                else:
                    loop.run_until_complete(ws_manager.broadcast({"type": msg_type, "payload": payload}, company_id or "default"))
            except RuntimeError:
                # If no loop in this thread, we could create one or just use a background task if possible
                # In most cases, the main thread loop is what we want. 
                # For now, let's just log and try to use the one from main thread if accessible
                pass

        except Exception as ws_err:
            print(f"Failed to broadcast from save_face: {ws_err}")

        return save_path
        
    except Exception as e:
        print("Error saving face image:", e)
        return None