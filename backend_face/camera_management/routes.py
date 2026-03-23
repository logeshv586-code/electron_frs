from fastapi import APIRouter, HTTPException, Depends, Request, Query
from fastapi.responses import JSONResponse, StreamingResponse
from typing import Optional
import os
import logging
import numpy as np

from .models import (
    CameraCreateRequest, CameraUpdateRequest, CameraValidationRequest,
    CameraValidationResponse, CameraListResponse, CameraOperationResponse,
    CollectionCreateRequest, CollectionUpdateRequest
)
from .service import EnhancedCameraService
from .streaming import get_stream_manager, CameraStreamManager
from .recording import get_recording_manager, CameraRecordingManager

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/api/collections", tags=["Camera Collections"])

# Get data directory
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data", "camera_management")

# Create service instance
camera_service = EnhancedCameraService(DATA_DIR)

def get_camera_service() -> EnhancedCameraService:
    return camera_service

def get_stream_service() -> CameraStreamManager:
    return get_stream_manager()

def get_recording_service() -> CameraRecordingManager:
    return get_recording_manager()

@router.post("/validate-camera", response_model=CameraValidationResponse)
async def validate_camera(
    request: CameraValidationRequest,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Validate camera data including duplicate checking"""
    try:
        return service.validate_camera(request)
    except Exception as e:
        logger.error(f"Error validating camera: {e}")
        return CameraValidationResponse(
            valid=False,
            error="Validation failed. Please try again.",
            type="server_error"
        )

@router.get("/cameras", response_model=CameraListResponse)
async def get_cameras(
    request: Request,
    page: int = 1,
    per_page: int = 6,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Get paginated list of cameras with collections"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id") if current_user.get("role") != "SuperAdmin" else None
        
        if page < 1:
            page = 1
        if per_page < 1 or per_page > 50:
            per_page = 6
            
        return service.get_cameras(page, per_page, company_id=company_id)
    except Exception as e:
        logger.error(f"Error getting cameras: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve cameras")

@router.post("/cameras", response_model=CameraOperationResponse)
async def create_camera(
    request_data: CameraCreateRequest,
    request: Request,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Create a new camera"""
    try:
        current_user = request.scope.get("user", {})
        # If Admin or Supervisor, force company_id from their account
        if current_user.get("role") != "SuperAdmin":
            request_data.company_id = current_user.get("company_id")
            
        return service.create_camera(request_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating camera: {e}")
        raise HTTPException(status_code=500, detail="Failed to create camera")

@router.put("/cameras/{camera_id}", response_model=CameraOperationResponse)
async def update_camera(
    camera_id: int,
    request_data: CameraUpdateRequest,
    request: Request,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Update an existing camera"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id") if current_user.get("role") != "SuperAdmin" else None

        # Verify ownership
        if company_id:
            cameras = service._load_cameras()
            camera = next((c for c in cameras if c.id == camera_id), None)
            if not camera or camera.company_id != company_id:
                raise HTTPException(status_code=403, detail="Not authorized to update this camera")

        return service.update_camera(camera_id, request_data)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating camera: {e}")
        raise HTTPException(status_code=500, detail="Failed to update camera")

@router.delete("/cameras/{camera_id}", response_model=CameraOperationResponse)
async def delete_camera(
    camera_id: int,
    request: Request,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Delete a camera"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id") if current_user.get("role") != "SuperAdmin" else None

        # Verify ownership
        if company_id:
            cameras = service._load_cameras()
            camera = next((c for c in cameras if c.id == camera_id), None)
            if not camera or camera.company_id != company_id:
                raise HTTPException(status_code=403, detail="Not authorized to delete this camera")

        return service.delete_camera(camera_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting camera: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete camera")

@router.get("/cameras/{camera_id}")
async def get_camera(
    camera_id: int,
    request: Request,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Get a specific camera by ID"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id") if current_user.get("role") != "SuperAdmin" else None

        cameras = service._load_cameras()
        camera = next((c for c in cameras if c.id == camera_id), None)

        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        # Verify ownership
        if company_id and camera.company_id != company_id:
            raise HTTPException(status_code=403, detail="Not authorized to view this camera")

        return camera
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting camera: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve camera")

@router.post("/cameras/{camera_id}/activate")
async def activate_camera(
    camera_id: int,
    request: Request,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Activate a camera"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id") if current_user.get("role") != "SuperAdmin" else None

        # Verify ownership
        if company_id:
            cameras = service._load_cameras()
            camera = next((c for c in cameras if c.id == camera_id), None)
            if not camera or camera.company_id != company_id:
                raise HTTPException(status_code=403, detail="Not authorized to activate this camera")

        return service.activate_camera(camera_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error activating camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to activate camera")

@router.post("/cameras/{camera_id}/deactivate")
async def deactivate_camera(
    camera_id: int,
    request: Request,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Deactivate a camera"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id") if current_user.get("role") != "SuperAdmin" else None

        # Verify ownership
        if company_id:
            cameras = service._load_cameras()
            camera = next((c for c in cameras if c.id == camera_id), None)
            if not camera or camera.company_id != company_id:
                raise HTTPException(status_code=403, detail="Not authorized to deactivate this camera")

        return service.deactivate_camera(camera_id)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deactivating camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to deactivate camera")

# Streaming endpoints
@router.post("/cameras/{camera_id}/start-stream")
async def start_camera_stream(
    camera_id: int,
    service: EnhancedCameraService = Depends(get_camera_service),
    stream_service: CameraStreamManager = Depends(get_stream_service)
):
    """Start streaming for a camera"""
    try:
        # Get camera info
        cameras = service._load_cameras()
        camera = next((c for c in cameras if c.id == camera_id), None)

        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        # Check if stream already exists
        existing_stream = stream_service.get_camera_stream(camera_id)
        if existing_stream:
            return {
                "success": True,
                "stream_id": existing_stream,
                "message": "Stream already active"
            }

        # Start new stream
        stream_id = stream_service.start_stream(camera_id, camera.rtsp_url, camera.name, company_id=camera.company_id)

        return {
            "success": True,
            "stream_id": stream_id,
            "message": "Stream started successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting stream for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to start stream")

@router.delete("/cameras/{camera_id}/stop-stream")
async def stop_camera_stream(
    camera_id: int,
    stream_service: CameraStreamManager = Depends(get_stream_service)
):
    """Stop streaming for a camera"""
    try:
        stream_id = stream_service.get_camera_stream(camera_id)
        if not stream_id:
            raise HTTPException(status_code=404, detail="No active stream found for camera")

        success = stream_service.stop_stream(stream_id)
        if success:
            return {"success": True, "message": "Stream stopped successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to stop stream")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping stream for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to stop stream")

@router.get("/cameras/{camera_id}/stream")
async def get_camera_stream(
    camera_id: int,
    service: EnhancedCameraService = Depends(get_camera_service),
    stream_service: CameraStreamManager = Depends(get_stream_service)
):
    """Get MJPEG stream for a camera"""
    try:
        # Get camera info
        cameras = service._load_cameras()
        camera = next((c for c in cameras if c.id == camera_id), None)

        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        # Get or create stream
        stream_id = stream_service.get_camera_stream(camera_id)
        if not stream_id:
            stream_id = stream_service.start_stream(camera_id, camera.rtsp_url, camera.name, company_id=camera.company_id)

        # Return MJPEG stream
        return StreamingResponse(
            stream_service.generate_mjpeg_stream(stream_id),
            media_type="multipart/x-mixed-replace; boundary=frame"
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting stream for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get stream")

@router.get("/cameras/{camera_id}/frame")
async def get_camera_frame(
    camera_id: int,
    service: EnhancedCameraService = Depends(get_camera_service),
    stream_service: CameraStreamManager = Depends(get_stream_service)
):
    """Get a single JPEG frame from camera (optimized for live streaming)"""
    try:
        from fastapi.responses import Response
        import cv2
        import numpy as np
        import datetime
        import time

        # Get camera info
        cameras = service._load_cameras()
        camera = next((c for c in cameras if c.id == camera_id), None)

        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        frame = None
        is_demo = False

        # Try to get frame from real camera with ultra-fast settings
        try:
            cap = cv2.VideoCapture(camera.rtsp_url)
            if cap.isOpened():
                # Optimized settings for minimum latency
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimal buffer
                cap.set(cv2.CAP_PROP_FPS, 15)  # Moderate FPS to reduce load
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)  # Smaller resolution for speed
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
                
                # Quick frame grab with timeout
                start_time = time.time()
                ret, frame = cap.read()
                grab_time = time.time() - start_time
                
                if ret and frame is not None and frame.size > 0:
                    # Quick quality validation
                    if np.mean(frame) > 10 and grab_time < 2.0:  # Frame quality and speed check
                        logger.debug(f"? Real frame captured from camera {camera_id} in {grab_time:.2f}s")
                    else:
                        frame = None  # Force demo mode for poor quality/slow frames
                        logger.debug(f"?? Slow/poor frame from camera {camera_id}, using demo")
                else:
                    frame = None
                    
            cap.release()
                
        except Exception as e:
            logger.debug(f"?? Camera {camera_id} unavailable: {e}")
            frame = None

        # Enhanced demo frame with ultra-smooth animation
        if frame is None:
            is_demo = True
            
            # Create optimized demo frame
            frame = np.zeros((480, 640, 3), dtype=np.uint8)

            # Time-based smooth animation
            current_time = time.time()
            wave_phase = (current_time * 3) % (2 * np.pi)  # 3 second cycle for smoother motion
            
            # Ultra-smooth gradient background
            for y in range(0, 480, 2):  # Skip every other line for performance
                for x in range(0, 640, 2):  # Skip every other pixel
                    wave_x = (x + int(80 * np.sin(wave_phase + x/100))) % 640
                    color_intensity = int(60 + 40 * np.sin(y / 30 + wave_phase))
                    frame[y:y+2, x:x+2] = [
                        int(30 + (wave_x / 640) * 100 + color_intensity),  # Blue
                        int(10 + (y / 480) * 80 + color_intensity),   # Green
                        int(50 + ((wave_x + y) / 1120) * 120)  # Red
                    ]

            # Dynamic elements with ultra-smooth motion
            timestamp_str = datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]  # Include milliseconds
            
            # Primary moving circle with trail effect
            circle_x = int(320 + 250 * np.sin(current_time * 0.7))
            circle_y = int(240 + 120 * np.cos(current_time * 0.5))
            
            # Draw trail
            for i in range(5):
                trail_phase = wave_phase - (i * 0.2)
                trail_x = int(320 + 250 * np.sin(current_time * 0.7 - i * 0.1))
                trail_y = int(240 + 120 * np.cos(current_time * 0.5 - i * 0.1))
                alpha = 255 - (i * 40)
                cv2.circle(frame, (trail_x, trail_y), 20 - i*2, (0, alpha, alpha), -1)
            
            cv2.circle(frame, (circle_x, circle_y), 25, (0, 255, 255), -1)
            cv2.circle(frame, (circle_x, circle_y), 30, (255, 255, 255), 2)
            
            # Secondary pulsing element
            pulse_radius = int(12 + 6 * np.sin(current_time * 4))
            pulse_x = int(320 + 150 * np.cos(current_time * 0.3))
            pulse_y = int(240 + 75 * np.sin(current_time * 0.4))
            cv2.circle(frame, (pulse_x, pulse_y), pulse_radius, (255, 128, 0), -1)

            # Enhanced text overlays with better contrast
            cv2.putText(frame, f"DEMO CAMERA {camera_id}", (50, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 4)  # White outline
            cv2.putText(frame, f"DEMO CAMERA {camera_id}", (50, 60),
                       cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 150, 255), 2)   # Orange text
            
            cv2.putText(frame, f"Time: {timestamp_str}", (50, 110),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            
            cv2.putText(frame, "STATUS: LIVE DEMO STREAMING", (50, 420),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 255, 0), 3)
            cv2.putText(frame, "STATUS: LIVE DEMO STREAMING", (50, 420),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 0), 2)
            
            # Real-time frame counter
            frame_number = int(current_time * 15) % 99999  # 15 FPS simulation
            cv2.putText(frame, f"Frame: #{frame_number:05d}", (450, 450),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)
            
            # Live activity indicator
            activity_pulse = int(128 + 127 * np.sin(current_time * 8))
            cv2.circle(frame, (600, 50), 15, (0, activity_pulse, 0), -1)
            cv2.putText(frame, "LIVE", (560, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

        # Ultra-optimized JPEG encoding for speed
        encode_params = [
            cv2.IMWRITE_JPEG_QUALITY, 70,  # Slightly lower quality for speed
            cv2.IMWRITE_JPEG_PROGRESSIVE, 0,  # Baseline JPEG for fastest decode
            cv2.IMWRITE_JPEG_OPTIMIZE, 0   # Skip optimization for speed
        ]
        
        ret, buffer = cv2.imencode('.jpg', frame, encode_params)
        if not ret:
            raise HTTPException(status_code=500, detail="Failed to encode frame")

        # Headers optimized for streaming with cache busting
        headers = {
            "Cache-Control": "no-cache, no-store, must-revalidate, max-age=0",
            "Pragma": "no-cache",
            "Expires": "0",
            "Content-Type": "image/jpeg",
            "X-Frame-Source": "demo" if is_demo else "camera",
            "X-Camera-ID": str(camera_id),
            "X-Timestamp": str(int(time.time() * 1000)),
            "X-Frame-Time": datetime.datetime.now().isoformat(),
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Expose-Headers": "*"
        }

        return Response(
            content=buffer.tobytes(),
            media_type="image/jpeg",
            headers=headers
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting frame for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get frame")

# Recording endpoints
@router.post("/cameras/{camera_id}/start-recording")
async def start_camera_recording(
    camera_id: int,
    duration_minutes: Optional[int] = None,
    service: EnhancedCameraService = Depends(get_camera_service),
    recording_service: CameraRecordingManager = Depends(get_recording_service)
):
    """Start recording from a camera"""
    try:
        # Get camera info
        cameras = service._load_cameras()
        camera = next((c for c in cameras if c.id == camera_id), None)

        if not camera:
            raise HTTPException(status_code=404, detail="Camera not found")

        # Start recording
        recording_id = recording_service.start_recording(
            camera_id,
            camera.rtsp_url,
            duration_minutes
        )

        return {
            "success": True,
            "recording_id": recording_id,
            "message": "Recording started successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error starting recording for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to start recording")

@router.post("/cameras/{camera_id}/stop-recording/{recording_id}")
async def stop_camera_recording(
    camera_id: int,
    recording_id: str,
    recording_service: CameraRecordingManager = Depends(get_recording_service)
):
    """Stop a camera recording"""
    try:
        success = recording_service.stop_recording(recording_id)
        if success:
            return {"success": True, "message": "Recording stopped successfully"}
        else:
            raise HTTPException(status_code=404, detail="Recording not found")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error stopping recording {recording_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to stop recording")

@router.get("/cameras/{camera_id}/recordings")
async def get_camera_recordings(
    camera_id: int,
    recording_service: CameraRecordingManager = Depends(get_recording_service)
):
    """Get all recordings for a camera"""
    try:
        return recording_service.get_camera_recordings(camera_id)
    except Exception as e:
        logger.error(f"Error getting recordings for camera {camera_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get recordings")

@router.get("/recordings/active")
async def get_active_recordings(
    recording_service: CameraRecordingManager = Depends(get_recording_service)
):
    """Get all active recordings"""
    try:
        return recording_service.get_active_recordings()
    except Exception as e:
        logger.error(f"Error getting active recordings: {e}")
        raise HTTPException(status_code=500, detail="Failed to get active recordings")

# Collection management endpoints
@router.get("/")
async def get_collections(
    request: Request,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Get all collections"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id") if current_user.get("role") != "SuperAdmin" else None
        
        collections = service._load_collections()
        
        # Filter by company_id strictly (no default collection leak)
        if company_id:
            collections = [c for c in collections if c.company_id == company_id]
            
        return {"collections": collections}
    except Exception as e:
        logger.error(f"Error getting collections: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve collections")

@router.post("/")
async def create_collection(
    request_data: CollectionCreateRequest,
    request: Request,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Create a new collection"""
    try:
        import uuid
        from datetime import datetime
        from .models import CameraCollection
        
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id")
        
        collections = service._load_collections()
        
        # Check for duplicate names (within the same company)
        if any(c.name.lower() == request_data.name.lower() and c.company_id == company_id for c in collections):
            raise HTTPException(status_code=409, detail="Collection name already exists for this company")
        
        new_collection = CameraCollection(
            id=str(uuid.uuid4()),
            name=request_data.name,
            description=request_data.description,
            created_at=datetime.now(),
            camera_count=0,
            company_id=company_id
        )
        
        collections.append(new_collection)
        service._save_collections(collections)
        
        return {"success": True, "collection": new_collection}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to create collection")

@router.put("/{collection_id}")
async def update_collection(
    collection_id: str,
    request_data: CollectionUpdateRequest,   # Re-aliased parameter to not conflict with FastAPI Request
    request: Request,                      # Added FastAPI Request for auth
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Update a collection"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id") if current_user.get("role") != "SuperAdmin" else None

        collections = service._load_collections()
        
        # Find the collection to update
        collection = next((c for c in collections if c.id == collection_id), None)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")
        
        # Authorization check
        if company_id and collection.company_id != company_id:
            raise HTTPException(status_code=403, detail="Not authorized to edit this collection")
        
        # Check for duplicate names (excluding current collection in same company)
        if request_data.name:
            if any(c.name.lower() == request_data.name.lower() and c.id != collection_id and c.company_id == collection.company_id for c in collections):
                raise HTTPException(status_code=409, detail="Collection name already exists in your company")
            collection.name = request_data.name
        
        if request_data.description is not None:
            collection.description = request_data.description
        
        service._save_collections(collections)
        
        # Update collection name in all cameras
        if request_data.name:
            cameras = service._load_cameras()
            for camera in cameras:
                if camera.collection_id == collection_id:
                    camera.collection_name = collection.name
            service._save_cameras(cameras)
        
        return {"success": True, "collection": collection}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to update collection")

@router.delete("/{collection_id}")
async def delete_collection(
    collection_id: str,
    request: Request,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Delete a collection"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id") if current_user.get("role") != "SuperAdmin" else None

        collections = service._load_collections()
        
        # Find the collection
        collection = next((c for c in collections if c.id == collection_id), None)
        if not collection:
            raise HTTPException(status_code=404, detail="Collection not found")
            
        # Authorization check
        if company_id and collection.company_id != company_id:
            raise HTTPException(status_code=403, detail="Not authorized to delete this collection")
            
        # Remove this collection from all cameras
        cameras = service._load_cameras()
        for camera in cameras:
            if camera.collection_id == collection_id:
                camera.collection_id = None
                camera.collection_name = None
        service._save_cameras(cameras)
        
        # Remove the collection
        collections = [c for c in collections if c.id != collection_id]
        service._save_collections(collections)
        
        # Update collection counts
        service._update_collection_counts()
        
        return {"success": True, "message": f"Collection '{collection.name}' deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting collection: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete collection")

# Health check endpoint
@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "camera_management"}

@router.get("/{collection_id}/streams")
async def get_collection_streams(
    collection_id: str,
    request: Request,
    service: EnhancedCameraService = Depends(get_camera_service)
):
    """Get all streams for a collection (Compatibility with frontend)"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id") if current_user.get("role") != "SuperAdmin" else None

        # Verify collection access
        if company_id:
            collections = service._load_collections()
            collection = next((c for c in collections if c.id == collection_id), None)
            if not collection or collection.company_id != company_id:
                # Still allow 'default' but it won't have cameras for this company anyway if filtered
                if collection_id != "default":
                    raise HTTPException(status_code=403, detail="Not authorized to access this collection")

        cameras = service._load_cameras()
        
        # Filter cameras by collection AND company_id
        collection_cameras = [c for c in cameras if c.collection_id == collection_id]
        if company_id:
            collection_cameras = [c for c in collection_cameras if c.company_id == company_id]
        
        streams = []
        for camera in collection_cameras:
            # Construct stream info expected by frontend
            streams.append({
                "camera_id": camera.id,
                "camera_name": camera.name,
                "stream_url": f"/api/collections/cameras/{camera.id}/stream",
                "rtsp_url": camera.rtsp_url,
                "camera_ip": camera.ip_address,
                "collection_name": camera.collection_name or collection_id,
                "room_id": f"{collection_id}_{camera.ip_address.replace('.', '_')}" if camera.ip_address else None,
                "stream_id": f"stream_{camera.id}"
            })
            
        return {"success": True, "streams": streams}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting collection streams: {e}")
        raise HTTPException(status_code=500, detail="Failed to get collection streams")
