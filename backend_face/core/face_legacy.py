from fastapi import FastAPI, HTTPException, Depends, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.encoders import jsonable_encoder
import cv2
import face_recognition
import os
import numpy as np
from datetime import datetime
from ultralytics import YOLO
import torch
import tensorflow as tf
import json
from typing import Dict, List, Optional, Tuple
import base64
import logging
from pydantic import BaseModel, validator
from fastapi import APIRouter
from urllib.parse import urlparse
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
import multiprocessing
# Configure base directory and paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BACKEND_DIR = os.path.join(BASE_DIR, "backend_face")
DATA_DIR = os.path.join(BACKEND_DIR, "data")  # Update data directory path
MODEL_PATH = os.path.join(BASE_DIR, "yolov8n-face.pt")

# Create data directory if it doesn't exist
os.makedirs(DATA_DIR, exist_ok=True)

# Configure logging with more detail
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Log directory structure for debugging
logger.info(f"Base Directory: {BASE_DIR}")
logger.info(f"Backend Directory: {BACKEND_DIR}")
logger.info(f"Data Directory: {DATA_DIR}")
logger.info(f"Model Path: {MODEL_PATH}")

# Define captured faces directory
CAPTURED_FACES_DIR = r"C:\Users\e629\Desktop\GUI_Face\backend_face\captured_faces"
KNOWN_FACES_DIR = os.path.join(CAPTURED_FACES_DIR, "known")
UNKNOWN_FACES_DIR = os.path.join(CAPTURED_FACES_DIR, "unknown")

# Create necessary directories
os.makedirs(CAPTURED_FACES_DIR, exist_ok=True)
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
os.makedirs(UNKNOWN_FACES_DIR, exist_ok=True)

logger.info(f"Captured Faces Directory: {CAPTURED_FACES_DIR}")
logger.info(f"Known Faces Directory: {KNOWN_FACES_DIR}")
logger.info(f"Unknown Faces Directory: {UNKNOWN_FACES_DIR}")

# Models
class CameraStatus(BaseModel):
    status: str
    camera_id: int
    active: bool
    page: Optional[int] = None
    total_pages: Optional[int] = None
    error_message: Optional[str] = None  # Add error message field
    connection_status: Optional[str] = None  # Add connection status field

class FaceRecognitionStatus(BaseModel):
    status: str
    camera_id: int
    face_recognition_active: bool

class ServiceStatus(BaseModel):
    status: str
    gpu_available: bool
    yolo_model_loaded: bool
    known_faces_count: int
    active_cameras: Dict[int, bool]
    face_recognition_states: Dict[int, bool]
    total_cameras: int
    stream_health: Dict[int, dict]

class RTSPCamera(BaseModel):
    rtsp_url: str
    name: Optional[str] = None

    @validator('rtsp_url')
    def validate_rtsp_url(cls, v):
        # Handle case where input is a list instead of string
        if isinstance(v, list):
            if len(v) > 0:
                v = v[0]  # Take the first element if it's a list
            else:
                raise ValueError("RTSP URL cannot be empty")

        if not isinstance(v, str):
            raise ValueError("RTSP URL must be a string")
       
        # Check if URL starts with rtsp://
        if not v.startswith('rtsp://'):
            raise ValueError("Camera URL must start with 'rtsp://'")
       
        try:
            # Parse the URL
            parsed = urlparse(v)
            netloc = parsed.netloc
           
            # Only add default port if no port is specified AND no path is present
            if '@' in netloc:
                # URL has authentication
                auth, host = netloc.rsplit('@', 1)
                if ':' not in host and not parsed.path:  # No port in host part and no path
                    new_netloc = f"{auth}@{host}:554"
                    v = v.replace(netloc, new_netloc)
            else:
                # URL has no authentication
                if ':' not in netloc and not parsed.path:  # No port specified and no path
                    new_netloc = f"{netloc}:554"
                    v = v.replace(netloc, new_netloc)
           
            # Reparse with potentially modified URL
            parsed = urlparse(v)
           
            # Validate port if present
            if ':' in parsed.netloc:
                host, port = parsed.netloc.rsplit(':', 1)
                try:
                    port = int(port)
                    if port < 1 or port > 65535:
                        raise ValueError("Invalid camera port number (must be between 1 and 65535)")
                except ValueError:
                    raise ValueError("Invalid camera port format")
           
            # Check for credentials format if present
            if '@' in parsed.netloc:
                auth = parsed.netloc.split('@')[0]
                if ':' not in auth:
                    raise ValueError("Invalid camera credentials (format should be username:password)")
           
            return v
        except Exception as e:
            raise ValueError(f"Invalid camera URL format: {str(e)}")

