from pydantic import BaseModel, validator
from pydantic import BaseModel, validator
from typing import Optional, List, Dict, Any
from datetime import datetime
import re
import ipaddress

class CameraCollection(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    camera_count: int = 0

class CollectionCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    
    @validator('name')
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Collection name is required")
        return v.strip()

class CollectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    
    @validator('name')
    def validate_name(cls, v):
        if v is not None and (not v or not v.strip()):
            raise ValueError("Collection name cannot be empty")
        return v.strip() if v else None

class CameraValidationRequest(BaseModel):
    ip: str
    streamUrl: str
    collection_name: Optional[str] = None
    exclude_ip: Optional[str] = None

class CameraValidationResponse(BaseModel):
    valid: bool
    error: Optional[str] = None
    type: Optional[str] = None
    existingCollection: Optional[str] = None

class EnhancedCamera(BaseModel):
    id: int
    name: str
    rtsp_url: str
    collection_id: Optional[str] = None
    collection_name: Optional[str] = None
    ip_address: Optional[str] = None
    location: Optional[str] = None
    status: str = "inactive"
    created_at: datetime
    last_seen: Optional[datetime] = None
    error_count: int = 0
    is_active: bool = False
    company_id: Optional[str] = None

class CameraCreateRequest(BaseModel):
    name: str
    rtsp_url: str
    collection_id: Optional[str] = None
    location: Optional[str] = None
    company_id: Optional[str] = None

    @validator('rtsp_url')
    def validate_rtsp_url(cls, v):
        if not v:
            raise ValueError("RTSP URL is required")
        
        v = v.strip()
        
        # Allow local camera indices (0, 1, 2, etc.) for testing
        if v.isdigit():
            return v
        
        if not (v.startswith('rtsp://') or v.startswith('http://')):
            raise ValueError("Stream URL must start with rtsp://, http://, or be a camera index (0, 1, 2)")
        
        # Extract IP address for validation
        ip_pattern = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
        match = re.search(ip_pattern, v)
        if not match:
            raise ValueError("Could not extract IP address from stream URL")
        
        ip = match.group(1)
        try:
            ip_obj = ipaddress.IPv4Address(ip)
            # Check if it's a private IP
            if not ip_obj.is_private:
                raise ValueError(f"IP address {ip} must be within private network ranges")
        except ipaddress.AddressValueError:
            raise ValueError(f"Invalid IP address: {ip}")
        
        return v

    @validator('name')
    def validate_name(cls, v):
        if not v or not v.strip():
            raise ValueError("Camera name is required")
        return v.strip()

class CameraUpdateRequest(BaseModel):
    name: Optional[str] = None
    rtsp_url: Optional[str] = None
    collection_id: Optional[str] = None
    location: Optional[str] = None

    @validator('rtsp_url')
    def validate_rtsp_url(cls, v):
        if v is not None:
            v = v.strip()
            # Allow local camera indices
            if v.isdigit():
                return v
            return CameraCreateRequest.validate_rtsp_url(v)
        return v

    @validator('name')
    def validate_name(cls, v):
        if v is not None:
            return CameraCreateRequest.validate_name(v)
        return v

class CameraListResponse(BaseModel):
    cameras: List[EnhancedCamera]
    collections: List[CameraCollection]
    total_cameras: int
    active_cameras: int
    current_page: int = 1
    total_pages: int = 1
    cameras_per_page: int = 6

class CameraOperationResponse(BaseModel):
    success: bool
    message: str
    camera: Optional[EnhancedCamera] = None
    error: Optional[str] = None

def extract_ip_from_url(url: str) -> Optional[str]:
    """Extract IP address from RTSP/HTTP URL or camera index for local cameras"""
    # Check if it's a local camera index (just a number)
    if re.match(r'^\d+$', url):
        return url  # Return the index as-is for camera indices
    
    ip_pattern = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
    match = re.search(ip_pattern, url)
    return match.group(1) if match else None

def validate_private_ip(ip: str) -> Dict[str, Any]:
    """Validate if IP is within private network ranges or is a valid camera index"""
    # Check if it's a local camera index (just a number)
    if re.match(r'^\d+$', ip):
        return {
            "isValid": True,
            "ip": ip,
            "type": "camera_index",
            "message": f"Valid local camera index: {ip}"
        }
    
    try:
        ip_obj = ipaddress.IPv4Address(ip)
        is_valid = ip_obj.is_private
        
        return {
            "isValid": is_valid,
            "ip": ip,
            "type": "private" if is_valid else "public",
            "message": "Valid private IP" if is_valid else "IP must be within private network ranges"
        }
    except ipaddress.AddressValueError:
        return {
            "isValid": False,
            "ip": ip,
            "type": "invalid",
            "message": "Invalid IP address format"
        }
