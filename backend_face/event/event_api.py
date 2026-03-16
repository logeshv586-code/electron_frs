from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Request
from pydantic import BaseModel
import os
import shutil
import re
import json 
from typing import List, Optional, Dict
from datetime import datetime
import logging
import face_recognition
import cv2
import numpy as np
from .config import KNOWN_FACES_DIR, UNKNOWN_FACES_DIR
from auth.storage import get_settings
from xhtml2pdf import pisa
from io import BytesIO
from fastapi.responses import Response, StreamingResponse
import matplotlib.pyplot as plt
import base64
from ws_manager import ws_manager
import uuid

def resolve_known_metadata(parts, face_file):
    """
    Extract person_id and camera_name from known face file path
    """
    person_id = None
    camera_name = None
    try:
        # Example path structure: known/companyA/person123/camera1/face_20260314.jpg
        if len(parts) >= 2:
            person_id = parts[-2]
        
        # Extract camera name from filename if available
        filename = os.path.basename(face_file)
        if "_" in filename:
            camera_name = filename.split("_")[0]
            
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.warning(f"[ATTENDANCE] metadata parse failed: {e}")
    return person_id, camera_name

def convert_file_path_to_url(file_path: str) -> str:
    try:
        normalized_path = os.path.normpath(file_path)
        known_root = os.path.normpath(KNOWN_FACES_DIR)
        unknown_root = os.path.normpath(UNKNOWN_FACES_DIR)

        if normalized_path.startswith(known_root):
            relative_path = os.path.relpath(normalized_path, known_root)
            parts = relative_path.split(os.sep)
            image_name = parts[-1]
            if len(parts) >= 4:
                company_id = parts[0]
                camera_name = parts[1]
                person_name = parts[2]
                return f"/api/captured/image/known/{company_id}/{camera_name}/{person_name}/{image_name}"
            if len(parts) >= 3:
                camera_name = parts[0]
                person_name = parts[1]
                return f"/api/captured/image/known/default/{camera_name}/{person_name}/{image_name}"
            return f"/api/captured/image/known/default/default/default/{image_name}"

        if normalized_path.startswith(unknown_root):
            relative_path = os.path.relpath(normalized_path, unknown_root)
            parts = relative_path.split(os.sep)
            image_name = parts[-1]
            if len(parts) >= 3:
                company_id = parts[0]
                camera_name = parts[1]
                return f"/api/captured/image/unknown/{company_id}/{camera_name}/unknown/{image_name}"
            elif len(parts) >= 2:
                camera_name = parts[0]
                return f"/api/captured/image/unknown/default/{camera_name}/unknown/{image_name}"
            return f"/api/captured/image/unknown/default/default/unknown/{image_name}"

        # Robust fallback for cross-platform paths (e.g. Windows paths on Linux)
        path_str = file_path.replace('\\', '/')

        # Try to detect captured known faces
        if 'captured_faces/known/' in path_str:
            parts = path_str.split('captured_faces/known/')
            if len(parts) > 1:
                relative_part = parts[-1]
                path_segments = relative_part.split('/')
                img = path_segments[-1]
                if len(path_segments) >= 2:
                    # Could be camera/person/img or person/img
                    # Usually camera/person/img in full path
                    # Let's try to infer
                    if len(path_segments) >= 3:
                         cam = path_segments[0]
                         person = path_segments[1]
                         return f"/api/captured/image/known/{cam}/{person}/{img}"
                    
                    cam = path_segments[0]
                    person = path_segments[1]
                    return f"/api/captured/image/known/{cam}/{person}/{img}"
                elif len(path_segments) == 1:
                     return f"/api/captured/image/known/default/default/{img}"

        # Try to detect captured unknown faces
        if 'captured_faces/unknown/' in path_str:
            parts = path_str.split('captured_faces/unknown/')
            if len(parts) > 1:
                relative_part = parts[-1]
                path_segments = relative_part.split('/')
                img = path_segments[-1]
                if len(path_segments) >= 1:
                    cam = path_segments[0] if path_segments[0] else "default"
                    return f"/api/captured/image/unknown/{cam}/unknown/{img}"

        return normalized_path
    except Exception as e:
        logger.warning(f"Error converting file path to URL: {file_path}, error: {e}")
        return file_path

router = APIRouter()

logger = logging.getLogger(__name__)

def load_camera_name_map() -> Dict[str, str]:
    """Load cameras and create a mapping from slugified IDs to real names."""
    try:
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cameras_file = os.path.join(backend_dir, "data", "camera_management", "cameras.json")
        
        if os.path.exists(cameras_file):
            with open(cameras_file, 'r') as f:
                cameras = json.load(f)
                mapping = {}
                for cam in cameras:
                    if isinstance(cam, dict):
                        name = cam.get('name', '')
                        if name:
                            mapping[name] = name
                            mapping[name.lower()] = name
                            mapping[name.lower().replace(' ', '_')] = name
                return mapping
    except Exception as e:
        logger.warning(f"Error loading cameras for name mapping: {e}")
    
    return {}

@router.delete("/delete")
async def delete_event(
    request: Request,
    image_path: str = Query(..., description="Path to the event image")
):
    """Delete a specific event image file."""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id")
        
        # Sanitize path
        # If it's a URL, extract the path part if possible, but frontend should send relative path
        clean_path = image_path
        if clean_path.startswith('/api/captured/image/'):
            # Convert URL back to filesystem path (best effort)
             # But it's safer to have frontend send the path it got from the API
             pass
        
        # Check if it's absolute, if not make it relative to BASE_DIR
        abs_path = os.path.normpath(clean_path)
        if not os.path.isabs(abs_path):
            backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            abs_path = os.path.join(backend_root, clean_path)
            
        abs_path = os.path.abspath(abs_path)
        captured_faces_root = os.path.abspath(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "captured_faces"))

        # Safety check: must be inside captured_faces
        if not abs_path.startswith(captured_faces_root):
            raise HTTPException(status_code=403, detail="Forbidden: Cannot delete files outside captured_faces")

        # Multi-tenancy check
        if current_user.get("role") != "SuperAdmin":
            if company_id not in abs_path.replace('\\', '/') and "/default/" not in abs_path.replace('\\', '/'):
                raise HTTPException(status_code=403, detail="Unauthorized to delete this company's data")

        if os.path.exists(abs_path):
            os.remove(abs_path)
            logger.info(f"Event image deleted: {abs_path}")
            return {"status": "success", "message": "Event deleted successfully"}
        else:
             # Try one more fallback: maybe it's just the filename?
             raise HTTPException(status_code=404, detail=f"Event file not found at {abs_path}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting event: {e}")
        raise HTTPException(status_code=500, detail=str(e))

class FaceEvent(BaseModel):
    name: str
    image_path: str
    timestamp: str
    company_id: str = "default"

class FaceMatch(BaseModel):
    image_path: str
    name: str
    confidence: float
    timestamp: str

@router.post("/known")
async def add_known_face(event: FaceEvent):
    """Add a known face event."""
    try:
        company_id = event.company_id or "default"
        # Create company directory if it doesn't exist
        company_dir = os.path.join(KNOWN_FACES_DIR, company_id)
        os.makedirs(company_dir, exist_ok=True)
        
        # Use camera from event or default
        camera_name = "camera_1" # Default fallback
        # In a real scenario, we'd extract camera from path or event
        
        camera_dir = os.path.join(company_dir, camera_name)
        os.makedirs(camera_dir, exist_ok=True)
        
        # Create person directory inside camera directory
        person_dir = os.path.join(camera_dir, event.name)
        os.makedirs(person_dir, exist_ok=True)
        
        # Move the image to the appropriate directory
        destination = os.path.join(person_dir, os.path.basename(event.image_path))
        shutil.move(event.image_path, destination)
        
        # Real-time WebSocket Broadcast
        try:
            image_url = convert_file_path_to_url(destination)
            payload = {
                "type": "RECOGNITION",
                "payload": {
                    "id": str(uuid.uuid4()),
                    "name": event.name,
                    "time": datetime.now().strftime("%H:%M"),
                    "camera": camera_name.replace('_', ' ').title(),
                    "status": "Recognized",
                    "imgColor": "bg-blue-500",
                    "image_url": image_url
                }
            }
            import asyncio
            asyncio.create_task(ws_manager.broadcast(payload, company_id))
        except Exception as ws_err:
            logger.error(f"Failed to broadcast recognition: {ws_err}")

        return {"message": "Known face added successfully"}
    except Exception as e:
        logger.error(f"Error adding known face: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/unknown")