# Service class
class CameraService:
    def __init__(self):
        self.active_cameras: Dict[int, bool] = {}
        self.face_recognition_states: Dict[int, bool] = {}
        self.known_faces: Dict[str, List] = {"encodings": [], "names": []}
        self.yolo_model = None
        self.gpu_available = self.configure_gpu()
       
        # Camera pagination settings
        self.CAMERAS_PER_PAGE = 6
        self.total_pages = 1
       
        # Configure standard camera properties for better performance
        self.camera_width = 640  # Reduced for better performance
        self.camera_height = 480  # Reduced for better performance
        self.camera_fps = 20  # Increased slightly for smoother display
       
        # Configure face detection parameters
        self.face_conf_threshold = 0.3  # YOLO confidence threshold
        self.face_iou_threshold = 0.5   # YOLO IOU threshold
        self.face_recognition_threshold = 0.5  # Face recognition tolerance
        self.min_face_size = 20  # Minimum face size to detect
       
        # Configure monitoring parameters
        self.max_frame_age = 5.0  # Maximum age of last frame in seconds
        self.max_reconnection_attempts = 5  # Maximum number of reconnection attempts
        self.reconnection_cooldown = 60  # Cooldown period between reconnection attempts in seconds
        self.health_check_interval = 10  # Health check interval in seconds
       
        # Configure 24/7 operation parameters
        self.continuous_operation = True  # Flag for continuous operation
        self.maintenance_interval = 3600  # Perform maintenance every hour (3600 seconds)
        self.last_maintenance_time = time.time()
        self.error_threshold = 10  # Maximum consecutive errors before maintenance
        self.error_counts: Dict[int, int] = {}  # Track error counts per camera
       
        # Configure processing parameters
        self.process_every_n_frames = 2  # Process every other frame
        self.frame_count = {}  # Track frame counts per camera
        self.max_queue_size = 2  # Reduced queue size for lower latency
        self.processing_frames = {}  # Track which cameras are being processed
        self.frame_skip = {}  # Track frame skipping per camera
       
        # Configure buffer settings
        self.buffer_size = 1  # Minimize frame buffer
        self.max_processing_time = 0.1  # Maximum time for frame processing (100ms)
       
        # Initialize thread pool and queues
        self.num_workers = min(multiprocessing.cpu_count(), 4)  # Limit to max 4 workers
        self.thread_pool = ThreadPoolExecutor(max_workers=self.num_workers * 2)
        self.frame_queues: Dict[int, Queue] = {}  # Queue for each camera's frames
        self.processing_queues: Dict[int, Queue] = {}  # Queue for processing results
       
        # Initialize components
        self.initialize_yolo()
        self.load_known_faces()
        self.camera_streams: Dict[int, str] = {}  # Store RTSP URLs
        self.next_camera_id = 1  # Track next available camera ID
        self.recognition_log = {}  # Store recognition timestamps
        self.db_path = os.path.join(BACKEND_DIR, "database", "cameras.json")
        self.load_cameras_from_db()
        self.video_captures: Dict[int, cv2.VideoCapture] = {}  # Store video capture objects
        self.stream_threads: Dict[int, dict] = {}  # Track streaming threads and their status
        self.stream_health: Dict[int, dict] = {}  # Track stream health metrics
        self.last_frame_time: Dict[int, float] = {}  # Track last successful frame time
        self.reconnection_attempts: Dict[int, int] = {}  # Track reconnection attempts
        self.frame_buffers: Dict[int, np.ndarray] = {}  # Store latest frames
        self.camera_error_states: Dict[int, dict] = {}  # Track camera errors
        self.max_retry_interval = 30  # Maximum seconds between retry attempts
        self.min_retry_interval = 5   # Minimum seconds between retry attempts
        self.camera_retry_times: Dict[int, float] = {}  # Track last retry times
       
        # Start streaming and monitoring
        self.initialize_all_cameras()
        self.start_health_monitoring()
        self.start_maintenance_monitoring()
       
    def configure_gpu(self) -> bool:
        """Enhanced GPU configuration with better error handling"""
        try:
            if torch.cuda.is_available():
                logger.info(f"CUDA is available. Using GPU: {torch.cuda.get_device_name(0)}")
                torch.cuda.set_device(0)
                return True
            elif tf.test.is_built_with_cuda():
                logger.info(f"TensorFlow GPU available. GPUs: {len(tf.config.list_physical_devices('GPU'))}")
                return True
            else:
                logger.info("No GPU available. Using CPU.")
                return False
        except Exception as e:
            logger.error(f"Error configuring GPU: {e}")
            return False

    def initialize_yolo(self) -> None:
        try:
            # Verify model file exists
            if not os.path.exists(MODEL_PATH):
                logger.error(f"YOLO model file not found at: {MODEL_PATH}")
                raise FileNotFoundError(f"YOLO model file not found at: {MODEL_PATH}")
           
            logger.info(f"Loading YOLO model from: {MODEL_PATH}")
           
            # Set device explicitly
            device = 'cuda' if self.gpu_available else 'cpu'
           
            # Configure YOLO with optimized settings
            self.yolo_model = YOLO(MODEL_PATH)
            self.yolo_model.to(device)
           
            # Configure model parameters for better face detection
            self.yolo_model.conf = 0.25  # Lower confidence threshold for known faces
            self.yolo_model.iou = 0.45   # Lower IOU threshold for better detection
            self.yolo_model.max_det = 5   # Limit detections per image
            self.yolo_model.verbose = False
           
            logger.info(f"YOLO model configured with conf={self.yolo_model.conf}, iou={self.yolo_model.iou}")
           
            # Warmup with different resolutions
            logger.info("Warming up YOLO model...")
            resolutions = [
                (640, 640),    # Base resolution
                (1280, 720),   # HD
                (1920, 1080)   # Full HD
            ]
           
            for size in resolutions:
                dummy_input = np.zeros((*size, 3), dtype=np.uint8)
                _ = self.yolo_model(dummy_input)
                logger.debug(f"Warmup completed for resolution {size}")
           
            logger.info(f"YOLO model loaded successfully on {device}")
           
        except Exception as e:
            logger.error(f"Error loading YOLO model: {e}")
            self.yolo_model = None

    def load_known_faces(self, known_faces_dir=None):
        """Load known faces from the data directory and its subdirectories"""
        try:
            # Always use the data directory for known faces
            known_faces_dir = DATA_DIR
            logger.info(f"Loading known faces from data directory: {known_faces_dir}")
           
            if not os.path.exists(known_faces_dir):
                os.makedirs(known_faces_dir)
                logger.warning(f"Created data directory at: {known_faces_dir}")
                return
           
            known_face_encodings = []
            known_face_names = []
           
            # Walk through all subdirectories
            for root, dirs, files in os.walk(known_faces_dir):
                # Skip the 'gallery' directory and the root data directory
                if root == known_faces_dir or os.path.basename(root) == 'gallery':
                    continue
               
                # Get person name from directory name
                person_name = os.path.basename(root)
               
                # Process image files in current directory
                image_files = [f for f in files if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
               
                if image_files:
                    logger.info(f"Found {len(image_files)} face images for {person_name} in {root}")
                   
                    # Process faces in parallel using ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                        futures = []
                       
                        for image_file in image_files:
                            image_path = os.path.join(root, image_file)
                            logger.debug(f"Processing image: {image_path}")
                            futures.append(
                                executor.submit(
                                    self._process_face_image,
                                    image_path,
                                    person_name
                                )
                            )
                       
                        # Collect results
                        for future in futures:
                            result = future.result()
                            if result:
                                encoding, name = result
                                known_face_encodings.append(encoding)
                                known_face_names.append(name)
                                logger.debug(f"Successfully processed face for {name}")
           
            self.known_faces = {
                "encodings": known_face_encodings,
                "names": known_face_names
            }
           
            # Log statistics
            unique_names = set(known_face_names)
            name_counts = {}
            for name in known_face_names:
                name_counts[name] = name_counts.get(name, 0) + 1
               
            logger.info(f"Successfully loaded {len(known_face_encodings)} face encodings")
            logger.info(f"Loaded faces for {len(unique_names)} unique persons")
            for name, count in name_counts.items():
                logger.info(f"  - {name}: {count} faces")
           
            if not known_face_encodings:
                logger.warning("No face encodings were loaded. Face recognition will not work!")
                logger.warning(f"Please add face images to subdirectories in: {known_faces_dir}")
                logger.warning("Directory structure should be:")
                logger.warning(f"{known_faces_dir}/")
                logger.warning("    ├── person1_name/")
                logger.warning("    │   ├── image1.jpg")
                logger.warning("    │   └── image2.jpg")
                logger.warning("    └── person2_name/")
                logger.warning("        ├── image1.jpg")
                logger.warning("        └── image2.jpg")
       
        except Exception as e:
            logger.error(f"Error loading known faces: {e}")
            self.known_faces = {"encodings": [], "names": []}

    def _process_face_image(self, image_path: str, person_name: str):
        """Process a single face image and return encoding and name"""
        try:
            logger.debug(f"Processing face image for {person_name}: {image_path}")
           
            # Read image using OpenCV for better performance
            image = cv2.imread(image_path)
            if image is None:
                logger.warning(f"Could not read image: {image_path}")
                return None
           
            # Convert BGR to RGB
            rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            logger.debug(f"Successfully converted image to RGB: {image_path}")
           
            # Use YOLO for face detection if available
            if self.yolo_model:
                results = self.yolo_model(rgb_image, verbose=False)
                if not results or len(results) == 0:
                    logger.warning(f"No faces detected by YOLO in image: {image_path}")
                    return None
               
                # Get the face with highest confidence
                boxes = results[0].boxes.cpu().numpy()
                if len(boxes) == 0:
                    logger.warning(f"No face boxes detected in image: {image_path}")
                    return None
               
                # Get the box with highest confidence
                best_box = max(boxes, key=lambda x: float(x.conf))
                confidence = float(best_box.conf)
                if confidence < self.face_conf_threshold:
                    logger.warning(f"Face detection confidence too low ({confidence:.2f}) in image: {image_path}")
                    return None
               
                x1, y1, x2, y2 = map(int, best_box.xyxy[0])
               
                # Instead of cropping, use the full image with face locations
                face_locations = [(y1, x2, y2, x1)]  # Convert to face_recognition format (top, right, bottom, left)
                face_encodings = face_recognition.face_encodings(rgb_image, face_locations)
               
                if not face_encodings:
                    logger.warning(f"Could not generate face encoding for detected face in: {image_path}")
                    return None
               
                logger.debug(f"Successfully processed face for {person_name} with confidence {confidence:.2f}")
                return face_encodings[0], person_name
           
            else:
                # Fallback to face_recognition library
                face_locations = face_recognition.face_locations(rgb_image)
                if not face_locations:
                    logger.warning(f"No faces detected by face_recognition in image: {image_path}")
                    return None
               
                face_encodings = face_recognition.face_encodings(rgb_image, face_locations)
                if not face_encodings:
                    logger.warning(f"Could not generate face encoding using face_recognition in: {image_path}")
                    return None
               
                logger.debug(f"Successfully processed face for {person_name} using face_recognition")
                return face_encodings[0], person_name
           
        except Exception as e:
            logger.error(f"Error processing image {image_path} for {person_name}: {e}")
            return None

    def load_cameras_from_db(self):
        """Load camera information from database file"""
        try:
            if os.path.exists(self.db_path):
                with open(self.db_path, 'r') as f:
                    data = json.load(f)
                    self.camera_streams = data.get('camera_streams', {})
                    self.next_camera_id = data.get('next_camera_id', 1)
                    # Convert string keys to integers
                    self.camera_streams = {int(k): v for k, v in self.camera_streams.items()}
                    logger.info(f"Loaded {len(self.camera_streams)} cameras from database")
        except Exception as e:
            logger.error(f"Error loading cameras from database: {e}")

    def save_cameras_to_db(self):
        """Save camera information to database file"""
        try:
            data = {
                'camera_streams': self.camera_streams,
                'next_camera_id': self.next_camera_id
            }
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            with open(self.db_path, 'w') as f:
                json.dump(data, f, indent=4)
            logger.info(f"Saved {len(self.camera_streams)} cameras to database")
        except Exception as e:
            logger.error(f"Error saving cameras to database: {e}")

    def initialize_all_cameras(self):
        """Initialize and start streaming for all cameras in database"""
        try:
            for camera_id, rtsp_url in self.camera_streams.items():
                self.start_camera_stream(camera_id)
        except Exception as e:
            logger.error(f"Error initializing cameras: {e}")

    def start_health_monitoring(self):
        """Start background thread for health monitoring"""
        import threading
        self.monitoring_active = True
        self.monitor_thread = threading.Thread(target=self._health_monitor_loop, daemon=True)
        self.monitor_thread.start()
        logger.info("Started health monitoring thread")

    def _health_monitor_loop(self):
        """Continuous monitoring loop for stream health"""
        while self.monitoring_active:
            try:
                current_time = time.time()
                for camera_id in list(self.active_cameras.keys()):
                    if not self.active_cameras[camera_id]:
                        continue

                    last_frame_time = self.last_frame_time.get(camera_id, 0)
                    frame_age = current_time - last_frame_time

                    # Check if stream is stale
                    if frame_age > self.max_frame_age:
                        logger.warning(f"Camera {camera_id} stream is stale (age: {frame_age:.1f}s)")
                        self._attempt_stream_recovery(camera_id)

                    # Update health metrics
                    self.stream_health[camera_id] = {
                        'last_frame_age': frame_age,
                        'reconnection_attempts': self.reconnection_attempts.get(camera_id, 0),
                        'status': 'healthy' if frame_age <= self.max_frame_age else 'stale'
                    }

                # Sleep for health check interval
                time.sleep(self.health_check_interval)
            except Exception as e:
                logger.error(f"Error in health monitor loop: {e}")
                time.sleep(5)  # Sleep on error to prevent tight loop

    def _attempt_stream_recovery(self, camera_id: int):
        """Attempt to recover a failed stream"""
        try:
            current_attempts = self.reconnection_attempts.get(camera_id, 0)
           
            # Check if we've exceeded max attempts
            if current_attempts >= self.max_reconnection_attempts:
                logger.error(f"Max reconnection attempts reached for camera {camera_id}")
                self.deactivate_camera(camera_id)
                return False

            # Increment attempt counter
            self.reconnection_attempts[camera_id] = current_attempts + 1
           
            # Stop existing stream
            self.stop_camera_stream(camera_id)
           
            # Wait for cooldown
            time.sleep(min(self.reconnection_cooldown, 5))  # Use shorter cooldown for first attempts
           
            # Attempt reconnection
            success = self.start_camera_stream(camera_id)
           
            if success:
                logger.info(f"Successfully recovered camera {camera_id} stream")
                self.reconnection_attempts[camera_id] = 0  # Reset counter on success
                return True
            else:
                logger.warning(f"Failed to recover camera {camera_id} stream")
                return False

        except Exception as e:
            logger.error(f"Error in stream recovery for camera {camera_id}: {e}")
            return False

    def start_maintenance_monitoring(self):
        """Start background thread for system maintenance"""
        import threading
        self.maintenance_active = True
        self.maintenance_thread = threading.Thread(target=self._maintenance_loop, daemon=True)
        self.maintenance_thread.start()
        logger.info("Started maintenance monitoring thread")

    def _maintenance_loop(self):
        """Continuous maintenance loop for 24/7 operation"""
        while self.maintenance_active:
            try:
                current_time = time.time()
               
                # Perform periodic maintenance
                if current_time - self.last_maintenance_time >= self.maintenance_interval:
                    logger.info("Performing scheduled maintenance")
                    self._perform_maintenance()
                    self.last_maintenance_time = current_time
               
                # Check for cameras with high error counts
                for camera_id in list(self.error_counts.keys()):
                    if self.error_counts[camera_id] >= self.error_threshold:
                        logger.warning(f"Camera {camera_id} exceeded error threshold, performing maintenance")
                        self._perform_camera_maintenance(camera_id)
               
                # Sleep for a short interval
                time.sleep(60)  # Check every minute
               
            except Exception as e:
                logger.error(f"Error in maintenance loop: {e}")
                time.sleep(60)  # Sleep on error to prevent tight loop

    def _perform_maintenance(self):
        """Perform system-wide maintenance tasks"""
        try:
            logger.info("Starting system maintenance")
           
            # Clear error counts
            self.error_counts.clear()
           
            # Reload known faces to catch any updates
            self.load_known_faces()
           
            # Check GPU status
            self.gpu_available = self.configure_gpu()
           
            # Verify YOLO model
            if self.yolo_model is None:
                self.initialize_yolo()
           
            # Clean up old captured face photos
            self._cleanup_old_captures()
           
            # Check and cleanup resources
            self._cleanup_resources()
           
            # Verify all active cameras
            for camera_id in list(self.active_cameras.keys()):
                if self.active_cameras[camera_id]:
                    self._verify_camera_stream(camera_id)
           
            logger.info("System maintenance completed successfully")
           
        except Exception as e:
            logger.error(f"Error during system maintenance: {e}")

    def _cleanup_old_captures(self):
        """Delete captured face photos older than one month"""
        try:
            import time
            from datetime import datetime, timedelta
            import os
           
            # Calculate the cutoff date (1 month ago)
            one_month_ago = datetime.now() - timedelta(days=30)
           
            # Function to check if a file is older than one month
            def is_old_file(filepath):
                try:
                    # Get file modification time
                    mtime = os.path.getmtime(filepath)
                    file_date = datetime.fromtimestamp(mtime)
                    return file_date < one_month_ago
                except Exception as e:
                    logger.error(f"Error checking file age for {filepath}: {e}")
                    return False

            # Clean up unknown faces directory
            if os.path.exists(UNKNOWN_FACES_DIR):
                deleted_count = 0
                for root, dirs, files in os.walk(UNKNOWN_FACES_DIR):
                    for file in files:
                        if file.endswith(('.jpg', '.jpeg', '.png')):
                            filepath = os.path.join(root, file)
                            if is_old_file(filepath):
                                try:
                                    os.remove(filepath)
                                    deleted_count += 1
                                    logger.info(f"Deleted old capture: {filepath}")
                                except Exception as e:
                                    logger.error(f"Error deleting file {filepath}: {e}")
               
                # Clean up empty camera directories
                for root, dirs, files in os.walk(UNKNOWN_FACES_DIR, topdown=False):
                    for dir_name in dirs:
                        dir_path = os.path.join(root, dir_name)
                        try:
                            if not os.listdir(dir_path):  # If directory is empty
                                os.rmdir(dir_path)
                                logger.info(f"Removed empty directory: {dir_path}")
                        except Exception as e:
                            logger.error(f"Error removing directory {dir_path}: {e}")
               
                logger.info(f"Cleanup completed: Deleted {deleted_count} files older than 30 days")
           
        except Exception as e:
            logger.error(f"Error during capture cleanup: {e}")

    def _perform_camera_maintenance(self, camera_id: int):
        """Perform maintenance for a specific camera"""
        try:
            logger.info(f"Starting maintenance for camera {camera_id}")
           
            # Reset error count
            self.error_counts[camera_id] = 0
           
            # Stop the camera stream
            self.stop_camera_stream(camera_id)
           
            # Wait for cooldown
            time.sleep(5)
           
            # Attempt to restart the stream
            if self.active_cameras.get(camera_id, False):
                success = self.start_camera_stream(camera_id)
                if success:
                    logger.info(f"Successfully restored camera {camera_id}")
                else:
                    logger.error(f"Failed to restore camera {camera_id}")
           
        except Exception as e:
            logger.error(f"Error during camera maintenance: {e}")

    def _verify_camera_stream(self, camera_id: int):
        """Verify camera stream is working properly"""
        try:
            if camera_id not in self.video_captures:
                return False
           
            cap = self.video_captures[camera_id]
            if not cap.isOpened():
                logger.warning(f"Camera {camera_id} stream is not open")
                return False
           
            ret, frame = cap.read()
            if not ret or frame is None:
                logger.warning(f"Failed to read frame from camera {camera_id}")
                return False
           
            return True
           
        except Exception as e:
            logger.error(f"Error verifying camera stream {camera_id}: {e}")
            return False

    def _cleanup_resources(self):
        """Cleanup system resources"""
        try:
            # Clear unused frame buffers
            for camera_id in list(self.frame_buffers.keys()):
                if not self.active_cameras.get(camera_id, False):
                    self.frame_buffers.pop(camera_id, None)
           
            # Clear old recognition logs
            current_time = time.time()
            for name in list(self.recognition_log.keys()):
                log_entry = self.recognition_log[name]
                if current_time - log_entry['last_seen'].timestamp() > 86400:  # Older than 24 hours
                    self.recognition_log.pop(name, None)
           
            # Reset reconnection attempts for stable cameras
            for camera_id in list(self.reconnection_attempts.keys()):
                if self._verify_camera_stream(camera_id):
                    self.reconnection_attempts[camera_id] = 0
           
        except Exception as e:
            logger.error(f"Error during resource cleanup: {e}")

    def _camera_stream_thread(self, camera_id: int):
        """Thread responsible for continuously reading frames from camera"""
        try:
            logger.info(f"Started streaming thread for camera {camera_id}")
            self.stream_health[camera_id] = {
                'status': 'starting',
                'fps': 0,
                'frame_count': 0,
                'start_time': time.time(),
                'last_frame_time': time.time()
            }
            
            # Reset error count
            self.error_counts[camera_id] = 0
            
            # Continue streaming while active
            while self.active_cameras.get(camera_id, False):
                try:
                    if camera_id not in self.video_captures or self.video_captures[camera_id] is None:
                        logger.warning(f"Video capture object not available for camera {camera_id}. Attempting to recreate.")
                        # Try to recreate the capture object
                        if camera_id in self.camera_streams:
                            rtsp_url = self.camera_streams[camera_id]
                            self.video_captures[camera_id] = cv2.VideoCapture(rtsp_url)
                            logger.info(f"Recreated video capture for camera {camera_id}")
                        else:
                            logger.error(f"Cannot recreate video capture: No URL for camera {camera_id}")
                            break
                    
                    # Read frame from camera
                    ret, frame = self.video_captures[camera_id].read()
                    
                    if not ret or frame is None or frame.size == 0:
                        self.error_counts[camera_id] += 1
                        logger.warning(f"Error reading frame from camera {camera_id} (attempt {self.error_counts[camera_id]})")
                        
                        if self.error_counts[camera_id] > 10:  # Allow more retries
                            logger.error(f"Failed to read frames from camera {camera_id} after multiple attempts")
                            self._handle_camera_error(camera_id, "Failed to read frames after multiple attempts")
                            break
                            
                        # Add short sleep to prevent tight loop
                        time.sleep(0.5)
                        continue
                    
                    # Reset error count on successful frame
                    self.error_counts[camera_id] = 0
                    
                    # Update health metrics
                    self.stream_health[camera_id]['status'] = 'streaming'
                    self.stream_health[camera_id]['frame_count'] += 1
                    self.stream_health[camera_id]['last_frame_time'] = time.time()
                    
                    # Calculate FPS every 30 frames
                    if self.stream_health[camera_id]['frame_count'] % 30 == 0:
                        elapsed = time.time() - self.stream_health[camera_id]['start_time']
                        if elapsed > 0:
                            self.stream_health[camera_id]['fps'] = 30 / elapsed
                        self.stream_health[camera_id]['start_time'] = time.time()
                    
                    # Apply preprocessing to frame (resize, enhance, etc.)
                    # Process frame if face recognition is active
                    if self.face_recognition_states.get(camera_id, False):
                        process_frame, _ = self.process_frame(frame, camera_id)
                        # Update processed frame
                        self.frame_buffers[camera_id] = process_frame
                    else:
                        # Store original frame
                        self.frame_buffers[camera_id] = frame
                    
                    # Control frame rate to reduce CPU usage
                    time.sleep(0.05)  # Cap at around 20fps max
                    
                except Exception as e:
                    error_msg = f"Error in camera stream loop for camera {camera_id}: {str(e)}"
                    logger.error(error_msg)
                    self._handle_camera_error(camera_id, error_msg)
                    time.sleep(1)  # Prevent tight loop on repeated errors
            
            # Clean up on thread exit
            logger.info(f"Exiting camera stream thread for camera {camera_id}")
            # Update status
            self.stream_health[camera_id]['status'] = 'stopped'
            
        except Exception as e:
            logger.error(f"Fatal error in stream thread for camera {camera_id}: {str(e)}")
            self._handle_camera_failure(camera_id)
            
        finally:
            # Ensure video capture is released
            if camera_id in self.video_captures and self.video_captures[camera_id] is not None:
                try:
                    self.video_captures[camera_id].release()
                    logger.info(f"Released video capture for camera {camera_id}")
                except Exception as release_error:
                    logger.error(f"Error releasing video capture for camera {camera_id}: {str(release_error)}")
                self.video_captures[camera_id] = None

    def _handle_camera_error(self, camera_id: int, error_message: str):
        """Handle camera errors and update status"""
        current_time = time.time()
       
        if camera_id not in self.camera_error_states:
            self.camera_error_states[camera_id] = {
                'first_error_time': current_time,
                'last_error_time': current_time,
                'error_count': 1,
                'current_error': error_message
            }
        else:
            self.camera_error_states[camera_id]['last_error_time'] = current_time
            self.camera_error_states[camera_id]['error_count'] += 1
            self.camera_error_states[camera_id]['current_error'] = error_message

        # Update stream health
        self.stream_health[camera_id] = {
            'status': 'error',
            'last_error': error_message,
            'error_count': self.camera_error_states[camera_id]['error_count'],
            'last_error_time': current_time
        }

        logger.error(f"Camera {camera_id} error: {error_message}")

    def _handle_camera_failure(self, camera_id: int):
        """Handle complete camera failure"""
        logger.error(f"Camera {camera_id} has failed. Stopping stream.")
        self._update_camera_status(camera_id, "failed")
       
        # Deactivate camera but keep in system for recovery
        self.active_cameras[camera_id] = False
        self.face_recognition_states[camera_id] = False
       
        # Schedule recovery attempt
        self.camera_retry_times[camera_id] = time.time()

    def _update_camera_status(self, camera_id: int, status: str):
        """Update camera status and health information"""
        self.stream_health[camera_id] = {
            'status': status,
            'last_update': time.time(),
            'error_count': self.error_counts.get(camera_id, 0),
            'last_error': self.camera_error_states.get(camera_id, {}).get('current_error', None)
        }

    def get_camera_status(self, camera_id: int) -> Dict:
        """Get detailed camera status including error information"""
        if camera_id not in self.camera_streams:
            raise HTTPException(status_code=404, detail="Camera not found")
       
        is_active = self.active_cameras.get(camera_id, False)
        error_state = self.camera_error_states.get(camera_id, {})
        stream_health = self.stream_health.get(camera_id, {})
       
        return {
            'camera_id': camera_id,
            'active': is_active,
            'status': stream_health.get('status', 'unknown'),
            'error_message': error_state.get('current_error', None),
            'error_count': error_state.get('error_count', 0),
            'last_error_time': error_state.get('last_error_time', None),
            'connection_status': 'connected' if is_active and stream_health.get('status') == 'running' else 'disconnected'
        }

    async def attempt_camera_recovery(self, camera_id: int) -> bool:
        """Attempt to recover a failed camera"""
        current_time = time.time()
        last_retry = self.camera_retry_times.get(camera_id, 0)
       
        # Calculate dynamic retry interval
        error_count = self.camera_error_states.get(camera_id, {}).get('error_count', 0)
        retry_interval = min(self.max_retry_interval,
                           max(self.min_retry_interval, error_count * 2))
       
        if current_time - last_retry < retry_interval:
            return False
           
        try:
            logger.info(f"Attempting to recover camera {camera_id}")
            self.camera_retry_times[camera_id] = current_time
           
            # Try to restart the camera
            if self.start_camera_stream(camera_id):
                self.active_cameras[camera_id] = True
                self._update_camera_status(camera_id, "running")
                self.camera_error_states.pop(camera_id, None)
                logger.info(f"Successfully recovered camera {camera_id}")
                return True
               
        except Exception as e:
            logger.error(f"Failed to recover camera {camera_id}: {e}")
            self._handle_camera_error(camera_id, f"Recovery failed: {str(e)}")
           
        return False

    def start_camera_stream(self, camera_id: int) -> bool:
        """Start the camera stream with optimized settings"""
        try:
            if camera_id not in self.camera_streams:
                logger.error(f"Camera {camera_id} not found")
                return False

            if camera_id not in self.video_captures:
                rtsp_url = self.camera_streams[camera_id]
               
                if isinstance(rtsp_url, str) and rtsp_url.isdigit():
                    rtsp_url = int(rtsp_url)
               
                # Create capture with specific backend for better performance
                if isinstance(rtsp_url, int):
                    # For local cameras, use DirectShow on Windows
                    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_DSHOW)
                else:
                    # For RTSP streams, use FFMPEG backend
                    cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
               
                if not cap.isOpened():
                    error_msg = f"Failed to open video capture for camera {camera_id}"
                    logger.error(error_msg)
                    self._handle_camera_error(camera_id, error_msg)
                    return False
               
                # Configure capture properties
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, self.buffer_size)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.camera_width)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.camera_height)
                    cap.set(cv2.CAP_PROP_FPS, self.camera_fps)
                   
                    # Additional optimizations for better performance
                    if isinstance(rtsp_url, str):
                        # For RTSP streams
                        cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
                        cap.set(cv2.CAP_PROP_CONVERT_RGB, True)
                except Exception as e:
                    logger.warning(f"Could not set some camera properties: {e}")
               
                # Verify camera is working with multiple attempts
                success = False
                for attempt in range(3):
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None:
                        success = True
                        break
                    logger.warning(f"Camera {camera_id} initialization attempt {attempt + 1} failed")
                    time.sleep(0.5)  # Longer delay between attempts
               
                if not success:
                    error_msg = f"Could not read initial frame from camera {camera_id} after 3 attempts"
                    logger.error(error_msg)
                    self._handle_camera_error(camera_id, error_msg)
                    cap.release()
                    return False
               
                self.video_captures[camera_id] = cap
                self.frame_skip[camera_id] = 0
                logger.info(f"Successfully initialized camera {camera_id}")

            # Update status and timestamps
            self.last_frame_time[camera_id] = time.time()
            self._update_camera_status(camera_id, "running")
           
            # Start streaming thread if not already running
            if not self.stream_threads.get(camera_id, {}).get('active', False):
                import threading
                self.stream_threads[camera_id] = {
                    'active': True,
                    'thread': threading.Thread(
                        target=self._camera_stream_thread,
                        args=(camera_id,),
                        daemon=True
                    )
                }
                self.stream_threads[camera_id]['thread'].start()
                logger.info(f"Started streaming thread for camera {camera_id}")
           
            return True

        except Exception as e:
            error_msg = f"Error starting camera {camera_id}: {str(e)}"
            logger.error(error_msg)
            self._handle_camera_error(camera_id, error_msg)
            if camera_id in self.video_captures:
                try:
                    self.video_captures[camera_id].release()
                except:
                    pass
                del self.video_captures[camera_id]
            return False

    def stop_camera_stream(self, camera_id: int):
        """Stop the camera stream and cleanup resources"""
        try:
            # Stop the streaming thread
            if camera_id in self.stream_threads:
                self.stream_threads[camera_id]['active'] = False
                if self.stream_threads[camera_id].get('thread'):
                    self.stream_threads[camera_id]['thread'].join(timeout=5)
                del self.stream_threads[camera_id]
           
            # Release video capture
            if camera_id in self.video_captures:
                try:
                    self.video_captures[camera_id].release()
                except Exception as e:
                    logger.error(f"Error releasing video capture for camera {camera_id}: {e}")
                finally:
                    del self.video_captures[camera_id]
           
            # Clear buffers and tracking data
            self.frame_buffers.pop(camera_id, None)
            self.last_frame_time.pop(camera_id, None)
            self.stream_health.pop(camera_id, None)
            self.reconnection_attempts.pop(camera_id, None)
           
            logger.info(f"Stopped streaming for camera {camera_id}")
           
        except Exception as e:
            logger.error(f"Error stopping camera stream {camera_id}: {e}")

    def get_frame(self, camera_id: int) -> Optional[np.ndarray]:
        """Get the latest frame from the camera buffer with enhanced error handling"""
        try:
            if not self.active_cameras.get(camera_id, False):
                logger.warning(f"Attempted to get frame from inactive camera {camera_id}")
                return None

            # Check if camera is in error state
            if self.stream_health.get(camera_id, {}).get('status') == 'error':
                logger.warning(f"Attempted to get frame from camera {camera_id} in error state")
                return None

            # Return the latest frame from buffer
            frame = self.frame_buffers.get(camera_id)
            if frame is None:
                logger.warning(f"No frame available in buffer for camera {camera_id}")
                return None
           
            # Update last frame time
            self.last_frame_time[camera_id] = time.time()
            
            logger.debug(f"Successfully retrieved frame for camera {camera_id}, shape: {frame.shape}")
           
            return frame.copy()  # Return a copy to prevent buffer modifications
       
        except Exception as e:
            error_msg = f"Error getting frame from camera {camera_id}: {str(e)}"
            logger.error(error_msg)
            self._handle_camera_error(camera_id, error_msg)
            return None

    def activate_camera(self, camera_id: int) -> CameraStatus:
        """Activate camera with automatic face recognition"""
        if camera_id not in self.camera_streams:
            raise HTTPException(status_code=404, detail="Camera not found")
       
        try:
            # Ensure stream is running
            if not self.start_camera_stream(camera_id):
                raise HTTPException(status_code=400, detail="Failed to start camera stream")
           
            # Mark camera as active and enable face recognition automatically
            self.active_cameras[camera_id] = True
            self.face_recognition_states[camera_id] = True  # Auto-enable face recognition
           
            logger.info(f"Activated camera {camera_id} with automatic face recognition")
            return CameraStatus(status="success", camera_id=camera_id, active=True)
        except Exception as e:
            logger.error(f"Error activating camera {camera_id}: {e}")
            raise HTTPException(status_code=400, detail=str(e))

    def deactivate_camera(self, camera_id: int) -> CameraStatus:
        """Deactivate camera display"""
        if camera_id not in self.camera_streams:
            raise HTTPException(status_code=404, detail="Camera not found")
       
        # Just mark camera as inactive (display disabled)
        self.active_cameras[camera_id] = False
        self.face_recognition_states[camera_id] = False
       
        logger.info(f"Deactivated camera {camera_id}")
        return CameraStatus(status="success", camera_id=camera_id, active=False)

    def get_status(self) -> ServiceStatus:
        """Get enhanced service status including stream health"""
        return ServiceStatus(
            status="running",
            gpu_available=self.gpu_available,
            yolo_model_loaded=self.yolo_model is not None,
            known_faces_count=len(self.known_faces["names"]),
            active_cameras=self.active_cameras,
            face_recognition_states=self.face_recognition_states,
            total_cameras=len(self.camera_streams),
            stream_health=self.stream_health
        )

    def apply_clahe(self, image):
        """
        Apply Contrast Limited Adaptive Histogram Equalization (CLAHE)
        to enhance image contrast
       
        Args:
            image (numpy.ndarray): Input image
       
        Returns:
            numpy.ndarray: Contrast enhanced image
        """
        # Convert to LAB color space
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
       
        # Split the LAB image to different channels
        l, a, b = cv2.split(lab)
       
        # Apply CLAHE to L-channel
        clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
        cl = clahe.apply(l)
       
        # Merge the CLAHE enhanced L-channel with the a and b channel
        limg = cv2.merge((cl,a,b))
       
        # Convert image from LAB Color model to BGR color space
        enhanced = cv2.cvtColor(limg, cv2.COLOR_LAB2BGR)
       
        return enhanced

    def process_frame(self, frame: np.ndarray, camera_id: int) -> Tuple[np.ndarray, List[str]]:
        """Process frame with face detection and recognition"""
        try:
            if frame is None or frame.size == 0:
                return frame, []

            # Create a copy of the frame for drawing
            display_frame = frame.copy()
           
            # Skip processing if face recognition is not active
            if not self.face_recognition_states.get(camera_id, False):
                return display_frame, []

            # Resize frame for better performance while maintaining accuracy
            height, width = frame.shape[:2]
            scale_factor = min(1.0, 640 / max(width, height))
            if scale_factor < 1.0:
                small_frame = cv2.resize(frame, (0, 0), fx=scale_factor, fy=scale_factor)
            else:
                small_frame = frame
           
            rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)
            face_names = []

            # Use YOLO for face detection
            if self.yolo_model:
                try:
                    # Run YOLO detection
                    results = self.yolo_model(rgb_small_frame, verbose=False)
                   
                    # Process each detected face
                    for result in results:
                        boxes = result.boxes.cpu().numpy()
                        for box in boxes:
                            confidence = float(box.conf)
                           
                            if confidence > self.face_conf_threshold:
                                # Get face coordinates
                                x1, y1, x2, y2 = map(int, box.xyxy[0])
                               
                                # Scale coordinates back if frame was resized
                                if scale_factor < 1.0:
                                    x1, y1, x2, y2 = map(lambda x: int(x / scale_factor), [x1, y1, x2, y2])
                               
                                # Add margin to face ROI for better recognition
                                margin = 30
                                y1_margin = max(0, y1 - margin)
                                y2_margin = min(height, y2 + margin)
                                x1_margin = max(0, x1 - margin)
                                x2_margin = min(width, x2 + margin)
                               
                                # Extract face ROI
                                face_image = frame[y1_margin:y2_margin, x1_margin:x2_margin]
                               
                                if face_image.size > 0:
                                    try:
                                        # Convert to RGB for face_recognition
                                        rgb_face = cv2.cvtColor(face_image, cv2.COLOR_BGR2RGB)
                                       
                                        # Get face encoding
                                        face_encodings = face_recognition.face_encodings(rgb_face)
                                       
                                        if face_encodings:
                                            face_encoding = face_encodings[0]
                                           
                                            # Compare with known faces
                                            if len(self.known_faces["encodings"]) > 0:
                                                matches = face_recognition.compare_faces(
                                                    self.known_faces["encodings"],
                                                    face_encoding,
                                                    tolerance=0.5  # Stricter tolerance for better accuracy
                                                )
                                               
                                                face_distances = face_recognition.face_distance(
                                                    self.known_faces["encodings"],
                                                    face_encoding
                                                )
                                               
                                                name = "Unknown"
                                                color = (0, 0, 255)  # Red for unknown faces
                                                save_dir = os.path.join(UNKNOWN_FACES_DIR, f"camera_{camera_id}")
                                               
                                                # If match found
                                                if True in matches:
                                                    best_match_index = np.argmin(face_distances)
                                                    match_confidence = (1 - face_distances[best_match_index]) * 100
                                                   
                                                    if matches[best_match_index] and match_confidence > 60:  # Higher confidence threshold
                                                        name = self.known_faces["names"][best_match_index]
                                                        color = (0, 255, 0)  # Green for known faces
                                                        # Restructure save directory: camera first, then name
                                                        save_dir = os.path.join(KNOWN_FACES_DIR, f"camera_{camera_id}", name)
                                                        logger.info(f"Known face detected - Name: {name}, Confidence: {match_confidence:.2f}%")
                                            else:
                                                logger.warning("No known faces loaded for comparison")
                                                name = "Unknown"
                                                color = (0, 0, 255)
                                                save_dir = os.path.join(UNKNOWN_FACES_DIR, f"camera_{camera_id}")
                                           
                                            # Create save directory if needed
                                            os.makedirs(save_dir, exist_ok=True)
                                           
                                            # Save face image with timestamp
                                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                                            face_path = os.path.join(
                                                save_dir,
                                                f"face_{timestamp}.jpg"
                                            )
                                            
                                            # Ensure the parent directory exists
                                            os.makedirs(os.path.dirname(face_path), exist_ok=True)
                                           
                                            # Save enhanced face image
                                            enhanced_face = self.apply_clahe(face_image)
                                            cv2.imwrite(face_path, enhanced_face)
                                           
                                            # Draw detection on frame
                                            cv2.rectangle(display_frame, (x1, y1), (x2, y2), color, 2)
                                            label = f"{name} {confidence:.2f}%"
                                            cv2.putText(
                                                display_frame,
                                                label,
                                                (x1, y1 - 10),
                                                cv2.FONT_HERSHEY_DUPLEX,
                                                0.8,
                                                color,
                                                1
                                            )
                                           
                                            # Log detection
                                            face_names.append(name)
                                            self.log_recognition(name, camera_id, confidence * 100)
                                           
                                            logger.info(
                                                f"Face detected - Name: {name}, "
                                                f"Camera: {camera_id}, "
                                                f"Confidence: {confidence:.2f}%, "
                                                f"Saved to: {face_path}"
                                            )
                                   
                                    except Exception as e:
                                        logger.error(f"Error processing detected face: {e}")
                                        continue
                except Exception as e:
                    logger.error(f"Error in YOLO face detection: {e}")
                    return display_frame, face_names

            return display_frame, face_names
           
        except Exception as e:
            logger.error(f"Error in process_frame: {e}")
            return frame, []

    def log_recognition(self, name: str, camera_id: int, confidence: float = None) -> None:
        """Enhanced logging with confidence score"""
        now = datetime.now()
        log_entry = {
            'last_seen': now,
            'camera_id': camera_id,
            'date': now.strftime("%Y-%m-%d"),
            'time': now.strftime("%H:%M:%S"),
            'confidence': round(confidence, 2) if confidence is not None else None
        }
       
        self.recognition_log[name] = log_entry
        logger.info(
            f"Face recognized - Name: {name}, Camera: {camera_id}, "
            f"Time: {now}, Confidence: {log_entry['confidence']}%"
        )

    def get_recognition_log(self) -> Dict[str, Dict]:
        """Get the face recognition log"""
        return self.recognition_log

    def add_camera(self, rtsp_url: str, name: Optional[str] = None) -> CameraStatus:
        """Add a new camera to the system with pagination support"""
        try:
            # Calculate current total cameras
            total_cameras = len(self.camera_streams)
           
            # Check if maximum camera limit is reached
            if total_cameras >= self.CAMERAS_PER_PAGE * 5:  # Maximum 5 pages (30 cameras)
                raise ValueError("Maximum camera limit reached (30 cameras)")

            # Validate RTSP URL using the RTSPCamera model
            camera_model = RTSPCamera(rtsp_url=rtsp_url, name=name)
            validated_url = camera_model.rtsp_url

            # Check if URL already exists
            if any(url == validated_url for url in self.camera_streams.values()):
                raise ValueError("Camera with this URL already exists")

            # Add camera with next available ID
            camera_id = self.next_camera_id
            self.camera_streams[camera_id] = validated_url
            self.next_camera_id += 1

            # Initialize camera states
            self.active_cameras[camera_id] = False
            self.face_recognition_states[camera_id] = False

            # Update total pages
            self.update_pagination()

            # Save updated configuration
            self.save_cameras_to_db()

            # Calculate which page this camera is on
            camera_page = (camera_id - 1) // self.CAMERAS_PER_PAGE + 1

            logger.info(f"Added new camera {camera_id} with URL: {validated_url} on page {camera_page}")
            return CameraStatus(
                status="success",
                camera_id=camera_id,
                active=False,
                page=camera_page,
                total_pages=self.total_pages
            )

        except ValueError as ve:
            logger.error(f"Validation error adding camera: {ve}")
            raise HTTPException(status_code=400, detail=str(ve))
        except Exception as e:
            logger.error(f"Error adding camera with URL {rtsp_url}: {e}")
            raise HTTPException(status_code=500, detail="Failed to add camera. Please check the connection details and try again.")

    def remove_camera(self, camera_id: int) -> CameraStatus:
        """Remove a camera and reorganize remaining camera IDs with pagination support"""
        if camera_id not in self.camera_streams:
            raise HTTPException(status_code=404, detail="Camera not found")
       
        try:
            # Get the current page of the camera being removed
            current_page = (camera_id - 1) // self.CAMERAS_PER_PAGE + 1

            # Deactivate camera if active
            if self.active_cameras.get(camera_id, False):
                self.deactivate_camera(camera_id)
           
            # Remove camera from streams
            del self.camera_streams[camera_id]
           
            # Reorganize remaining camera IDs
            new_camera_streams = {}
            new_id = 1
           
            # Sort existing camera IDs and reassign them sequentially
            for old_id in sorted(self.camera_streams.keys()):
                new_camera_streams[new_id] = self.camera_streams[old_id]
                new_id += 1
           
            # Update camera streams with new IDs
            self.camera_streams = new_camera_streams
           
            # Update next_camera_id to be one more than the highest used ID
            self.next_camera_id = len(self.camera_streams) + 1
           
            # Update pagination
            self.update_pagination()
           
            # Save updated configuration
            self.save_cameras_to_db()
           
            logger.info(f"Removed camera {camera_id} from page {current_page}")
            return CameraStatus(
                status="success",
                camera_id=camera_id,
                active=False,
                page=current_page,
                total_pages=self.total_pages
            )
           
        except Exception as e:
            logger.error(f"Error removing camera {camera_id}: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def update_pagination(self):
        """Update total pages based on current number of cameras"""
        total_cameras = len(self.camera_streams)
        self.total_pages = (total_cameras + self.CAMERAS_PER_PAGE - 1) // self.CAMERAS_PER_PAGE
        if self.total_pages == 0:
            self.total_pages = 1

    def get_cameras_by_page(self, page: int = 1) -> Dict:
        """Get cameras for a specific page with enhanced error handling"""
        try:
            if page < 1 or page > self.total_pages:
                raise ValueError(f"Invalid page number. Available pages: 1 to {self.total_pages}")

            start_idx = (page - 1) * self.CAMERAS_PER_PAGE
            end_idx = start_idx + self.CAMERAS_PER_PAGE

            # Get cameras for the requested page
            page_cameras = {}
            sorted_cameras = sorted(list(self.camera_streams.items()))  # Convert to list before sorting
            for i in range(start_idx, min(end_idx, len(sorted_cameras))):
                camera_id, url = sorted_cameras[i]
                status = self.get_camera_status(camera_id)
                page_cameras[camera_id] = {
                    'url': url,
                    'active': self.active_cameras.get(camera_id, False),
                    'face_recognition_active': self.face_recognition_states.get(camera_id, False),
                    'status': status.get('status', 'unknown'),
                    'error_message': status.get('error_message', None),
                    'connection_status': status.get('connection_status', 'disconnected')
                }

            return {
                'cameras': page_cameras,
                'current_page': page,
                'total_pages': self.total_pages,
                'cameras_per_page': self.CAMERAS_PER_PAGE,
                'total_cameras': len(self.camera_streams)
            }
        except ValueError as ve:
            logger.error(f"Page error: {str(ve)}")
            raise
        except Exception as e:
            logger.error(f"Error getting cameras by page: {str(e)}")
            return {
                'cameras': {},
                'current_page': 1,
                'total_pages': 1,
                'cameras_per_page': self.CAMERAS_PER_PAGE,
                'total_cameras': 0,
                'error': str(e)
            }

    def get_camera_health(self, camera_id: int) -> Dict:
        """Get detailed camera status including face detection"""
        try:
            if camera_id not in self.camera_streams:
                raise HTTPException(status_code=404, detail="Camera not found")
           
            # Get basic camera status
            is_active = self.active_cameras.get(camera_id, False)
            face_detection_active = self.face_recognition_states.get(camera_id, False)
           
            # Get stream health metrics
            stream_health = self.stream_health.get(camera_id, {})
            last_frame_age = stream_health.get('last_frame_age', 0)
            reconnection_attempts = stream_health.get('reconnection_attempts', 0)
            stream_status = stream_health.get('status', 'unknown')
           
            # Get recent detections for this camera
            recent_detections = []
            current_time = time.time()
            for name, log_entry in self.recognition_log.items():
                if log_entry['camera_id'] == camera_id:
                    detection_time = datetime.strptime(
                        f"{log_entry['date']} {log_entry['time']}",
                        "%Y-%m-%d %H:%M:%S"
                    )
                    age = current_time - detection_time.timestamp()
                    if age < 300:  # Show detections from last 5 minutes
                        recent_detections.append({
                            'time': log_entry['time'],
                            'confidence': log_entry.get('confidence', None)
                        })
           
            # Sort recent detections by time
            recent_detections.sort(key=lambda x: x['time'], reverse=True)
           
            return {
                'camera_id': camera_id,
                'active': is_active,
                'face_detection_active': face_detection_active,
                'stream_status': stream_status,
                'last_frame_age': last_frame_age,
                'reconnection_attempts': reconnection_attempts,
                'recent_detections': recent_detections[:5],  # Return last 5 detections
                'error_count': self.error_counts.get(camera_id, 0)
            }
       
        except HTTPException as he:
            raise he
        except Exception as e:
            logger.error(f"Error getting camera status: {e}")
            raise HTTPException(status_code=500, detail=str(e))

# Initialize FastAPI app and camera service
app = FastAPI()
camera_service = CameraService()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Dependency to get camera service
def get_camera_service() -> CameraService:
    return camera_service

# Create router for camera endpoints
camera_router = APIRouter(prefix="/api/camera")

# Add all the camera endpoints to the router
@camera_router.post("/add", response_model=CameraStatus)
async def add_camera(
    camera: RTSPCamera,
    service: CameraService = Depends(get_camera_service)
) -> CameraStatus:
    """Add a new RTSP camera"""
    try:
        return service.add_camera(camera.rtsp_url, camera.name)
    except HTTPException as he:
        # Convert error to user-friendly message
        error_msg = he.detail
        if "Input should be a valid string" in str(error_msg):
            error_msg = "Invalid camera URL format. Please check the URL and try again."
        return JSONResponse(
            status_code=he.status_code,
            content={"detail": error_msg}
        )
    except ValueError as ve:
        # Handle validation errors
        return JSONResponse(
            status_code=400,
            content={"detail": str(ve)}
        )
    except Exception as e:
        # Handle unexpected errors
        return JSONResponse(
            status_code=500,
            content={"detail": "Failed to add camera. Please check the connection details and try again."}
        )

@camera_router.post("/{camera_id}/remove", response_model=CameraStatus)
async def remove_camera(
    camera_id: int,
    service: CameraService = Depends(get_camera_service)
) -> CameraStatus:
    """Remove a camera"""
    try:
        result = service.remove_camera(camera_id)
        logger.info(f"Successfully removed camera {camera_id}")
        return result
    except HTTPException as he:
        logger.error(f"HTTP error removing camera {camera_id}: {he.detail}")
        return JSONResponse(
            status_code=he.status_code,
            content={"status": "error", "detail": he.detail}
        )
    except Exception as e:
        logger.error(f"Unexpected error removing camera {camera_id}: {str(e)}")
        return JSONResponse(
            status_code=500,
            content={"status": "error", "detail": f"Failed to remove camera: {str(e)}"}
        )

@camera_router.post("/{camera_id}/activate", response_model=CameraStatus)
async def activate_camera(
    camera_id: int,
    service: CameraService = Depends(get_camera_service)
) -> CameraStatus:
    """Activate a camera"""
    return service.activate_camera(camera_id)

@camera_router.post("/{camera_id}/deactivate", response_model=CameraStatus)
async def deactivate_camera(
    camera_id: int,
    service: CameraService = Depends(get_camera_service)
) -> CameraStatus:
    """Deactivate a camera"""
    return service.deactivate_camera(camera_id)

@camera_router.post("/verify", response_model=dict)
async def verify_face(
    image: UploadFile = File(...),
    service: CameraService = Depends(get_camera_service)
):
    """Verify a face in an image"""
    try:
        contents = await image.read()
        nparr = np.frombuffer(contents, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
       
        # Use YOLO for face detection
        if service.yolo_model:
            results = service.yolo_model(frame)
            face_locations = []
            for result in results:
                boxes = result.boxes.cpu().numpy()
                for box in boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    face_locations.append((y1, x2, y2, x1))
        else:
            face_locations = face_recognition.face_locations(frame)
       
        if not face_locations:
            return {"match": False, "message": "No face detected"}
       
        face_encoding = face_recognition.face_encodings(frame, face_locations)[0]
        matches = face_recognition.compare_faces(service.known_faces["encodings"], face_encoding)
       
        if True in matches:
            face_distances = face_recognition.face_distance(service.known_faces["encodings"], face_encoding)
            best_match_index = np.argmin(face_distances)
            if matches[best_match_index]:
                name = service.known_faces["names"][best_match_index]
                confidence = (1 - face_distances[best_match_index]) * 100
                return {
                    "match": True,
                    "name": name,
                    "confidence": confidence
                }
       
        return {"match": False, "message": "No match found"}
       
    except Exception as e:
        logger.error(f"Error in verify_face: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@camera_router.post("/detect", response_model=dict)
async def detect_faces(
    image: UploadFile = File(...),
    service: CameraService = Depends(get_camera_service)
):
    """Detect faces in an image"""
    try:
        contents = await image.read()
        nparr = np.frombuffer(contents, np.uint8)
        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
       
        # Use YOLO for face detection
        if service.yolo_model:
            results = service.yolo_model(frame)
            face_locations = []
            for result in results:
                boxes = result.boxes.cpu().numpy()
                for box in boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    face_locations.append({
                        "top": y1,
                        "right": x2,
                        "bottom": y2,
                        "left": x1
                    })
        else:
            face_locations = [
                {
                    "top": top,
                    "right": right,
                    "bottom": bottom,
                    "left": left
                }
                for top, right, bottom, left in face_recognition.face_locations(frame)
            ]
       
        return {"face_locations": face_locations}
       
    except Exception as e:
        logger.error(f"Error in detect_faces: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@camera_router.post("/compare", response_model=dict)
async def compare_faces(
    probe: UploadFile = File(...),
    gallery: UploadFile = File(...),
    service: CameraService = Depends(get_camera_service)
):
    """Compare faces in two images"""
    try:
        # Read probe image
        probe_contents = await probe.read()
        probe_nparr = np.frombuffer(probe_contents, np.uint8)
        probe_frame = cv2.imdecode(probe_nparr, cv2.IMREAD_COLOR)
       
        # Read gallery image
        gallery_contents = await gallery.read()
        gallery_nparr = np.frombuffer(gallery_contents, np.uint8)
        gallery_frame = cv2.imdecode(gallery_nparr, cv2.IMREAD_COLOR)
       
        # Detect and encode faces
        probe_encoding = face_recognition.face_encodings(probe_frame)[0]
        gallery_encoding = face_recognition.face_encodings(gallery_frame)[0]
       
        # Compare faces
        matches = face_recognition.compare_faces([probe_encoding], gallery_encoding)
        face_distance = face_recognition.face_distance([probe_encoding], gallery_encoding)[0]
        confidence = (1 - face_distance) * 100
       
        return {
            "is_match": matches[0],
            "confidence": confidence
        }
       
    except Exception as e:
        logger.error(f"Error in compare_faces: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@camera_router.get("/recognition_log", response_model=Dict[str, Dict])
async def get_recognition_log(
    service: CameraService = Depends(get_camera_service)
) -> Dict[str, Dict]:
    """Get the face recognition log"""
    return service.get_recognition_log()

@camera_router.get("/{camera_id}/frame")
async def get_frame(
    camera_id: int,
    service: CameraService = Depends(get_camera_service)
) -> Response:
    """Get the current frame from a camera with enhanced error handling"""
    try:
        # Check if camera exists and is active
        if camera_id not in service.camera_streams:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "message": "Camera not found",
                    "display_message": "Camera is not available"
                }
            )
       
        if not service.active_cameras.get(camera_id, False):
            return JSONResponse(
                status_code=400,
                content={
                    "status": "error",
                    "message": "Camera is not active",
                    "display_message": "Camera is currently inactive"
                }
            )
       
        # Check camera health
        health = service.get_camera_status(camera_id)
        if health['status'] == 'error' or health['status'] == 'failed':
            return JSONResponse(
                status_code=503,
                content={
                    "status": "error",
                    "message": f"Camera is {health['status']}: {health.get('error_message', 'Unknown error')}",
                    "display_message": "Camera is temporarily unavailable. Please try again later."
                }
            )
       
        # Get frame with timeout
        frame = service.get_frame(camera_id)
        if frame is None:
            return JSONResponse(
                status_code=404,
                content={
                    "status": "error",
                    "message": "No frame available",
                    "display_message": "Camera feed is not available"
                }
            )
       
        # Encode frame as JPEG with optimized settings
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 85]  # Balanced quality
        _, buffer = cv2.imencode('.jpg', frame, encode_params)
        frame_bytes = buffer.tobytes()
       
        # Return frame with appropriate headers
        return Response(
            content=frame_bytes,
            media_type="image/jpeg",
            headers={
                "X-Frame-Status": "ok",
                "X-Camera-ID": str(camera_id),
                "X-Frame-Time": str(time.time())
            }
        )
   
    except Exception as e:
        error_msg = f"Error getting frame from camera {camera_id}: {str(e)}"
        logger.error(error_msg)
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": error_msg,
                "display_message": "Unable to connect to camera. Please check your connection."
            }
        )

