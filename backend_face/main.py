from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import logging
import os
import json
import uuid
import time
import cv2
import threading
from typing import Dict, Optional
from face_pipeline import init as init_face_pipeline, process_frame, render_bounding_boxes
from auth.middleware import RBACMiddleware
from auth.routes import router as auth_router
from auth.user_routes import router as user_router
from auth.camera_routes import router as camera_router
from auth.license_checker import start_license_checker
from ws_manager import ws_manager

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
FACE_PIPELINE_READY = False

# Global bounding box settings cache (company_id -> bool)
# Loaded from auth/storage.py on demand
company_bbox_settings: Dict[str, bool] = {}
bbox_lock = threading.Lock()

def get_company_bbox_setting(company_id: Optional[str] = None, stream_id: Optional[str] = None) -> bool:
    """Get bounding box setting, checking stream-specific first then company."""
    try:
        from camera_management.streaming import get_stream_manager
        return get_stream_manager().get_bounding_box(stream_id=stream_id, company_id=company_id)
    except Exception:
        return True

# Create main FastAPI app
app = FastAPI(
    title="Face Recognition System API",
    description="Unified API for face recognition, camera management, registration, and video processing",
    version="1.0.0"
)

async def start_persistent_streams():
    """Start streams for all cameras marked as active in the database"""
    print("\n[DEBUG] Starting persistent streams check...")
    logger.info("Starting persistent streams check...")
    try:
        from camera_management.service import EnhancedCameraService
        from camera_management.streaming import get_stream_manager
        
        # Initialize camera service with absolute path relative to main.py
        base_dir = os.path.dirname(os.path.abspath(__file__))
        data_dir = os.path.join(base_dir, "data", "camera_management")
        print(f"[DEBUG] Loading cameras from: {data_dir}")
        camera_service = EnhancedCameraService(data_dir)
        stream_manager = get_stream_manager()
        
        # Load all cameras
        cameras = camera_service._load_cameras()
        print(f"[DEBUG] Found {len(cameras)} total cameras")
        active_count = 0
        
        for camera in cameras:
            if camera.is_active:
                try:
                    # Check if stream already exists
                    existing_stream = stream_manager.get_camera_stream(camera.id)
                    if not existing_stream:
                        # Start new stream
                        stream_id = stream_manager.start_stream(
                            camera_id=camera.id,
                            rtsp_url=camera.rtsp_url,
                            camera_name=camera.name,
                            company_id=camera.company_id
                        )
                        logger.info(f"✓ Persistent stream started: {camera.name} ({stream_id})")
                        active_count += 1
                    else:
                        logger.info(f"Stream already running for camera: {camera.name}")
                        active_count += 1
                except Exception as stream_err:
                    logger.error(f"✗ Failed to start persistent stream for {camera.name}: {stream_err}")
        
        logger.info(f"Total persistent streams active: {active_count}")
        
    except Exception as e:
        logger.error(f"Error starting persistent streams: {e}")

@app.on_event("startup")
async def startup_event():
    start_license_checker()
    logger.info("License checker background task started")
    
    # Start persistent streams for all active cameras
    await start_persistent_streams()
    
    # Start backup scheduler (non-blocking, handles Redis unavailability gracefully)
    try:
        from backup.backup_service import RedisBackupService
        from backup.backup_scheduler import BackupScheduler
        backup_service = RedisBackupService()
        scheduler = BackupScheduler(backup_service)
        scheduler.start()
        logger.info("✓ Backup scheduler started (monthly backups on 1st)")
    except Exception as e:
        logger.warning(f"⚠ Backup scheduler not started: {e}")
        logger.info("Backup management will work on-demand only (no auto-scheduling)")

    # Start image retention worker
    try:
        from image_retention import start_retention_worker
        start_retention_worker()
        logger.info("✓ Image retention worker started")
    except Exception as e:
        logger.warning(f"⚠ Image retention worker not started: {e}")

# Add RBAC middleware for authentication and authorization
app.add_middleware(RBACMiddleware)

# Configure CORS to allow frontend requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)

# ============= WEBSOCKET ENDPOINT =============

@app.websocket("/ws/recognitions/{company_id}")
async def websocket_endpoint(websocket: WebSocket, company_id: str):
    """
    WebSocket endpoint for real-time recognition events.
    Filtered by company_id for multi-tenancy.
    """
    await ws_manager.connect(websocket, company_id)
    try:
        while True:
            # Keep connection alive and wait for client to disconnect
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket, company_id)
    except Exception as e:
        logger.error(f"WebSocket error for {company_id}: {e}")
        ws_manager.disconnect(websocket, company_id)

# ============= END WEBSOCKET =============

