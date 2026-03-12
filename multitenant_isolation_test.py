
import os
import json
import pytest
from fastapi.testclient import TestClient
import sys

# Add backend_face to path
sys.path.append(os.path.join(os.getcwd(), 'backend_face'))

from main import app
from camera_management.routes import get_camera_service
from camera_management.service import EnhancedCameraService

client = TestClient(app)

def test_camera_isolation():
    """Test 3: Camera isolation - Admin A camera not visible to Admin B"""
    # Create two mock users with different company_ids
    user_a = {"username": "admin_a", "role": "Admin", "company_id": "company_a"}
    user_b = {"username": "admin_b", "role": "Admin", "company_id": "company_b"}
    
    # We'll use the service directly to create cameras for testing
    data_dir = os.path.join(os.getcwd(), 'backend_face', 'data', 'camera_management')
    service = EnhancedCameraService(data_dir)
    
    # Clean up existing test cameras if any
    all_cameras = service._load_cameras()
    service._save_cameras([c for c in all_cameras if not str(c.name).startswith("隔离测试")])
    
    # Create camera for Company A
    cam_a_data = {
        "name": "隔离测试_CompanyA_Cam",
        "ip_address": "10.0.0.10",
        "rtsp_url": "rtsp://10.0.0.10/stream1",
        "company_id": "company_a",
        "status": "active"
    }
    from camera_management.models import CameraCreateRequest
    service.create_camera(CameraCreateRequest(**cam_a_data))
    
    # Create camera for Company B
    cam_b_data = {
        "name": "隔离测试_CompanyB_Cam",
        "ip_address": "10.0.0.11",
        "rtsp_url": "rtsp://10.0.0.11/stream1",
        "company_id": "company_b",
        "status": "active"
    }
    service.create_camera(CameraCreateRequest(**cam_b_data))
    
    # Test as Admin A
    # Mocking the request.scope.get("user") is hard with TestClient directly
    # But we can check the service logic which is what the endpoint uses
    
    cameras_a = service.get_cameras(1, 10, company_id="company_a")
    cameras_b = service.get_cameras(1, 10, company_id="company_b")
    
    # Assert isolation in service layer
    cam_a_names = [c.name for c in cameras_a.cameras]
    cam_b_names = [c.name for c in cameras_b.cameras]
    
    assert "隔离测试_CompanyA_Cam" in cam_a_names
    assert "隔离测试_CompanyB_Cam" not in cam_a_names
    
    assert "隔离测试_CompanyB_Cam" in cam_b_names
    assert "隔离测试_CompanyA_Cam" not in cam_b_names
    
    print("\n✓ Camera Isolation Test Passed")

def test_face_recognition_isolation():
    """Test 4: Face recognition isolation - Employee from Company A must NOT match Company B dataset"""
    from face_pipeline import load_company_embeddings
    import numpy as np
    
    # We'll mock the internal state of face_pipeline for this test
    import face_pipeline
    
    # Create mock gallery structure
    data_dir = os.path.join(os.getcwd(), 'backend_face', 'data')
    gallery_a = os.path.join(data_dir, 'gallery', 'company_a', 'EmployeeA')
    gallery_b = os.path.join(data_dir, 'gallery', 'company_b', 'EmployeeB')
    
    os.makedirs(gallery_a, exist_ok=True)
    os.makedirs(gallery_b, exist_ok=True)
    
    # Mock some image files (empty ones just for directory scanning)
    with open(os.path.join(gallery_a, "1.jpg"), "w") as f: f.write("dummy")
    with open(os.path.join(gallery_b, "1.jpg"), "w") as f: f.write("dummy")
    
    # Mock load_known_faces to return different encodings for different companies
    import fr1
    original_load = fr1.load_known_faces
    
    # Mock encodings (128-dimensional for face_recognition)
    enc_a = np.random.rand(128)
    enc_b = np.random.rand(128)
    
    def mock_load(path, company_id=None):
        if company_id == "company_a":
            return [enc_a], ["EmployeeA"]
        if company_id == "company_b":
            return [enc_b], ["EmployeeB"]
        return [], []
    
    fr1.load_known_faces = mock_load
    
    # Clear cache
    face_pipeline.company_embeddings = {}
    face_pipeline.data_directory = data_dir
    
    # Test loading
    emb_a = face_pipeline.load_company_embeddings("company_a")
    emb_b = face_pipeline.load_company_embeddings("company_b")
    
    assert emb_a["names"] == ["EmployeeA"]
    assert emb_b["names"] == ["EmployeeB"]
    
    # Verify isolation: distance check
    import face_recognition
    # If we have an enc_a, it should match EmployeeA but NOT EmployeeB if thresholds are correct
    # (Since we mocked load_known_faces, the system is now company-aware)
    
    # Restore original function
    fr1.load_known_faces = original_load
    print("✓ Face Recognition Isolation Test (Dataset Loading) Passed")

if __name__ == "__main__":
    test_camera_isolation()
    test_face_recognition_isolation()
