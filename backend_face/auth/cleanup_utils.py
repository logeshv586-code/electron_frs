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
METADATA_FILE = DATA_DIR / "metadata.json"
GALLERY_DIR = DATA_DIR / "gallery"
EMBEDDINGS_CACHE_FILE = DATA_DIR / "embeddings_cache.pkl"

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
            
    # 7. Clean up person metadata (metadata.json)
    if METADATA_FILE.exists():
        try:
            metadata = load_json(METADATA_FILE, {})
            # Persons can be at top level or nested in "persons"
            original_len = len(metadata)
            
            # Helper to filter persons
            def filter_persons(p_dict):
                return {k: v for k, v in p_dict.items() if v.get("company_id") != company_id}

            # Filter top-level persons
            new_metadata = {k: v for k, v in metadata.items() if k == "persons" or (isinstance(v, dict) and v.get("company_id") != company_id)}
            
            # Filter nested "persons" if exists
            if "persons" in metadata and isinstance(metadata["persons"], dict):
                new_metadata["persons"] = filter_persons(metadata["persons"])
            
            # Additional cleanup for orphaned entries at top level (matching created_by if missing company_id)
            for k in list(new_metadata.keys()):
                if k == "persons": continue
                v = new_metadata[k]
                if isinstance(v, dict) and v.get("created_by") in users_to_delete:
                    del new_metadata[k]
                    
            if "persons" in new_metadata and isinstance(new_metadata["persons"], dict):
                for k in list(new_metadata["persons"].keys()):
                    v = new_metadata["persons"][k]
                    if v.get("created_by") in users_to_delete:
                        del new_metadata["persons"][k]

            # Only write if changed
            atomic_write_json(METADATA_FILE, new_metadata)
            logger.info(f"Cleaned up person metadata for company {company_id}")
        except Exception as e:
            logger.error(f"Failed to clean up metadata.json: {e}")

    # 8. Clean up company gallery
    comp_gallery_dir = GALLERY_DIR / company_id
    if comp_gallery_dir.exists() and comp_gallery_dir.is_dir():
        try:
            shutil.rmtree(comp_gallery_dir)
            logger.info(f"Deleted gallery folder for company {company_id}")
        except Exception as e:
            logger.error(f"Failed to delete company gallery folder: {e}")

    # 9. Clear embeddings cache to force rebuild
    if EMBEDDINGS_CACHE_FILE.exists():
        try:
            EMBEDDINGS_CACHE_FILE.unlink()
            logger.info(f"Cleared embeddings cache for cascading update")
        except Exception as e:
            logger.error(f"Failed to clear embeddings cache: {e}")

    logger.info(f"Cascading cleanup finished for company: {company_id}")
