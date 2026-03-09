import unittest
import json
import tempfile
import shutil
from pathlib import Path
from fastapi.testclient import TestClient
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app
from auth.storage import USERS_FILE, SETTINGS_FILE, save_users, save_settings
from auth.users import create_user
from auth.security import get_password_hash

class TestRBACCameraLimits(unittest.TestCase):
    def setUp(self):
        """Set up test environment"""
        # Create temporary directory for test data
        self.temp_dir = tempfile.mkdtemp()
        self.original_users_file = USERS_FILE
        self.original_settings_file = SETTINGS_FILE
        
        # Override file paths to use temp directory
        import auth.storage as storage
        storage.USERS_FILE = Path(self.temp_dir) / "users.json"
        storage.SETTINGS_FILE = Path(self.temp_dir) / "settings.json"
        storage.AUTH_DATA_DIR = Path(self.temp_dir)
        
        # Create test client
        self.client = TestClient(app)
        
        # Create test users
        self.create_test_users()
    
    def tearDown(self):
        """Clean up test environment"""
        # Restore original file paths
        import backend_face.auth.storage as storage
        storage.USERS_FILE = self.original_users_file
        storage.SETTINGS_FILE = self.original_settings_file
        storage.AUTH_DATA_DIR = Path("data/auth")
        
        # Remove temp directory
        shutil.rmtree(self.temp_dir)
    
    def create_test_users(self):
        """Create test users for testing"""
        # Create SuperAdmin
        create_user("superadmin", "super123", "SuperAdmin", "system")
        
        # Create Admin
        create_user("admin", "admin123", "Admin", "superadmin")
        
        # Create Supervisors
        create_user("supervisor1", "supervisor123", "Supervisor", "admin")
        create_user("supervisor2", "supervisor123", "Supervisor", "admin")
        
        # Set camera limits
        save_settings({
            "max_cameras_per_admin": 10,
            "max_cameras_per_supervisor": 5
        })
    
    def login_as(self, username, password, role):
        """Helper method to login and get token"""
        response = self.client.post("/api/auth/login", json={
            "username": username,
            "password": password,
            "role": role
        })
        if response.status_code == 200:
            return response.json()["access_token"]
        return None
    
    def test_superadmin_login(self):
        """Test SuperAdmin login"""
        response = self.client.post("/api/auth/login", json={
            "username": "superadmin",
            "password": "super123",
            "role": "SuperAdmin"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["role"], "SuperAdmin")
    
    def test_admin_login(self):
        """Test Admin login"""
        response = self.client.post("/api/auth/login", json={
            "username": "admin",
            "password": "admin123",
            "role": "Admin"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["role"], "Admin")
    
    def test_supervisor_login(self):
        """Test Supervisor login"""
        response = self.client.post("/api/auth/login", json={
            "username": "supervisor1",
            "password": "supervisor123",
            "role": "Supervisor"
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("access_token", data)
        self.assertEqual(data["role"], "Supervisor")
    
    def test_invalid_login(self):
        """Test invalid login credentials"""
        response = self.client.post("/api/auth/login", json={
            "username": "invalid",
            "password": "wrong",
            "role": "Admin"
        })
        self.assertEqual(response.status_code, 401)
    
    def test_superadmin_can_create_admin(self):
        """Test SuperAdmin can create Admin users"""
        token = self.login_as("superadmin", "super123", "SuperAdmin")
        headers = {"Authorization": f"Bearer {token}"}
        
        response = self.client.post("/api/users/", json={
            "username": "newadmin",
            "password": "newadmin123",
            "role": "Admin"
        }, headers=headers)
        
        self.assertEqual(response.status_code, 200)
    
    def test_admin_cannot_create_admin(self):
        """Test Admin cannot create other Admin users"""
        token = self.login_as("admin", "admin123", "Admin")
        headers = {"Authorization": f"Bearer {token}"}
        
        response = self.client.post("/api/users/", json={
            "username": "newadmin",
            "password": "newadmin123",
            "role": "Admin"
        }, headers=headers)
        
        self.assertEqual(response.status_code, 403)
    
    def test_admin_can_create_supervisor(self):
        """Test Admin can create Supervisor users"""
        token = self.login_as("admin", "admin123", "Admin")
        headers = {"Authorization": f"Bearer {token}"}
        
        response = self.client.post("/api/users/", json={
            "username": "newsupervisor",
            "password": "supervisor123",
            "role": "Supervisor"
        }, headers=headers)
        
        self.assertEqual(response.status_code, 200)
    
    def test_supervisor_cannot_create_users(self):
        """Test Supervisors cannot create any users"""
        token = self.login_as("supervisor1", "supervisor123", "Supervisor")
        headers = {"Authorization": f"Bearer {token}"}
        
        # Try to create another supervisor
        response = self.client.post("/api/users/", json={
            "username": "newsupervisor",
            "password": "supervisor123",
            "role": "Supervisor"
        }, headers=headers)
        
        self.assertEqual(response.status_code, 403)
    
    def test_camera_assignment_limits(self):
        """Test camera assignment limits"""
        token = self.login_as("admin", "admin123", "Admin")
        headers = {"Authorization": f"Bearer {token}"}
        
        # Try to assign more cameras than allowed to supervisor
        camera_ids = [f"camera_{i}" for i in range(10)]  # More than limit of 5
        
        response = self.client.post("/api/users/supervisor1/cameras/assign", json={
            "camera_ids": camera_ids
        }, headers=headers)
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("exceed maximum cameras", response.json()["detail"].lower())
    
    def test_exclusive_camera_assignment(self):
        """Test that cameras can only be assigned to one user"""
        token = self.login_as("admin", "admin123", "Admin")
        headers = {"Authorization": f"Bearer {token}"}
        
        # Assign camera to supervisor1
        camera_ids = ["camera_1", "camera_2"]
        response = self.client.post("/api/users/supervisor1/cameras/assign", json={
            "camera_ids": camera_ids
        }, headers=headers)
        
        self.assertEqual(response.status_code, 200)
        
        # Try to assign same cameras to supervisor2
        response = self.client.post("/api/users/supervisor2/cameras/assign", json={
            "camera_ids": ["camera_1"]  # Same camera
        }, headers=headers)
        
        self.assertEqual(response.status_code, 400)
        self.assertIn("already assigned", response.json()["detail"].lower())
    
    def test_supervisor_can_only_see_assigned_cameras(self):
        """Test supervisors can only access their assigned cameras"""
        admin_token = self.login_as("admin", "admin123", "Admin")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}
        
        # Assign cameras to supervisor1
        camera_ids = ["camera_1", "camera_2"]
        response = self.client.post("/api/users/supervisor1/cameras/assign", json={
            "camera_ids": camera_ids
        }, headers=admin_headers)
        
        self.assertEqual(response.status_code, 200)
        
        # Login as supervisor and check cameras
        supervisor_token = self.login_as("supervisor1", "supervisor123", "Supervisor")
        supervisor_headers = {"Authorization": f"Bearer {supervisor_token}"}
        
        response = self.client.get("/api/cameras/my-cameras", headers=supervisor_headers)
        self.assertEqual(response.status_code, 200)
        
        data = response.json()
        self.assertEqual(len(data["cameras"]), 2)
        camera_ids_returned = [cam["id"] for cam in data["cameras"]]
        self.assertIn("camera_1", camera_ids_returned)
        self.assertIn("camera_2", camera_ids_returned)
    
    def test_supervisor_cannot_access_other_endpoints(self):
        """Test supervisors cannot access admin/superadmin endpoints"""
        token = self.login_as("supervisor1", "supervisor123", "Supervisor")
        headers = {"Authorization": f"Bearer {token}"}
        
        # Try to access users list
        response = self.client.get("/api/users/", headers=headers)
        self.assertEqual(response.status_code, 403)
        
        # Try to access system settings
        response = self.client.get("/api/users/settings/system", headers=headers)
        self.assertEqual(response.status_code, 403)
    
    def test_admin_cannot_access_superadmin_endpoints(self):
        """Test admins cannot access superadmin-only endpoints"""
        token = self.login_as("admin", "admin123", "Admin")
        headers = {"Authorization": f"Bearer {token}"}
        
        # Try to access system settings (superadmin only)
        response = self.client.get("/api/users/settings/system", headers=headers)
        self.assertEqual(response.status_code, 403)
    
    def test_superadmin_can_access_all_endpoints(self):
        """Test SuperAdmin can access all endpoints"""
        token = self.login_as("superadmin", "super123", "SuperAdmin")
        headers = {"Authorization": f"Bearer {token}"}
        
        # Access users list
        response = self.client.get("/api/users/", headers=headers)
        self.assertEqual(response.status_code, 200)
        
        # Access system settings
        response = self.client.get("/api/users/settings/system", headers=headers)
        self.assertEqual(response.status_code, 200)
    
    def test_bootstrap_superadmin(self):
        """Test SuperAdmin bootstrap functionality"""
        # Clear existing users first
        import auth.storage as storage
        storage.save_users({})
        
        response = self.client.post("/api/auth/bootstrap/superadmin", json={
            "username": "bootstrapsuper",
            "password": "bootstrap123"
        })
        
        self.assertEqual(response.status_code, 200)
        
        # Try to create another superadmin (should fail)
        response = self.client.post("/api/auth/bootstrap/superadmin", json={
            "username": "bootstrapsuper2",
            "password": "bootstrap123"
        })
        
        self.assertEqual(response.status_code, 400)

if __name__ == '__main__':
    # Set environment variables to skip heavy services during testing
    import os
    os.environ['FRS_SKIP_HEAVY_SERVICES'] = '1'
    os.environ['FRS_SKIP_FACE_PIPELINE'] = '1'
    
    unittest.main()