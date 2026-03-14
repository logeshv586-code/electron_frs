import cv2
import threading
import time
import logging
from typing import Dict, Optional, Tuple, List
import uuid
from fastapi import HTTPException
from fastapi.responses import StreamingResponse
import io
import numpy as np
from queue import Queue, Empty
from collections import deque
import os

logger = logging.getLogger(__name__)

class CameraStreamManager:
    """Manages camera streams for the enhanced camera management system"""
    
    def __init__(self):
        self.active_streams: Dict[str, Dict] = {}
        self.stream_lock = threading.Lock()
        # Bounding box visualization toggle (default: True)
        self.show_bounding_box: bool = True
        
        # Diagnostic logging for singleton verification
        instance_id = id(self)
        logger.info(f"Initialized CameraStreamManager instance ID: {instance_id}")
        
        # Per-stream frame shared state (replaces queues to prevent buffering/looping)
        self.current_frames: Dict[str, Tuple[np.ndarray, int]] = {}  # The absolute latest raw frame to process
        self.processed_frames_latest: Dict[str, np.ndarray] = {}  # The absolute latest processed frame
        self.processing_threads: Dict[str, threading.Thread] = {}
        self.frame_counters: Dict[str, int] = {}  # Per-stream frame counters
        self.max_buffer_size = 1  # Keep max 1 processed frame in buffer (ensures no old frame looping)
        # Frame quality tracking
        self.last_good_frames: Dict[str, np.ndarray] = {}  # Store last valid frame per stream
        self.frame_validation_enabled = True
        # Frame buffer for sharp face capture (stores raw frames with timestamps)
        self.frame_buffers: Dict[str, deque] = {}  # Buffer of raw frames for best capture
        self.max_frame_buffer_size = 20  # Optimized for Tesla T4: More frames = better sharpness selection
        
        # Set FFmpeg environment variables to suppress H.264 error messages and handle errors better
        os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|strict;experimental|err_detect;ignore_err'
        # Suppress FFmpeg stderr output for H.264 errors (they're handled gracefully)
        os.environ['OPENCV_LOG_LEVEL'] = 'ERROR'
    
    def start_stream(self, camera_id: int, rtsp_url: str, camera_name: str = "Unknown", company_id: Optional[str] = None) -> str:
        """Start a new camera stream"""
        stream_id = str(uuid.uuid4())
        
        try:
            # Test the RTSP connection (handle camera index vs RTSP URL)
            if isinstance(rtsp_url, str) and rtsp_url.isdigit():
                cap = cv2.VideoCapture(int(rtsp_url))
            else:
                cap = cv2.VideoCapture(rtsp_url)
            
            if not cap.isOpened():
                raise HTTPException(status_code=400, detail="Cannot connect to camera stream")
            
            # Read a test frame
            ret, frame = cap.read()
            if not ret:
                cap.release()
                raise HTTPException(status_code=400, detail="Cannot read from camera stream")
            
            cap.release()
            
            # Store stream info
            with self.stream_lock:
                self.active_streams[stream_id] = {
                    'camera_id': camera_id,
                    'camera_name': camera_name,
                    'rtsp_url': rtsp_url,
                    'company_id': company_id,
                    'created_at': time.time(),
                    'is_active': True,
                    'frame_count': 0
                }
            
            logger.info(f"Started stream {stream_id} for camera {camera_id}")
            return stream_id
            
        except Exception as e:
            logger.error(f"Error starting stream for camera {camera_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to start stream: {str(e)}")
    
    def stop_stream(self, stream_id: str) -> bool:
        """Stop a camera stream"""
        try:
            # Stop processing thread
            if stream_id in self.processing_threads:
                if stream_id in self.current_frames:
                    # Thread will die naturally when is_active goes false
                    pass
                # Wait for thread to finish (with timeout)
                thread = self.processing_threads[stream_id]
                if thread.is_alive():
                    thread.join(timeout=2.0)
                del self.processing_threads[stream_id]
            
            # Clean up queues and buffers
            if stream_id in self.current_frames:
                del self.current_frames[stream_id]
            if stream_id in self.processed_frames_latest:
                del self.processed_frames_latest[stream_id]
            if stream_id in self.frame_counters:
                del self.frame_counters[stream_id]
            if stream_id in self.last_good_frames:
                del self.last_good_frames[stream_id]
            if stream_id in self.frame_buffers:
                del self.frame_buffers[stream_id]
            
            with self.stream_lock:
                if stream_id in self.active_streams:
                    self.active_streams[stream_id]['is_active'] = False
                    del self.active_streams[stream_id]
                    logger.info(f"Stopped stream {stream_id}")
                    return True
                return False
        except Exception as e:
            logger.error(f"Error stopping stream {stream_id}: {e}")
            return False
    
    def get_stream_info(self, stream_id: str) -> Optional[Dict]:
        """Get information about a stream"""
        with self.stream_lock:
            return self.active_streams.get(stream_id)
    
    def _is_stream_active(self, stream_id: str) -> bool:
        """Check if a stream is still active (exists and is_active=True)"""
        with self.stream_lock:
            stream = self.active_streams.get(stream_id)
            return stream is not None and stream.get('is_active', False)
    
    def get_camera_stream(self, camera_id: int) -> Optional[str]:
        """Get active stream ID for a camera"""
        with self.stream_lock:
            for stream_id, info in self.active_streams.items():
                if info['camera_id'] == camera_id and info['is_active']:
                    return stream_id
        return None
    
    def set_bounding_box(self, enabled: bool) -> None:
        """Set bounding box visualization toggle."""
        self.show_bounding_box = enabled
        logger.info(f"CameraStreamManager (ID: {id(self)}) bounding box visualization {'enabled' if enabled else 'disabled'}")
    
    def get_bounding_box(self) -> bool:
        """Get current bounding box toggle state."""
        return self.show_bounding_box
    
    def _validate_frame(self, frame: np.ndarray) -> bool:
        """Validate frame quality - check for corruption or pixelation"""
        if frame is None:
            return False
        if frame.size == 0:
            return False
        if len(frame.shape) != 3 or frame.shape[2] != 3:
            return False
        
        h, w = frame.shape[:2]
        if h < 10 or w < 10:  # Too small
            return False
        
        # Check for completely black or white frames (likely corruption)
        mean_val = np.mean(frame)
        if mean_val < 5 or mean_val > 250:
            return False
        
        # Check for excessive noise or pixelation patterns
        # Sample a few regions to check for blocky artifacts
        sample_regions = [
            frame[0:h//4, 0:w//4],      # Top-left
            frame[h//4:h//2, w//2:3*w//4],  # Center
            frame[3*h//4:h, 3*w//4:w]    # Bottom-right
        ]
        
        for region in sample_regions:
            if region.size > 0:
                region_std = np.std(region)
                # Very low std might indicate blocky/pixelated regions
                if region_std < 0.5:
                    return False
        
        return True
    
    def generate_mjpeg_stream(self, stream_id: str):
        """Generate MJPEG stream for a camera with improved stability"""
        stream_info = self.get_stream_info(stream_id)
        if not stream_info:
            return

        rtsp_url = stream_info['rtsp_url']
        logger.info(f"Starting MJPEG stream generation for {stream_id}")

        # Try to connect to real camera first
        cap = None
        camera_accessible = False

        try:
            # Handle camera index (0, 1, 2, etc.) vs RTSP URL
            if isinstance(rtsp_url, str) and rtsp_url.isdigit():
                cap = cv2.VideoCapture(int(rtsp_url))
            else:
                # Use FFMPEG backend for RTSP streams
                cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
                
            if cap.isOpened():
                # Test with multiple frames to ensure stable connection
                test_frames_count = 0
                for _ in range(3):
                    ret, test_frame = cap.read()
                    if ret and test_frame is not None and test_frame.size > 0:
                        test_frames_count += 1
                    time.sleep(0.1)

                if test_frames_count >= 2:  # At least 2 successful frames
                    camera_accessible = True
                    logger.info(f"Camera accessible for stream {stream_id} ({test_frames_count}/3 test frames)")
                else:
                    logger.warning(f"Camera unstable for stream {stream_id} ({test_frames_count}/3 test frames)")

            if cap:
                cap.release()
                cap = None
        except Exception as e:
            logger.warning(f"Error testing camera for stream {stream_id}: {e}")
            if cap:
                cap.release()
                cap = None

        # Always try to stream from real camera, even if initial test failed
        # This allows for cameras that take time to initialize
        if not camera_accessible:
            logger.warning(f"Camera initial test failed for stream {stream_id}, but will attempt real stream anyway")

        # Real camera streaming with improved stability
        yield from self._generate_real_camera_stream(stream_id, stream_info, rtsp_url)

    def _focus_measure(self, gray: np.ndarray) -> float:
        """Calculate sharpness using variance of Laplacian (improved for better detection)"""
        try:
            # Use Laplacian variance for sharpness
            laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
            
            # Also check gradient magnitude for additional sharpness metric
            grad_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
            grad_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
            gradient_mag = np.sqrt(grad_x**2 + grad_y**2).mean()
            
            # Combine both metrics (weighted average)
            combined_score = laplacian_var * 0.7 + gradient_mag * 0.3
            return combined_score
        except:
            return 0.0
    
    def _get_best_frame_from_buffer(self, stream_id: str, bbox: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
        """Get the sharpest frame from buffer for the given bounding box"""
        buffer = self.frame_buffers.get(stream_id)
        if not buffer or len(buffer) == 0:
            return None
        
        x1, y1, x2, y2 = bbox
        best_frame = None
        best_score = -1
        
        for frame_data in buffer:
            frame, _ = frame_data
            if frame is None:
                continue
            
            h, w = frame.shape[:2]
            # Clamp bbox to frame bounds
            x1_c = max(0, min(w-1, x1))
            y1_c = max(0, min(h-1, y1))
            x2_c = max(0, min(w-1, x2))
            y2_c = max(0, min(h-1, y2))
            
            if x2_c <= x1_c or y2_c <= y1_c:
                continue
            
            # Extract crop
            crop = frame[y1_c:y2_c, x1_c:x2_c]
            if crop.size == 0:
                continue
            
            # Convert to grayscale and measure sharpness
            if len(crop.shape) == 3:
                gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            else:
                gray = crop
            
            score = self._focus_measure(gray)
            if score > best_score:
                best_score = score
                best_frame = frame.copy()
        
        # Only return if sharpness is above threshold (avoid very blurry faces)
        # Lowered threshold slightly but improved measurement should catch more good frames
        if best_score < 30:  # Threshold for acceptable sharpness (reduced from 50, improved measurement compensates)
            return None
        
        return best_frame
    
    def _face_processing_worker(self, stream_id: str):
        """Background worker thread for async face processing using shared state (no queues)"""
        frame_counter = 0
        PROCESS_EVERY_N_FRAMES = 2  # Process every 2nd frame for balance of speed and accuracy
        
        last_processed_frame_num = -1
        
        try:
            while self._is_stream_active(stream_id):
                try:
                    # Get the absolute latest frame from shared state
                    if stream_id not in self.current_frames:
                        time.sleep(0.01)
                        continue
                        
                    frame, frame_num = self.current_frames[stream_id]
                    
                    # Don't re-process the exact same frame
                    if frame_num <= last_processed_frame_num:
                        time.sleep(0.01)
                        continue
                        
                    last_processed_frame_num = frame_num
                    frame_counter += 1
                    
                    # Skip processing for some frames to maintain frame rate.
                    # Pass raw frame only – re-rendering stale tracking data
                    # causes ghost bounding boxes and wastes CPU every other frame.
                    if frame_counter % PROCESS_EVERY_N_FRAMES != 0:
                        self.processed_frames_latest[stream_id] = frame.copy()
                    else:
                        # Process frame for face detection
                        try:
                            from face_pipeline import process_frame as face_process_frame
                            from face_pipeline import render_bounding_boxes
                            processed_frame, detections = face_process_frame(frame, force_process=True, stream_id=stream_id)
                            # Broad diagnostic: Are we detecting anything?
                            if detections:
                                logger.info(f"[BBOX-STRE-PRE] Detected {len(detections)} faces. Toggle={self.show_bounding_box}")
                            
                            # Only render when faces were actually detected in THIS frame.
                            if self.show_bounding_box and detections:
                                logger.info(f"[BBOX-STRE] show={self.show_bounding_box}, detections={len(detections)}")
                                processed_frame = render_bounding_boxes(
                                    processed_frame, detections, show_bounding_box=True
                                )
                        except Exception as e:
                            logger.error(f"Error in face processing: {e}")
                            processed_frame = frame
                        
                        self.processed_frames_latest[stream_id] = processed_frame.copy()
                            
                except Exception as e:
                    logger.error(f"Error in face processing worker for {stream_id}: {e}")
                    time.sleep(0.1)
                    continue
        except Exception as e:
            logger.error(f"Face processing worker exited for {stream_id}: {e}")
    
    def _generate_real_camera_stream(self, stream_id: str, stream_info: Dict, rtsp_url: str):
        """Generate stream from real camera with robust reconnection and exponential backoff."""
        cap = None
        frame_count = 0
        last_frame = None
        consecutive_failures = 0
        max_failures = 15  # Slightly more tolerant for network jitter
        
        # Exponential backoff parameters
        reconnect_delays = [5, 10, 20, 40, 60]
        reconnect_index = 0

        # JPEG encoding parameters
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, 80]
        
        # Initialize processing thread
        if stream_id not in self.processing_threads:
            self.frame_counters[stream_id] = 0
            self.current_frames[stream_id] = (np.zeros((10,10,3), dtype=np.uint8), 0)
            processing_thread = threading.Thread(
                target=self._face_processing_worker,
                args=(stream_id,),
                daemon=True
            )
            processing_thread.start()
            self.processing_threads[stream_id] = processing_thread
            logger.info(f"Started face processing thread for stream {stream_id}")

        while self._is_stream_active(stream_id):
            try:
                # 1. CONNECT PHASE
                if cap is None or not cap.isOpened():
                    logger.info(f"Connecting to camera {rtsp_url} for stream {stream_id}")
                    if isinstance(rtsp_url, str) and rtsp_url.isdigit():
                        cap = cv2.VideoCapture(int(rtsp_url))
                    else:
                        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)

                    if not cap.isOpened():
                        delay = reconnect_delays[min(reconnect_index, len(reconnect_delays)-1)]
                        logger.warning(f"Camera connection failed. Retrying in {delay}s (Attempt {reconnect_index+1})")
                        reconnect_index += 1
                        
                        # Sleep in small chunks to remain responsive to deactivation
                        for _ in range(delay * 10):
                            if not self._is_stream_active(stream_id):
                                break
                            time.sleep(0.1)
                        continue
                    
                    # Successfully connected
                    logger.info(f"Camera connected: {stream_id}")
                    reconnect_index = 0
                    consecutive_failures = 0
                    
                    # Optimize cap settings
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
                    if not isinstance(rtsp_url, str) or not rtsp_url.isdigit():
                        # Try to enable GPU acceleration if available
                        os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp|fflags;nobuffer'

                # 2. STREAM PHASE
                while self._is_stream_active(stream_id):
                    if not cap.grab():
                        consecutive_failures += 1
                        if consecutive_failures >= max_failures:
                            logger.error(f"Camera lost for {stream_id}. Reconnecting...")
                            break
                        time.sleep(0.01)
                        continue
                    
                    ret, frame = cap.retrieve()
                    if not ret or frame is None or frame.size == 0:
                        consecutive_failures += 1
                        if consecutive_failures >= max_failures:
                            break
                        continue

                    # Successfull frame
                    consecutive_failures = 0
                    frame_count += 1
                    self.frame_counters[stream_id] = frame_count

                    # Shared state update for face processing
                    self.current_frames[stream_id] = (frame.copy(), frame_count)

                    # Get processed frame (async)
                    processed_frame = self.processed_frames_latest.get(stream_id, frame)
                    if processed_frame is None or processed_frame.size < 100:
                        processed_frame = frame

                    # Encode and yield
                    try:
                        ret_encode, buffer = cv2.imencode('.jpg', processed_frame, encode_params)
                        if ret_encode:
                            yield (b'--frame\r\n'
                                   b'Content-Type: image/jpeg\r\n'
                                   b'Content-Length: ' + str(len(buffer)).encode() + b'\r\n\r\n' +
                                   buffer.tobytes() + b'\r\n')
                    except Exception as e:
                        logger.error(f"Encoding error: {e}")

                # Cleanup cap before reconnecting or exiting
                if cap:
                    cap.release()
                    cap = None

            except Exception as e:
                logger.error(f"Unexpected error in stream {stream_id}: {e}")
                if cap:
                    cap.release()
                    cap = None
                time.sleep(2)

        # FINAL CLEANUP
        if cap:
            cap.release()
        logger.info(f"Stream {stream_id} loop exited (Deactivated)")

    def _generate_demo_stream(self, stream_id: str, stream_info: Dict):
        """Generate a demo stream when real camera is not available"""
        import numpy as np
        import datetime

        frame_count = 0
        start_time = time.time()

        try:
            while self._is_stream_active(stream_id):
                # Create a demo frame (640x480)
                frame = np.zeros((480, 640, 3), dtype=np.uint8)

                # Add gradient background
                for y in range(480):
                    for x in range(640):
                        frame[y, x] = [
                            int(50 + (x / 640) * 100),  # Blue gradient
                            int(30 + (y / 480) * 80),   # Green gradient
                            int(80 + ((x + y) / 1120) * 100)  # Red gradient
                        ]

                # Add camera info text
                camera_id = stream_info.get('camera_id', 'Unknown')
                current_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                # Add text overlays
                cv2.putText(frame, f"DEMO CAMERA {camera_id}", (50, 50),
                           cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                cv2.putText(frame, f"Time: {current_time}", (50, 100),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(frame, f"Frame: {frame_count}", (50, 130),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(frame, f"FPS: 30", (50, 160),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2)
                cv2.putText(frame, "Camera Offline - Demo Mode", (50, 400),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 0), 2)

                # Add moving elements
                elapsed = time.time() - start_time
                circle_x = int(320 + 200 * np.sin(elapsed))
                circle_y = int(240 + 100 * np.cos(elapsed * 1.5))
                cv2.circle(frame, (circle_x, circle_y), 20, (0, 255, 255), -1)

                # Add timestamp in corner
                cv2.putText(frame, f"Uptime: {int(elapsed)}s", (450, 450),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)

                # Encode frame as JPEG
                ret, buffer = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                if not ret:
                    continue

                # Update frame count
                with self.stream_lock:
                    if stream_id in self.active_streams:
                        self.active_streams[stream_id]['frame_count'] += 1

                # Yield frame in MJPEG format
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')

                frame_count += 1
                time.sleep(0.033)  # ~30 FPS

        except Exception as e:
            logger.error(f"Error in demo stream {stream_id}: {e}")
        finally:
            self.stop_stream(stream_id)

    def get_active_streams(self) -> Dict[str, Dict]:
        """Get all active streams"""
        with self.stream_lock:
            return self.active_streams.copy()
    
    def cleanup_inactive_streams(self):
        """Clean up streams that have been inactive for too long"""
        current_time = time.time()
        inactive_threshold = 300  # 5 minutes
        
        with self.stream_lock:
            inactive_streams = []
            for stream_id, info in self.active_streams.items():
                if current_time - info['created_at'] > inactive_threshold and not info['is_active']:
                    inactive_streams.append(stream_id)
            
            for stream_id in inactive_streams:
                del self.active_streams[stream_id]
                logger.info(f"Cleaned up inactive stream {stream_id}")

# Global stream manager instance
stream_manager = CameraStreamManager()

def get_stream_manager() -> CameraStreamManager:
    """Get the global stream manager instance"""
    return stream_manager
