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
import sqlite3
import logging

# Configure logging
logger = logging.getLogger(__name__)

# CONFIG - Use dynamic path based on file location
BACKEND_FACE_DIR = Path(__file__).parent.absolute()
BASE_DIR = BACKEND_FACE_DIR / "captured_faces"
DATA_DIR = BACKEND_FACE_DIR / "data"
DB_PATH = DATA_DIR / "attendance.db"
KNOWN_DIRNAME = "known"
UNKNOWN_DIRNAME = "unknown"
LOG_CSV = BASE_DIR / "capture_log.csv"

# Minimum seconds between saves for same label (to avoid duplicates in-memory)
DEFAULT_MIN_SAVE_INTERVAL_SECONDS = 8.0
MIN_KNOWN_SAVE_CONFIDENCE = 0.35
MIN_UNKNOWN_SAVE_CONFIDENCE = 0.45

# Internal state for rate-limiting and thread-safety
_last_saved_time: Dict[str, float] = {}
_lock = threading.Lock()

# Ensure data directory exists
DATA_DIR.mkdir(parents=True, exist_ok=True)

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
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")

def _init_db():
    """ Initialize SQLite database with the correct schema. """
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                company_id TEXT,
                camera TEXT,
                timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                date TEXT,
                confidence REAL
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.error(f"[DB-ERROR] Failed to initialize database: {e}")

def _should_insert(cursor, name, camera, company_id, cooldown=5):
    """ Check if the last insertion for this person/camera was more than 'cooldown' seconds ago. """
    cursor.execute("""
        SELECT timestamp FROM attendance 
        WHERE name=? AND camera=? AND company_id=?
        ORDER BY timestamp DESC LIMIT 1
    """, (name, camera, company_id))

    last = cursor.fetchone()
    if last:
        # sqlite CURRENT_TIMESTAMP is in UTC, but depends on setup. 
        # Using string comparison or parsing.
        try:
            last_time = datetime.strptime(last[0], "%Y-%m-%d %H:%M:%S")
            if datetime.utcnow() - last_time < timedelta(seconds=cooldown):
                return False
        except Exception:
            # Fallback for different time formats if any
            return True

    return True

from datetime import timedelta

def _record_attendance_db(name: str, company_id: str, camera: str, confidence: float):
    """ Record attendance in SQLite with a cooldown to avoid spam. """
    if name.lower() == "unknown":
        return

    _init_db() # Ensure table exists
    today = datetime.now().strftime("%Y-%m-%d")
    try:
        conn = sqlite3.connect(str(DB_PATH))
        cursor = conn.cursor()
        
        # Cooldown Check: Use 5 second cooldown to prevent DB bloat
        if not _should_insert(cursor, name, camera, company_id, cooldown=5):
            logger.debug(f"[DB-COOLDOWN] Skipping record for {name} on {camera} (under cooldown)")
            conn.close()
            return

        # Insert new record
        cursor.execute("""
            INSERT INTO attendance (name, company_id, camera, date, confidence)
            VALUES (?, ?, ?, ?, ?)
        """, (name, company_id, camera, today, confidence))
        
        conn.commit()
        conn.close()
        logger.info(f"[DB-EVENT] Attendance recorded: {name} | Cam: {camera} | Conf: {confidence:.2f}")
    except Exception as e:
        logger.error(f"[DB-ERROR] Failed to record attendance: {e}")

def _append_log(row: dict):
    header = ["filename", "label", "timestamp_iso", "saved_path", "confidence", "source", "company_id"]
    write_header = not LOG_CSV.exists()
    try:
        LOG_CSV.parent.mkdir(parents=True, exist_ok=True)
        with LOG_CSV.open("a", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=header)
            if write_header:
                writer.writeheader()
            writer.writerow({k: row.get(k, "") for k in header})
    except Exception as e:
        logger.error(f"Failed to write capture log: {e}")


# ===========================================================================
#   IMAGE ENHANCEMENT PIPELINE
# ===========================================================================

def _enhance_face_crop(face_crop_bgr: np.ndarray) -> np.ndarray:
    """CLAHE + unsharp mask for normal-sized face crops (>100px)."""
    if face_crop_bgr is None or face_crop_bgr.size == 0:
        return face_crop_bgr
    try:
        # CLAHE on L channel for contrast
        lab = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
        enhanced = cv2.cvtColor(cv2.merge([clahe.apply(l), a, b]), cv2.COLOR_LAB2BGR)
        # Unsharp mask for sharpness
        blur = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=1.0)
        sharpened = cv2.addWeighted(enhanced, 1.5, blur, -0.5, 0)
        return sharpened
    except Exception:
        return face_crop_bgr


