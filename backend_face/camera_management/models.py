from __future__ import annotations

from datetime import datetime
from typing import Optional, List, Dict, Any
import ipaddress
import os
import re

from pydantic import BaseModel, field_validator

CAMERA_ROLES = {"ENTRY", "EXIT", "BIDIRECTIONAL", "REFERENCE_ONLY"}
CAMERA_DIRECTIONS = {"IN", "OUT", "AUTO", "NONE"}


class CameraCollection(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    created_at: datetime
    camera_count: int = 0
    company_id: Optional[str] = None


class CollectionCreateRequest(BaseModel):
    name: str
    description: Optional[str] = None
    company_id: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str):
        if not value or not value.strip():
            raise ValueError("Collection name is required")
        return value.strip()


class CollectionUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]):
        if value is not None and not value.strip():
            raise ValueError("Collection name cannot be empty")
        return value.strip() if value else None


class CameraValidationRequest(BaseModel):
    ip: str
    streamUrl: str
    collection_name: Optional[str] = None
    exclude_ip: Optional[str] = None
    company_id: Optional[str] = None


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
    site_id: Optional[str] = None
    zone_id: Optional[str] = None
    camera_role: str = "BIDIRECTIONAL"
    direction: str = "AUTO"
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
    site_id: Optional[str] = None
    zone_id: Optional[str] = None
    camera_role: str = "BIDIRECTIONAL"
    direction: str = "AUTO"
    company_id: Optional[str] = None

    @field_validator("rtsp_url")
    @classmethod
    def validate_rtsp_url(cls, value: str):
        if not value:
            raise ValueError("Stream URL is required")
        value = value.strip()
        if value.isdigit():
            return value
        if not value.lower().startswith(("rtsp://", "http://", "https://")):
            raise ValueError("Stream URL must start with rtsp://, http://, https:// or be a local camera index")
        ip = extract_ip_from_url(value)
        if ip:
            result = validate_private_ip(ip)
            if not result["isValid"] and os.getenv("FRS_ALLOW_PUBLIC_CAMERA_URLS", "0").lower() not in {"1", "true", "yes"}:
                raise ValueError(result["message"])
        return value

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str):
        if not value or not value.strip():
            raise ValueError("Camera name is required")
        return value.strip()

    @field_validator("camera_role")
    @classmethod
    def validate_role(cls, value: str):
        value = (value or "BIDIRECTIONAL").upper()
        if value not in CAMERA_ROLES:
            raise ValueError(f"camera_role must be one of {sorted(CAMERA_ROLES)}")
        return value

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: str):
        value = (value or "AUTO").upper()
        if value not in CAMERA_DIRECTIONS:
            raise ValueError(f"direction must be one of {sorted(CAMERA_DIRECTIONS)}")
        return value


class CameraUpdateRequest(BaseModel):
    name: Optional[str] = None
    rtsp_url: Optional[str] = None
    collection_id: Optional[str] = None
    location: Optional[str] = None
    site_id: Optional[str] = None
    zone_id: Optional[str] = None
    camera_role: Optional[str] = None
    direction: Optional[str] = None

    @field_validator("rtsp_url")
    @classmethod
    def validate_rtsp_url(cls, value: Optional[str]):
        if value is None:
            return value
        return CameraCreateRequest.validate_rtsp_url(value)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: Optional[str]):
        if value is None:
            return value
        return CameraCreateRequest.validate_name(value)

    @field_validator("camera_role")
    @classmethod
    def validate_role(cls, value: Optional[str]):
        if value is None:
            return value
        return CameraCreateRequest.validate_role(value)

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, value: Optional[str]):
        if value is None:
            return value
        return CameraCreateRequest.validate_direction(value)


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
    if re.match(r"^\d+$", str(url or "")):
        return str(url)
    match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", str(url or ""))
    return match.group(1) if match else None


def validate_private_ip(ip: str) -> Dict[str, Any]:
    if re.match(r"^\d+$", str(ip or "")):
        return {"isValid": True, "ip": ip, "type": "camera_index", "message": f"Valid local camera index: {ip}"}
    try:
        ip_obj = ipaddress.IPv4Address(ip)
        is_valid = bool(ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local)
        return {
            "isValid": is_valid,
            "ip": ip,
            "type": "private" if is_valid else "public",
            "message": "Valid private IP" if is_valid else "Camera IP must be private unless FRS_ALLOW_PUBLIC_CAMERA_URLS is enabled",
        }
    except ipaddress.AddressValueError:
        return {"isValid": False, "ip": ip, "type": "invalid", "message": "Invalid IP address format"}