@camera_router.get("/list/{page}", response_model=Dict)
async def get_cameras(
    page: int = 1,
    service: CameraService = Depends(get_camera_service)
) -> Dict:
    """Get cameras for a specific page"""
    try:
        return service.get_cameras_by_page(page)
    except ValueError as ve:
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@camera_router.get("/{camera_id}/status")
async def get_camera_status(
    camera_id: int,
    service: CameraService = Depends(get_camera_service)
) -> Dict:
    """Get detailed camera status including face detection"""
    try:
        if camera_id not in service.camera_streams:
            raise HTTPException(status_code=404, detail="Camera not found")
       
        # Get basic camera status
        is_active = service.active_cameras.get(camera_id, False)
        face_detection_active = service.face_recognition_states.get(camera_id, False)
       
        # Get stream health metrics
        stream_health = service.stream_health.get(camera_id, {})
        last_frame_age = stream_health.get('last_frame_age', 0)
        reconnection_attempts = stream_health.get('reconnection_attempts', 0)
        stream_status = stream_health.get('status', 'unknown')
       
        # Get recent detections for this camera
        recent_detections = []
        current_time = time.time()
        for name, log_entry in service.recognition_log.items():
            if log_entry['camera_id'] == camera_id:
                detection_time = datetime.strptime(
                    f"{log_entry['date']} {log_entry['time']}",
                    "%Y-%m-%d %H:%M:%S"
                )
                age = current_time - detection_time.timestamp()
                if age < 300:  # Show detections from last 5 minutes
                    recent_detections.append({
                        'time': log_entry['time'],
                        'confidence': log_entry.get('confidence', None)
                    })
       
        # Sort recent detections by time
        recent_detections.sort(key=lambda x: x['time'], reverse=True)
       
        return {
            'camera_id': camera_id,
            'active': is_active,
            'face_detection_active': face_detection_active,
            'stream_status': stream_status,
            'last_frame_age': last_frame_age,
            'reconnection_attempts': reconnection_attempts,
            'recent_detections': recent_detections[:5],  # Return last 5 detections
            'error_count': service.error_counts.get(camera_id, 0)
        }
       
    except HTTPException as he:
        raise he
    except Exception as e:
        logger.error(f"Error getting camera status: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@camera_router.get("/{camera_id}/health")
async def get_camera_health(
    camera_id: int,
    service: CameraService = Depends(get_camera_service)
) -> Dict:
    """Get detailed camera health status"""
    return service.get_camera_status(camera_id)

@camera_router.post("/{camera_id}/recover")
async def recover_camera(
    camera_id: int,
    service: CameraService = Depends(get_camera_service)
) -> Dict:
    """Attempt to recover a failed camera"""
    success = await service.attempt_camera_recovery(camera_id)
    return {
        "success": success,
        "status": service.get_camera_status(camera_id)
    }

# Add the camera router to the app
app.include_router(camera_router)

# Add the status endpoint directly to the app
@app.get("/api/status", response_model=ServiceStatus)
async def get_status(service: CameraService = Depends(get_camera_service)) -> ServiceStatus:
    """Get service status"""
    return service.get_status()

def int_to_ip(num):
    """Convert integer to IP address string."""
    return '.'.join(str((num >> (8 * i)) & 255) for i in reversed(range(4)))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
