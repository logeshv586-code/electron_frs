# face_pipeline.py
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

# Tuning constants
TOLERANCE = 0.48  # Reduced from 0.55 to prevent false positives when 1 reference image exists
# Rate limit for saving same face per label (seconds)
MIN_SAVE_INTERVAL = 5.0

# Best face quality tracking: stream_id -> person_name -> {quality, timestamp}
best_face_quality: Dict[str, Dict[str, Dict[str, float]]] = defaultdict(dict)
BEST_QUALITY_RESET_SECONDS = 30.0  # Reset best quality tracking after 30s of not seeing the person

# Frame skipping removed - process every frame for maximum face capture quality
# Tesla T4 GPU can handle full frame processing efficiently

# Initialize detector and known faces (singleton-like)
# Support for multiple GPUs: maintain separate face_app instances per GPU
face_apps: Dict[int, Any] = {}  # GPU ID -> FaceAnalysis instance
face_app = None  # Default/fallback instance
available_gpus: List[int] = []  # List of available GPU IDs
# Multi-tenant embedding cache: company_id -> {'encodings': [], 'names': [], 'last_loaded': float}
company_embeddings: Dict[str, Dict[str, Any]] = {}
embedding_lock = threading.Lock()
data_directory: str = ""

# Person tracking across frames: stream_id -> track_id -> tracking_info
# tracking_info: {
#   'name': str,  # Persisted name (once recognized, never changes to Unknown)
#   'bbox': (x1, y1, x2, y2),  # Last known bbox
#   'last_seen': float,  # Timestamp of last detection
#   'frame_count': int,  # Frames since first seen
#   'encoding': np.ndarray  # Face encoding for matching
# }
person_tracking: Dict[str, Dict[int, Dict[str, Any]]] = defaultdict(dict)
track_id_counter: Dict[str, int] = defaultdict(int)  # Per-stream track ID counter
tracking_lock = threading.Lock()  # Thread-safe access to tracking data

# Tracking parameters
IOU_THRESHOLD = 0.3  # Minimum IoU to match detections to tracked persons
MAX_TRACK_AGE_FRAMES = 30  # Remove tracks not seen for this many frames
MAX_TRACK_AGE_SECONDS = 1.5  # Reduced from 2.0 to match user request for persistence


def _calculate_face_quality(face_crop: np.ndarray, det_conf: float = 0.0) -> float:
    """Calculate face quality score (0-1) based on sharpness, size, and detection confidence.
    
    Higher score = better quality face for saving.
    """
    try:
        if face_crop is None or face_crop.size == 0:
            return 0.0
        
        h, w = face_crop.shape[:2]
        
        # 1. Sharpness via Laplacian variance (most important factor)
        gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        # Normalize: typical range 0-2000, cap at 500 for scoring
        sharpness_score = min(laplacian_var / 500.0, 1.0)
        
        # 2. Face size score (bigger = better, up to a point)
        face_area = h * w
        # Score based on area: 50x50=2500 min, 200x200=40000 ideal
        size_score = min(face_area / 40000.0, 1.0)
        
        # 3. Detection confidence
        conf_score = max(0.0, min(1.0, det_conf))
        
        # Weighted combination: sharpness matters most
        quality = (sharpness_score * 0.5) + (size_score * 0.25) + (conf_score * 0.25)
        
        return min(1.0, max(0.0, quality))
    except Exception:
        return 0.0