async def add_unknown_face(event: FaceEvent):
    """Add an unknown face event."""
    try:
        company_id = event.company_id or "default"
        # Create company directory if it doesn't exist
        company_dir = os.path.join(UNKNOWN_FACES_DIR, company_id)
        os.makedirs(company_dir, exist_ok=True)
        
        camera_name = "camera_1" # Default fallback
        
        # Create camera directory if it doesn't exist
        camera_dir = os.path.join(company_dir, camera_name)
        os.makedirs(camera_dir, exist_ok=True)
        
        # Move the image to the appropriate directory
        destination = os.path.join(camera_dir, os.path.basename(event.image_path))
        shutil.move(event.image_path, destination)

        # Real-time WebSocket Broadcast
        try:
            image_url = convert_file_path_to_url(destination)
            payload = {
                "type": "ALERT",
                "payload": {
                    "id": str(uuid.uuid4()),
                    "type": "Unknown Person",
                    "time": datetime.now().strftime("%H:%M"),
                    "location": camera_name.replace('_', ' ').title(),
                    "image_url": image_url
                }
            }
            import asyncio
            asyncio.create_task(ws_manager.broadcast(payload, company_id))
        except Exception as ws_err:
            logger.error(f"Failed to broadcast alert: {ws_err}")

        return {"message": "Unknown face added successfully"}
    except Exception as e:
        logger.error(f"Error adding unknown face: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/cameras")
async def get_cameras(request: Request):
    """Get list of available cameras from both known and unknown directories."""
    current_user = request.scope.get("user", {})
    role = current_user.get("role")
    company_id = current_user.get("company_id", "default")
    assigned_cameras = current_user.get("assigned_cameras", [])
    
    cameras = set()
    
    def scan_cameras(base_dir, comp_id):
        target = os.path.join(base_dir, comp_id)
        if os.path.exists(target):
            detected = [d for d in os.listdir(target) 
                       if os.path.isdir(os.path.join(target, d)) 
                       and d.startswith('camera_')]
            cameras.update(detected)
        
        # Fallback for default
        if comp_id == "default" and base_dir == KNOWN_FACES_DIR:
             detected = [d for d in os.listdir(base_dir) 
                         if os.path.isdir(os.path.join(base_dir, d)) 
                         and d.startswith('camera_')]
             cameras.update(detected)

    if role == "SuperAdmin":
        # Scan all company folders
        for base in [KNOWN_FACES_DIR, UNKNOWN_FACES_DIR]:
            if os.path.exists(base):
                for item in os.listdir(base):
                    full_path = os.path.join(base, item)
                    if os.path.isdir(full_path):
                        if item.startswith('camera_'):
                            cameras.add(item)
                        else:
                            scan_cameras(base, item)
    else:
        # Scan specific company
        scan_cameras(KNOWN_FACES_DIR, company_id)
        scan_cameras(UNKNOWN_FACES_DIR, company_id)

    # RBAC: Filter by assigned_cameras if provided
    if assigned_cameras:
        cameras = {c for c in cameras if c in assigned_cameras}
    
    # Sort cameras numerically
    def sort_key(x):
        parts = x.split('_')
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
        return 999

    sorted_cameras = sorted(list(cameras), key=sort_key)
    
    return {"cameras": sorted_cameras}

@router.get("/filter")
async def filter_faces(
    request: Request,
    name: Optional[str] = Query(None, description="Filter by name"),
    from_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format"),
    to_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format"),
    camera: Optional[str] = Query("all_cameras", description="Filter by camera"),
    face_type: Optional[str] = Query(None, description="Filter by face type: known or unknown")
):
    """Filter faces by name, date range, and camera."""
    return await filter_faces_logic(request, name, from_date, to_date, camera, face_type)

async def filter_faces_logic(
    request: Optional[Request] = None,
    name: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    camera: Optional[str] = "all_cameras",
    face_type: Optional[str] = None
):
    current_user = request.scope.get("user", {}) if request else {}
    # SuperAdmin gets None so process_directory scans ALL companies.
    # Regular users without a company_id fall back to "default".
    company_id = current_user.get("company_id")
    if company_id is None and current_user.get("role") != "SuperAdmin":
        company_id = "default"
    
    name_filter = name.lower().strip() if name and isinstance(name, str) else None
    from_date_obj = None
    to_date_obj = None
    face_type_filter = None

    if face_type:
        normalized_face_type = face_type.lower().strip()
        if normalized_face_type not in {"known", "unknown"}:
            raise HTTPException(
                status_code=400,
                detail="Invalid face type. Allowed values are 'known' or 'unknown'"
            )
        face_type_filter = normalized_face_type

    try:
        if from_date:
            from_date_obj = datetime.strptime(from_date, "%Y-%m-%d").date()
        if to_date:
            to_date_obj = datetime.strptime(to_date, "%Y-%m-%d").date()
        if from_date_obj and to_date_obj and from_date_obj > to_date_obj:
            raise HTTPException(
                status_code=400,
                detail="Invalid date range: from_date cannot be later than to_date"
            )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format. Please use YYYY-MM-DD format: {exc}"
        ) from exc

    timestamp_regex = re.compile(r"(\d{8}_\d{6}(?:_\d{3,6})?)")

    def extract_timestamp(face_file: str, img_path: str) -> datetime:
        match = timestamp_regex.search(face_file)
        if match:
            raw = match.group(1)
            for fmt in ("%Y%m%d_%H%M%S_%f", "%Y%m%d_%H%M%S"):
                try:
                    return datetime.strptime(raw, fmt)
                except ValueError:
                    continue
        try:
            return datetime.fromtimestamp(os.path.getmtime(img_path))
        except Exception:
            return datetime.utcnow()

    def resolve_known_metadata(parts: List[str], face_file: str) -> tuple[str, str]:
        image_name = parts[-1] if parts else face_file
        if len(parts) >= 3:
            return parts[1], parts[0]
        if len(parts) >= 2:
            person = parts[-2]
            camera_name = parts[0] if parts[0].lower().startswith("camera_") else "default"
            return person, camera_name
        base_name = os.path.splitext(image_name)[0]
        match = timestamp_regex.search(base_name)
        if match:
            person = base_name[:match.start()].rstrip('_') or "Unknown"
        else:
            splits = base_name.split('_')
            person = splits[0] if splits else base_name
        return person, "default"

    def resolve_unknown_metadata(parts: List[str]) -> str:
        if len(parts) >= 2:
            return parts[0]
        return "default"

    camera_name_map = load_camera_name_map()

    def get_camera_display_name(camera_id: str) -> str:
        if camera_id in camera_name_map:
            return camera_name_map[camera_id]
        if camera_id.lower() in camera_name_map:
            return camera_name_map[camera_id.lower()]
        for cam_key, cam_name in camera_name_map.items():
            if cam_key.lower() == camera_id.lower():
                return cam_name
        if camera_id.lower() == "default":
            return "Default Camera"
        return camera_id.replace('_', ' ').title()