# Mount individual service applications
def mount_services():
    """Mount all service applications"""
    
    # Mount authentication service
    try:
        from auth.company_routes import router as company_router
        app.include_router(auth_router, prefix="/api")
        app.include_router(user_router, prefix="/api")
        app.include_router(camera_router, prefix="/api")
        app.include_router(company_router, prefix="/api")
        logger.info("✓ Authentication and Company services mounted")
    except Exception as e:
        logger.error(f"✗ Failed to mount authentication service: {e}")

    # Mount event service
    try:
        from event.event_api import router as event_router
        app.include_router(event_router, prefix="/api/events", tags=["Events"])
        logger.info("✓ Event service mounted")
    except Exception as e:
        logger.error(f"✗ Failed to mount event service: {e}")

    # Old camera service removed - using enhanced camera management instead
    # Add a basic status endpoint
    @app.get("/api/status", tags=["System"])
    async def get_basic_status():
        """Get basic service status"""
        return {
            "status": "running",
            "camera_service": "enhanced",
            "message": "Using enhanced camera management system"
        }

    # Mount registration service
    try:
        from registration.reg import app as registration_app
        app.mount("/api/registration", registration_app)
        logger.info("✓ Registration service mounted")
    except Exception as e:
        logger.error(f"✗ Failed to mount registration service: {e}")

    # Mount enhanced camera management service
    try:
        from camera_management.routes import router as camera_management_router
        app.include_router(camera_management_router)
        logger.info("✓ Enhanced camera management service mounted")
    except Exception as e:
        logger.error(f"✗ Failed to mount enhanced camera management service: {e}")

    # Mount WebRTC streaming service
    try:
        from webrtc_streaming.routes import router as webrtc_router
        app.include_router(webrtc_router, prefix="/api/webrtc")
        logger.info("✓ WebRTC streaming service mounted")
    except Exception as e:
        logger.error(f"✗ Failed to mount WebRTC streaming service: {e}")
        logger.info("Continuing with basic camera service only")

    # Mount backup management service (SuperAdmin only)
    try:
        from backup.backup_routes import router as backup_router
        app.include_router(backup_router, prefix="/api/backup", tags=["Backup"])
        logger.info("✓ Backup management service mounted")
    except Exception as e:
        logger.error(f"✗ Failed to mount backup service: {e}")
        logger.info("Backup management will be unavailable")

    # Mount matching service
    try:
        from matching.one import app as matching_app
        app.mount("/api/matching", matching_app)
        logger.info("? Matching service mounted")
    except Exception as e:
        logger.error(f"✗ Failed to mount matching service: {e}")

    # Mount video processing service
    try:
        from video.video_thread import app as video_app
        app.mount("/api/video", video_app)
        logger.info("? Video processing service mounted")
    except Exception as e:
        logger.error(f"✗ Failed to mount video processing service: {e}")
        logger.info("Adding basic video endpoints as fallback")

        # Add basic video endpoints as fallback
        from fastapi import UploadFile, File, HTTPException
        import os
        import uuid
        from datetime import datetime

        @app.get("/api/video/formats")
        async def get_video_formats():
            """Get supported video formats"""
            return {
                "formats": ['.mp4', '.avi', '.mov', '.mkv', '.wmv'],
                "max_size": 1024 * 1024 * 100  # 100MB
            }

        @app.post("/api/video/upload")
        async def upload_video_fallback(file: UploadFile = File(...)):
            """Basic video upload endpoint"""
            try:
                # Check file format
                file_ext = os.path.splitext(file.filename)[1].lower()
                if file_ext not in ['.mp4', '.avi', '.mov', '.mkv', '.wmv']:
                    raise HTTPException(
                        status_code=400,
                        detail="Unsupported file format"
                    )

                # Generate file ID
                file_id = str(uuid.uuid4())

                return {
                    "filename": file_id,
                    "size": file.size if hasattr(file, 'size') else 0,
                    "format": file_ext,
                    "status": "uploaded",
                    "message": "Video uploaded successfully. Processing service is currently unavailable."
                }
            except Exception as e:
                logger.error(f"Video upload error: {e}")
                raise HTTPException(status_code=500, detail=str(e))

# Mount all services
mount_services()
# Initialize face pipeline (non-disruptive; skips if unavailable)
# Auto-select GPU when CUDA is available; otherwise use the CPU-safe profile.
try:
    # GPU keeps long-distance detection at 1280. CPU is auto-throttled inside face_pipeline.
    init_face_pipeline(os.path.join(os.path.dirname(__file__), "data"), ctx=-1, det_size=(1280, 1280))
    FACE_PIPELINE_READY = True
    logger.info("? Face pipeline initialized")
except Exception as e:
    FACE_PIPELINE_READY = False
    logger.error(f"? Face pipeline init failed: {e}")
    logger.info("Face recognition will be disabled. Check CUDA/GPU setup if GPU was expected.")

# Configure static file serving for gallery images and captured faces
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
GALLERY_DIR = os.path.join(DATA_DIR, "gallery")
CAPTURED_FACES_DIR = os.path.join(BASE_DIR, "captured_faces")

# API base URL for constructing image URLs
API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8005")

# Create directories if they don't exist
os.makedirs(GALLERY_DIR, exist_ok=True)
os.makedirs(CAPTURED_FACES_DIR, exist_ok=True)

# Mount static files for gallery images and captured faces
app.mount("/static/gallery", StaticFiles(directory=GALLERY_DIR), name="gallery")
app.mount("/static/captured", StaticFiles(directory=CAPTURED_FACES_DIR), name="captured")

# Add endpoint to serve gallery images with error handling
from fastapi import HTTPException
from fastapi.responses import FileResponse

