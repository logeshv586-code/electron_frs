from PyQt6.QtCore import QThread, pyqtSignal
import cv2
import time
import logging
import threading
from PyQt6.QtGui import QImage
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from typing import Dict, List, Optional, Any
import os
import uuid
import json
import numpy as np
from datetime import datetime
import face_recognition
import shutil
from fastapi import UploadFile
import glob
from ultralytics import YOLO
import torch
import base64
import tempfile
import asyncio

# Configure logging
logging.basicConfig(level=logging.INFO, 
                   format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Configure base directory and paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
logger.info(f"Base directory: {BASE_DIR}")
logger.info(f"Data directory: {DATA_DIR}")

# Initialize YOLO model
try:
    # Try different possible locations for YOLO models
    possible_paths = [
        os.path.join(BASE_DIR, "yolov8n-face.pt"),  # Face-specific model in root
        os.path.join(BASE_DIR, "backend_face", "yolov8n-face.pt"),  # Face-specific in backend_face
        os.path.join(BASE_DIR, "yolov11n-face.pt"),  # Alternative face models
        os.path.join(BASE_DIR, "yolov11l-face.pt"),
        os.path.join(BASE_DIR, "backend_face", "yolov8n.pt"),  # General YOLO in backend_face
        os.path.join(BASE_DIR, "yolov8n.pt")  # General YOLO in root
    ]

    model_path = None
    for path in possible_paths:
        if os.path.exists(path):
            model_path = path
            logger.info(f"Found YOLO model at: {model_path}")
            break

    if model_path is None:
        logger.warning(f"No YOLO model found in any of these locations:")
        for path in possible_paths:
            logger.warning(f"  - {path}")
        logger.warning("Will use face_recognition library only")

    if model_path and os.path.exists(model_path):
        YOLO_MODEL = YOLO(model_path)
        # Check if this is a general YOLO model (not face-specific)
        if "face" not in os.path.basename(model_path):
            logger.warning("Using general YOLO model - will prioritize face_recognition library")
            USE_FACE_RECOGNITION_FALLBACK = True
        else:
            logger.info("Using face-specific YOLO model")
            USE_FACE_RECOGNITION_FALLBACK = False
        logger.info(f"YOLO model loaded successfully from: {model_path}")
    else:
        logger.info("No YOLO model found - using face_recognition library only")
        YOLO_MODEL = None
        USE_FACE_RECOGNITION_FALLBACK = True
except Exception as e:
    logger.error(f"Error loading YOLO model: {e}")
    YOLO_MODEL = None
    USE_FACE_RECOGNITION_FALLBACK = True

# Check for GPU availability
GPU_AVAILABLE = torch.cuda.is_available()
if GPU_AVAILABLE:
    logger.info(f"Using GPU: {torch.cuda.get_device_name(0)}")
    torch.cuda.set_device(0)
else:
    logger.info("No GPU available. Using CPU.")

class PersonTrackingInfo:
    def __init__(self, name):
        self.name = name
        self.first_seen = datetime.now()
        self.last_seen = datetime.now()
        self.is_present = True
        self.total_appearances = 1
        self.details = {}

class VideoThread(QThread):
    frame_ready = pyqtSignal(object)
    face_detected = pyqtSignal(dict)
    person_entered = pyqtSignal(dict)
    person_exited = pyqtSignal(dict)
    error_occurred = pyqtSignal(str)

    def __init__(self, rtsp_url):
        super().__init__()
        self.rtsp_url = rtsp_url
        self.running = False
        self.lock = threading.Lock()
        self.logger = logging.getLogger(__name__)
        self.known_faces = {"encodings": [], "names": []}
        self.person_tracking = {}  # Track person presence and timing
        self.person_details = {}   # Store person details from data directory
        self.absence_threshold = 30  # Seconds before considering a person has exited
        self.last_check_time = datetime.now()
        self.check_interval = 1    # Check for exits every second
        self.load_known_faces()
        self.load_person_details()

    def load_known_faces(self):
        """Load known faces from data directory"""
        try:
            if not os.path.exists(DATA_DIR):
                os.makedirs(DATA_DIR)
                self.logger.warning(f"Created data directory at: {DATA_DIR}")
                return

            known_face_encodings = []
            known_face_names = []

            # List all person directories
            person_dirs = [d for d in os.listdir(DATA_DIR) 
                         if os.path.isdir(os.path.join(DATA_DIR, d))]

            self.logger.info(f"Found {len(person_dirs)} person directories")

            for person_name in person_dirs:
                person_folder = os.path.join(DATA_DIR, person_name)
                image_files = [f for f in os.listdir(person_folder) 
                             if f.lower().endswith(('jpg', 'jpeg', 'png'))]

                self.logger.info(f"Processing {len(image_files)} images for {person_name}")

                for image_file in image_files:
                    try:
                        image_path = os.path.join(person_folder, image_file)
                        image = face_recognition.load_image_file(image_path)

                        # Detect faces in image
                        face_locations = face_recognition.face_locations(image)
                        if not face_locations:
                            self.logger.warning(f"No face found in {image_file}")
                            continue

                        # Get face encodings
                        face_encodings = face_recognition.face_encodings(image, face_locations)
                        if not face_encodings:
                            self.logger.warning(f"Could not encode face in {image_file}")
                            continue

                        # Add all detected faces
                        for encoding in face_encodings:
                            known_face_encodings.append(encoding)
                            known_face_names.append(person_name)

                    except Exception as e:
                        self.logger.error(f"Error processing {image_file}: {e}")
                        continue

            self.known_faces = {
                "encodings": known_face_encodings,
                "names": known_face_names
            }

            self.logger.info(f"Successfully loaded {len(known_face_names)} face encodings for {len(set(known_face_names))} unique persons")
            for name in set(known_face_names):
                count = known_face_names.count(name)
                self.logger.info(f"  - {name}: {count} face encodings")

        except Exception as e:
            self.logger.error(f"Error loading known faces: {e}")
            self.known_faces = {"encodings": [], "names": []}

    def load_person_details(self):
        """Load person details from data directory"""
        try:
            for person_name in os.listdir(DATA_DIR):
                person_path = os.path.join(DATA_DIR, person_name)
                if os.path.isdir(person_path):
                    # Look for a details.json file
                    details_file = os.path.join(person_path, "details.json")
                    if os.path.exists(details_file):
                        with open(details_file, 'r') as f:
                            self.person_details[person_name] = json.load(f)
                    else:
                        # Create basic details from directory name
                        self.person_details[person_name] = {
                            "name": person_name,
                            "id": str(uuid.uuid4()),
                            "registered": datetime.now().isoformat()
                        }
            
            self.logger.info(f"Loaded details for {len(self.person_details)} persons")
        except Exception as e:
            self.logger.error(f"Error loading person details: {e}")

    def check_exits(self):
        """Check for people who have exited based on absence duration"""
        current_time = datetime.now()
        
        if (current_time - self.last_check_time).total_seconds() < self.check_interval:
            return
        
        self.last_check_time = current_time
        
        for name, info in self.person_tracking.items():
            if info.is_present:
                time_since_last_seen = (current_time - info.last_seen).total_seconds()
                if time_since_last_seen > self.absence_threshold:
                    info.is_present = False
                    # Emit person exited event
                    self.person_exited.emit({
                        'name': name,
                        'exit_time': current_time.isoformat(),
                        'duration': (current_time - info.first_seen).total_seconds(),
                        'details': self.person_details.get(name, {})
                    })

    def update_person_tracking(self, name, confidence):
        """Update person tracking information"""
        current_time = datetime.now()
        
        if name == "Unknown":
            return
            
        if name not in self.person_tracking:
            # New person detected
            self.person_tracking[name] = PersonTrackingInfo(name)
            # Emit person entered event
            self.person_entered.emit({
                'name': name,
                'entry_time': current_time.isoformat(),
                'confidence': confidence,
                'details': self.person_details.get(name, {})
            })
        else:
            info = self.person_tracking[name]
            info.last_seen = current_time
            
            if not info.is_present:
                # Person has re-entered
                info.is_present = True
                info.first_seen = current_time
                info.total_appearances += 1
                self.person_entered.emit({
                    'name': name,
                    'entry_time': current_time.isoformat(),
                    'confidence': confidence,
                    'details': self.person_details.get(name, {}),
                    'appearance_count': info.total_appearances
                })

    def process_frame(self, frame):
        """Process frame for face detection and recognition"""
        try:
            # Create a copy of the frame for drawing
            display_frame = frame.copy()
            
            # Convert BGR to RGB for face recognition
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            
            # Detect faces in the frame using improved detection
            face_locations = []

            # Use face_recognition as primary method for better accuracy
            try:
                face_locations = face_recognition.face_locations(rgb_frame, model="hog")
                logger.debug(f"face_recognition detected {len(face_locations)} faces in real-time")
            except Exception as e:
                logger.error(f"Error with face_recognition in real-time: {e}")
                face_locations = []

            # If no faces found and we have YOLO, try as backup
            if not face_locations and YOLO_MODEL is not None:
                try:
                    results_yolo = YOLO_MODEL(rgb_frame, conf=0.3)
                    for result in results_yolo:
                        if hasattr(result, 'boxes') and result.boxes is not None:
                            boxes = result.boxes.cpu().numpy()
                            for box in boxes:
                                # For general YOLO, look for person class (class 0)
                                if hasattr(box, 'cls') and int(box.cls[0]) == 0:  # Person class
                                    if box.conf[0] > 0.3:
                                        x1, y1, x2, y2 = map(int, box.xyxy[0])
                                        # Convert person detection to face region (upper portion)
                                        height = y2 - y1
                                        face_y1 = y1
                                        face_y2 = y1 + int(height * 0.3)  # Top 30% for face
                                        face_locations.append((face_y1, x2, face_y2, x1))
                    logger.debug(f"YOLO detected {len(face_locations)} person regions in real-time")
                except Exception as e:
                    logger.error(f"Error with YOLO detection in real-time: {e}")
            
            # Check for exits before processing new detections
            self.check_exits()
            
            # If no faces found, return original frame
            if not face_locations:
                return display_frame, []
            
            # Get face encodings
            face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
            
            annotations = []
            
            # Process each detected face
            for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
                name = "Unknown"
                confidence = 0.0
                face_details = {}
                
                # Expand face detection area to reduce zoom-in effect
                margin = 0.3  # 30% margin around detected face
                height = bottom - top
                width = right - left
                
                # Calculate expanded face region
                expanded_top = max(0, int(top - height * margin))
                expanded_bottom = min(frame.shape[0], int(bottom + height * margin))
                expanded_left = max(0, int(left - width * margin))
                expanded_right = min(frame.shape[1], int(right + width * margin))
                
                # Extract face image with margin
                face_image = frame[expanded_top:expanded_bottom, expanded_left:expanded_right]
                
                # Resize face image to a consistent size while maintaining aspect ratio
                if face_image.size > 0:
                    target_width = 300
                    aspect_ratio = face_image.shape[1] / face_image.shape[0]
                    target_height = int(target_width / aspect_ratio)
                    face_image = cv2.resize(face_image, (target_width, target_height), interpolation=cv2.INTER_AREA)
                
                if len(self.known_faces["encodings"]) > 0:
                    # Compare with known faces
                    matches = face_recognition.compare_faces(
                        self.known_faces["encodings"],
                        face_encoding,
                        tolerance=0.55
                    )
                    
                    if True in matches:
                        # Calculate face distances
                        face_distances = face_recognition.face_distance(
                            self.known_faces["encodings"],
                            face_encoding
                        )
                        best_match_index = np.argmin(face_distances)
                        if matches[best_match_index]:
                            name = self.known_faces["names"][best_match_index]
                            confidence = (1 - face_distances[best_match_index]) * 100
                            
                            # Get person details from loaded data
                            if name in self.person_details:
                                face_details = self.person_details[name]
                                # Add encoding information
                                face_details['face_encoding'] = face_encoding.tolist()
                                face_details['face_distance'] = float(face_distances[best_match_index])
                                face_details['face_image'] = face_image
                                
                            # Update tracking for recognized person
                            self.update_person_tracking(name, confidence)
                
                # Add annotation with additional details
                person_details = face_details if name != "Unknown" else {}
                tracking_info = self.person_tracking.get(name) if name != "Unknown" else None
                
                annotation = {
                    'box': (expanded_left, expanded_top, expanded_right - expanded_left, expanded_bottom - expanded_top),
                    'name': name,
                    'confidence': confidence,
                    'face_image': face_image if face_image.size > 0 else None,
                    'details': person_details,
                    'tracking': {
                        'first_seen': tracking_info.first_seen.isoformat() if tracking_info else None,
                        'last_seen': tracking_info.last_seen.isoformat() if tracking_info else None,
                        'total_appearances': tracking_info.total_appearances if tracking_info else 0,
                        'is_present': tracking_info.is_present if tracking_info else False
                    } if tracking_info else None
                }
                annotations.append(annotation)
                
                # Draw on frame
                color = (0, 255, 0) if name != "Unknown" else (0, 0, 255)
                
                # Draw rectangle around expanded region
                cv2.rectangle(display_frame, 
                            (expanded_left, expanded_top), 
                            (expanded_right, expanded_bottom), 
                            color, 2)
                
                # Draw label
                label = f"{name} ({confidence:.1f}%)"
                (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2)
                cv2.rectangle(display_frame, 
                            (expanded_left, expanded_top - label_h - 10), 
                            (expanded_left + label_w, expanded_top), 
                            color, -1)
                cv2.putText(display_frame, label, 
                          (expanded_left, expanded_top - 5),
                          cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2)
            
            return display_frame, annotations
            
        except Exception as e:
            self.logger.error(f"Error processing frame: {e}")
            return frame, []

    def run(self):
        self.running = True
        retry_count = 0
        max_retries = 3

        while retry_count < max_retries and self.running:
            try:
                # Initialize capture with FFMPEG backend
                self.capture = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
                self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 3)

                if not self.capture.isOpened():
                    raise Exception(f"Failed to open RTSP stream: {self.rtsp_url}")

                self.logger.info(f"Successfully connected to {self.rtsp_url}")

                while self.running:
                    with self.lock:
                        ret, frame = self.capture.read()
                        if ret:
                            # Process frame for face detection and recognition
                            processed_frame, annotations = self.process_frame(frame)
                            
                            # Emit detected faces
                            if annotations:
                                self.face_detected.emit({
                                    'timestamp': datetime.now().isoformat(),
                                    'detections': annotations
                                })
                            
                            # Convert BGR to RGB for display
                            rgb_frame = cv2.cvtColor(processed_frame, cv2.COLOR_BGR2RGB)
                            self.frame_ready.emit(rgb_frame)
                        else:
                            self.logger.warning("Failed to read frame")
                            break

                if not self.running:
                    break

                retry_count += 1
                if retry_count < max_retries:
                    self.logger.info(f"Attempting to reconnect... ({retry_count + 1}/{max_retries})")
                    time.sleep(2)

            except Exception as e:
                self.logger.error(f"Error in video thread: {str(e)}")
                self.error_occurred.emit(str(e))
                retry_count += 1
                if retry_count < max_retries:
                    time.sleep(2)

        if retry_count >= max_retries:
            self.error_occurred.emit("Failed to connect to camera after multiple attempts")

    def stop(self):
        """Stop the video capture and release resources"""
        self.running = False
        try:
            with self.lock:
                if hasattr(self, 'capture') and self.capture.isOpened():
                    self.capture.release()
                    self.logger.info("Video capture released successfully")
        except Exception as e:
            self.logger.error(f"Error releasing video capture: {e}")

        cv2.destroyAllWindows()
        self.logger.info("All windows closed")