def process_company_directory(company_dir: str, company_id: str, face_type_filter: Optional[str], from_date_obj: Optional[datetime.date], to_date_obj: Optional[datetime.date], name_filter: Optional[str], camera_filter: Optional[str], camera_name_map: Dict[str, str], assigned_cameras: Optional[List[str]] = None) -> List[Dict]:
    """Helper to process events within a specific company directory."""
    faces = []
    
    timestamp_regex = re.compile(r"(\d{8}_\d{6}(?:_\d{3,6})?)")

    def extract_timestamp(face_file: str, img_path: str) -> datetime:
        match = timestamp_regex.search(face_file)
        if match:
            raw = match.group(1)
            for fmt in ("%Y%m%d_%H%M%S_%f", "%Y%m%d_%H%M%S"):
                try:
                    return datetime.strptime(raw, fmt)
                except ValueError:
                    continue
        try:
            return datetime.fromtimestamp(os.path.getmtime(img_path))
        except Exception:
            return datetime.utcnow()

    def resolve_known_metadata(parts: List[str], face_file: str) -> tuple[str, str]:
        image_name = parts[-1] if parts else face_file
        if len(parts) >= 3:
            return parts[1], parts[0]
        if len(parts) >= 2:
            person = parts[-2]
            camera_name = parts[0] if parts[0].lower().startswith("camera_") else "default"
            return person, camera_name
        base_name = os.path.splitext(image_name)[0]
        match = timestamp_regex.search(base_name)
        if match:
            person = base_name[:match.start()].rstrip('_') or "Unknown"
        else:
            splits = base_name.split('_')
            person = splits[0] if splits else base_name
        return person, "default"

    def resolve_unknown_metadata(parts: List[str]) -> str:
        if len(parts) >= 2:
            return parts[0]
        return "default"

    def get_camera_display_name(camera_id: str) -> str:
        if camera_id in camera_name_map:
            return camera_name_map[camera_id]
        if camera_id.lower() in camera_name_map:
            return camera_name_map[camera_id.lower()]
        for cam_key, cam_name in camera_name_map.items():
            if cam_key.lower() == camera_id.lower():
                return cam_name
        if camera_id.lower() == "default":
            return "Default Camera"
        return camera_id.replace('_', ' ').title()

    # Determine directory types to scan
    dir_types = ["known", "unknown"]
    if face_type_filter:
        dir_types = [face_type_filter]

    for directory_type in dir_types:
        scan_base = KNOWN_FACES_DIR if directory_type == "known" else UNKNOWN_FACES_DIR
        # Narrow down to company directory
        target_dir = os.path.join(scan_base, company_id)
        
        if not os.path.exists(target_dir):
            # Legacy fallback: if company_id is "default", try the root
            if company_id == "default" and os.path.exists(scan_base):
                target_dir = scan_base
            else:
                continue

        for root_dir, _, files in os.walk(target_dir):
            # Skip recursion into other company folders if we're at the root of KNOWN_FACES_DIR
            if company_id == "default" and target_dir == scan_base:
                rel = os.path.relpath(root_dir, scan_base)
                if rel != "." and rel.split(os.sep)[0] not in ["camera_1", "camera_2", "camera_3", "default"]:
                    # This looks like it might be another company's folder
                    continue

            for face_file in files:
                if not face_file.lower().endswith((".jpg", ".jpeg", ".png")):
                    continue
                img_path = os.path.join(root_dir, face_file)
                
                timestamp = extract_timestamp(face_file, img_path)
                timestamp_date = timestamp.date()
                if from_date_obj and timestamp_date < from_date_obj:
                    continue
                if to_date_obj and timestamp_date > to_date_obj:
                    continue

                relative_path = os.path.relpath(img_path, target_dir)
                parts = relative_path.split(os.sep)

                if directory_type == "known":
                    person_name, camera_name = resolve_known_metadata(parts, face_file)
                    if name_filter and name_filter not in person_name.lower():
                        continue
                else:
                    camera_name = resolve_unknown_metadata(parts)
                    person_name = "Unknown"
                    if name_filter and name_filter not in "unknown":
                        continue

                mapped_camera_name = get_camera_display_name(camera_name)

                # RBAC: If user has assigned_cameras, only show those unless it's "all_cameras" or SuperAdmin logic already handled it
                if assigned_cameras:
                    # check if camera slug or display name matches any of the assigned IDs
                    if camera_name not in assigned_cameras and mapped_camera_name not in assigned_cameras:
                        continue

                if camera_filter and camera_filter != "all_cameras" and mapped_camera_name != camera_filter:
                    continue

                faces.append({
                    "name": person_name,
                    "image_path": convert_file_path_to_url(img_path),
                    "timestamp": timestamp.isoformat(),
                    "type": directory_type,
                    "camera": mapped_camera_name,
                    "company_id": company_id
                })
    return faces

async def filter_faces_logic(
    request: Optional[Request] = None,
    name: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    camera: Optional[str] = "all_cameras",
    face_type: Optional[str] = None
):
    current_user = request.scope.get("user", {}) if request else {}
    role = current_user.get("role")
    # SuperAdmin should see all companies
    if role == "SuperAdmin":
        company_id = None
    else:
        company_id = current_user.get("company_id", "default")
    
    name_filter = name.lower().strip() if name and isinstance(name, str) else None
    from_date_obj = None
    to_date_obj = None

    try:
        if from_date:
            from_date_obj = datetime.strptime(from_date, "%Y-%m-%d").date()
        if to_date:
            to_date_obj = datetime.strptime(to_date, "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid date format.")

    camera_name_map = load_camera_name_map()
    matching_faces = []

    assigned_cameras = current_user.get("assigned_cameras")

    if company_id is None:
        # SUPERADMIN → scan all company directories
        if os.path.exists(KNOWN_FACES_DIR):
            companies = [d for d in os.listdir(KNOWN_FACES_DIR) if os.path.isdir(os.path.join(KNOWN_FACES_DIR, d))]
            for comp in companies:
                if comp.startswith("camera_") or comp == "__pycache__":
                    continue
                matching_faces.extend(process_company_directory(
                    os.path.join(KNOWN_FACES_DIR, comp), comp, face_type, from_date_obj, to_date_obj, name_filter, camera, camera_name_map, assigned_cameras
                ))
            if "default" not in companies:
                matching_faces.extend(process_company_directory(
                    KNOWN_FACES_DIR, "default", face_type, from_date_obj, to_date_obj, name_filter, camera, camera_name_map, assigned_cameras
                ))
    else:
        # NORMAL TENANT
        matching_faces.extend(process_company_directory(
            os.path.join(KNOWN_FACES_DIR, company_id), company_id, face_type, from_date_obj, to_date_obj, name_filter, camera, camera_name_map, assigned_cameras
        ))

    matching_faces.sort(key=lambda item: item["timestamp"], reverse=True)
    return matching_faces

@router.get("/directories")
async def get_directories():
    """Return the known and unknown faces directories."""
    return {
        "known_faces_dir": KNOWN_FACES_DIR,
        "unknown_faces_dir": UNKNOWN_FACES_DIR
    }

