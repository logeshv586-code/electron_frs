from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Deque, Dict, List, Optional, Tuple

import cv2
import numpy as np
from fastapi import HTTPException

logger = logging.getLogger(__name__)

os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS",
    "rtsp_transport;tcp|fflags;nobuffer|flags;low_delay|max_delay;0",
)
os.environ.setdefault("OPENCV_LOG_LEVEL", "ERROR")


class CameraStreamManager:
    """Low-latency RTSP manager with one recognition worker per camera.

    Frames are never queued for recognition: the worker always consumes the newest
    frame. This prevents attendance being generated from stale buffered video. A small
    per-track crop history stores each face with its bbox from that frame, fixing the
    old bug that applied a current bbox to historical frames.
    """

    def __init__(self):
        self.active_streams: Dict[str, Dict] = {}
        self.stream_lock = threading.RLock()
        self.current_frames: Dict[str, Tuple[np.ndarray, int, float]] = {}
        self.frame_counters: Dict[str, int] = defaultdict(int)
        self.processing_threads: Dict[str, threading.Thread] = {}
        self.latest_detections: Dict[str, List[Dict]] = {}
        self.latest_detection_times: Dict[str, float] = {}
        self.detections_lock = threading.RLock()
        self.stream_bounding_boxes: Dict[str, bool] = {}
        self.track_crop_buffers: Dict[str, Dict[int, Deque[Dict]]] = defaultdict(dict)
        self.crop_lock = threading.RLock()
        self.max_track_crops = max(3, int(os.getenv("FACE_TRACK_CROP_BUFFER", "8")))
        logger.info("CameraStreamManager ready")

    def start_stream(
        self,
        camera_id: int,
        rtsp_url: str,
        camera_name: str = "Unknown",
        company_id: Optional[str] = None,
        location: Optional[str] = None,
        camera_role: str = "BIDIRECTIONAL",
        direction: str = "AUTO",
        site_id: Optional[str] = None,
        zone_id: Optional[str] = None,
        line_x1: Optional[float] = None,
        line_y1: Optional[float] = None,
        line_x2: Optional[float] = None,
        line_y2: Optional[float] = None,
        in_side: str = "POSITIVE",
    ) -> str:
        existing = self.get_camera_stream(camera_id)
        if existing:
            return existing

        cap = self._open_capture(rtsp_url)
        if cap is None or not cap.isOpened():
            if cap is not None:
                cap.release()
            raise HTTPException(status_code=400, detail="Cannot connect to camera stream")
        ok, frame = cap.read()
        cap.release()
        if not ok or frame is None or frame.size == 0:
            raise HTTPException(status_code=400, detail="Camera connected but no valid frame was received")

        stream_id = str(uuid.uuid4())
        with self.stream_lock:
            self.active_streams[stream_id] = {
                "camera_id": int(camera_id),
                "camera_name": camera_name,
                "rtsp_url": rtsp_url,
                "company_id": company_id or "default",
                "location": location or camera_name,
                "camera_role": (camera_role or "BIDIRECTIONAL").upper(),
                "direction": (direction or "AUTO").upper(),
                "site_id": site_id,
                "zone_id": zone_id,
                "line_x1": line_x1,
                "line_y1": line_y1,
                "line_x2": line_x2,
                "line_y2": line_y2,
                "in_side": (in_side or "POSITIVE").upper(),
                "created_at": time.time(),
                "is_active": True,
                "frame_count": 0,
                "last_frame_at": None,
                "reconnect_count": 0,
            }
        logger.info("Started stream %s for camera %s (%s)", stream_id, camera_id, camera_name)
        return stream_id

    def _open_capture(self, rtsp_url):
        try:
            if isinstance(rtsp_url, str) and rtsp_url.isdigit():
                cap = cv2.VideoCapture(int(rtsp_url))
            else:
                cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
            if cap is not None:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            return cap
        except Exception as exc:
            logger.warning("Could not open camera: %s", exc)
            return None

    def stop_stream(self, stream_id: str) -> bool:
        with self.stream_lock:
            info = self.active_streams.get(stream_id)
            if not info:
                return False
            info["is_active"] = False

        thread = self.processing_threads.get(stream_id)
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=1.5)

        with self.stream_lock:
            self.active_streams.pop(stream_id, None)
        self.processing_threads.pop(stream_id, None)
        self.current_frames.pop(stream_id, None)
        self.frame_counters.pop(stream_id, None)
        with self.detections_lock:
            self.latest_detections.pop(stream_id, None)
            self.latest_detection_times.pop(stream_id, None)
        with self.crop_lock:
            self.track_crop_buffers.pop(stream_id, None)
        logger.info("Stopped stream %s", stream_id)
        return True

    def get_stream_info(self, stream_id: str) -> Optional[Dict]:
        with self.stream_lock:
            value = self.active_streams.get(stream_id)
            return dict(value) if value else None

    def _is_stream_active(self, stream_id: str) -> bool:
        with self.stream_lock:
            return bool(self.active_streams.get(stream_id, {}).get("is_active"))

    def get_camera_stream(self, camera_id: int) -> Optional[str]:
        with self.stream_lock:
            for stream_id, info in self.active_streams.items():
                if int(info.get("camera_id", -1)) == int(camera_id) and info.get("is_active"):
                    return stream_id
        return None

    def set_bounding_box(
        self,
        enabled: bool,
        stream_id: Optional[str] = None,
        company_id: Optional[str] = None,
        camera_id: Optional[str] = None,
    ) -> None:
        if stream_id:
            self.stream_bounding_boxes[str(stream_id)] = bool(enabled)
        if camera_id is not None:
            self.stream_bounding_boxes[f"camera:{camera_id}"] = bool(enabled)
        if company_id:
            self.stream_bounding_boxes[f"company:{company_id}"] = bool(enabled)
        with self.stream_lock:
            for sid, info in self.active_streams.items():
                if camera_id is not None and str(info.get("camera_id")) == str(camera_id):
                    self.stream_bounding_boxes[sid] = bool(enabled)

    def get_bounding_box(self, stream_id: Optional[str] = None, company_id: Optional[str] = None) -> bool:
        if stream_id and stream_id in self.stream_bounding_boxes:
            return self.stream_bounding_boxes[stream_id]
        if stream_id:
            info = self.get_stream_info(stream_id)
            if info:
                camera_key = f"camera:{info.get('camera_id')}"
                if camera_key in self.stream_bounding_boxes:
                    return self.stream_bounding_boxes[camera_key]
                company_id = company_id or info.get("company_id")
        if company_id and f"company:{company_id}" in self.stream_bounding_boxes:
            return self.stream_bounding_boxes[f"company:{company_id}"]
        return True

    @staticmethod
    def _focus_score(crop: np.ndarray) -> float:
        if crop is None or crop.size == 0:
            return 0.0
        try:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) if crop.ndim == 3 else crop
            lap = float(cv2.Laplacian(gray, cv2.CV_64F).var())
            mean = float(np.mean(gray))
            exposure = max(0.0, 1.0 - abs(mean - 128.0) / 128.0)
            return lap * (0.75 + 0.25 * exposure)
        except Exception:
            return 0.0

    def register_track_frame(
        self,
        stream_id: str,
        track_id: int,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
    ) -> None:
        if frame is None or frame.size == 0:
            return
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = [int(v) for v in bbox]
        fw, fh = max(1, x2 - x1), max(1, y2 - y1)
        pad_x, pad_y = int(fw * 0.35), int(fh * 0.35)
        x1 = max(0, x1 - pad_x); x2 = min(w, x2 + pad_x)
        y1 = max(0, y1 - pad_y); y2 = min(h, y2 + pad_y)
        crop = frame[y1:y2, x1:x2].copy()
        if crop.size == 0 or min(crop.shape[:2]) < 10:
            return
        try:
            from recognition.evidence_quality import evidence_score
            best_score = evidence_score(crop, tuple(bbox))
        except Exception:
            best_score = self._focus_score(crop)
        item = {
            "crop": crop,
            "bbox": tuple(bbox),
            "score": best_score,
            "timestamp": time.time(),
        }
        with self.crop_lock:
            stream_buffers = self.track_crop_buffers.setdefault(stream_id, {})
            buffer = stream_buffers.get(int(track_id))
            if buffer is None:
                buffer = deque(maxlen=self.max_track_crops)
                stream_buffers[int(track_id)] = buffer
            buffer.append(item)
            cutoff = time.time() - 5.0
            for tid in list(stream_buffers.keys()):
                buf = stream_buffers[tid]
                while buf and buf[0]["timestamp"] < cutoff:
                    buf.popleft()
                if not buf:
                    stream_buffers.pop(tid, None)

    def get_best_crop_for_track(self, stream_id: str, track_id: int) -> Optional[np.ndarray]:
        with self.crop_lock:
            buffer = self.track_crop_buffers.get(stream_id, {}).get(int(track_id))
            if not buffer:
                return None
            best = max(buffer, key=lambda item: item.get("score", 0.0))
            return best["crop"].copy()

    def get_best_frame_for_bbox(self, stream_id: str, bbox: Tuple[int, int, int, int]) -> Optional[np.ndarray]:
        value = self.current_frames.get(stream_id)
        return value[0].copy() if value and value[0] is not None else None

    def _processing_worker(self, stream_id: str) -> None:
        last_frame_number = -1
        cadence = 4
        try:
            from face_pipeline import get_runtime_profile
            cadence = max(1, int(get_runtime_profile().get("process_every_n", cadence)))
        except Exception:
            pass
        logical_count = 0

        while self._is_stream_active(stream_id):
            value = self.current_frames.get(stream_id)
            if not value:
                time.sleep(0.005)
                continue
            frame, frame_number, _ = value
            if frame_number <= last_frame_number:
                time.sleep(0.005)
                continue
            last_frame_number = frame_number
            logical_count += 1
            if logical_count % cadence != 0:
                continue

            info = self.get_stream_info(stream_id) or {}
            try:
                from face_pipeline import process_frame
                started = time.perf_counter()
                _, detections = process_frame(
                    frame,
                    force_process=True,
                    stream_id=stream_id,
                    company_id=info.get("company_id") or "default",
                )
                elapsed = time.perf_counter() - started
                for detection in detections:
                    if detection.get("track_id") is not None and detection.get("bbox"):
                        self.register_track_frame(stream_id, detection["track_id"], frame, tuple(detection["bbox"]))
                with self.detections_lock:
                    self.latest_detections[stream_id] = detections
                    self.latest_detection_times[stream_id] = time.time()

                if elapsed > 0.55 and cadence < 10:
                    cadence += 1
                elif elapsed < 0.18 and cadence > 2:
                    cadence -= 1
            except Exception as exc:
                logger.error("Recognition worker error for %s: %s", stream_id, exc)
                time.sleep(0.02)

    def generate_mjpeg_stream(self, stream_id: str):
        info = self.get_stream_info(stream_id)
        if not info:
            return

        if stream_id not in self.processing_threads or not self.processing_threads[stream_id].is_alive():
            thread = threading.Thread(target=self._processing_worker, args=(stream_id,), daemon=True)
            self.processing_threads[stream_id] = thread
            thread.start()

        rtsp_url = info["rtsp_url"]
        cap = None
        reconnect_delays = (1, 2, 5, 10, 20, 30)
        reconnect_index = 0
        encode_params = [cv2.IMWRITE_JPEG_QUALITY, int(os.getenv("FRS_STREAM_JPEG_QUALITY", "82"))]

        try:
            while self._is_stream_active(stream_id):
                if cap is None or not cap.isOpened():
                    cap = self._open_capture(rtsp_url)
                    if cap is None or not cap.isOpened():
                        delay = reconnect_delays[min(reconnect_index, len(reconnect_delays) - 1)]
                        reconnect_index += 1
                        self._sleep_interruptible(stream_id, delay)
                        continue
                    reconnect_index = 0
                    with self.stream_lock:
                        if stream_id in self.active_streams:
                            self.active_streams[stream_id]["reconnect_count"] += 1

                if not cap.grab():
                    cap.release(); cap = None
                    continue
                ok, frame = cap.retrieve()
                if not ok or frame is None or frame.size == 0:
                    cap.release(); cap = None
                    continue

                self.frame_counters[stream_id] += 1
                frame_no = self.frame_counters[stream_id]
                self.current_frames[stream_id] = (frame, frame_no, time.time())
                with self.stream_lock:
                    if stream_id in self.active_streams:
                        self.active_streams[stream_id]["frame_count"] = frame_no
                        self.active_streams[stream_id]["last_frame_at"] = time.time()

                with self.detections_lock:
                    detections = list(self.latest_detections.get(stream_id, []))
                    age = time.time() - self.latest_detection_times.get(stream_id, 0.0)
                if age > 1.2:
                    detections = []

                output = frame
                if detections and self.get_bounding_box(stream_id=stream_id, company_id=info.get("company_id")):
                    try:
                        from face_pipeline import render_bounding_boxes
                        output = render_bounding_boxes(frame, detections, True)
                    except Exception:
                        output = frame

                ok, buffer = cv2.imencode(".jpg", output, encode_params)
                if ok:
                    payload = buffer.tobytes()
                    yield (
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(payload)).encode("ascii") + b"\r\n\r\n" +
                        payload + b"\r\n"
                    )
        finally:
            if cap is not None:
                cap.release()

    def _sleep_interruptible(self, stream_id: str, seconds: float):
        end = time.time() + seconds
        while time.time() < end and self._is_stream_active(stream_id):
            time.sleep(min(0.1, max(0.0, end - time.time())))

    def get_active_streams(self) -> Dict[str, Dict]:
        with self.stream_lock:
            return {key: dict(value) for key, value in self.active_streams.items()}

    def cleanup_inactive_streams(self):
        for stream_id in list(self.active_streams.keys()):
            if not self._is_stream_active(stream_id):
                self.stop_stream(stream_id)


stream_manager = CameraStreamManager()


def get_stream_manager() -> CameraStreamManager:
    return stream_manager