app = FastAPI()

# Storage for active processing tasks and uploaded files
TASKS = {}
UPLOADED_FILES = {}  # Store uploaded files in memory

class ProcessRequest(BaseModel):
    video_id: str
    options: Dict[str, Any]

class TaskStatus(BaseModel):
    task_id: str
    status: str  # "pending", "processing", "completed", "failed"
    progress: float  # 0-100
    message: Optional[str] = None
    created_at: datetime
    updated_at: datetime

def process_video_task(task_id: str, video_id: str, options: Dict[str, Any]):
    """Background task for video processing"""
    temp_path = None
    cap = None
    try:
        # Check if task exists and is in valid state
        if task_id not in TASKS:
            logger.error(f"Task {task_id} not found")
            return
            
        task = TASKS[task_id]
        if task["status"] in ["completed", "failed", "cancelled"]:
            logger.warning(f"Task {task_id} already in final state: {task['status']}")
            return
        
        # Update task status to processing
        TASKS[task_id]["status"] = "processing"
        TASKS[task_id]["progress"] = 0
        TASKS[task_id]["message"] = "Starting video processing"
        TASKS[task_id]["updated_at"] = datetime.now()
        
        # Get video data from memory
        if video_id not in UPLOADED_FILES:
            raise Exception(f"Video data not found: {video_id}")
        
        video_data = UPLOADED_FILES[video_id]["data"]
        
        # Create temporary file for processing
        with tempfile.NamedTemporaryFile(suffix=UPLOADED_FILES[video_id]["extension"], delete=False) as temp_file:
            temp_file.write(video_data)
            temp_path = temp_file.name
        
        # Open video
        cap = cv2.VideoCapture(temp_path)
        if not cap.isOpened():
            raise Exception(f"Failed to open video")
        
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        # Check if task was cancelled before processing
        if task_id not in TASKS or TASKS[task_id]["status"] == "cancelled":
            return
            
        # Process options
        detect_faces = options.get("detect_faces", False)
        
        # Load known faces for recognition
        known_faces = {"encodings": [], "names": [], "confidence_threshold": 0.75}
        if detect_faces:
            try:
                if not os.path.exists(DATA_DIR):
                    os.makedirs(DATA_DIR)
                    logger.warning(f"Created data directory: {DATA_DIR}")

                logger.info(f"Loading known faces from: {DATA_DIR}")

                # Process multiple images per person for better recognition
                for person_name in os.listdir(DATA_DIR):
                    person_path = os.path.join(DATA_DIR, person_name)
                    if os.path.isdir(person_path) and person_name != "gallery":
                        image_files = [f for f in os.listdir(person_path)
                                     if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
                        logger.info(f"Processing {len(image_files)} images for {person_name}")

                        # Process first 3 images for each person
                        processed_count = 0
                        for img_file in image_files[:3]:
                            try:
                                image_path = os.path.join(person_path, img_file)
                                image = face_recognition.load_image_file(image_path)
                                if image is None:
                                    logger.warning(f"  ? Could not load image: {img_file}")
                                    continue
                                face_locations = face_recognition.face_locations(image)

                                if face_locations:
                                    encodings = face_recognition.face_encodings(image, face_locations)
                                    if encodings:
                                        known_faces["encodings"].append(encodings[0])
                                        known_faces["names"].append(person_name)
                                        processed_count += 1
                                        logger.debug(f"  ? Processed {img_file}")
                                    else:
                                        logger.warning(f"  ? No encodings for {img_file}")
                                else:
                                    logger.warning(f"  ? No face detected in {img_file}")
                            except Exception as e:
                                logger.error(f"  ? Error processing {img_file}: {e}")

                        logger.info(f"  Successfully processed {processed_count} images for {person_name}")

                logger.info(f"Total known faces loaded: {len(known_faces['encodings'])} from {len(set(known_faces['names']))} persons")
                for name in set(known_faces["names"]):
                    count = known_faces["names"].count(name)
                    logger.info(f"  - {name}: {count} encodings")

            except Exception as e:
                logger.error(f"Error loading known faces: {str(e)}")
                raise
        
        # Track processing start time
        start_time = datetime.now()

        # Results storage
        results = {
            "video_id": video_id,
            "task_id": task_id,
            "processed_frames": 0,
            "total_frames": total_frames,
            "fps": fps,
            "face_detections": [] if detect_faces else None,
            "person_tracking": {},
            "person_appearances": {}  # New: Store each appearance interval
        }
        
        # Process frames
        frame_count = 0
        last_progress_update = 0
        current_appearances = {}  # Track current appearance intervals
        
        while True:
            # Check if task still exists and is not cancelled
            if task_id not in TASKS or TASKS[task_id]["status"] == "cancelled":
                logger.info(f"Task {task_id} was cancelled or deleted")
                break
                
            ret, frame = cap.read()
            if not ret:
                break
                
            frame_count += 1
            frame_time = frame_count / fps  # Time in seconds
            
            # Skip even frames for faster processing (process only odd frames)
            if frame_count % 2 == 0:
                logger.debug(f"Skipping even frame {frame_count}")
                continue
            logger.debug(f"Processing odd frame {frame_count}")
            
            # Update progress more frequently (every 10 frames)
            if frame_count - last_progress_update >= 10:
                progress = min(100, (frame_count / total_frames) * 100)
                if task_id in TASKS:  # Check if task still exists
                    TASKS[task_id]["progress"] = progress
                    TASKS[task_id]["updated_at"] = datetime.now()
                    TASKS[task_id]["message"] = f"Processing frame {frame_count}/{total_frames}"
                last_progress_update = frame_count
            
            # Process face detection
            if detect_faces:
                # Convert frame to RGB for face detection
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                face_locations = []

                # Use face_recognition as primary method for better accuracy
                if USE_FACE_RECOGNITION_FALLBACK or YOLO_MODEL is None:
                    # Use face_recognition library for more accurate face detection
                    try:
                        face_locations = face_recognition.face_locations(rgb_frame, model="hog")
                        logger.debug(f"face_recognition detected {len(face_locations)} faces")
                    except Exception as e:
                        logger.error(f"Error with face_recognition: {e}")
                        face_locations = []

                # If face_recognition didn't find faces and we have YOLO, try YOLO as backup
                if not face_locations and YOLO_MODEL is not None:
                    try:
                        # Detect faces using YOLO (for general object detection)
                        results_yolo = YOLO_MODEL(rgb_frame, conf=0.3)

                        for result in results_yolo:
                            if hasattr(result, 'boxes') and result.boxes is not None:
                                boxes = result.boxes.cpu().numpy()
                                for box in boxes:
                                    # For general YOLO, look for person class (class 0)
                                    if hasattr(box, 'cls') and int(box.cls[0]) == 0:  # Person class
                                        if box.conf[0] > 0.3:
                                            x1, y1, x2, y2 = map(int, box.xyxy[0])
                                            # Convert person detection to face region (upper portion)
                                            height = y2 - y1
                                            face_y1 = y1
                                            face_y2 = y1 + int(height * 0.3)  # Top 30% for face
                                            face_locations.append((face_y1, x2, face_y2, x1))
                        logger.debug(f"YOLO detected {len(face_locations)} person regions")
                    except Exception as e:
                        logger.error(f"Error with YOLO detection: {e}")
                        face_locations = []
                
                if face_locations:
                    logger.debug(f"Frame {frame_count}: Found {len(face_locations)} face locations")
                    # Get face encodings for detected faces
                    face_encodings = face_recognition.face_encodings(rgb_frame, face_locations)
                    logger.debug(f"Frame {frame_count}: Generated {len(face_encodings)} face encodings")
                    
                    # Track detected names in this frame
                    detected_names = set()
                    
                    # Store face detection results
                    face_data = []
                    for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
                        name = "Unknown"
                        confidence = 0.0
                        
                        if known_faces["encodings"]:
                            # Compare with known faces using stricter threshold
                            matches = face_recognition.compare_faces(
                                known_faces["encodings"],
                                face_encoding,
                                tolerance=0.55
                            )
                            
                            if True in matches:
                                face_distances = face_recognition.face_distance(
                                    known_faces["encodings"],
                                    face_encoding
                                )
                                best_match_index = np.argmin(face_distances)
                                if matches[best_match_index]:
                                    confidence = (1 - face_distances[best_match_index]) * 100
                                    logger.debug(f"Frame {frame_count}: Face distance: {face_distances[best_match_index]:.3f}, confidence: {confidence:.1f}%")
                                    if confidence > 53:
                                        name = known_faces["names"][best_match_index]
                                        detected_names.add(name)
                                        logger.info(f"Frame {frame_count}: Recognized {name} with {confidence:.1f}% confidence")
                                        
                                        # Track appearance intervals
                                        if name not in current_appearances:
                                            # Start new appearance interval
                                            current_appearances[name] = {
                                                "start": frame_time,
                                                "confidence": confidence
                                            }
                                        else:
                                            # Update last seen time
                                            current_appearances[name]["last_seen"] = frame_time
                                            current_appearances[name]["confidence"] = max(
                                                current_appearances[name]["confidence"],
                                                confidence
                                            )
                        
                        if confidence > 53:  # Only store high confidence detections
                            # Extract face image with margin
                            margin = 0.2  # 20% margin
                            height = bottom - top
                            width = right - left
                            
                            # Calculate expanded face region
                            exp_top = max(0, int(top - height * margin))
                            exp_bottom = min(rgb_frame.shape[0], int(bottom + height * margin))
                            exp_left = max(0, int(left - width * margin))
                            exp_right = min(rgb_frame.shape[1], int(right + width * margin))
                            
                            # Extract and encode face image
                            face_img = rgb_frame[exp_top:exp_bottom, exp_left:exp_right]
                            _, img_encoded = cv2.imencode('.jpg', face_img)
                            img_base64 = base64.b64encode(img_encoded.tobytes()).decode('utf-8')
                            
                            face_data.append({
                                "bbox": [top, right, bottom, left],
                                "name": name,
                                "confidence": confidence,
                                "frame_position": frame_count / total_frames,
                                "timestamp": frame_time,
                                "face_image": img_base64
                            })
                    
                    if face_data:  # Only store frames with valid detections
                        logger.debug(f"Frame {frame_count}: Adding {len(face_data)} faces to detections")
                        results["face_detections"].append({
                            "frame": frame_count,
                            "timestamp": frame_time,
                            "faces": face_data
                        })
                    else:
                        if face_locations:
                            logger.debug(f"Frame {frame_count}: {len(face_locations)} faces detected but confidence too low or processing skipped")
        
        logger.info(f"Frame processing loop ended - total frames processed: {frame_count}, face_detections collected: {len(results['face_detections'])}")
        
        # Process final appearances after frame loop completes
        # Check for ended appearances (persons no longer in frame)
        for name in list(current_appearances.keys()):
            # Person has disappeared at end of video
            appearance = current_appearances.pop(name)
            if name not in results["person_appearances"]:
                results["person_appearances"][name] = []
            
            # Add the appearance interval
            results["person_appearances"][name].append({
                "start_time": appearance["start"],
                "end_time": appearance.get("last_seen", appearance["start"]),
                "confidence": appearance["confidence"]
            })
        
        # Calculate total duration for each person
        for name in results["person_appearances"]:
            total_duration = sum(
                app["end_time"] - app["start_time"]
                for app in results["person_appearances"][name]
            )
            if name not in results["person_tracking"]:
                results["person_tracking"][name] = {}
            results["person_tracking"][name]["total_duration"] = total_duration
            results["person_tracking"][name]["appearances"] = results["person_appearances"][name]
        
        # Calculate summary statistics for frontend compatibility
        total_faces = 0
        known_faces_count = 0
        unknown_faces_count = 0
        detected_persons = []
        
        logger.info(f"Before summary calculation:")
        logger.info(f"  Face detections count: {len(results['face_detections']) if results['face_detections'] else 0}")
        logger.info(f"  Person tracking: {list(results['person_tracking'].keys())}")
        logger.info(f"  Person appearances: {list(results['person_appearances'].keys())}")
        if results['face_detections']:
            logger.info(f"  First detection: {len(results['face_detections'][0]['faces']) if results['face_detections'] else 0} faces")

        if results["face_detections"]:
            for detection in results["face_detections"]:
                total_faces += len(detection["faces"])
                for face in detection["faces"]:
                    if face["name"] and face["name"] != "Unknown":
                        known_faces_count += 1
                    else:
                        unknown_faces_count += 1

        # Create detected persons summary
        for person_name, tracking_data in results["person_tracking"].items():
            if person_name and person_name != "Unknown":
                # Count total detections for this person
                person_detections = sum(
                    len([f for f in detection["faces"] if f["name"] == person_name])
                    for detection in (results["face_detections"] or [])
                )
                detected_persons.append({
                    "name": person_name,
                    "count": person_detections,
                    "total_duration": tracking_data.get("total_duration", 0)
                })

        # Calculate processing time
        processing_time = (datetime.now() - start_time).total_seconds()

        # Add frontend-compatible fields
        results.update({
            "total_faces": total_faces,
            "known_faces": known_faces_count,
            "unknown_faces": unknown_faces_count,
            "detected_persons": detected_persons,
            "processing_time": f"{processing_time:.2f}s",
            "processing_time_seconds": processing_time
        })
        
        logger.info(f"Results summary - total: {total_faces}, known: {known_faces_count}, unknown: {unknown_faces_count}, persons: {len(detected_persons)}")

        # Final status update
        if task_id in TASKS and TASKS[task_id]["status"] != "cancelled":
            logger.info(f"Finalizing results for task {task_id}")
            TASKS[task_id]["status"] = "completed"
            TASKS[task_id]["progress"] = 100
            TASKS[task_id]["message"] = "Processing completed successfully"
            TASKS[task_id]["updated_at"] = datetime.now()
            TASKS[task_id]["results"] = results
            
            logger.info(f"Results stored in task - verification:")
            logger.info(f"  Task in TASKS: {task_id in TASKS}")
            logger.info(f"  Results in task: {'results' in TASKS[task_id]}")
            logger.info(f"  Results total_faces: {TASKS[task_id]['results'].get('total_faces')}")

            # Log final summary
            logger.info(f"Processing completed for task {task_id}:")
            logger.info(f"  Total faces detected: {total_faces}")
            logger.info(f"  Known faces: {known_faces_count}")
            logger.info(f"  Unknown faces: {unknown_faces_count}")
            logger.info(f"  Detected persons: {len(detected_persons)}")
            logger.info(f"  Processing time: {processing_time:.2f}s")
            logger.info(f"  Detected persons: {detected_persons}")
            
    except Exception as e:
        logger.error(f"Error processing video: {e}")
        if task_id in TASKS:
            TASKS[task_id]["status"] = "failed"
            TASKS[task_id]["message"] = str(e)
            TASKS[task_id]["updated_at"] = datetime.now()
        raise
        
    finally:
        # Clean up resources
        if cap is not None:
            cap.release()
            
        # Clean up temporary file
        if temp_path and os.path.exists(temp_path):
            try:
                # Add a small delay to ensure file is released
                time.sleep(0.1)
                os.unlink(temp_path)
            except Exception as e:
                logger.error(f"Error removing temporary file: {e}")
                # Try one more time after a longer delay
                try:
                    time.sleep(1)
                    os.unlink(temp_path)
                except Exception as e:
                    logger.error(f"Failed to remove temporary file after retry: {e}")

@app.post("/process/async", response_model=TaskStatus)
async def start_video_processing(request: ProcessRequest, background_tasks: BackgroundTasks):
    """Start asynchronous video processing"""
    task_id = str(uuid.uuid4())
    now = datetime.now()
    
    try:
        # Create task record with video_id
        TASKS[task_id] = {
            "task_id": task_id,
            "video_id": request.video_id,
            "status": "pending",
            "progress": 0,
            "message": "Task queued",
            "created_at": now,
            "updated_at": now,
            "options": request.options
        }
        
        # Log task creation
        logger.info(f"Created new task {task_id} for video {request.video_id}")
        logger.info(f"Processing options: {request.options}")
        
        # Start background processing
        background_tasks.add_task(
            process_video_task, 
            task_id=task_id,
            video_id=request.video_id,
            options=request.options
        )
        
        return TASKS[task_id]
        
    except Exception as e:
        logger.error(f"Failed to start processing: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to start processing: {str(e)}"
        )

@app.get("/process/{task_id}/status", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """Get status of a processing task"""
    try:
        if task_id not in TASKS:
            logger.warning(f"Task {task_id} not found")
            raise HTTPException(status_code=404, detail="Task not found")
        
        task = TASKS[task_id]
        logger.debug(f"Task {task_id} status: {task['status']}, progress: {task['progress']}%")
        
        return task
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting task status: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error getting task status: {str(e)}"
        )

@app.get("/process/{task_id}/result")
async def get_task_result(task_id: str):
    """Get result of a completed task"""
    try:
        if task_id not in TASKS:
            logger.warning(f"Task {task_id} not found")
            raise HTTPException(status_code=404, detail="Task not found")
        
        task = TASKS[task_id]
        logger.info(f"Getting results for task {task_id}, status: {task['status']}")
        
        if task["status"] != "completed":
            logger.warning(f"Task {task_id} is not completed. Current status: {task['status']}")
            raise HTTPException(
                status_code=400, 
                detail=f"Task is not completed. Current status: {task['status']}"
            )
        
        # Get results from memory
        if "results" not in task:
            logger.error(f"Results not found for task {task_id}")
            raise HTTPException(status_code=404, detail="Results not found")
            
        results = task["results"]
        logger.info(f"Returning results for task {task_id}:")
        logger.info(f"  Type: {type(results)}")
        logger.info(f"  Total faces: {results.get('total_faces', 'MISSING')}")
        logger.info(f"  Known faces: {results.get('known_faces', 'MISSING')}")
        logger.info(f"  Unknown faces: {results.get('unknown_faces', 'MISSING')}")
        logger.info(f"  Processing time: {results.get('processing_time', 'MISSING')}")
        logger.info(f"  Face detections: {len(results.get('face_detections', []))} frames")
        logger.info(f"  Detected persons: {len(results.get('detected_persons', []))}")
        return results
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving results: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Error retrieving results: {str(e)}"
        )