@router.post("/match-face")
async def match_face(request: Request, image: UploadFile = File(...)):
    """Match a face against the database of known faces."""
    try:
        current_user = request.scope.get("user", {})
        role = current_user.get("role")
        company_id = current_user.get("company_id", "default")
        
        # Read and process the uploaded image
        contents = await image.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image file")
            
        # Convert to RGB for face recognition
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        # Get face encodings
        face_locations = face_recognition.face_locations(img_rgb)
        if not face_locations:
            raise HTTPException(status_code=400, detail="No face detected in the image")
            
        face_encoding = face_recognition.face_encodings(img_rgb, face_locations)[0]
        
        # Find matching faces
        matching_faces = []
        
        # Determine paths to scan
        scan_paths = []
        if role == "SuperAdmin":
            scan_paths.append(KNOWN_FACES_DIR)
        else:
            company_path = os.path.join(KNOWN_FACES_DIR, company_id)
            if os.path.exists(company_path):
                scan_paths.append(company_path)
            # Fallback for default
            if company_id == "default" and KNOWN_FACES_DIR not in scan_paths:
                scan_paths.append(KNOWN_FACES_DIR)

        # Walk through directories
        for base_path in scan_paths:
            for root, dirs, files in os.walk(base_path):
                # Skip other company folders if at root
                if base_path == KNOWN_FACES_DIR and role != "SuperAdmin":
                    rel = os.path.relpath(root, KNOWN_FACES_DIR)
                    if rel != "." and rel.split(os.sep)[0] not in ["camera_1", "camera_2", "camera_3", "default"]:
                        continue

                for file in files:
                    if file.lower().endswith(('.jpg', '.jpeg', '.png')):
                        try:
                            # Load and process each image
                            img_path = os.path.join(root, file)
                            known_img = cv2.imread(img_path)
                            if known_img is None:
                                continue
                                
                            known_img_rgb = cv2.cvtColor(known_img, cv2.COLOR_BGR2RGB)
                            known_face_locations = face_recognition.face_locations(known_img_rgb)
                            
                            if known_face_locations:
                                known_face_encodings = face_recognition.face_encodings(known_img_rgb, known_face_locations)
                                
                                # Compare with uploaded face
                                for known_face_encoding in known_face_encodings:
                                    # Compare faces
                                    matches = face_recognition.compare_faces([face_encoding], known_face_encoding, tolerance=0.5)
                                    if matches[0]:
                                        # Calculate face distance (lower is better)
                                        face_distance = face_recognition.face_distance([face_encoding], known_face_encoding)[0]
                                        confidence = 1 - face_distance
                                        
                                        # Only include matches with confidence >= 50%
                                        if confidence >= 0.53:
                                            # Get person name from directory structure
                                            person_name = os.path.basename(os.path.dirname(img_path))
                                            
                                            # Get timestamp from filename
                                            timestamp_str = file.split('_', 1)[1].rsplit('.', 1)[0] if '_' in file else None
                                            try:
                                                if timestamp_str:
                                                    timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                                                else:
                                                    timestamp = datetime.fromtimestamp(os.path.getctime(img_path))
                                            except ValueError:
                                                timestamp = datetime.fromtimestamp(os.path.getctime(img_path))
                                            
                                            matching_faces.append(FaceMatch(
                                                image_path=convert_file_path_to_url(img_path),
                                                name=person_name,
                                                confidence=float(confidence),
                                                timestamp=timestamp.isoformat()
                                            ))
                                        break  # Found a match for this image, move to next
                        except Exception as e:
                            logger.error(f"Error processing {file}: {str(e)}")
                            continue
        
        # Sort matching faces by confidence (highest first)
        matching_faces.sort(key=lambda x: x.confidence, reverse=True)
        
        return matching_faces
        
    except Exception as e:
        logger.error(f"Error matching face: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/match-face-unknown")
