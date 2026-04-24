import os
import time
import logging
import threading
import json
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Default retention days if not configured
DEFAULT_RETENTION_DAYS = 60

# Minimum age to delete (safety)
MIN_RETENTION_DAYS = 7

# How often to run the cleanup (in seconds) - default once a day
CLEANUP_INTERVAL = 24 * 60 * 60

def _get_retention_days() -> int:
    """Get image retention days without depending on backup route imports."""
    try:
        days = os.getenv("IMAGE_RETENTION_DAYS") or os.getenv("BACKUP_RETENTION_DAYS")
        if not days:
            settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "backup_settings.json")
            if os.path.exists(settings_path):
                with open(settings_path, "r", encoding="utf-8") as f:
                    settings = json.load(f)
                days = settings.get("retention_days")
        days = days or DEFAULT_RETENTION_DAYS
        return max(MIN_RETENTION_DAYS, int(days))
    except Exception as e:
        logger.warning(f"Error reading retention settings, using default {DEFAULT_RETENTION_DAYS}: {e}")
        return DEFAULT_RETENTION_DAYS

def _run_retention_cleanup():
    """Actually run the cleanup logic for captured images"""
    try:
        retention_days = _get_retention_days()
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        cutoff_timestamp = cutoff_date.timestamp()
        
        backend_dir = os.path.dirname(os.path.abspath(__file__))
        captured_faces_dir = os.path.join(backend_dir, "captured_faces")
        
        if not os.path.exists(captured_faces_dir):
            return
            
        logger.info(f"[RETENTION] Starting image retention cleanup. Removing images older than {retention_days} days (before {cutoff_date.date()})")
        
        deleted_count = 0
        deleted_bytes = 0
        
        # Walk through captured_faces directory
        for root, dirs, files in os.walk(captured_faces_dir):
            for file in files:
                if not file.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue
                    
                file_path = os.path.join(root, file)
                try:
                    # Check file modification time
                    mtime = os.path.getmtime(file_path)
                    
                    if mtime < cutoff_timestamp:
                        # File is older than retention period
                        size = os.path.getsize(file_path)
                        os.remove(file_path)
                        
                        deleted_count += 1
                        deleted_bytes += size
                        logger.debug(f"[RETENTION] Deleted old image: {file_path}")
                except Exception as e:
                    logger.warning(f"[RETENTION] Error processing file {file_path}: {e}")
                    
        # Clean up empty directories
        for root, dirs, files in os.walk(captured_faces_dir, topdown=False):
            for dir_name in dirs:
                dir_path = os.path.join(root, dir_name)
                try:
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        logger.debug(f"[RETENTION] Removed empty directory: {dir_path}")
                except Exception as e:
                    pass
                    
        if deleted_count > 0:
            mb_saved = deleted_bytes / (1024 * 1024)
            logger.info(f"[RETENTION] Cleanup complete. Deleted {deleted_count} images ({mb_saved:.2f} MB freed)")
        else:
            logger.info("[RETENTION] Cleanup complete. No old images found.")
            
    except Exception as e:
        logger.error(f"[RETENTION] Background worker error: {e}")

def retention_worker():
    """Background worker thread for image retention"""
    logger.info("Image retention background worker started")
    
    # Run immediately on startup (after a short delay to let things settle), 
    # then loop every CLEANUP_INTERVAL
    time.sleep(10)
    
    while True:
        try:
            _run_retention_cleanup()
        except Exception as e:
            logger.error(f"[RETENTION ERROR]: {e}")
            
        # Sleep until next interval
        time.sleep(CLEANUP_INTERVAL)

def start_retention_worker():
    """Start the retention background thread"""
    thread = threading.Thread(target=retention_worker, daemon=True)
    thread.start()
    return thread
