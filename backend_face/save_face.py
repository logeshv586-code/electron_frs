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


def _enhance_face_crop(face_crop_bgr: np.ndarray) -> np.ndarray:
    if face_crop_bgr is None or face_crop_bgr.size == 0:
        return face_crop_bgr
    try:
        lab = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = cv2.cvtColor(cv2.merge([clahe.apply(l), a, b]), cv2.COLOR_LAB2BGR)
        blurred = cv2.GaussianBlur(enhanced, (0, 0), sigmaX=0.8)
        return cv2.addWeighted(enhanced, 1.35, blurred, -0.35, 0)
    except Exception:
        return face_crop_bgr


def _prepare_crop_for_save(
    face_crop_bgr: np.ndarray,
    target_width: Optional[int],
    max_upscale: float,
) -> np.ndarray:
    h, w = face_crop_bgr.shape[:2]
    prepared = face_crop_bgr
    if target_width and w > 0 and w < target_width:
        scale = min(float(target_width) / float(w), max_upscale)
        new_w = max(1, int(w * scale))
        new_h = max(1, int(h * scale))
        prepared = cv2.resize(prepared, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
    return _enhance_face_crop(prepared)

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

def save_face_image(
    face_crop_bgr: Optional[np.ndarray] = None,
    frame_bgr: Optional[np.ndarray] = None,
    bbox: Optional[Tuple] = None,
    label: Optional[str] = None,
    confidence: Optional[float] = None,
    min_interval: float = DEFAULT_MIN_SAVE_INTERVAL_SECONDS,
    source: str = "stream",
    expand_factor: float = 0.3,
    target_width: Optional[int] = None,
    max_upscale: float = 1.2,
    jpeg_quality: int = 95,
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
            
            ew, eh = int(w_box * expand_factor), int(h_box * expand_factor)
            el, et, er, eb = max(0, l - ew), max(0, t - eh), min(W, r + ew), min(H, b + eh)
            
            face_crop_bgr = frame_bgr[et:eb, el:er].copy()

        if face_crop_bgr is None or face_crop_bgr.size == 0 or face_crop_bgr.shape[0] < 20 or face_crop_bgr.shape[1] < 20:
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