async def match_face_unknown(request: Request, image: UploadFile = File(...)):
    """Match a face against the database of unknown faces."""
    try:
        current_user = request.scope.get("user", {})
        role = current_user.get("role")
        company_id = current_user.get("company_id", "default")
        
        # Read and process the uploaded image
        contents = await image.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(status_code=400, detail="Invalid image file")
            
        # Convert to RGB for face recognition
        img_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        
        # Get face encodings
        face_locations = face_recognition.face_locations(img_rgb)
        if not face_locations:
            raise HTTPException(status_code=400, detail="No face detected in the image")
            
        face_encoding = face_recognition.face_encodings(img_rgb, face_locations)[0]
        
        # Find matching faces
        matching_faces = []
        
        # Determine paths to scan
        scan_paths = []
        if role == "SuperAdmin":
            scan_paths.append(UNKNOWN_FACES_DIR)
        else:
            company_path = os.path.join(UNKNOWN_FACES_DIR, company_id)
            if os.path.exists(company_path):
                scan_paths.append(company_path)
            # Fallback for default
            if company_id == "default" and UNKNOWN_FACES_DIR not in scan_paths:
                scan_paths.append(UNKNOWN_FACES_DIR)

        # Walk through unknown faces directory
        for base_path in scan_paths:
            for root, dirs, files in os.walk(base_path):
                # Skip other company folders if at root
                if base_path == UNKNOWN_FACES_DIR and role != "SuperAdmin":
                    rel = os.path.relpath(root, UNKNOWN_FACES_DIR)
                    if rel != "." and rel.split(os.sep)[0] not in ["camera_1", "camera_2", "camera_3", "default"]:
                        continue

                for file in files:
                    if file.lower().endswith(('.jpg', '.jpeg', '.png')):
                        try:
                            # Load and process each image
                            img_path = os.path.join(root, file)
                            unknown_img = cv2.imread(img_path)
                            if unknown_img is None:
                                continue
                                
                            unknown_img_rgb = cv2.cvtColor(unknown_img, cv2.COLOR_BGR2RGB)
                            unknown_face_locations = face_recognition.face_locations(unknown_img_rgb)
                            
                            if unknown_face_locations:
                                unknown_face_encodings = face_recognition.face_encodings(unknown_img_rgb, unknown_face_locations)
                                
                                # Compare with uploaded face
                                for unknown_face_encoding in unknown_face_encodings:
                                    # Compare faces
                                    matches = face_recognition.compare_faces([face_encoding], unknown_face_encoding, tolerance=0.5)
                                    if matches[0]:
                                        # Calculate face distance (lower is better)
                                        face_distance = face_recognition.face_distance([face_encoding], unknown_face_encoding)[0]
                                        confidence = 1 - face_distance
                                        
                                        # Only include matches with confidence >= 50%
                                        if confidence >= 0.53:
                                            # Get camera name from directory structure (if available)
                                            target_dir = UNKNOWN_FACES_DIR
                                            if role != "SuperAdmin":
                                                target_dir = os.path.join(UNKNOWN_FACES_DIR, company_id)
                                                if not os.path.exists(target_dir):
                                                    target_dir = UNKNOWN_FACES_DIR

                                            relative_path = os.path.relpath(img_path, target_dir)
                                            parts = relative_path.split(os.sep)
                                            camera_name = parts[0] if len(parts) >= 2 else "default"
                                            
                                            # Get timestamp from filename
                                            timestamp_str = file.split('_', 1)[1].rsplit('.', 1)[0] if '_' in file else None
                                            try:
                                                if timestamp_str:
                                                    timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")
                                                else:
                                                    timestamp = datetime.fromtimestamp(os.path.getctime(img_path))
                                            except ValueError:
                                                timestamp = datetime.fromtimestamp(os.path.getctime(img_path))
                                            
                                            matching_faces.append(FaceMatch(
                                                image_path=convert_file_path_to_url(img_path),
                                                name="Unknown",
                                                confidence=float(confidence),
                                                timestamp=timestamp.isoformat()
                                            ))
                                        break  # Found a match for this image, move to next
                        except Exception as e:
                            logger.error(f"Error processing {file}: {str(e)}")
                            continue
        
        # Sort matching faces by confidence (highest first)
        matching_faces.sort(key=lambda x: x.confidence, reverse=True)
        
        return matching_faces
        
    except Exception as e:
        logger.error(f"Error matching face against unknown faces: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

def get_metadata():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    metadata_file = os.path.join(base_dir, "data", "metadata.json")
    try:
        with open(metadata_file, 'r') as f:
            return json.load(f)
    except Exception:
        return {}

@router.get("/attendance")
async def get_attendance(
    request: Request,
    target_date: Optional[str] = Query(None, description="Target date in YYYY-MM-DD format")
):
    """Get attendance report for a specific date (Punch In / Punch Out)."""
    return await get_attendance_logic(request, target_date)

async def get_attendance_logic(
    request: Request,
    target_date: Optional[str] = None
):
    try:
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")
            
        target_date_obj = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")

    current_user = request.scope.get("user", {})
    metadata = get_metadata()
    persons = {}
    if "persons" in metadata:
        persons = metadata["persons"]
    else:
        for k, v in metadata.items():
            if k != "persons" and isinstance(v, dict) and 'name' in v:
                persons[k] = v

    # SaaS Filter: Company visibility
    role = current_user.get("role")
    company_id = current_user.get("company_id")

    if role == "SuperAdmin":
        # SuperAdmin sees everyone
        pass
    else:
        # Admins and Supervisors see everyone in their own company
        if company_id:
            persons = {pid: pdata for pid, pdata in persons.items() if pdata.get("company_id") == company_id}
        else:
            # Fallback for users without company_id (legacy)
            username = current_user.get("username")
            persons = {pid: pdata for pid, pdata in persons.items() if pdata.get("created_by") == username or pdata.get("company_id") == "default"}

    # Build attendance dictionary
    attendance_records = {}
    for pid, pdata in persons.items():
        name = pdata.get("name", pid)
        attendance_records[pid] = {
            "s_no": 0,
            "emp_id": pdata.get("emp_id", ""),
            "name": name,
            "department": pdata.get("department", ""),
            "designation": pdata.get("designation", ""),
            "email": pdata.get("email", ""),
            "status": "Absent",
            "punch_in": None,
            "punch_out": None,
            "working_hours": "-",
            "is_late": False,
            "photo_path": pdata.get("photo_path", ""),
            "events": []
        }

    timestamp_regex = re.compile(r"(\d{8}_\d{6}(?:_\d{3,6})?)")
    def extract_ts(face_file: str, img_path: str) -> datetime:
        match = timestamp_regex.search(face_file)
        if match:
            raw = match.group(1)
            for fmt in ("%Y%m%d_%H%M%S_%f", "%Y%m%d_%H%M%S"):
                try:
                    return datetime.strptime(raw, fmt)
                except ValueError:
                    continue
        try:
            return datetime.fromtimestamp(os.path.getmtime(img_path))
        except Exception:
            return datetime.utcnow()

    settings = get_settings().get("attendance", {})
    punch_in_limit = settings.get("punch_in", "09:30")
    LATE_THRESHOLD_HOUR, LATE_THRESHOLD_MINUTE = map(int, punch_in_limit.split(":"))
    TARGET_WORKING_HOURS = settings.get("working_hours", 8)
    GRACE_MINUTES = settings.get("grace_minutes", 15)
    MIN_HOURS_PRESENT = settings.get("min_hours_present", 4.0)

    # Scan KNOWN_FACES_DIR
    role = current_user.get("role")
    company_id = current_user.get("company_id")
    if role == "SuperAdmin":
        company_id = None
        
    assigned_cameras = current_user.get("assigned_cameras")

    camera_name_map = load_camera_name_map()

    def get_camera_display_name(camera_id: str) -> str:
        if camera_id in camera_name_map:
            return camera_name_map[camera_id]
        if camera_id.lower() in camera_name_map:
            return camera_name_map[camera_id.lower()]
        for cam_key, cam_name in camera_name_map.items():
            if cam_key.lower() == camera_id.lower():
                return cam_name
        if camera_id.lower() == "default":
            return "Default Camera"
        return camera_id.replace('_', ' ').title()

    # Reuse logic for scanning company directories
    def scan_for_attendance(comp_id, target_dir):
        if not os.path.exists(target_dir):
            # Fallback for default
            if comp_id == "default" and os.path.exists(KNOWN_FACES_DIR):
                target_dir = KNOWN_FACES_DIR
            else:
                return

        for root_dir, _, files in os.walk(target_dir):
            # Skip other company folders if at root
            if comp_id == "default" and target_dir == KNOWN_FACES_DIR:
                rel = os.path.relpath(root_dir, KNOWN_FACES_DIR)
                if rel != "." and rel.split(os.sep)[0] not in ["camera_1", "camera_2", "camera_3", "default"]:
                    continue

            for face_file in files:
                if not face_file.lower().endswith((".jpg", ".jpeg", ".png")):
                    continue
                img_path = os.path.join(root_dir, face_file)
                ts = extract_ts(face_file, img_path)
                
                if ts.date() != target_date_obj:
                    continue
                
                relative_path = os.path.relpath(img_path, target_dir)
                parts = relative_path.split(os.sep)
                
                # Resolve camera and person
                person_id, camera_name = resolve_known_metadata(parts, face_file)
                mapped_camera_name = get_camera_display_name(camera_name)

                # RBAC: Assigned Cameras check
                if assigned_cameras:
                    if camera_name not in assigned_cameras and mapped_camera_name not in assigned_cameras:
                        continue
                    
                if person_id in attendance_records:
                    attendance_records[person_id]["events"].append(ts)

    if company_id is None:
        # SuperAdmin: scan all
        if os.path.exists(KNOWN_FACES_DIR):
            companies = [d for d in os.listdir(KNOWN_FACES_DIR) if os.path.isdir(os.path.join(KNOWN_FACES_DIR, d))]
            for comp in companies:
                if comp.startswith("camera_") or comp == "__pycache__":
                    continue
                scan_for_attendance(comp, os.path.join(KNOWN_FACES_DIR, comp))
            if "default" not in companies:
                scan_for_attendance("default", KNOWN_FACES_DIR)
    else:
        # Specific company
        scan_for_attendance(company_id, os.path.join(KNOWN_FACES_DIR, company_id))

    # Calculate Punch In / Out and Working Hours
    result_list = []
    s_no = 1
    for pid, record in attendance_records.items():
        events = sorted(record["events"])
        if events:
            punch_in_dt = events[0]
            punch_out_dt = events[-1]
            record["punch_in"] = punch_in_dt.strftime("%I:%M %p")
            record["punch_out"] = punch_out_dt.strftime("%I:%M %p")
            record["status"] = "Present"
            
            # Calculate working hours
            delta = punch_out_dt - punch_in_dt
            total_seconds = max(delta.total_seconds(), 0)
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            record["working_hours"] = f"{hours}h {minutes}m"
            
            # Check if late (using grace period)
            threshold_dt = punch_in_dt.replace(hour=LATE_THRESHOLD_HOUR, minute=LATE_THRESHOLD_MINUTE, second=0, microsecond=0)
            from datetime import timedelta
            if punch_in_dt > (threshold_dt + timedelta(minutes=GRACE_MINUTES)):
                record["is_late"] = True
                record["status"] = "Late"
            
            # Optional: Mark as absent if worked hours < MIN_HOURS_PRESENT
            if total_seconds / 3600 < MIN_HOURS_PRESENT:
                # We can keep 'Present' or 'Late' but maybe add a warning or change status?
                # For now, let's keep the existing status but maybe record['status'] = "Short Attendance" if preferred.
                # The user didn't specify exactly, so let's stick to the late fix.
                pass
        
        del record["events"]
        record["s_no"] = s_no
        s_no += 1
        result_list.append(record)

    return {"date": target_date, "attendance": result_list}

@router.get("/export/dashboard-pdf")
async def export_dashboard_pdf(
    request: Request,
    target_date: Optional[str] = Query(None, description="Target date in YYYY-MM-DD format")
):
    """Export dashboard summary (Stats + Charts + Attendance Table) as PDF."""
    try:
        dashboard_data = await get_dashboard_logic(request, target_date)
        stats = dashboard_data.get("stats", { })
        attendance = dashboard_data.get("attendance", [])
        
        # 1. Generate Summary Chart
        chart_base64 = generate_summary_chart(
            stats.get("present_today", 0), 
            stats.get("absent", 0), 
            stats.get("late", 0)
        )
        
        # 2. Prepare headers and rows for attendance table
        headers = ["Name", "Department", "Punch In", "Status"]
        rows = []
        for r in attendance[:15]: # Limit to top 15 for dashboard summary
            rows.append([
                r.get("name", ""),
                r.get("department", ""),
                r.get("punch_in", "-"),
                r.get("status", "")
            ])
            
        generated_on = datetime.now().strftime("%d %b %Y %I:%M %p")
        title = f"Dashboard Summary Report - {target_date or datetime.now().strftime('%Y-%m-%d')}"
        
        # We can add a "Stats Section" to the HTML specifically for dashboard
        stats_html = f"""
        <div style="display: table; width: 100%; margin-bottom: 20px;">
            <div style="display: table-row;">
                <div style="display: table-cell; width: 33%; padding: 10px; background: #f1f5f9; text-align: center;">
                    <div style="font-size: 8pt; color: #64748b;">TOTAL EMPLOYEES</div>
                    <div style="font-size: 14pt; font-weight: bold; color: #1e293b;">{stats.get("total_employees", 0)}</div>
                </div>
                <div style="display: table-cell; width: 33%; padding: 10px; background: #ecfdf5; text-align: center; border-left: 10px solid white;">
                    <div style="font-size: 8pt; color: #059669;">PRESENT TODAY</div>
                    <div style="font-size: 14pt; font-weight: bold; color: #059669;">{stats.get("present_today", 0)}</div>
                </div>
                <div style="display: table-cell; width: 33%; padding: 10px; background: #fff7ed; text-align: center; border-left: 10px solid white;">
                    <div style="font-size: 8pt; color: #d97706;">LATE TODAY</div>
                    <div style="font-size: 14pt; font-weight: bold; color: #d97706;">{stats.get("late", 0)}</div>
                </div>
            </div>
        </div>
        """
        
        # Build HTML
        header_html = "".join([f"<th>{h}</th>" for h in headers])
        rows_html = "".join(["<tr>" + "".join([f"<td>{cell}</td>" for cell in row]) + "</tr>" for row in rows])
        
        html = f"""
        <html>
        <head>
        <style>
            @page {{ size: a4; margin: 1cm; }}
            body {{ font-family: 'Helvetica', 'Arial', sans-serif; color: #333; line-height: 1.4; }}
            .header {{ text-align: center; border-bottom: 2px solid #1e293b; padding-bottom: 10px; margin-bottom: 20px; }}
            .header h1 {{ margin: 0; color: #1e293b; font-size: 18pt; }}
            .header h2 {{ margin: 5px 0; color: #475569; font-size: 14pt; }}
            .info {{ margin-bottom: 10px; font-size: 9pt; color: #64748b; }}
            .chart-section {{ text-align: center; margin-bottom: 20px; }}
            table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
            th {{ background-color: #1e293b; color: white; text-align: left; padding: 6px; font-size: 9pt; }}
            td {{ border-bottom: 1px solid #e2e8f0; padding: 6px; font-size: 8pt; }}
            tr:nth-child(even) {{ background-color: #f8fafc; }}
            .footer {{ border-top: 1px solid #cbd5e1; padding-top: 10px; margin-top: 20px; text-align: center; font-size: 8pt; color: #64748b; }}
        </style>
        </head>
        <body>
            <div class="header">
                <h1>FACE RECOGNITION SYSTEM</h1>
                <h2>{title}</h2>
            </div>
            <div class="info">Generated On: {generated_on}</div>
            
            {stats_html}

            <div class="chart-section">
                <img src="data:image/png;base64,{chart_base64}" style="width: 300px;">
            </div>

            <h3 style="font-size: 12pt; color: #1e293b; margin-bottom: 10px;">Attendance Highlights</h3>
            <table>
                <thead><tr>{header_html}</tr></thead>
                <tbody>{rows_html}</tbody>
            </table>
            
            <div class="footer">Generated by AI Surveillance System</div>
        </body>
        </html>
        """
        
        pdf_bytes = render_pdf(html)
        if not pdf_bytes:
            raise HTTPException(status_code=500, detail="Failed to generate PDF")
            
        filename = f"dashboard_summary_{target_date or datetime.now().strftime('%Y-%m-%d')}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Error exporting dashboard PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard")