@app.api_route("/api/gallery/image/{company_id}/{person_name}/{image_name:path}", methods=["GET", "HEAD"])
async def get_gallery_image(request: Request, company_id: str, person_name: str, image_name: str):
    """Serve gallery images with proper error handling and fallback"""
    try:
        # Security: Verify company access
        current_user = request.scope.get("user", {})
        user_company_id = current_user.get("company_id")
        user_role = current_user.get("role")
        
        # If no user is found in scope or it's an empty dict, we allow access to public gallery paths
        # (RBACMiddleware already verified it's a public path)
        if current_user and isinstance(current_user, dict) and "company_id" in current_user:
            if user_role != "SuperAdmin" and user_company_id != company_id:
                raise HTTPException(status_code=403, detail="Unauthorized to access this company's gallery")

        # Sanitize the inputs to prevent directory traversal
        person_name = person_name.replace('..', '').replace('/', '').replace('\\', '')
        # Extract just the filename from image_name (in case full path is passed)
        image_name = os.path.basename(image_name)
        image_name = image_name.replace('..', '').replace('/', '').replace('\\', '')

        # Construct the image path
        image_path = os.path.join(GALLERY_DIR, company_id, person_name, image_name)

        # Fallback: If company_id is "default" and folder doesn't exist, check gallery root
        if not os.path.exists(image_path) and company_id == "default":
            root_fallback = os.path.join(GALLERY_DIR, person_name, image_name)
            if os.path.exists(root_fallback):
                image_path = root_fallback
                logger.info(f"Using root gallery fallback for {person_name}/{image_name}")

        # Check if file exists and is within the gallery directory
        if not os.path.exists(image_path):
            # Try fallback images if the requested image doesn't exist
            fallback_names = ['1.jpg', 'original.jpg']
            if image_name not in fallback_names:
                for fallback_name in fallback_names:
                    fallback_path = os.path.join(GALLERY_DIR, company_id, person_name, fallback_name)
                    if os.path.exists(fallback_path):
                        image_path = fallback_path
                        logger.info(f"Using fallback image {fallback_name} for {person_name}/{image_name}")
                        break
                else:
                    raise HTTPException(status_code=404, detail=f"Image not found: {person_name}/{image_name}")
            else:
                raise HTTPException(status_code=404, detail=f"Image not found: {person_name}/{image_name}")

        # Ensure the path is within the gallery directory (security check)
        if not os.path.abspath(image_path).startswith(os.path.abspath(GALLERY_DIR)):
            raise HTTPException(status_code=403, detail="Access denied")

        # Return the image file
        return FileResponse(
            image_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving gallery image {person_name}/{image_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

@app.api_route("/api/gallery/image/{person_name}/{image_name:path}", methods=["GET", "HEAD"])
async def get_gallery_image_legacy(request: Request, person_name: str, image_name: str):
    """Fallback for 2-parameter legacy gallery URLs"""
    return await get_gallery_image(request, "default", person_name, image_name)

@app.api_route("/api/captured/image/{face_type}/{company_id}/{camera}/{person}/{image_name}", methods=["GET", "HEAD"])
async def get_captured_image(request: Request, face_type: str, company_id: str, camera: str, person: str, image_name: str):
    """Serve captured face images with proper error handling"""
    try:
        # Security: Verify company access
        current_user = request.scope.get("user", {})
        user_company_id = current_user.get("company_id")
        user_role = current_user.get("role")
        
        if current_user and isinstance(current_user, dict) and "company_id" in current_user:
            if user_role != "SuperAdmin" and user_company_id != company_id:
                raise HTTPException(status_code=403, detail="Unauthorized to access this company's data")

        # Validate face_type
        if face_type not in ['known', 'unknown']:
            raise HTTPException(status_code=400, detail="Invalid face type. Must be 'known' or 'unknown'")

        # Sanitize the inputs to prevent directory traversal
        camera = camera.replace('..', '').replace('/', '').replace('\\', '')
        person = person.replace('..', '').replace('/', '').replace('\\', '')
        # Extract just the filename from image_name (in case full path is passed)
        image_name = os.path.basename(image_name)
        image_name = image_name.replace('..', '').replace('/', '').replace('\\', '')

        base_dir = os.path.join(CAPTURED_FACES_DIR, face_type, company_id)
        fallback_base_dir = os.path.join(CAPTURED_FACES_DIR, face_type)
        candidates = []

        for b_dir in [base_dir, fallback_base_dir]:
            if camera == "default":
                candidates.append(os.path.join(b_dir, image_name))
                if person and person not in ["default", "unknown"]:
                    candidates.append(os.path.join(b_dir, person, image_name))
            else:
                candidates.append(os.path.join(b_dir, camera, person, image_name))
                candidates.append(os.path.join(b_dir, camera, image_name))
                if person and person not in ["default", "unknown"]:
                    candidates.append(os.path.join(b_dir, person, image_name))

        image_path = next((path for path in candidates if os.path.exists(path)), None)

        if not image_path:
            raise HTTPException(status_code=404, detail="Image not found")

        if not os.path.abspath(image_path).startswith(os.path.abspath(CAPTURED_FACES_DIR)):
            raise HTTPException(status_code=403, detail="Access denied")

        return FileResponse(
            image_path,
            media_type="image/jpeg",
            headers={"Cache-Control": "public, max-age=3600"}
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error serving captured image {face_type}/{camera}/{person}/{image_name}: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")



@app.get("/", tags=["System"])
async def root():
    """Root endpoint"""
    return {
        "message": "Face Recognition System API",
        "version": "1.0.0",
        "status": "running",
        "endpoints": {
            "events": "/api/events",
            "camera": "/api/camera",
            "registration": "/api/register",
            "matching": "/api/match",
            "video": "/api/video",
            "status": "/api/status",
            "health": "/api/health",
            "collections": "/api/collections",
            "analytics": "/api/analytics",
            "capture": "/capture_face_upload or /capture_face_b64"
        }
    }

# ============= ANALYTICS ENDPOINTS =============

@app.get("/api/analytics/overview", tags=["Analytics"])
async def get_analytics_overview(request: Request):
    """Get overall analytics overview"""
    try:
        from event.event_api import filter_faces_logic
        import csv
        
        all_faces = await filter_faces_logic(request=request, name=None, from_date=None, to_date=None, camera="all_cameras", face_type=None)

        total_faces = len(all_faces)
        known_faces = sum(1 for f in all_faces if f["type"] == "known")
        unknown_faces = total_faces - known_faces
        unique_persons = set(f["name"] for f in all_faces if f["type"] == "known" and f["name"] != "Unknown")

        recognition_rate = (known_faces / total_faces * 100) if total_faces > 0 else 0
        
        avg_confidence = 0.85
        # Compute real average confidence from capture logs
        try:
            current_user = request.scope.get("user", {})
            user_company_id = current_user.get("company_id")
            user_role = current_user.get("role")
            
            log_csv_path = os.path.join(CAPTURED_FACES_DIR, "capture_log.csv")
            if os.path.exists(log_csv_path):
                total_conf = 0.0
                count_conf = 0
                with open(log_csv_path, 'r', newline='', encoding='utf-8') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # RBAC
                        if user_role != "SuperAdmin" and row.get("company_id") != user_company_id:
                            continue
                        conf_str = row.get("confidence", "")
                        if conf_str:
                            try:
                                total_conf += float(conf_conf := float(conf_str))
                                count_conf += 1
                            except ValueError:
                                pass
                if count_conf > 0:
                    avg_confidence = total_conf / count_conf
        except Exception as e:
            logger.warning(f"Failed to compute avg_confidence from log: {e}")

        return {
            "total_faces": total_faces,
            "known_faces": known_faces,
            "unknown_faces": unknown_faces,
            "recognition_rate": round(recognition_rate, 2),
            "avg_confidence": round(avg_confidence, 3),
            "unique_persons": len(unique_persons)
        }
    except Exception as e:
        logger.error(f"Error getting analytics overview: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics/face-detection-trend", tags=["Analytics"])
async def get_face_detection_trend(request: Request, days: int = 7):
    """Get face detection trends over time"""
    try:
        from event.event_api import filter_faces_logic
        from datetime import datetime, timedelta
        from collections import defaultdict

        all_faces = await filter_faces_logic(request=request, name=None, from_date=None, to_date=None, camera="all_cameras", face_type=None)
        cutoff_date = datetime.now() - timedelta(days=days)
        daily_stats = defaultdict(lambda: defaultdict(int))

        for face in all_faces:
            try:
                ts = datetime.fromisoformat(face["timestamp"].replace('Z', '+00:00'))
                if ts >= cutoff_date:
                    date_str = ts.date().isoformat()
                    daily_stats[date_str][face["name"]] += 1
            except ValueError:
                continue

        # Prepare data for chart
        dates = sorted(daily_stats.keys())
        known_data = []
        unknown_data = []

        for date in dates:
            stats = daily_stats[date]
            known_count = sum(count for person, count in stats.items() if person.lower() != 'unknown')
            unknown_count = stats.get('Unknown', 0) + stats.get('unknown', 0)
            known_data.append(known_count)
            unknown_data.append(unknown_count)

        return {
            "labels": dates,
            "known": known_data,
            "unknown": unknown_data
        }
    except Exception as e:
        logger.error(f"Error getting face detection trend: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics/confidence-distribution", tags=["Analytics"])
async def get_confidence_distribution(request: Request):
    """Get confidence score distribution"""
    try:
        # Confidence is not strictly available in events mapping, returning placeholder distribution
        labels = ['0-0.2', '0.2-0.4', '0.4-0.6', '0.6-0.8', '0.8-1.0']
        
        from event.event_api import filter_faces_logic
        all_faces = await filter_faces_logic(request=request, name=None, from_date=None, to_date=None, camera="all_cameras", face_type=None)
        
        # Simulate confidence distribution based on known/unknown
        data = [0, 0, 0, 0, 0]
        for f in all_faces:
            if f["type"] == "known":
                data[4] += 1 # 0.8-1.0
            else:
                data[3] += 1 # 0.6-0.8
                
        return {
            "labels": labels,
            "data": data
        }
    except Exception as e:
        logger.error(f"Error getting confidence distribution: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics/person-frequency", tags=["Analytics"])
async def get_person_frequency(request: Request, limit: int = 10):
    """Get most frequently recognized persons"""
    try:
        from event.event_api import filter_faces_logic
        from collections import defaultdict
        
        all_faces = await filter_faces_logic(request=request, name=None, from_date=None, to_date=None, camera="all_cameras", face_type=None)
        person_freq = defaultdict(int)

        for face in all_faces:
            person = face["name"]
            if person.lower() != 'unknown' and face["type"] == "known":
                person_freq[person] += 1

        # Sort by frequency and get top N
        sorted_persons = sorted(person_freq.items(), key=lambda x: x[1], reverse=True)[:limit]

        return {
            "labels": [person for person, count in sorted_persons],
            "data": [count for person, count in sorted_persons]
        }
    except Exception as e:
        logger.error(f"Error getting person frequency: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics/hourly-activity", tags=["Analytics"])
async def get_hourly_activity(request: Request):
    """Get face detection activity by hour of day"""
    try:
        from event.event_api import filter_faces_logic
        from datetime import datetime
        from collections import defaultdict
        
        all_faces = await filter_faces_logic(request=request, name=None, from_date=None, to_date=None, camera="all_cameras", face_type=None)
        hourly_activity = defaultdict(int)

        for face in all_faces:
            try:
                timestamp_dt = datetime.fromisoformat(face["timestamp"].replace('Z', '+00:00'))
                hour = timestamp_dt.hour
                hourly_activity[hour] += 1
            except ValueError:
                continue

        # Fill missing hours with 0
        all_hours = range(24)
        hourly_data = [hourly_activity.get(hour, 0) for hour in all_hours]

        return {
            "labels": [f"{h:02d}:00" for h in all_hours],
            "data": hourly_data
        }
    except Exception as e:
        logger.error(f"Error getting hourly activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics/camera-activity", tags=["Analytics"])
async def get_camera_activity(request: Request):
    """Get face detection activity by camera/source"""
    try:
        from event.event_api import filter_faces_logic
        from collections import defaultdict
        
        all_faces = await filter_faces_logic(request=request, name=None, from_date=None, to_date=None, camera="all_cameras", face_type=None)
        camera_activity = defaultdict(int)

        for face in all_faces:
            camera_activity[face.get("camera", "default")] += 1

        return {
            "labels": list(camera_activity.keys()),
            "data": list(camera_activity.values())
        }
    except Exception as e:
        logger.error(f"Error getting camera activity: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics/top-persons", tags=["Analytics"])
async def get_top_persons(request: Request, limit: int = 5):
    """Get top detected persons (alias for person-frequency)"""
    return await get_person_frequency(request, limit)

@app.get("/api/analytics/detections-over-time", tags=["Analytics"])
async def get_detections_over_time(request: Request, days: int = 7):
    """Get detections over time (alias for face-detection-trend)"""
    return await get_face_detection_trend(request, days)

@app.get("/api/analytics/face-types", tags=["Analytics"])
async def get_face_types(request: Request):
    """Get distribution of face types (Known vs Unknown)"""
    try:
        overview = await get_analytics_overview(request)
        return {
            "labels": ["Known Faces", "Unknown Faces"],
            "data": [overview["known_faces"], overview["unknown_faces"]]
        }
    except Exception as e:
        logger.error(f"Error getting face types: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics/persons-list", tags=["Analytics"])
async def get_persons_list(request: Request):
    """Get list of all persons with their profile images and basic stats"""
    try:
        from event.event_api import filter_faces_logic
        from collections import defaultdict
        from datetime import datetime

        all_faces = await filter_faces_logic(request=request, name=None, from_date=None, to_date=None, camera="all_cameras", face_type=None)
        persons_data = defaultdict(lambda: {
            "count": 0,
            "avg_confidence": 0.0,
            "last_seen": None,
            "first_seen": None,
            "total_confidence": 0.0,
            "image_url": None
        })

        for face in all_faces:
            person = face["name"]
            if person.lower() == 'unknown' or face["type"] != "known":
                continue
            
            persons_data[person]["count"] += 1
            persons_data[person]["total_confidence"] += 0.85
            
            try:
                ts = datetime.fromisoformat(face["timestamp"].replace('Z', '+00:00'))
                if persons_data[person]["last_seen"] is None or ts > persons_data[person]["last_seen"]:
                    persons_data[person]["last_seen"] = ts
                if persons_data[person]["first_seen"] is None or ts < persons_data[person]["first_seen"]:
                    persons_data[person]["first_seen"] = ts
            except ValueError:
                pass

        # Calculate averages and get profile images
        result = []
        for person_name, data in persons_data.items():
            if data["count"] > 0:
                data["avg_confidence"] = round(data["total_confidence"] / data["count"], 3)
            
            # Find an image URL from events data since it has one
            profile_image = next((f["image_path"] for f in all_faces if f["name"] == person_name), None)

            result.append({
                "name": person_name,
                "count": data["count"],
                "avg_confidence": data["avg_confidence"],
                "last_seen": data["last_seen"].isoformat() if data["last_seen"] else None,
                "first_seen": data["first_seen"].isoformat() if data["first_seen"] else None,
                "profile_image": profile_image
            })

        # Sort by count (most frequent first)
        result.sort(key=lambda x: x["count"], reverse=True)
        return result
    except Exception as e:
        logger.error(f"Error getting persons list: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/analytics/person/{person_name}", tags=["Analytics"])
async def get_person_analytics(request: Request, person_name: str):
    """Get detailed analytics for a specific person"""
    try:
        from event.event_api import filter_faces_logic
        from datetime import datetime, timedelta
        from collections import defaultdict

        all_faces = await filter_faces_logic(request=request, name=None, from_date=None, to_date=None, camera="all_cameras", face_type=None)
        person_faces = [f for f in all_faces if f["name"] == person_name and f["type"] == "known"]

        if not person_faces:
            return {
                "name": person_name,
                "total_detections": 0,
                "avg_confidence": 0,
                "dynamic_recognition": 0,
                "output_intensity": 0,
                "output_volume": 0,
                "basic_info": 0,
                "hourly_distribution": [],
                "daily_distribution": [],
                "camera_distribution": {},
                "recent_images": []
            }

        total_detections = len(person_faces)
        total_confidence = 0.85 * total_detections # dummy fallback since no confidence
        hourly_dist = defaultdict(int)
        daily_dist = defaultdict(int)
        camera_dist = defaultdict(int)
        recent_images = []
        last_7_days = datetime.now() - timedelta(days=7)

        for face in person_faces:
            try:
                ts = datetime.fromisoformat(face["timestamp"].replace('Z', '+00:00'))
                hour = ts.hour
                date_str = ts.date().isoformat()
                hourly_dist[hour] += 1
                daily_dist[date_str] += 1
                
                if ts >= last_7_days:
                    recent_images.append({
                        "url": face.get("image_path"),
                        "timestamp": ts.isoformat(),
                        "confidence": 0.85
                    })
            except ValueError:
                pass

            camera_dist[face.get("camera", "default")] += 1

        avg_confidence = total_confidence / total_detections if total_detections > 0 else 0
        
        dynamic_recognition = min(100, int((total_detections / max(1, len(daily_dist))) * 10))
        output_intensity = min(100, int(avg_confidence * 100))
        output_volume = total_detections
        basic_info = min(100, int((len(camera_dist) / 10) * 100))

        recent_images.sort(key=lambda x: x["timestamp"], reverse=True)
        recent_images = recent_images[:10]

        hourly_data = [hourly_dist.get(h, 0) for h in range(24)]
        
        daily_labels = []
        daily_data = []
        for i in range(7):
            date = (datetime.now() - timedelta(days=i)).date().isoformat()
            daily_labels.append(date)
            daily_data.append(daily_dist.get(date, 0))
        daily_labels.reverse()
        daily_data.reverse()

        return {
            "name": person_name,
            "total_detections": total_detections,
            "avg_confidence": round(avg_confidence, 3),
            "dynamic_recognition": dynamic_recognition,
            "output_intensity": output_intensity,
            "output_volume": output_volume,
            "basic_info": basic_info,
            "hourly_distribution": hourly_data,
            "daily_distribution": {
                "labels": daily_labels,
                "data": daily_data
            },
            "camera_distribution": dict(camera_dist),
            "recent_images": recent_images
        }
    except Exception as e:
        logger.error(f"Error getting person analytics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

def convert_file_path_to_url(file_path: str) -> str:
    """Convert file path to API URL"""
    try:
        if not file_path:
            return ""
        
        normalized_path = os.path.normpath(file_path)
        
        # Check if it's a gallery image
        gallery_dir = os.path.normpath(GALLERY_DIR)
        if normalized_path.startswith(gallery_dir):
            relative_path = os.path.relpath(normalized_path, gallery_dir)
            parts = relative_path.split(os.sep)
            if len(parts) >= 2:
                person_name = parts[0]
                image_name = parts[-1]
                return f"{API_BASE_URL}/api/gallery/image/default/{person_name}/{image_name}"
        
        # Check if it's a captured face (known)
        known_faces_dir = os.path.join(CAPTURED_FACES_DIR, "known")
        known_dir = os.path.normpath(known_faces_dir)
        if normalized_path.startswith(known_dir):
            relative_path = os.path.relpath(normalized_path, known_dir)
            parts = relative_path.split(os.sep)
            image_name = os.path.basename(normalized_path)
            if len(parts) >= 2:
                camera_name = parts[0]
                person_name = parts[1] if len(parts) > 1 else "default"
                return f"{API_BASE_URL}/api/captured/image/known/{camera_name}/{person_name}/{image_name}"
            elif len(parts) == 1:
                return f"{API_BASE_URL}/api/captured/image/known/default/default/{image_name}"
        
        # Check if it's a captured face (unknown)
        unknown_faces_dir = os.path.join(CAPTURED_FACES_DIR, "unknown")
        unknown_dir = os.path.normpath(unknown_faces_dir)
        if normalized_path.startswith(unknown_dir):
            relative_path = os.path.relpath(normalized_path, unknown_dir)
            parts = relative_path.split(os.sep)
            image_name = os.path.basename(normalized_path)
            if len(parts) >= 1:
                camera_name = parts[0] if parts[0] else "default"
                return f"{API_BASE_URL}/api/captured/image/unknown/{camera_name}/unknown/{image_name}"

        # Robust fallback for cross-platform paths (e.g. Windows paths on Linux)
        path_str = file_path.replace('\\', '/')
        
        # Try to detect gallery images
        if 'gallery/' in path_str:
            parts = path_str.split('gallery/')
            if len(parts) > 1:
                relative_part = parts[-1]
                path_segments = relative_part.split('/')
                if len(path_segments) >= 2:
                    person = path_segments[0]
                    img = path_segments[-1]
                    return f"{API_BASE_URL}/api/gallery/image/default/{person}/{img}"

        # Try to detect captured known faces
        if 'captured_faces/known/' in path_str:
            parts = path_str.split('captured_faces/known/')
            if len(parts) > 1:
                relative_part = parts[-1]
                path_segments = relative_part.split('/')
                img = path_segments[-1]
                if len(path_segments) >= 2:
                    cam = path_segments[0]
                    person = path_segments[1]
                    return f"{API_BASE_URL}/api/captured/image/known/{cam}/{person}/{img}"
                elif len(path_segments) == 1:
                    # Maybe just person/image or just image? Assume default structure
                    return f"{API_BASE_URL}/api/captured/image/known/default/default/{img}"

        # Try to detect captured unknown faces
        if 'captured_faces/unknown/' in path_str:
            parts = path_str.split('captured_faces/unknown/')
            if len(parts) > 1:
                relative_part = parts[-1]
                path_segments = relative_part.split('/')
                img = path_segments[-1]
                if len(path_segments) >= 1:
                    cam = path_segments[0] if path_segments[0] else "default"
                    return f"{API_BASE_URL}/api/captured/image/unknown/{cam}/unknown/{img}"
        
        return normalized_path
    except Exception as e:
        logger.warning(f"Error converting file path to URL: {file_path}, error: {e}")
        return file_path

# ============= FACE CAPTURE ENDPOINTS =============

class CaptureBase64(BaseModel):
    """Pydantic model for base64 face capture requests"""
    image_b64: str
    label: str = "unknown"
    confidence: Optional[float] = None

@app.post("/capture_face_upload", tags=["Face Capture"])
async def capture_face_upload(file: UploadFile = File(...), label: str = Form("unknown"), confidence: float = Form(None)):
    """
    Upload a face image file and save it to captured_faces.
    
    Parameters:
    - file: JPEG/PNG image file
    - label: Person name/label for the face (default: "unknown")
    - confidence: Optional confidence score (0.0-1.0)
    """
    try:
        from save_face import save_face_image
        import numpy as np
        
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image format")
        
        saved = save_face_image(img, label, confidence=confidence, source="upload")
        
        return {
            "saved": bool(saved),
            "path": str(saved) if saved else None,
            "label": label,
            "source": "upload"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading face image: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save face: {str(e)}")

@app.post("/capture_face_b64", tags=["Face Capture"])
async def capture_face_b64(payload: CaptureBase64):
    """
    Capture face from base64 encoded image (typically from frontend video element).
    
    JSON payload:
    {
        "image_b64": "data:image/jpeg;base64,...",
        "label": "person_name",
        "confidence": 0.95
    }
    """
    try:
        from save_face import save_face_image
        import base64
        import numpy as np
        
        image_b64 = payload.image_b64
        label = payload.label
        confidence = payload.confidence
        
        if not image_b64:
            raise HTTPException(status_code=400, detail="No image_b64 provided")
        
        # Handle data URL prefix (e.g., "data:image/jpeg;base64,...")
        header, data = (image_b64.split(",", 1) if "," in image_b64 else (None, image_b64))
        img_data = base64.b64decode(data)
        nparr = np.frombuffer(img_data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image format")
        
        saved = save_face_image(img, label, confidence=confidence, source="upload")
        
        return {
            "saved": bool(saved),
            "path": str(saved) if saved else None,
            "label": label,
            "source": "upload_b64"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error capturing face from base64: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to save face: {str(e)}")

# Simple stream management for compatibility with working implementation
active_streams: Dict[str, Dict] = {}
stream_lock = threading.Lock()

class SimpleRTSPStream:
    """Simple RTSP stream handler for MJPEG streaming"""

    def __init__(self, rtsp_url: str, stream_id: str):
        self.rtsp_url = rtsp_url
        self.stream_id = stream_id
        self.cap = None
        self.is_running = False
        self.lock = threading.Lock()
        self.last_frame = None
        self.thread = None

    def start(self):
        """Start the RTSP stream capture in a separate thread"""
        with self.lock:
            if self.is_running:
                return

            self.is_running = True
            self.thread = threading.Thread(target=self._capture_frames, daemon=True)
            self.thread.start()
            logger.info(f"Started RTSP stream for {self.rtsp_url}")

    def stop(self):
        """Stop the RTSP stream capture"""
        with self.lock:
            self.is_running = False
            if self.cap:
                self.cap.release()
                self.cap = None
            logger.info(f"Stopped RTSP stream for {self.rtsp_url}")

    def _capture_frames(self):
        """Continuously capture frames from RTSP stream"""
        retry_count = 0
        max_retries = 5

        while self.is_running:
            try:
                if self.cap is None or not self.cap.isOpened():
                    logger.info(f"Connecting to RTSP stream: {self.rtsp_url}")
                    # Handle camera index (0, 1, 2, etc.) vs RTSP URL
                    if isinstance(self.rtsp_url, str) and self.rtsp_url.isdigit():
                        import platform
                        # On Windows, use DirectShow for USB cameras to avoid MSMF errors
                        if platform.system() == 'Windows':
                            self.cap = cv2.VideoCapture(int(self.rtsp_url), cv2.CAP_DSHOW)
                        else:
                            self.cap = cv2.VideoCapture(int(self.rtsp_url))
                    else:
                        self.cap = cv2.VideoCapture(self.rtsp_url)

                    if self.cap.isOpened():
                        # Optimized for Tesla T4: High quality capture settings
                        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)  # Minimal buffering for low latency
                        self.cap.set(cv2.CAP_PROP_FPS, 30)  # Higher FPS for smoother streams
                        # Maximize resolution for Tesla T4
                        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
                        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
                        logger.info(f"Successfully connected to RTSP stream")
                        retry_count = 0
                    else:
                        raise Exception("Failed to open camera")

                # Read frame
                ret, frame = self.cap.read()

                if ret and frame is not None and frame.size > 0:
                    with self.lock:
                        self.last_frame = frame.copy()
                    retry_count = 0
                else:
                    retry_count += 1
                    if retry_count >= max_retries:
                        logger.error(f"Too many consecutive failures for stream {self.stream_id}")
                        if self.cap:
                            self.cap.release()
                            self.cap = None
                        time.sleep(2)
                        retry_count = 0
                        continue

                # Control frame rate
                time.sleep(0.04)  # ~25 FPS

            except Exception as e:
                logger.error(f"Error in RTSP capture for {self.rtsp_url}: {e}")
                if self.cap:
                    self.cap.release()
                    self.cap = None
                time.sleep(2)

    def get_frame(self) -> Optional[bytes]:
        """Get the latest frame as JPEG bytes"""
        with self.lock:
            if self.last_frame is not None:
                try:
                    # Balanced JPEG quality for smooth streaming
                    _, buffer = cv2.imencode('.jpg', self.last_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    return buffer.tobytes()
                except Exception as e:
                    logger.error(f"Error encoding frame: {e}")
                    return None
            return None

def generate_mjpeg_stream(stream_id: str):
    """Generate MJPEG stream for a given stream ID"""
    if stream_id not in active_streams:
        logger.error(f"Stream {stream_id} not found")
        return

    stream = active_streams[stream_id]['stream']
    logger.info(f"Starting MJPEG stream generation for {stream_id}")
    frame_index = 0
    last_detections = []
    last_detection_time = 0.0
    process_every_n = 4
    try:
        from face_pipeline import get_runtime_profile
        process_every_n = int(get_runtime_profile().get("process_every_n", process_every_n))
    except Exception:
        pass

    try:
        while True:
            # Prefer raw frame for processing if pipeline ready
            frame = None
            if FACE_PIPELINE_READY:
                try:
                    with stream.lock:
                        frame = stream.last_frame.copy() if getattr(stream, 'last_frame', None) is not None else None
                except Exception:
                    frame = None

            if frame is not None:
                frame_index += 1
                processed_frame = frame
                try:
                    stream_company_id = active_streams.get(stream_id, {}).get('company_id')
                    detections = last_detections
                    if frame_index % process_every_n == 0:
                        processed_frame, detections = process_frame(
                            frame, stream_id=stream_id, company_id=stream_company_id
                        )
                        last_detections = detections or []
                        last_detection_time = time.time()
                    elif time.time() - last_detection_time > 0.9:
                        detections = []
                        last_detections = []
                    # Broad diagnostic: Are we detecting anything?
                    if detections:
                        logger.debug(f"[BBOX-MAIN-PRE] Detected {len(detections)} faces for {stream_id}")
                    
                    # Only render when faces were actually detected in THIS frame.
                    # An empty list or None means no faces – skip entirely.
                    # Get bounding box setting for this stream's company
                    show_bbox = get_company_bbox_setting(company_id=stream_company_id, stream_id=stream_id)
                    
                    if show_bbox and detections:
                        logger.debug(f"[BBOX-MAIN] detections={len(detections)}, company={stream_company_id}")
                        processed_frame = render_bounding_boxes(
                            processed_frame, detections, show_bounding_box=True
                        )
                except Exception as e:
                    logger.warning(f"Face pipeline processing error for {stream_id}: {e}")
                    processed_frame = frame  # fall back to raw frame
                try:
                    _, buffer = cv2.imencode('.jpg', processed_frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + buffer.tobytes() + b'\r\n')
                except Exception as e:
                    logger.error(f"Error encoding processed frame for {stream_id}: {e}")
                    time.sleep(0.033)
                continue

            # Fallback: use existing encoded frame path (no changes to behavior)
            frame_data = stream.get_frame()
            if frame_data:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_data + b'\r\n')
            else:
                # Send a small delay if no frame is available
                time.sleep(0.033)  # ~30 FPS
    except Exception as e:
        logger.error(f"Error in MJPEG stream generation for {stream_id}: {e}")
        return

@app.get("/api/video_feed/{stream_id}")
async def video_feed(stream_id: str):
    """Serve MJPEG video feed for a specific stream"""
    logger.info(f"Video feed requested for stream: {stream_id}")

    if stream_id not in active_streams:
        logger.error(f"Stream {stream_id} not found in active streams")
        return JSONResponse({"error": "Stream not found"}, status_code=404)

    stream = active_streams[stream_id]['stream']
    if not stream.is_running:
        logger.error(f"Stream {stream_id} is not running")
        return JSONResponse({"error": "Stream not running"}, status_code=404)

    logger.info(f"Serving MJPEG video feed for stream: {stream_id}")
    return StreamingResponse(
        generate_mjpeg_stream(stream_id),
        media_type='multipart/x-mixed-replace; boundary=frame',
        headers={
            'Cache-Control': 'no-cache, no-store, must-revalidate',
            'Pragma': 'no-cache',
            'Expires': '0'
        }
    )

@app.get("/api/get_stream_for_camera")
async def get_stream_for_camera(camera_ip: str, collection_name: str = None):
    """Get existing stream information for a camera"""
    try:
        # Generate consistent stream ID
        if not collection_name:
            collection_name = 'default'

        consistent_stream_id = f"{collection_name}_{camera_ip}"

        # Check if stream already exists
        if consistent_stream_id in active_streams:
            existing_stream = active_streams[consistent_stream_id]
            if existing_stream['stream'].is_running:
                return JSONResponse({
                    "success": True,
                    "stream_id": consistent_stream_id,
                    "feed_url": f"/api/video_feed/{consistent_stream_id}",
                    "exists": True,
                    "is_running": True
                })

        return JSONResponse({
            "success": True,
            "stream_id": consistent_stream_id,
            "feed_url": f"/api/video_feed/{consistent_stream_id}",
            "exists": False,
            "is_running": False
        })

    except Exception as e:
        logger.error(f"Error getting stream for camera: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/start_stream")
async def start_stream(request: Request):
    """Start a new RTSP stream"""
    try:
        body = await request.json()
        rtsp_url = body.get("rtsp_url")
        stream_id = body.get("stream_id")

        if not rtsp_url or not stream_id:
            return JSONResponse({"error": "rtsp_url and stream_id are required"}, status_code=400)

        # Check if stream already exists and is running
        if stream_id in active_streams:
            existing_stream = active_streams[stream_id]
            if existing_stream['stream'].is_running and existing_stream['rtsp_url'] == rtsp_url:
                logger.debug(f"Stream {stream_id} already exists and running, reusing...")
                return JSONResponse({
                    "success": True,
                    "stream_id": stream_id,
                    "feed_url": f"/api/video_feed/{stream_id}",
                    "reused": True
                })
            else:
                # Stop existing stream if URL is different or not running
                logger.info(f"Stopping existing stream {stream_id}")
                existing_stream['stream'].stop()
                del active_streams[stream_id]

        # Create new stream
        logger.info(f"Creating new stream {stream_id} for URL: {rtsp_url}")
        stream = SimpleRTSPStream(rtsp_url, stream_id)
        stream.start()

        active_streams[stream_id] = {
            'stream': stream,
            'rtsp_url': rtsp_url,
            'company_id': body.get("company_id"),
            'created_at': time.time()
        }

        logger.info(f"Started stream {stream_id} for URL: {rtsp_url}")

        return JSONResponse({
            "success": True,
            "stream_id": stream_id,
            "feed_url": f"/api/video_feed/{stream_id}"
        })

    except Exception as e:
        logger.error(f"Error starting stream: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.delete("/api/stop_stream/{stream_id}")
async def stop_stream(stream_id: str):
    """Stop a specific stream"""
    try:
        if stream_id in active_streams:
            active_streams[stream_id]['stream'].stop()
            del active_streams[stream_id]
            logger.info(f"Stopped stream {stream_id}")
            return JSONResponse({"success": True, "message": f"Stream {stream_id} stopped"})
        else:
            return JSONResponse({"error": "Stream not found"}, status_code=404)
    except Exception as e:
        logger.error(f"Error stopping stream {stream_id}: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)

@app.options("/api/{full_path:path}")
async def options_handler(full_path: str):
    """Handle OPTIONS requests for CORS preflight"""
    return {"message": "OK"}

# ============= BOUNDING BOX TOGGLE ENDPOINTS =============

class BoundingBoxToggle(BaseModel):
    """Pydantic model for bounding box toggle request"""
    enabled: bool
    stream_id: Optional[str] = None
    camera_id: Optional[int] = None

@app.post("/api/bounding-box/toggle", tags=["Visualization"])
async def toggle_bounding_box(request: Request, payload: BoundingBoxToggle):
    """Toggle bounding box visualization on the video stream.
    
    When enabled, bounding boxes are drawn on detected faces.
    When disabled, the video stream is shown without any overlays.
    This does NOT affect detection, recognition, or event-saving.
    Optionally accepts stream_id for per-camera control.
    """
    current_user = request.scope.get("user", {})
    company_id: Optional[str] = None
    if current_user.get("role") != "SuperAdmin":
        company_id = current_user.get("company_id")
    else:
        company_id = "default"
        
    company_id = company_id if company_id and str(company_id).strip() else "default"
    
    # Update stream manager with per-stream or per-company toggle
    try:
        from camera_management.streaming import get_stream_manager
        get_stream_manager().set_bounding_box(
            enabled=payload.enabled,
            stream_id=payload.stream_id,
            company_id=company_id,
            camera_id=payload.camera_id
        )
        logger.debug(f"[BBOX-TOGG] {payload.enabled} for stream={payload.stream_id} company={company_id}")
    except Exception as e:
        logger.error(f"Error updating stream manager bbox: {e}")
        
    return {"status": "success", "show_bounding_box": payload.enabled, "stream_id": payload.stream_id}

@app.get("/api/bounding-box/status", tags=["Visualization"])
async def get_bounding_box_status(request: Request, stream_id: Optional[str] = None):
    """Get current bounding box toggle state, optionally per-stream."""
    user = request.scope.get("user", {})
    company_id = user.get("company_id", "default")
    enabled = get_company_bbox_setting(company_id=company_id, stream_id=stream_id)
    return {"enabled": enabled, "company_id": company_id, "stream_id": stream_id}

if __name__ == "__main__":
    import uvicorn
    logger.info("Starting unified Face Recognition System API on port 8005")
    uvicorn.run(app, host="0.0.0.0", port=8005)