def _pre_upscale_denoise(img: np.ndarray, min_side: int) -> np.ndarray:
    """
    Denoise BEFORE upscaling so noise does not get amplified.
    Stronger denoising for smaller (noisier) crops.
    """
    if img is None or img.size == 0:
        return img
    try:
        if min_side < 40:
            # Very small crop - heavy denoise with non-local means
            return cv2.fastNlMeansDenoisingColored(
                img, None, h=10, hForColorComponents=10,
                templateWindowSize=7, searchWindowSize=21
            )
        elif min_side < 80:
            # Small crop - moderate edge-preserving denoise
            return cv2.bilateralFilter(img, d=9, sigmaColor=55, sigmaSpace=55)
        else:
            # Normal crop - light denoise
            return cv2.bilateralFilter(img, d=5, sigmaColor=30, sigmaSpace=30)
    except Exception:
        return img


def _iterative_upscale(img: np.ndarray, target_size: int, max_scale: float) -> np.ndarray:
    """
    Upscale in 2x steps with intermediate sharpening at each step.
    This produces MUCH cleaner results than a single large jump because
    each step only doubles, keeping detail crisp at every stage.
    """
    h, w = img.shape[:2]
    min_dim = min(h, w)
    if min_dim >= target_size:
        return img

    total_scale = min(float(target_size) / float(min_dim), max_scale)
    if total_scale <= 1.0:
        return img

    result = img.copy()
    accumulated_scale = 1.0
    step_scale = 2.0  # upscale 2x per step

    while accumulated_scale * step_scale <= total_scale:
        cur_h, cur_w = result.shape[:2]
        new_w = int(cur_w * step_scale)
        new_h = int(cur_h * step_scale)

        # Upscale with Lanczos4 (sharpest interpolation for upscaling)
        result = cv2.resize(result, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

        # Sharpen after each 2x step to recover edges before next step
        blur = cv2.GaussianBlur(result, (0, 0), sigmaX=0.8)
        result = cv2.addWeighted(result, 1.4, blur, -0.4, 0)

        accumulated_scale *= step_scale

    # Final fractional upscale for the remainder
    remaining = total_scale / accumulated_scale
    if remaining > 1.05:
        cur_h, cur_w = result.shape[:2]
        new_w = max(1, int(cur_w * remaining))
        new_h = max(1, int(cur_h * remaining))
        result = cv2.resize(result, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        # Lighter sharpen for the small final step
        blur = cv2.GaussianBlur(result, (0, 0), sigmaX=0.7)
        result = cv2.addWeighted(result, 1.3, blur, -0.3, 0)

    return result


def _super_enhance_small_face(face_crop_bgr: np.ndarray) -> np.ndarray:
    """
    Aggressive enhancement for small / distant face crops.
    Applied AFTER upscaling to maximize detail recovery.
    Pipeline:
      1. Bilateral filter - edge-preserving denoise on upscaled image
      2. CLAHE - recover facial features in low contrast
      3. Saturation + brightness boost - fix washed-out distant captures
      4. Multi-scale unsharp mask - restore fine and coarse detail
      5. Non-local-means denoise - final artifact cleanup
    """
    if face_crop_bgr is None or face_crop_bgr.size == 0:
        return face_crop_bgr
    try:
        # 1. Bilateral filter (denoise while keeping edges crisp)
        denoised = cv2.bilateralFilter(face_crop_bgr, d=9, sigmaColor=60, sigmaSpace=60)

        # 2. CLAHE with stronger clip for washed-out distant faces
        lab = cv2.cvtColor(denoised, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=3.5, tileGridSize=(4, 4))
        enhanced = cv2.cvtColor(cv2.merge([clahe.apply(l), a, b]), cv2.COLOR_LAB2BGR)

        # 3. Boost saturation + brightness for washed-out distant faces
        hsv = cv2.cvtColor(enhanced, cv2.COLOR_BGR2HSV).astype(np.float32)
        hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.3, 0, 255)   # saturation +30%
        hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.08, 0, 255)   # brightness +8%
        enhanced = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

        # 4. Multi-scale unsharp mask (fine detail + coarse structure)
        blur_fine = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=1.0)
        blur_coarse = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=2.5)
        sharpened = cv2.addWeighted(enhanced, 1.8, blur_fine, -0.6, 0)
        sharpened = cv2.addWeighted(sharpened, 1.3, blur_coarse, -0.3, 0)

        # 5. Non-local-means denoising to clean up sharpening artifacts
        final = cv2.fastNlMeansDenoisingColored(
            sharpened, None, h=5, hForColorComponents=5,
            templateWindowSize=7, searchWindowSize=21
        )
        return final
    except Exception:
        return _enhance_face_crop(face_crop_bgr)


