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

class TestRBACLicenseLimits(unittest.TestCase):
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
        
        # Create initial SuperAdmin
        create_user("superadmin", "super123", "SuperAdmin", "system")

    def tearDown(self):
        """Clean up test environment"""
        # Restore original file paths
        import auth.storage as storage
        storage.USERS_FILE = self.original_users_file
        storage.SETTINGS_FILE = self.original_settings_file
        storage.AUTH_DATA_DIR = Path("data/auth")
        
        # Remove temp directory
        shutil.rmtree(self.temp_dir)

    def login_as(self, username, password, role):
        response = self.client.post("/api/auth/login", json={
            "username": username,
            "password": password,
            "role": role
        })
        if response.status_code == 200:
            return response.json()["access_token"]
        return None

    def test_admin_user_limit(self):
        """Test Admin cannot create more users than their limit"""
        token = self.login_as("superadmin", "super123", "SuperAdmin")
        headers = {"Authorization": f"Bearer {token}"}
        
        # Create Admin with limit of 1 user
        response = self.client.post("/api/users/", json={
            "username": "admin_limited",
            "password": "admin123",
            "role": "Admin",
            "max_users_limit": 1
        }, headers=headers)
        self.assertEqual(response.status_code, 200)

        # Login as limited Admin
        admin_token = self.login_as("admin_limited", "admin123", "Admin")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Create 1st Supervisor - Should Succeed
        response = self.client.post("/api/users/", json={
            "username": "sup1",
            "password": "sup123",
            "role": "Supervisor"
        }, headers=admin_headers)
        self.assertEqual(response.status_code, 200)

        # Create 2nd Supervisor - Should Fail
        response = self.client.post("/api/users/", json={
            "username": "sup2",
            "password": "sup123",
            "role": "Supervisor"
        }, headers=admin_headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("User creation limit reached", response.json()["detail"])

    def test_admin_camera_access_enforcement(self):
        """Test Admin can only assign cameras they have access to"""
        token = self.login_as("superadmin", "super123", "SuperAdmin")
        headers = {"Authorization": f"Bearer {token}"}
        
        # Create Admin
        self.client.post("/api/users/", json={
            "username": "admin_cam",
            "password": "admin123",
            "role": "Admin",
            "max_cameras_limit": 5
        }, headers=headers)

        # Assign cameras to Admin (Admin must have cameras assigned to them first!)
        # Wait, the current logic is that Admin *manages* cameras.
        # But my implementation in `assign_cameras_to_user` checks `if not cameras_to_assign.issubset(admin_cameras)`.
        # This means Admin MUST have cameras assigned to them first by SuperAdmin.
        
        # SuperAdmin assigns cameras to Admin
        self.client.post("/api/users/admin_cam/cameras/assign", json={
            "camera_ids": ["cam1", "cam2"]
        }, headers=headers)

        # Login as Admin
        admin_token = self.login_as("admin_cam", "admin123", "Admin")
        admin_headers = {"Authorization": f"Bearer {admin_token}"}

        # Create Supervisor
        self.client.post("/api/users/", json={
            "username": "sup_cam",
            "password": "sup123",
            "role": "Supervisor"
        }, headers=admin_headers)

        # Admin tries to assign "cam1" (Valid)
        response = self.client.post("/api/users/sup_cam/cameras/assign", json={
            "camera_ids": ["cam1"]
        }, headers=admin_headers)
        self.assertEqual(response.status_code, 200)

        # Admin tries to assign "cam3" (Invalid - not in Admin's list)
        response = self.client.post("/api/users/sup_cam/cameras/assign", json={
            "camera_ids": ["cam3"]
        }, headers=admin_headers)
        self.assertEqual(response.status_code, 400)
        self.assertIn("only assign cameras that you have access to", response.json()["detail"])

    def test_menu_permissions(self):
        """Test assigned menus are returned correctly"""
        token = self.login_as("superadmin", "super123", "SuperAdmin")
        headers = {"Authorization": f"Bearer {token}"}

        # Create Admin with specific menus
        custom_menus = ["dashboard", "users"]
        response = self.client.post("/api/users/", json={
            "username": "admin_menu",
            "password": "admin123",
            "role": "Admin",
            "assigned_menus": custom_menus
        }, headers=headers)
        self.assertEqual(response.status_code, 200)

        # Login as Admin
        response = self.client.post("/api/auth/login", json={
            "username": "admin_menu",
            "password": "admin123",
            "role": "Admin"
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["assigned_menus"], custom_menus)

if __name__ == "__main__":
    unittest.main()