def _extract_face_crop(frame: np.ndarray, bbox: Tuple[int, int, int, int], padding: float = 0.3) -> Optional[np.ndarray]:
    """Extract face crop from frame with controlled padding.
    
    Args:
        frame: Full BGR frame
        bbox: (x1, y1, x2, y2) bounding box
        padding: Fraction of bbox size to add as padding (0.3 = 30%)
    
    Returns:
        Cropped face image or None if invalid
    """
    try:
        if frame is None or frame.size == 0:
            return None
        
        H, W = frame.shape[:2]
        x1, y1, x2, y2 = bbox
        
        # Calculate padding in pixels
        w_box = x2 - x1
        h_box = y2 - y1
        
        if w_box <= 0 or h_box <= 0:
            return None
        
        pad_w = int(w_box * padding)
        pad_h = int(h_box * padding)
        
        # Expand with padding, clamped to image bounds
        crop_x1 = max(0, x1 - pad_w)
        crop_y1 = max(0, y1 - pad_h)
        crop_x2 = min(W, x2 + pad_w)
        crop_y2 = min(H, y2 + pad_h)
        
        crop = frame[crop_y1:crop_y2, crop_x1:crop_x2].copy()
        
        # Enforce strict minimum size to prevent garbage saves
        if crop.size == 0 or crop.shape[0] < 60 or crop.shape[1] < 60:
            return None
        
        return crop
    except Exception:
        return None