@app.delete("/process/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a processing task"""
    try:
        if task_id not in TASKS:
            raise HTTPException(status_code=404, detail="Task not found")
        
        task = TASKS[task_id]
        if task["status"] in ["completed", "failed", "cancelled"]:
            raise HTTPException(
                status_code=400, 
                detail=f"Cannot cancel task with status: {task['status']}"
            )
        
        # Update task status
        TASKS[task_id]["status"] = "cancelled"
        TASKS[task_id]["message"] = "Task cancelled by user"
        TASKS[task_id]["progress"] = 0
        TASKS[task_id]["updated_at"] = datetime.now()
        
        # Clean up any temporary files
        video_id = task.get("video_id")
        if video_id:
            temp_files = glob.glob(os.path.join("uploads", f"{video_id}*"))
            for temp_file in temp_files:
                try:
                    os.remove(temp_file)
                except Exception as e:
                    logger.error(f"Error removing temp file {temp_file}: {e}")
        
        return {
            "status": "success",
            "message": "Task cancelled",
            "task_id": task_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling task: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to cancel task: {str(e)}"
        )

@app.get("/process/list")
async def list_tasks(status: Optional[str] = None):
    """List all processing tasks, optionally filtered by status"""
    if status:
        filtered_tasks = {k: v for k, v in TASKS.items() if v["status"] == status}
        return filtered_tasks
    return TASKS

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    try:
        # Check if YOLO model is loaded
        model_status = "loaded" if YOLO_MODEL is not None else "not loaded"
        gpu_status = "available" if GPU_AVAILABLE else "not available"
        
        return {
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "yolo_model": model_status,
            "gpu": gpu_status,
            "data_dir": os.path.exists(DATA_DIR)
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Health check failed: {str(e)}"
        )

@app.get("/formats")
async def get_supported_formats():
    """Get list of supported video formats"""
    return {
        "formats": ['.mp4', '.avi', '.mov', '.mkv', '.wmv'],
        "max_size": 1024 * 1024 * 100  # 100MB
    }

@app.post("/upload")
async def upload_video(file: UploadFile):
    """Handle video file upload"""
    try:
        # Check file format
        file_ext = os.path.splitext(file.filename)[1].lower()
        if file_ext not in ['.mp4', '.avi', '.mov', '.mkv', '.wmv']:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file format"
            )
        
        # Read file data into memory
        file_data = await file.read()
        file_id = str(uuid.uuid4())
        
        # Store in memory
        UPLOADED_FILES[file_id] = {
            "data": file_data,
            "filename": file.filename,
            "extension": file_ext,
            "size": len(file_data),
            "upload_time": datetime.now()
        }
        
        logger.info(f"Video uploaded: {file.filename} -> {file_id}, size: {len(file_data)} bytes")
        
        return {
            "filename": file_id,
            "size": len(file_data),
            "format": file_ext,
            "status": "processed"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Upload error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

@app.delete("/{video_id}")
async def delete_video(video_id: str):
    """Delete a video and its processed results"""
    try:
        # Check if video exists in memory
        if video_id not in UPLOADED_FILES:
            raise HTTPException(
                status_code=404,
                detail="Video not found"
            )
            
        # Find tasks associated with this video
        tasks_to_remove = []
        for task_id, task in TASKS.items():
            if task.get("video_id") == video_id:
                # Mark task as cancelled if still processing
                if task["status"] == "processing":
                    task["status"] = "cancelled"
                tasks_to_remove.append(task_id)
        
        # Wait a short time for any processing to complete
        await asyncio.sleep(0.5)
            
        # Remove from memory
        del UPLOADED_FILES[video_id]
            
        # Remove tasks
        for task_id in tasks_to_remove:
            if task_id in TASKS:  # Check again in case task was removed
                del TASKS[task_id]
        
        return {
            "status": "success",
            "message": "Video and associated data deleted successfully"
        }
        
    except Exception as e:
        logger.error(f"Delete error: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=str(e)
        )

# This app can be mounted in the main application

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
