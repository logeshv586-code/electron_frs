import os
import subprocess
import threading
import time
import logging
from typing import Dict, Optional
import uuid
from datetime import datetime
from fastapi import HTTPException

logger = logging.getLogger(__name__)

class CameraRecordingManager:
    """Manages camera recordings using FFmpeg"""
    
    def __init__(self, recordings_dir: str = "recordings"):
        self.recordings_dir = recordings_dir
        self.active_recordings: Dict[str, Dict] = {}
        self.recording_lock = threading.Lock()
        
        # Create recordings directory
        os.makedirs(self.recordings_dir, exist_ok=True)
        
    def start_recording(self, camera_id: int, rtsp_url: str, duration_minutes: Optional[int] = None) -> str:
        """Start recording from a camera"""
        recording_id = str(uuid.uuid4())
        
        try:
            # Create camera-specific directory
            camera_dir = os.path.join(self.recordings_dir, f"camera_{camera_id}")
            os.makedirs(camera_dir, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"recording_{timestamp}.mp4"
            output_path = os.path.join(camera_dir, filename)
            
            # Build FFmpeg command
            ffmpeg_cmd = [
                'ffmpeg',
                '-i', rtsp_url,
                '-c:v', 'libx264',  # Video codec
                '-preset', 'fast',   # Encoding speed
                '-crf', '23',        # Quality (lower = better quality)
                '-c:a', 'aac',       # Audio codec
                '-f', 'mp4',         # Output format
                '-y',                # Overwrite output file
            ]
            
            # Add duration if specified
            if duration_minutes:
                ffmpeg_cmd.extend(['-t', str(duration_minutes * 60)])
            
            ffmpeg_cmd.append(output_path)
            
            # Start FFmpeg process
            process = subprocess.Popen(
                ffmpeg_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                universal_newlines=True
            )
            
            # Store recording info
            with self.recording_lock:
                self.active_recordings[recording_id] = {
                    'camera_id': camera_id,
                    'rtsp_url': rtsp_url,
                    'output_path': output_path,
                    'process': process,
                    'started_at': datetime.now(),
                    'duration_minutes': duration_minutes,
                    'status': 'recording'
                }
            
            logger.info(f"Started recording {recording_id} for camera {camera_id}")
            return recording_id
            
        except Exception as e:
            logger.error(f"Error starting recording for camera {camera_id}: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to start recording: {str(e)}")
    
    def stop_recording(self, recording_id: str) -> bool:
        """Stop a recording"""
        try:
            with self.recording_lock:
                if recording_id not in self.active_recordings:
                    return False
                
                recording_info = self.active_recordings[recording_id]
                process = recording_info['process']
                
                # Terminate FFmpeg process gracefully
                process.terminate()
                
                # Wait for process to finish (with timeout)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                
                # Update status
                recording_info['status'] = 'stopped'
                recording_info['stopped_at'] = datetime.now()
                
                # Remove from active recordings
                del self.active_recordings[recording_id]
                
                logger.info(f"Stopped recording {recording_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error stopping recording {recording_id}: {e}")
            return False
    
    def get_recording_status(self, recording_id: str) -> Optional[Dict]:
        """Get status of a recording"""
        with self.recording_lock:
            if recording_id in self.active_recordings:
                recording_info = self.active_recordings[recording_id].copy()
                # Don't include the process object in the response
                recording_info.pop('process', None)
                return recording_info
        return None
    
    def get_camera_recordings(self, camera_id: int) -> Dict:
        """Get all recordings for a camera"""
        camera_dir = os.path.join(self.recordings_dir, f"camera_{camera_id}")
        recordings = []
        
        if os.path.exists(camera_dir):
            for filename in os.listdir(camera_dir):
                if filename.endswith('.mp4'):
                    file_path = os.path.join(camera_dir, filename)
                    file_stats = os.stat(file_path)
                    
                    recordings.append({
                        'filename': filename,
                        'path': file_path,
                        'size_bytes': file_stats.st_size,
                        'created_at': datetime.fromtimestamp(file_stats.st_ctime).isoformat(),
                        'modified_at': datetime.fromtimestamp(file_stats.st_mtime).isoformat()
                    })
        
        # Sort by creation time (newest first)
        recordings.sort(key=lambda x: x['created_at'], reverse=True)
        
        return {
            'camera_id': camera_id,
            'recordings': recordings,
            'total_recordings': len(recordings)
        }
    
    def get_active_recordings(self) -> Dict[str, Dict]:
        """Get all active recordings"""
        with self.recording_lock:
            active = {}
            for recording_id, info in self.active_recordings.items():
                # Create a copy without the process object
                active[recording_id] = {
                    'camera_id': info['camera_id'],
                    'started_at': info['started_at'].isoformat(),
                    'duration_minutes': info['duration_minutes'],
                    'status': info['status']
                }
            return active
    
    def cleanup_old_recordings(self, days_to_keep: int = 30):
        """Clean up recordings older than specified days"""
        cutoff_time = time.time() - (days_to_keep * 24 * 60 * 60)
        deleted_count = 0
        
        for camera_dir in os.listdir(self.recordings_dir):
            camera_path = os.path.join(self.recordings_dir, camera_dir)
            if os.path.isdir(camera_path):
                for filename in os.listdir(camera_path):
                    if filename.endswith('.mp4'):
                        file_path = os.path.join(camera_path, filename)
                        if os.path.getctime(file_path) < cutoff_time:
                            try:
                                os.remove(file_path)
                                deleted_count += 1
                                logger.info(f"Deleted old recording: {file_path}")
                            except Exception as e:
                                logger.error(f"Error deleting {file_path}: {e}")
        
        logger.info(f"Cleanup completed. Deleted {deleted_count} old recordings.")
        return deleted_count

# Global recording manager instance
recording_manager = CameraRecordingManager()

def get_recording_manager() -> CameraRecordingManager:
    """Get the global recording manager instance"""
    return recording_manager