async def get_dashboard(
    request: Request,
    target_date: Optional[str] = Query(None, description="Target date in YYYY-MM-DD format")
):
    """Simplified dashboard query returning combined stats and attendance."""
    return await get_dashboard_logic(request, target_date)

async def get_dashboard_logic(
    request: Request,
    target_date: Optional[str] = None
):
    try:
        if not target_date or not isinstance(target_date, str):
            target_date = datetime.now().strftime("%Y-%m-%d")
        
        # Get stats
        stats = await get_dashboard_stats_logic(request, target_date)
        
        # Get attendance records
        attendance_data = await get_attendance_logic(request, target_date)
        records = attendance_data.get("attendance", [])
        
        return {
            "date": target_date,
            "stats": stats,
            "attendance": records
        }
    except Exception as e:
        logger.error(f"Error getting dashboard data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard-stats")
async def get_dashboard_stats(
    request: Request,
    target_date: Optional[str] = Query(None, description="Target date in YYYY-MM-DD format")
):
    """Get simplified statistics for the dashboard."""
    return await get_dashboard_stats_logic(request, target_date)

async def get_dashboard_stats_logic(
    request: Request,
    target_date: Optional[str] = None
):
    try:
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")
        
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id")
        
        # 1. Total Employees (from registration)
        # We need to call the registration service or metadata directly
        metadata = get_metadata()
        persons = metadata.get("persons", metadata)
        if company_id:
            total_employees = sum(1 for p in persons.values() if p.get("company_id") == company_id)
        elif current_user.get("role") != "SuperAdmin":
            username = current_user.get("username")
            total_employees = sum(1 for p in persons.values() if p.get("created_by") == username)
        else:
            total_employees = len(persons)

        # 2. Present, Absent, Late (from attendance)
        attendance_data = await get_attendance_logic(request, target_date)
        records = attendance_data.get("attendance", [])
        
        # CORRECT — count both Present and Late as "attended"
        present = sum(1 for r in records if r["status"] in ["Present", "Late"])
        absent = total_employees - present
        late = sum(1 for r in records if r.get("is_late", False))
        
        assigned_cameras = current_user.get("assigned_cameras")

        # 3. Cameras Active
        # Count cameras from data/camera_management/cameras.json that match company and assigned_cameras
        cameras_active = 0
        try:
            backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            cameras_file = os.path.join(backend_dir, "data", "camera_management", "cameras.json")
            if os.path.exists(cameras_file):
                with open(cameras_file, 'r') as f:
                    cameras = json.load(f)
                    
                    filtered_cameras = cameras
                    if company_id:
                        filtered_cameras = [c for c in filtered_cameras if c.get("company_id") == company_id]
                    
                    if assigned_cameras:
                        # Map assigned camera IDs/names to those in the config
                        filtered_cameras = [c for c in filtered_cameras if c.get("id") in assigned_cameras or c.get("name") in assigned_cameras]
                        
                    cameras_active = sum(1 for c in filtered_cameras if c.get("status") == "active")
        except Exception as e:
            logger.warning(f"Error counting active cameras: {e}")

        # 4. Recognitions Today (total events for today)
        recognitions_today = 0
        faces = await filter_faces_logic(request, from_date=target_date, to_date=target_date)
        recognitions_today = len(faces)
        
        return {
            "date": target_date,
            "present_today": present,
            "absent": absent,
            "late": late,
            "total_employees": total_employees,
            "cameras_active": cameras_active,
            "recognitions_today": recognitions_today
        }
    except Exception as e:
        logger.error(f"Error getting dashboard stats: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/attendance/weekly")
async def get_weekly_attendance(request: Request):
    """Get attendance summary for the last 7 days."""
    from datetime import timedelta
    result = []
    today = datetime.now().date()
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        day_str = day.strftime("%Y-%m-%d")
        try:
            data = await get_attendance_logic(request, day_str)
            records = data.get("attendance", [])
            present = sum(1 for r in records if r["status"] == "Present")
            absent = len(records) - present
            late = sum(1 for r in records if r.get("is_late", False))
            result.append({
                "date": day_str,
                "day": day.strftime("%a"),
                "present": present,
                "absent": absent,
                "late": late,
                "total": len(records)
            })
        except Exception:
            result.append({"date": day_str, "day": day.strftime("%a"), "present": 0, "absent": 0, "late": 0, "total": 0})
    return {"weekly": result}