def check_gpu_availability() -> List[int]:
    """Check available GPUs for InsightFace/ONNXRuntime. Returns list of GPU IDs."""
    available = []
    try:
        import onnxruntime as ort
        providers = ort.get_available_providers()
        if 'CUDAExecutionProvider' in providers:
            # Check how many GPUs are available
            try:
                import subprocess
                result = subprocess.run(['nvidia-smi', '--list-gpus'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0:
                    # Count GPUs from nvidia-smi output
                    gpu_count = len([line for line in result.stdout.strip().split('\n') if line.strip()])
                    for gpu_id in range(gpu_count):
                        available.append(gpu_id)
                    print(f"[INFO] Detected {gpu_count} GPU(s) via nvidia-smi")
                else:
                    # Fallback: try GPU 0
                    available.append(0)
                    print(f"[INFO] ONNX providers available: {providers}, assuming GPU 0")
            except Exception:
                # Fallback: try GPU 0
                available.append(0)
                print(f"[INFO] ONNX providers available: {providers}, using GPU 0")
        else:
            print(f"[INFO] CUDA provider not available. Available providers: {providers}")
    except ImportError:
        print("[WARN] onnxruntime not available")
    except Exception as e:
        print(f"[WARN] Error checking GPU availability: {e}")
    return available


def init(data_dir: str, ctx: int = -1, det_size: Tuple[int, int] = (640, 640), use_dual_gpu: bool = True) -> None:
    """Initialize known faces and InsightFace detector with GPU detection.
    
    Args:
        data_dir: Directory containing known face images
        ctx: GPU context ID (-1 for CPU, 0+ for GPU). If -1 and use_dual_gpu=True, auto-detects GPUs
        det_size: Detection size for InsightFace
        use_dual_gpu: If True, automatically initialize all available GPUs (up to 2)
    """
    global face_app, face_apps, available_gpus, data_directory
    data_directory = data_dir

    # Reuse your function from fr1.py
    try:
        from fr1 import load_known_faces
    except Exception as e:
        raise ImportError("Cannot import load_known_faces from fr1.py") from e

    with embedding_lock:
        # NOTICE: _global embeddings are now empty by default to ensure strict isolation.
        # This prevents unnamed streams from matching against the "default" company faces.
        company_embeddings["_global"] = {
            "encodings": [],
            "names": [],
            "last_loaded": time.time()
        }

    # Clear existing instances
    face_apps = {}
    face_app = None
    available_gpus = []

    # Auto-detect and initialize multiple GPUs if requested
    if use_dual_gpu and ctx == -1:
        detected_gpus = check_gpu_availability()
        if detected_gpus:
            print(f"[INFO] Detected {len(detected_gpus)} GPU(s): {detected_gpus}")
            # Initialize up to 2 GPUs for optimal performance
            for gpu_id in detected_gpus[:2]:
                try:
                    app = FaceAnalysis(allowed_modules=['detection'])
                    app.prepare(ctx_id=gpu_id, det_size=det_size)
                    face_apps[gpu_id] = app
                    available_gpus.append(gpu_id)
                    print(f"[face_pipeline] Initialized GPU {gpu_id} successfully, det_size={det_size}")
                except Exception as e:
                    print(f"[WARN] Failed to initialize GPU {gpu_id}: {e}")
            
            if face_apps:
                # Set default to first GPU
                face_app = face_apps[available_gpus[0]]
                print(f"[INFO] Using {len(face_apps)} GPU(s) for face detection")
            else:
                print("[WARN] All GPU initializations failed, falling back to CPU")
                ctx = -1
        else:
            print("[INFO] No GPUs detected, using CPU")
            ctx = -1

    # Initialize single GPU or CPU if dual GPU not used or failed
    if not face_apps:
        if ctx == 0:
            detected_gpus = check_gpu_availability()
            if detected_gpus:
                ctx = detected_gpus[0]
                print(f"[INFO] Using GPU {ctx} for face detection")
            else:
                print("[WARN] GPU requested but not available, using CPU")
                ctx = -1
        elif ctx == -1:
            print("[INFO] Using CPU for face detection")

        try:
            face_app = FaceAnalysis(allowed_modules=['detection'])
            face_app.prepare(ctx_id=ctx, det_size=det_size)
            if ctx >= 0:
                face_apps[ctx] = face_app
                available_gpus.append(ctx)
            print(f"[face_pipeline] Initialized successfully with ctx={ctx}, det_size={det_size}")
        except Exception as e:
            # If GPU init fails, try CPU
            if ctx != -1:
                print(f"[WARN] GPU initialization failed: {e}")
                print("[INFO] Falling back to CPU")
                try:
                    face_app = FaceAnalysis(allowed_modules=['detection'])
                    face_app.prepare(ctx_id=-1, det_size=det_size)
                    print(f"[face_pipeline] Initialized with CPU fallback, det_size={det_size}")
                except Exception as cpu_error:
                    raise RuntimeError(f"Failed to initialize face pipeline (GPU and CPU): {cpu_error}") from cpu_error
            else:
                raise

def clear_company_embeddings_cache(company_id: str) -> None:
    """Clear the in-memory embeddings cache for a specific company."""
    with embedding_lock:
        if company_id in company_embeddings:
            del company_embeddings[company_id]
            logger.info(f"Cleared in-memory embeddings cache for company {company_id}")

def load_company_embeddings(company_id: str) -> Dict[str, Any]:
    """Load embeddings for a specific company and cache them."""
    global data_directory
    
    with embedding_lock:
        if company_id in company_embeddings:
            # Check if cache is older than 5 minutes (optional refresh)
            if time.time() - company_embeddings[company_id]["last_loaded"] < 300:
                return company_embeddings[company_id]

    try:
        from fr1 import load_known_faces
        encs, names = load_known_faces(data_directory, company_id=company_id)
        
        entry = {
            "encodings": encs,
            "names": names,
            "last_loaded": time.time()
        }
        
        with embedding_lock:
            company_embeddings[company_id] = entry
            
        return entry
    except Exception as e:
        print(f"[ERROR] Failed to load embeddings for company {company_id}: {e}")
        return {"encodings": [], "names": [], "last_loaded": 0}

def _get_face_app_for_stream(stream_id: Optional[str] = None):
    """Get appropriate face_app instance for a stream (distributes across GPUs)."""
    global face_app, face_apps, available_gpus
    
    if not face_apps:
        return face_app
    
    if not available_gpus:
        return face_app
    
    # Distribute streams across available GPUs using stream_id hash
    if stream_id:
        # Use hash of stream_id to consistently assign to same GPU
        gpu_idx = hash(stream_id) % len(available_gpus)
        selected_gpu = available_gpus[gpu_idx]
        return face_apps[selected_gpu]
    else:
        # Round-robin for streams without ID
        return face_apps[available_gpus[0]]


def _calculate_iou(bbox1: Tuple[int, int, int, int], bbox2: Tuple[int, int, int, int]) -> float:
    """Calculate Intersection over Union (IoU) between two bounding boxes.
    
    Args:
        bbox1: (x1, y1, x2, y2)
        bbox2: (x1, y1, x2, y2)
    
    Returns:
        IoU value between 0 and 1
    """
    x1_1, y1_1, x2_1, y2_1 = bbox1
    x1_2, y1_2, x2_2, y2_2 = bbox2
    
    # Calculate intersection
    x1_i = max(x1_1, x1_2)
    y1_i = max(y1_1, y1_2)
    x2_i = min(x2_1, x2_2)
    y2_i = min(y2_1, y2_2)
    
    if x2_i <= x1_i or y2_i <= y1_i:
        return 0.0
    
    intersection = (x2_i - x1_i) * (y2_i - y1_i)
    
    # Calculate union
    area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
    area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
    union = area1 + area2 - intersection
    
    if union == 0:
        return 0.0
    
    return intersection / union


def _match_detection_to_track(bbox: Tuple[int, int, int, int], 
                               tracks: Dict[int, Dict[str, Any]]) -> Optional[int]:
    """Match a detection to an existing track based on IoU.
    
    Args:
        bbox: Current detection bounding box (x1, y1, x2, y2)
        tracks: Dictionary of existing tracks (track_id -> tracking_info)
    
    Returns:
        track_id if match found, None otherwise
    """
    best_iou = 0.0
    best_track_id = None
    
    for track_id, track_info in tracks.items():
        track_bbox = track_info.get('bbox')
        if track_bbox is None:
            continue
        
        iou = _calculate_iou(bbox, track_bbox)
        if iou > best_iou and iou >= IOU_THRESHOLD:
            best_iou = iou
            best_track_id = track_id
    
    return best_track_id


def _cleanup_old_tracks(stream_id: str, current_frame_count: int, current_time: float):
    """Remove tracks that haven't been seen for too long.
    
    Args:
        stream_id: Stream identifier
        current_frame_count: Current frame number
        current_time: Current timestamp
    """
    global person_tracking
    
    if stream_id not in person_tracking:
        return
    
    tracks_to_remove = []
    tracks = person_tracking[stream_id]
    
    for track_id, track_info in tracks.items():
        last_seen = track_info.get('last_seen', 0)
        frame_count = track_info.get('frame_count', 0)
        frames_since_seen = current_frame_count - frame_count
        seconds_since_seen = current_time - last_seen
        
        # Remove if not seen for too long
        if frames_since_seen > MAX_TRACK_AGE_FRAMES or seconds_since_seen > MAX_TRACK_AGE_SECONDS:
            tracks_to_remove.append(track_id)
    
    for track_id in tracks_to_remove:
        del tracks[track_id]


def process_frame(frame_bgr: np.ndarray, force_process: bool = False, stream_id: Optional[str] = None, company_id: Optional[str] = None) -> Tuple[np.ndarray, List[Dict[str, Any]]]:
    """Detect + recognize faces in one frame. Returns annotated frame + detections.
    
    Args:
        frame_bgr: Input BGR frame
        force_process: Deprecated - all frames are now processed (kept for backward compatibility)
        stream_id: Optional stream ID for frame buffer access and GPU assignment
        company_id: Optional company ID to scope face recognition
    """
    global person_tracking, track_id_counter
    
    # Get appropriate face_app instance (distributed across GPUs if multiple available)
    current_face_app = _get_face_app_for_stream(stream_id)
    
    if current_face_app is None:
        raise RuntimeError("Face pipeline not initialized. Call init() first.")

    if frame_bgr is None:
        return frame_bgr, []

    # Initialize tracking for this stream if needed
    if stream_id:
        if stream_id not in person_tracking:
            person_tracking[stream_id] = {}
        if stream_id not in track_id_counter:
            track_id_counter[stream_id] = 0
            
    # Resolve company_id if not explicitly provided
    if company_id is None and stream_id:
        try:
            from camera_management.streaming import get_stream_manager
            s_info = get_stream_manager().get_stream_info(stream_id)
            if s_info:
                company_id = s_info.get('company_id')
        except Exception:
            pass
            
    # Treat unassigned (Null/None) companies as 'default' so SuperAdmin registered faces are loaded
    if not company_id or str(company_id).strip() in ("", "None"):
        company_id = "default"
    
    # Load embeddings for this company
    if company_id:
        embeddings = load_company_embeddings(str(company_id))
    else:
        # Strict Isolation: No company_id means no known faces to match against.
        # This ensures cameras from one tenant cannot recognize faces from others (or 'default').
        with embedding_lock:
            embeddings = company_embeddings.get("_global", {"encodings": [], "names": []})
            
    current_known_encodings = embeddings.get("encodings", [])
    current_known_names = embeddings.get("names", [])
    
    # Track frame count and time for cleanup
    current_time = time.time()
    frame_count_key = f"{stream_id}_frame_count" if stream_id else "default_frame_count"
    if not hasattr(process_frame, '_frame_counts'):
        process_frame._frame_counts = {}
    if frame_count_key not in process_frame._frame_counts:
        process_frame._frame_counts[frame_count_key] = 0
    process_frame._frame_counts[frame_count_key] += 1
    current_frame_count = process_frame._frame_counts[frame_count_key]
    
    # Cleanup old tracks periodically
    if stream_id and current_frame_count % 10 == 0:  # Every 10 frames
        with tracking_lock:
            _cleanup_old_tracks(stream_id, current_frame_count, current_time)

    # Process every frame - no skipping for maximum face capture quality

    # Optimized for Tesla T4 GPU: Process at HD resolution (720p) for maximum speed
    # Tesla T4 can handle full resolution processing efficiently, but 720p reduces latency
    original_h, original_w = frame_bgr.shape[:2]
    max_width = 1280  # Process HD resolution (Tesla T4 optimized for speed)
    
    if original_w > max_width:
        scale = max_width / original_w
        new_w = max_width
        new_h = int(original_h * scale)
        # Use faster interpolation for real-time processing
        scaled_frame = cv2.resize(frame_bgr, (new_w, new_h), interpolation=cv2.INTER_AREA)
        scale_back = original_w / new_w
    else:
        scaled_frame = frame_bgr
        scale_back = 1.0
        new_w, new_h = original_w, original_h

    h, w = new_h, new_w
    logger.debug(f"[FACE_PIPE] Processing frame: {w}x{h}, stream_id={stream_id}")
    start_time = time.time()
    faces = current_face_app.get(scaled_frame)
    det_time = time.time() - start_time
    if len(faces) > 0:
        logger.info(f"[FACE_PIPE] Found {len(faces)} faces in raw detection")
    detections: List[Dict[str, Any]] = []
    
    # Get tracks for this stream (ensure it exists)
    if stream_id:
        if stream_id not in person_tracking:
            with tracking_lock:
                if stream_id not in person_tracking:
                    person_tracking[stream_id] = {}
        tracks = person_tracking[stream_id]
    else:
        tracks = {}

    for f in faces:
        # InsightFace bbox order: [x1, y1, x2, y2]
        try:
            x1, y1, x2, y2 = map(int, f.bbox)
        except Exception:
            bbox = getattr(f, "bbox", None)
            if bbox is None or len(bbox) < 4:
                continue
            x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])

        # Scale bbox back to original frame size if we downscaled
        if scale_back != 1.0:
            x1 = int(x1 * scale_back)
            x2 = int(x2 * scale_back)
            y1 = int(y1 * scale_back)
            y2 = int(y2 * scale_back)
            w, h = original_w, original_h

        # Clamp to original image bounds
        x1 = max(0, min(w - 1, x1))
        x2 = max(0, min(w - 1, x2))
        y1 = max(0, min(h - 1, y1))
        y2 = max(0, min(h - 1, y2))

        # Skip tiny boxes globally
        if (x2 - x1) < 50 or (y2 - y1) < 50:
            continue

        # Crop face from original frame (not downscaled)
        face_crop_bgr = frame_bgr[y1:y2, x1:x2]
        if face_crop_bgr.size == 0:
            continue

        # Skip very small faces (likely false positives) - slightly more lenient for streaming
        if (x2 - x1) < 60 or (y2 - y1) < 60:
            continue

        face_crop_rgb = cv2.cvtColor(face_crop_bgr, cv2.COLOR_BGR2RGB)

        # Provide location relative to crop for speed (num_jitters=0 for speed)
        crop_h, crop_w = face_crop_rgb.shape[:2]
        crop_location = [(0, crop_w - 1, crop_h - 1, 0)]
        try:
            # Use large model to match known face encodings (loaded with large model in fr1.py)
            # CRITICAL: model must match what was used in load_known_faces()
            encs = face_recognition.face_encodings(
                face_crop_rgb, 
                known_face_locations=crop_location, 
                num_jitters=1,   # 1 jitter for better accuracy
                model='large'    # Must match fr1.py's load_known_faces encoding model
            )
        except Exception as e:
            # Silently skip encoding errors to avoid log spam
            encs = []

        # Get current bounding box
        current_bbox = (x1, y1, x2, y2)
        
        # Try to match this detection to an existing track
        matched_track_id = None
        persisted_name = None
        
        if stream_id and tracks:
            with tracking_lock:
                # Make a copy of track IDs to iterate safely
                track_ids = list(tracks.keys())
                matched_track_id = _match_detection_to_track(current_bbox, tracks)
                if matched_track_id is not None:
                    # Found a match - get persisted name
                    track_info = tracks[matched_track_id]
                    persisted_name = track_info.get('name')
        
        # Initialize name: use persisted name if it's a known person, otherwise "Unknown"
        # Once a person is recognized as known, we keep that name
        if persisted_name and persisted_name != "Unknown":
            name = persisted_name
        else:
            name = "Unknown"
        
        conf = 0.0
        
        # Get InsightFace detection confidence (how confident the detector is that it found a face)
        det_conf = getattr(f, "det_score", None) or getattr(f, "score", None)
        if det_conf is None:
            det_conf = 0.0
        else:
            det_conf = float(det_conf)

        # Try to recognize the face
        recognized_name = None
        face_encoding = None
        
        if encs and len(current_known_encodings) > 0:
            enc = encs[0]
            face_encoding = enc  # Store for tracking
            distances = face_recognition.face_distance(current_known_encodings, enc)
            
            # Multi-match consensus: require multiple encodings to agree on the same person
            # Sort indices by distance (best matches first)
            sorted_indices = np.argsort(distances)
            best_dist = float(distances[sorted_indices[0]])
            
            if best_dist <= TOLERANCE:
                best_name = current_known_names[sorted_indices[0]]
                
                # Count how many of the top-N closest matches agree on the same person
                top_n = min(5, len(sorted_indices))
                name_votes = {}
                for i in range(top_n):
                    idx = sorted_indices[i]
                    dist = float(distances[idx])
                    if dist <= TOLERANCE + 0.05:  # Margin for consensus vote counting (max 0.60 distance)
                        vote_name = current_known_names[idx]
                        name_votes[vote_name] = name_votes.get(vote_name, 0) + 1
                
                # Determine required votes based on how many reference images exist for this person
                total_references = current_known_names.count(best_name)
                required_votes = min(2, total_references)

                # Require consensus based on available reference images
                if name_votes.get(best_name, 0) >= required_votes:
                    recognized_name = best_name
                    if recognized_name and recognized_name != "Unknown":
                        name = recognized_name
                        recog_conf = max(0.0, 1.0 - best_dist)
                        conf = recog_conf
                    else:
                        conf = det_conf
                else:
                    # Not enough consensus — treat as unknown to prevent false positives
                    logger.warning(f"[UNKNOWN] Low consensus | best={best_name} | votes={name_votes.get(best_name, 0)}/{required_votes} | det_conf={det_conf:.2f}")
                    conf = det_conf
            else:
                # Recognition failed - keep current name (persisted known name or "Unknown")
                if det_conf > 0.4:
                    logger.info(f"[UNKNOWN] No match | det_conf={det_conf:.2f}")
                conf = det_conf

        if name != "Unknown":
            logger.info(f"[MATCH] {name} | confidence={conf:.2f} | det_conf={det_conf:.2f}")

        # Reconstruction of missing logic: Person tracking, quality check, and saving decision
        face_quality = _calculate_face_quality(face_crop_bgr, det_conf)
        should_save = False
        face_crop_to_save = face_crop_bgr
        save_label = name

        if stream_id:
            # Thread-safe tracking update
            with tracking_lock:
                if matched_track_id is None:
                    # New person/track
                    track_id_counter[stream_id] += 1
                    new_track_id = track_id_counter[stream_id]
                    person_tracking[stream_id][new_track_id] = {
                        'name': name,
                        'bbox': current_bbox,
                        'last_seen': current_time,
                        'frame_count': 1,
                        'encoding': face_encoding
                    }
                    matched_track_id = new_track_id
                else:
                    # Update existing track
                    track_info = person_tracking[stream_id][matched_track_id]
                    track_info['bbox'] = current_bbox
                    track_info['last_seen'] = current_time
                    track_info['frame_count'] += 1
                    # If we just recognized a previously unknown track, update it
                    if track_info['name'] == "Unknown" and name != "Unknown":
                        track_info['name'] = name
                    if face_encoding is not None:
                        track_info['encoding'] = face_encoding

            # Saving decision based on quality and frequency
            person_key = f"{name}_{matched_track_id}" if name != "Unknown" else f"Unknown_{matched_track_id}"
            
            # Check if we have a better quality face for this person-track in this window
            with tracking_lock:
                best_record = best_face_quality[stream_id].get(person_key)
                
                if best_record:
                    # Reset best quality after time threshold to allow new captures
                    if current_time - best_record['timestamp'] > BEST_QUALITY_RESET_SECONDS:
                        should_save = True
                        best_face_quality[stream_id][person_key] = {
                            'quality': face_quality,
                            'timestamp': current_time
                        }
                    elif face_quality > best_record['quality'] + 0.05: # Significant improvement
                        should_save = True
                        best_face_quality[stream_id][person_key] = {
                            'quality': face_quality,
                            'timestamp': current_time
                        }
                    else:
                        should_save = False
                else:
                    # First detection of this person-track
                    should_save = True
                    best_face_quality[stream_id][person_key] = {
                        'quality': face_quality,
                        'timestamp': current_time
                    }
        else:
            # Fallback for streams without ID (less common)
            should_save = True

        
        if should_save:
            # Make a safe copy for the thread
            face_copy = face_crop_to_save.copy()
            camera_name_to_save = stream_id or "default"
            if stream_id:
                try:
                    from camera_management.streaming import get_stream_manager
                    s_info = get_stream_manager().get_stream_info(stream_id)
                    if s_info and 'camera_name' in s_info:
                        camera_name_to_save = s_info['camera_name']
                except Exception as e:
                    print(f"Failed to lookup camera_name/company_id for {stream_id}: {e}")
            
            company_id_to_save = None
            if stream_id:
                try:
                    from camera_management.streaming import get_stream_manager
                    s_info = get_stream_manager().get_stream_info(stream_id)
                    if s_info and 'company_id' in s_info:
                        company_id_to_save = s_info['company_id']
                except Exception as e:
                    print(f"Failed to lookup company_id for {stream_id}: {e}")

            def _save_face_async():
                try:
                    save_face_image(
                        face_crop_bgr=face_copy,
                        label=save_label,
                        confidence=conf,
                        min_interval=MIN_SAVE_INTERVAL,
                        source="stream",
                        jpeg_quality=95,
                        camera_name=camera_name_to_save,
                        company_id=company_id_to_save
                    )
                except Exception as e:
                    print(f"Error saving face in async thread: {e}")
            
            # Spawn thread to save face without blocking frame processing
            save_thread = threading.Thread(target=_save_face_async, daemon=True)
            save_thread.start()

        detections.append({"name": name, "conf": conf, "bbox": (x1, y1, x2, y2)})

    # Calculate and log structured metrics
    end_time = time.time()
    recognized_users = [d["name"] for d in detections if d["name"] != "Unknown"]
    metrics = {
        "frame_time": end_time - start_time,
        "faces_detected": len(faces),
        "faces_recognized": len(recognized_users),
        "stream_id": stream_id
    }
    logger.info(f"[METRICS] {metrics}")

    # DETECTION PERSISTENCE: Return all currently active tracks for UI rendering
    if stream_id:
        active_detections = []
        with tracking_lock:
            # We iterate over the tracking data for this stream
            for tid, tinfo in person_tracking.get(stream_id, {}).items():
                seen_delta = current_time - tinfo.get('last_seen', 0)
                if seen_delta < MAX_TRACK_AGE_SECONDS:
                    # Map track info to detection format for the UI
                    active_detections.append({
                        "name": tinfo.get('name', 'Unknown'),
                        "conf": 0.95 if tinfo.get('name') != "Unknown" else 0.5,
                        "bbox": tinfo.get('bbox'),
                        "track_id": tid,
                        "is_persisted": seen_delta > 0.1 # Mark as persisted if not from current frame (approx)
                    })
        return frame_bgr, active_detections

    return frame_bgr, detections



