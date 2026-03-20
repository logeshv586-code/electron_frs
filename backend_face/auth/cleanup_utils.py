import os
import shutil
import sqlite3
import logging
from pathlib import Path
from typing import List, Optional
from .storage import get_tokens, save_tokens, get_users, save_users, load_json, atomic_write_json, AUTH_DATA_DIR

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).parent.parent.absolute()
DATA_DIR = BACKEND_DIR / "data"
CAPTURED_FACES_DIR = BACKEND_DIR / "captured_faces"
DB_PATH = DATA_DIR / "attendance.db"
CAMERAS_FILE = DATA_DIR / "cameras.json"
CAMERA_ASSIGNMENTS_FILE = AUTH_DATA_DIR / "camera_assignments.json"

def cleanup_user_tokens(username: str):
    """Remove all active tokens for a specific user."""
    tokens = get_tokens()
    original_count = len(tokens)
    tokens = {t: v for t, v in tokens.items() if v.get("username") != username}
    if len(tokens) < original_count:
        save_tokens(tokens)
        logger.info(f"Cleaned up {original_count - len(tokens)} tokens for user: {username}")

def cleanup_user_images(username: str, company_id: Optional[str] = None):
    """Remove known face images for a specific user."""
    comp = company_id if company_id else "default"
    known_dir = CAPTURED_FACES_DIR / "known" / comp
    
    if not known_dir.exists():
        return

    # User images are stored in captured_faces/known/{comp}/{cam}/{username}
    # We need to search all camera subfolders
    for cam_dir in known_dir.iterdir():
        if cam_dir.is_dir():
            user_dir = cam_dir / username
            if user_dir.exists() and user_dir.is_dir():
                try:
                    shutil.rmtree(user_dir)
                    logger.info(f"Deleted face images for user {username} in camera {cam_dir.name}")
                except Exception as e:
                    logger.error(f"Failed to delete images for user {username}: {e}")

def cleanup_company_data(company_id: str):
    """Thorough cleanup of all data associated with a company."""
    logger.info(f"Starting cascading cleanup for company: {company_id}")

    # 1. Clean up Users and their tokens
    users = get_users()
    users_to_delete = [uname for uname, udata in users.items() if udata.get("company_id") == company_id]
    
    for username in users_to_delete:
        cleanup_user_tokens(username)
        cleanup_user_images(username, company_id)
        if username in users:
            del users[username]
    
    save_users(users)
    logger.info(f"Deleted {len(users_to_delete)} users associated with company {company_id}")

    # 2. Clean up settings
    settings_file = AUTH_DATA_DIR / f"settings_{company_id}.json"
    if settings_file.exists():
        try:
            settings_file.unlink()
            logger.info(f"Deleted settings for company {company_id}")
        except Exception as e:
            logger.error(f"Failed to delete settings file: {e}")

    # 3. Clean up camera assignments
    if CAMERA_ASSIGNMENTS_FILE.exists():
        assignments = load_json(CAMERA_ASSIGNMENTS_FILE, {})
        original_count = len(assignments)
        assignments = {k: v for k, v in assignments.items() if v != company_id}
        if len(assignments) < original_count:
            atomic_write_json(CAMERA_ASSIGNMENTS_FILE, assignments)
            logger.info(f"Cleaned up {original_count - len(assignments)} camera assignments for company {company_id}")

    # 4. Clean up Physical Data Folders
    company_data_dir = DATA_DIR / company_id
    if company_data_dir.exists() and company_data_dir.is_dir():
        try:
            shutil.rmtree(company_data_dir)
            logger.info(f"Deleted data folder for company {company_id}")
        except Exception as e:
            logger.error(f"Failed to delete company data folder: {e}")

    # 5. Clean up Captured Faces (Known and Unknown)
    for folder in ["known", "unknown"]:
        comp_faces_dir = CAPTURED_FACES_DIR / folder / company_id
        if comp_faces_dir.exists() and comp_faces_dir.is_dir():
            try:
                shutil.rmtree(comp_faces_dir)
                logger.info(f"Deleted {folder} faces for company {company_id}")
            except Exception as e:
                logger.error(f"Failed to delete {folder} faces folder: {e}")

    # 6. Clean up Database records
    if DB_PATH.exists():
        try:
            conn = sqlite3.connect(str(DB_PATH))
            cursor = conn.cursor()
            cursor.execute("DELETE FROM attendance WHERE company_id = ?", (company_id,))
            deleted_rows = cursor.rowcount
            conn.commit()
            conn.close()
            logger.info(f"Deleted {deleted_rows} attendance records for company {company_id}")
        except Exception as e:
            logger.error(f"Failed to clear database records: {e}")

    logger.info(f"Cascading cleanup finished for company: {company_id}")