@router.get("/attendance/department-stats")
async def get_department_stats(request: Request, target_date: Optional[str] = Query(None)):
    """Get department-wise attendance statistics."""
    try:
        data = await get_attendance_logic(request, target_date)
        records = data.get("attendance", [])
        
        dept_stats = {}
        for r in records:
            dept = r.get("department", "Unknown")
            if dept not in dept_stats:
                dept_stats[dept] = {"present": 0, "total": 0}
            dept_stats[dept]["total"] += 1
            if r["status"] == "Present":
                dept_stats[dept]["present"] += 1
                
        return {"departments": dept_stats}
    except Exception as e:
        logger.error(f"Error getting department stats: {e}")
        return {"departments": {}}

@router.get("/attendance/aggregate")
async def get_attendance_aggregate(
    request: Request,
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format")
):
    """Get aggregated attendance for a date range per employee."""
    try:
        from datetime import datetime, timedelta
        start = datetime.strptime(start_date, "%Y-%m-%d").date()
        end = datetime.strptime(end_date, "%Y-%m-%d").date()
        
        if (end - start).days > 31:
            raise HTTPException(status_code=400, detail="Date range cannot exceed 31 days")
        
        metadata = get_metadata()
        persons = metadata.get("persons", metadata)
        
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id")
        if company_id:
            persons = {pid: pdata for pid, pdata in persons.items() if pdata.get("company_id") == company_id}
        elif current_user.get("role") != "SuperAdmin":
            username = current_user.get("username")
            persons = {pid: pdata for pid, pdata in persons.items() if pdata.get("created_by") == username}

        aggregate = {}
        for pid, pdata in persons.items():
            aggregate[pid] = {
                "emp_id": pdata.get("emp_id", ""),
                "name": pdata.get("name", pid),
                "department": pdata.get("department", ""),
                "designation": pdata.get("designation", ""),
                "email": pdata.get("email", ""),
                "photo_path": pdata.get("photo_path", ""),
                "total_present": 0,
                "total_absent": 0,
                "total_late": 0,
                "total_working_hours": 0
            }
        
        current_date = start
        while current_date <= end:
            day_str = current_date.strftime("%Y-%m-%d")
            try:
                daily_data = await get_attendance_logic(request, day_str)
                for record in daily_data.get("attendance", []):
                    pid = None
                    for dict_pid, pdata in persons.items():
                        if pdata.get("name") == record["name"] and pdata.get("emp_id", "") == record.get("emp_id", ""):
                            pid = dict_pid
                            break
                    if not pid:
                        continue
                    
                    if record["status"] == "Present":
                        aggregate[pid]["total_present"] += 1
                    else:
                        aggregate[pid]["total_absent"] += 1
                        
                    if record.get("is_late", False):
                        aggregate[pid]["total_late"] += 1
                        
                    wh = record.get("working_hours", "-")
                    if wh != "-":
                        parts = wh.replace("h", "").replace("m", "").split()
                        if len(parts) >= 2:
                            secs = int(parts[0]) * 3600 + int(parts[1]) * 60
                            aggregate[pid]["total_working_hours"] += secs
                            
            except Exception as e:
                logger.error(f"Error fetching {day_str}: {e}")
            
            current_date += timedelta(days=1)
            
        result_list = []
        s_no = 1
        for pid, data in aggregate.items():
            total_sec = data["total_working_hours"]
            h = total_sec // 3600
            m = (total_sec % 3600) // 60
            data["avg_working_hours"] = f"{int(h/data['total_present'])}h {int(m/data['total_present'])}m" if data["total_present"] > 0 else "-"
            data["total_working_hours"] = f"{h}h {m}m"
            data["s_no"] = s_no
            s_no += 1
            result_list.append(data)
            
        return {
            "start_date": start_date,
            "end_date": end_date,
            "aggregate": result_list
        }
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Use YYYY-MM-DD")
    except Exception as e:
        logger.error(f"Error in aggregate report: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/attendance/department-stats")
async def get_department_stats(
    request: Request,
    target_date: Optional[str] = Query(None, description="Target date in YYYY-MM-DD format")
):
    """Get attendance stats grouped by department."""
    if not target_date:
        target_date = datetime.now().strftime("%Y-%m-%d")
    
    data = await get_attendance_logic(request, target_date)
    records = data.get("attendance", [])
    
    dept_map = {}
    for r in records:
        dept = r.get("department", "Unknown") or "Unknown"
        if dept not in dept_map:
            dept_map[dept] = {"present": 0, "absent": 0, "total": 0}
        dept_map[dept]["total"] += 1
        if r["status"] == "Present":
            dept_map[dept]["present"] += 1
        else:
            dept_map[dept]["absent"] += 1
    
    return {"date": target_date, "departments": dept_map}

@router.get("/employees/export")
async def export_employees(request: Request):
    """Export employee list as CSV."""
    import csv
    from io import StringIO
    from fastapi.responses import StreamingResponse
    
    current_user = request.scope.get("user", {})
    metadata = get_metadata()
    persons = metadata.get("persons", metadata)
    
    # SaaS Filter
    if current_user.get("role") != "SuperAdmin":
        username = current_user.get("username")
        persons = {pid: pdata for pid, pdata in persons.items() if pdata.get("created_by") == username}
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["Emp ID", "Name", "Email", "Phone", "Department", "Designation", "Role", "Status", "Joining Date"])
    
    for pid, pdata in persons.items():
        if not isinstance(pdata, dict) or 'name' not in pdata:
            continue
        writer.writerow([
            pdata.get("emp_id", ""),
            pdata.get("name", ""),
            pdata.get("email", ""),
            pdata.get("phone", ""),
            pdata.get("department", ""),
            pdata.get("designation", ""),
            pdata.get("role", ""),
            pdata.get("status", "Active"),
            pdata.get("joining_date", "")
        ])
    
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=employees_export.csv"}
    )

@router.get("/attendance/export")
async def export_attendance(
    request: Request,
    target_date: Optional[str] = Query(None, description="Target date in YYYY-MM-DD format")
):
    """Export attendance report for a specific date as CSV."""
    import csv
    from io import StringIO
    from fastapi.responses import StreamingResponse
    
    data = await get_attendance_logic(request, target_date)
    records = data.get("attendance", [])
    
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["S.No", "Emp ID", "Name", "Department", "Designation", "Status", "Punch In", "Punch Out", "Working Hours", "Late"])
    
    for r in records:
        writer.writerow([
            r.get("s_no", ""),
            r.get("emp_id", ""),
            r.get("name", ""),
            r.get("department", ""),
            r.get("designation", ""),
            r.get("status", ""),
            r.get("punch_in", ""),
            r.get("punch_out", ""),
            r.get("working_hours", ""),
            "Yes" if r.get("is_late") else "No"
        ])
    
    output.seek(0)
    filename = f"attendance_report_{target_date or datetime.now().strftime('%Y-%m-%d')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

def render_pdf(html_content: str) -> bytes:
    """Helper to convert HTML to PDF bytes using xhtml2pdf."""
    result = BytesIO()
    # xhtml2pdf doesn't like some complicated CSS, but basic should work
    pdf = pisa.pisaDocument(BytesIO(html_content.encode("UTF-8")), result)
    if not pdf.err:
        return result.getvalue()
    return None