def render_bounding_boxes(frame: np.ndarray, detections: List[Dict[str, Any]], show_bounding_box: bool = True) -> np.ndarray:
    """Draw bounding boxes on the frame as a separate visualization overlay.
    
    This function is purely cosmetic and does NOT affect detection, recognition,
    or event-saving logic. It should be called after process_frame().
    
    Args:
        frame: BGR frame to annotate
        detections: List of detection dicts from process_frame(), each with 'name', 'conf', 'bbox'
        show_bounding_box: If False, returns the frame unchanged
    
    Returns:
        Annotated frame (copy) if show_bounding_box is True, otherwise the original frame
    """
    if not show_bounding_box:
        return frame
    
    if not detections:
        return frame
    
    annotated = frame.copy()
    
    # Scale font based on frame resolution for consistent appearance
    h, w = annotated.shape[:2]
    font_scale = max(0.8, min(1.5, w / 640.0))  # 1.0 at 640px, scales up for HD
    thickness = max(2, int(font_scale * 2))
    box_thickness = max(2, int(font_scale * 2.5))
    
    for det in detections:
        name = det.get("name", "Unknown")
        conf = det.get("conf", 0.0)
        bbox = det.get("bbox")
        if bbox is None:
            continue
        x1, y1, x2, y2 = int(bbox[0]), int(bbox[1]), int(bbox[2]), int(bbox[3])
        
        # Green for known faces, red for unknown
        is_known = name != "Unknown"
        color = (0, 255, 0) if is_known else (0, 0, 255)
        
        # Draw bounding box with rounded corners effect (thick)
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, box_thickness)
        
        # Build label text — name only, no confidence number
        label = name
        
        # Calculate label dimensions
        (label_w, label_h), baseline = cv2.getTextSize(
            label, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness
        )
        
        # Position label ABOVE the bounding box
        label_y_top = y1 - label_h - baseline - 8
        if label_y_top < 0:
            # If no room above, place BELOW top edge
            label_y_top = y1 + 4
        
        # Draw filled background behind label for readability
        cv2.rectangle(
            annotated,
            (x1, label_y_top),
            (x1 + label_w + 8, label_y_top + label_h + baseline + 8),
            color,
            cv2.FILLED
        )
        
        # Draw label text (white on colored background)
        cv2.putText(
            annotated,
            label,
            (x1 + 4, label_y_top + label_h + 4),
            cv2.FONT_HERSHEY_SIMPLEX,
            font_scale,
            (255, 255, 255),
            thickness,
            cv2.LINE_AA,
        )
    
    return annotated