def _prepare_crop_for_save(
    face_crop_bgr: np.ndarray,
    target_width: Optional[int],
    max_upscale: float,
) -> np.ndarray:
    """
    High-quality upscale + enhance pipeline for saving face crops.

    For small/distant faces:
      1. Pre-upscale denoise (prevents noise amplification)
      2. Multi-step 2x upscale with intermediate sharpening
      3. Aggressive super-enhancement (CLAHE + saturation + multi-scale sharpen)

    For normal faces:
      1. Standard CLAHE + unsharp mask
    """
    h, w = face_crop_bgr.shape[:2]
    min_side = min(h, w)
    is_small_face = min_side < 100

    prepared = face_crop_bgr.copy()

    # --- Step 1: Denoise BEFORE upscaling (prevents noise amplification) ---
    if is_small_face:
        prepared = _pre_upscale_denoise(prepared, min_side)

    # --- Step 2: Multi-step iterative upscale (2x per step) ---
    if target_width and target_width > 0:
        prepared = _iterative_upscale(prepared, target_width, max_upscale)

    # --- Step 3: Ensure both width AND height meet target ---
    cur_h, cur_w = prepared.shape[:2]
    if target_width and min(cur_h, cur_w) < target_width:
        remaining_scale = min(float(target_width) / float(min(cur_h, cur_w)), max_upscale)
        if remaining_scale > 1.05:
            new_w = max(1, int(cur_w * remaining_scale))
            new_h = max(1, int(cur_h * remaining_scale))
            prepared = cv2.resize(prepared, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

    # --- Step 4: Enhancement based on original face size ---
    if is_small_face:
        prepared = _super_enhance_small_face(prepared)
    else:
        prepared = _enhance_face_crop(prepared)

    return prepared


# ===========================================================================
#   BBOX CONVERSION
# ===========================================================================

def _bbox_to_ltrb(bbox: Tuple, frame_shape: Tuple) -> Tuple[int, int, int, int]:
    H, W = frame_shape[0], frame_shape[1]
    x0, x1, x2, x3 = bbox
    
    if 0 <= x0 <= 1 and 0 <= x1 <= 1 and 0 <= x2 <= 1 and 0 <= x3 <= 1:
        x = int(x0 * W)
        y = int(x1 * H)
        w = int(x2 * W)
        h = int(x3 * H)
        l, t, r, b = x, y, x + w, y + h
        return max(0, l), max(0, t), min(W, r), min(H, b)
    
    if x2 > 0 and x3 > 0 and (x0 + x2) <= W and (x1 + x3) <= H:
        l = int(x0)
        t = int(x1)
        r = int(x0 + x2)
        b = int(x1 + x3)
        return max(0, l), max(0, t), min(W, r), min(H, b)
    
    if x2 > x0 and x3 > x1 and x2 <= W and x3 <= H:
        l = int(x0)
        t = int(x1)
        r = int(x2)
        b = int(x3)
        return max(0, l), max(0, t), min(W, r), min(H, b)
    
    l = int(np.clip(x0, 0, W - 1))
    t = int(np.clip(x1, 0, H - 1))
    r = int(np.clip(x2, 0, W - 1))
    b = int(np.clip(x3, 0, H - 1))
    return l, t, r, b


# ===========================================================================
#   MAIN SAVE FUNCTION
# ===========================================================================

def save_face_image(
    face_crop_bgr: Optional[np.ndarray] = None,
    frame_bgr: Optional[np.ndarray] = None,
    bbox: Optional[Tuple] = None,
    label: Optional[str] = None,
    confidence: Optional[float] = None,
    min_interval: float = DEFAULT_MIN_SAVE_INTERVAL_SECONDS,
    source: str = "stream",
    expand_factor: float = 0.5,
    target_width: Optional[int] = 320,
    max_upscale: float = 6.0,
    jpeg_quality: int = 98,
    stream_id: Optional[str] = None,
    prefer_png: bool = False,
    camera_name: Optional[str] = None,
    company_id: Optional[str] = None,
    identity_key: Optional[str] = None
) -> Optional[Path]:
    if face_crop_bgr is None and (frame_bgr is None or bbox is None):
        return None

    label = label or "unknown"
    label_s = sanitize_label(label)
    cam = sanitize_label(camera_name) if camera_name else "default"
    comp = sanitize_label(company_id) if company_id else "default"

    min_confidence = MIN_UNKNOWN_SAVE_CONFIDENCE if label_s == "unknown" else MIN_KNOWN_SAVE_CONFIDENCE
    if confidence is not None and confidence < min_confidence:
        logger.warning(
            f"Skipping save: Low confidence {confidence:.2f} < {min_confidence:.2f} for {label_s}"
        )
        return None

    cooldown_identity = sanitize_label(identity_key) if identity_key else label_s
    cooldown_key = f"{comp}:{cam}:{label_s}:{cooldown_identity}"
    now = time.time()
    with _lock:
        last_saved = _last_saved_time.get(cooldown_key, 0)
        if min_interval > 0 and now - last_saved < min_interval:
            logger.debug(f"Skipping save under cooldown for {cooldown_key}")
            return None
        _last_saved_time[cooldown_key] = now

    try:
        if frame_bgr is not None and bbox is not None:
            H, W = frame_bgr.shape[:2]
            l, t, r, b = _bbox_to_ltrb(bbox, frame_bgr.shape)
            w_box, h_box = r - l, b - t
            
            if w_box <= 0 or h_box <= 0:
                return None
            
            # Adaptive expansion: smaller/distant faces get a much larger
            # crop region to capture head + shoulders context, making the
            # person identifiable even from far away.
            min_side = min(w_box, h_box)
            if min_side < 30:
                effective_expand = max(expand_factor, 0.9)
            elif min_side < 50:
                effective_expand = max(expand_factor, 0.7)
            elif min_side < 80:
                effective_expand = max(expand_factor, 0.6)
            else:
                effective_expand = expand_factor
            
            ew, eh = int(w_box * effective_expand), int(h_box * effective_expand)
            el, et, er, eb = max(0, l - ew), max(0, t - eh), min(W, r + ew), min(H, b + eh)
            
            face_crop_bgr = frame_bgr[et:eb, el:er].copy()

        if face_crop_bgr is None or face_crop_bgr.size == 0 or face_crop_bgr.shape[0] < 10 or face_crop_bgr.shape[1] < 10:
            return None

        face_crop_bgr = _prepare_crop_for_save(face_crop_bgr, target_width, max_upscale)

        dir_path = ensure_dirs_for_label(label_s, camera_name=camera_name, company_id=company_id)
        fname = f"{label_s}_{_current_timestamp_str()}.jpg"
        save_path = dir_path / fname
        
        success = cv2.imwrite(str(save_path), face_crop_bgr, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        if not success:
            return None

        with _lock:
            _last_saved_time[cooldown_key] = time.time()
        
        # Record attendance in DB
        _record_attendance_db(label_s, comp, cam, confidence or 0.0)

        # Log to CSV
        log_row = {
            "filename": fname,
            "label": label_s,
            "timestamp_iso": datetime.now().isoformat(),
            "saved_path": save_path.relative_to(BACKEND_FACE_DIR).as_posix(),
            "confidence": confidence if confidence is not None else "",
            "source": source,
            "company_id": comp
        }
        _append_log(log_row)
        
        # WebSocket Broadcast (Simplified)
        try:
            from ws_manager import ws_manager
            payload = {
                "id": str(uuid.uuid4()),
                "name": label.title() if label_s != "unknown" else "Unknown Person",
                "time": datetime.now().strftime("%H:%M"),
                "camera": camera_name or "Camera 1",
                "status": "Recognized" if label_s != "unknown" else "Alert",
                "image_url": f"/api/captured/image/{'known' if label_s != 'unknown' else 'unknown'}/{comp}/{cam}/{label_s + '/' if label_s != 'unknown' else ''}{fname}",
                "company_id": comp
            }
            msg_type = "RECOGNITION" if label_s != "unknown" else "ALERT"
            
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(ws_manager.broadcast({"type": msg_type, "payload": payload}, comp))
        except Exception:
            pass

        return save_path
        
    except Exception as e:
        logger.error(f"Error saving face image: {e}")
        return None