def generate_summary_chart(present, absent, late):
    """Generate a pie chart for attendance summary and return as base64 string."""
    try:
        plt.figure(figsize=(5, 3))
        labels = []
        sizes = []
        colors = []
        
        if present > 0:
            labels.append('Present')
            sizes.append(present)
            colors.append('#10b981')
        if absent > 0:
            labels.append('Absent')
            sizes.append(absent)
            colors.append('#ef4444')
        if late > 0:
            labels.append('Late')
            sizes.append(late)
            colors.append('#f97316')
            
        if not sizes:
             # Default empty chart
             labels = ['No Data']
             sizes = [1]
             colors = ['#e2e8f0']

        plt.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=140, colors=colors)
        plt.axis('equal')
        plt.title('Attendance Summary')
        
        buf = BytesIO()
        plt.savefig(buf, format='png', bbox_inches='tight', dpi=100)
        plt.close()
        return base64.b64encode(buf.getvalue()).decode('utf-8')
    except Exception as e:
        logger.warning(f"Error generating chart: {e}")
        return None

def get_base_html_template(title, generated_on, headers, rows, total_count, chart_base64=None):
    """Generate the base HTML template for reports."""
    header_html = "".join([f"<th>{h}</th>" for h in headers])
    
    rows_html = ""
    for row in rows:
        rows_html += "<tr>"
        for cell in row:
            rows_html += f"<td>{cell}</td>"
        rows_html += "</tr>"

    chart_html = ""
    if chart_base64:
        chart_html = f"""
        <div class="chart-section">
            <img src="data:image/png;base64,{chart_base64}" style="width: 350px;">
        </div>
        """

    return f"""
    <html>
    <head>
    <style>
        @page {{
            size: a4;
            margin: 1cm;
        }}
        body {{
            font-family: 'Helvetica', 'Arial', sans-serif;
            color: #333;
            line-height: 1.4;
        }}
        .header {{
            text-align: center;
            border-bottom: 2px solid #1e293b;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .header h1 {{
            margin: 0;
            color: #1e293b;
            font-size: 18pt;
        }}
        .header h2 {{
            margin: 5px 0;
            color: #475569;
            font-size: 14pt;
        }}
        .info {{
            margin-bottom: 10px;
            font-size: 9pt;
            color: #64748b;
        }}
        .chart-section {{
            text-align: center;
            margin-bottom: 20px;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin-bottom: 20px;
        }}
        th {{
            background-color: #1e293b;
            color: white;
            text-align: left;
            padding: 6px;
            font-size: 9pt;
        }}
        td {{
            border-bottom: 1px solid #e2e8f0;
            padding: 6px;
            font-size: 8pt;
        }}
        tr:nth-child(even) {{
            background-color: #f8fafc;
        }}
        .footer {{
            border-top: 1px solid #cbd5e1;
            padding-top: 10px;
            margin-top: 20px;
            text-align: center;
            font-size: 8pt;
            color: #64748b;
        }}
        .summary {{
            font-weight: bold;
            text-align: right;
            margin-top: 10px;
            font-size: 10pt;
            color: #1e293b;
        }}
    </style>
    </head>
    <body>
        <div class="header">
            <h1>FACE RECOGNITION SYSTEM</h1>
            <h2>{title}</h2>
        </div>
        <div class="info">
            Generated On: {generated_on}
        </div>
        
        {chart_html}

        <table>
            <thead>
                <tr>
                    {header_html}
                </tr>
            </thead>
            <tbody>
                {rows_html}
            </tbody>
        </table>
        <div class="summary">
            Total Records: {total_count}
        </div>
        <div class="footer">
            Generated by AI Surveillance System
        </div>
    </body>
    </html>
    """

@router.get("/export/attendance-pdf")
async def export_attendance_pdf(
    request: Request,
    target_date: Optional[str] = Query(None, description="Target date in YYYY-MM-DD format")
):
    """Export attendance report for a specific date as PDF."""
    data = await get_attendance_logic(request, target_date)
    records = data.get("attendance", [])
    
    headers = ["S.No", "Emp ID", "Name", "Department", "Designation", "Status", "Punch In", "Punch Out", "Working Hours", "Late"]
    rows = []
    for r in records:
        rows.append([
            r.get("s_no", ""),
            r.get("emp_id", ""),
            r.get("name", ""),
            r.get("department", ""),
            r.get("designation", ""),
            r.get("status", ""),
            r.get("punch_in", ""),
            r.get("punch_out", ""),
            r.get("working_hours", ""),
            "Yes" if r.get("is_late") else "No"
        ])
    
    generated_on = datetime.now().strftime("%d %b %Y %I:%M %p")
    
    # Generate chart
    present = sum(1 for r in records if r.get("status") == "Present")
    absent = len(records) - present
    late = sum(1 for r in records if r.get("is_late", False))
    chart_base64 = generate_summary_chart(present, absent, late)
    
    html = get_base_html_template("Daily Attendance Report", generated_on, headers, rows, len(records), chart_base64)
    
    pdf_bytes = render_pdf(html)
    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="Failed to generate PDF")
        
    filename = f"attendance_report_{target_date or datetime.now().strftime('%Y-%m-%d')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/export/employees-pdf")
async def export_employees_pdf(request: Request):
    """Export employee list as PDF."""
    current_user = request.scope.get("user", {})
    metadata = get_metadata()
    persons = metadata.get("persons", metadata)
    
    # SaaS Filter
    if current_user.get("role") != "SuperAdmin":
        username = current_user.get("username")
        persons = {pid: pdata for pid, pdata in persons.items() if pdata.get("created_by") == username}
    
    headers = ["Emp ID", "Name", "Department", "Designation", "Email", "Status"]
    rows = []
    for pid, pdata in persons.items():
        if not isinstance(pdata, dict) or 'name' not in pdata:
            continue
        rows.append([
            pdata.get("emp_id", ""),
            pdata.get("name", ""),
            pdata.get("department", ""),
            pdata.get("designation", ""),
            pdata.get("email", ""),
            pdata.get("status", "Active")
        ])
    
    generated_on = datetime.now().strftime("%d %b %Y %I:%M %p")
    html = get_base_html_template("Employee Registration Report", generated_on, headers, rows, len(persons))
    
    pdf_bytes = render_pdf(html)
    if not pdf_bytes:
        raise HTTPException(status_code=500, detail="Failed to generate PDF")
        
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=employees_report.pdf"}
    )

@router.get("/export/attendance-aggregate-pdf")
async def export_attendance_pdf_aggregate(
    request: Request,
    start_date: str = Query(..., description="Start date in YYYY-MM-DD format"),
    end_date: str = Query(..., description="End date in YYYY-MM-DD format")
):
    """Export aggregated attendance report for a date range as PDF."""
    try:
        data = await get_attendance_aggregate(request, start_date, end_date)
        records = data.get("aggregate", [])
        
        headers = ["S.No", "Emp ID", "Name", "Department", "Designation", "Total Present", "Total Absent", "Total Late", "Total Hrs", "Avg Hrs/Day"]
        rows = []
        for r in records:
            rows.append([
                r.get("s_no", ""),
                r.get("emp_id", ""),
                r.get("name", ""),
                r.get("department", ""),
                r.get("designation", ""),
                r.get("total_present", 0),
                r.get("total_absent", 0),
                r.get("total_late", 0),
                r.get("total_working_hours", "-"),
                r.get("avg_working_hours", "-")
            ])
        
        generated_on = datetime.now().strftime("%d %b %Y %I:%M %p")
        title = f"Attendance Aggregate Report ({start_date} to {end_date})"
        
        # Calculate summary for aggregate chart
        total_p = sum(r.get("total_present", 0) for r in records)
        total_a = sum(r.get("total_absent", 0) for r in records)
        total_l = sum(r.get("total_late", 0) for r in records)
        chart_base64 = generate_summary_chart(total_p, total_a, total_l)
        
        html = get_base_html_template(title, generated_on, headers, rows, len(records), chart_base64)
        
        pdf_bytes = render_pdf(html)
        if not pdf_bytes:
            raise HTTPException(status_code=500, detail="Failed to generate PDF")
            
        filename = f"attendance_aggregate_{start_date}_to_{end_date}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        logger.error(f"Error exporting aggregate PDF: {e}")
        raise HTTPException(status_code=500, detail=str(e))


