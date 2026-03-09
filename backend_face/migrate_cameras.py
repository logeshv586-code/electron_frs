#!/usr/bin/env python3
"""
Migration script to transfer cameras from the old system to the enhanced camera management system.
"""

import json
import os
import sys
from datetime import datetime
from typing import List, Dict

# Add the backend_face directory to the path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from camera_management.models import EnhancedCamera, CameraCollection
from camera_management.service import EnhancedCameraService

def extract_ip_from_url(url: str) -> str:
    """Extract IP address from RTSP URL"""
    import re
    # Pattern to match IP addresses in URLs
    ip_pattern = r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})'
    match = re.search(ip_pattern, url)
    return match.group(1) if match else None

def migrate_cameras():
    """Migrate cameras from old system to enhanced system"""
    
    # Paths
    old_db_path = os.path.join(os.path.dirname(__file__), "database", "cameras.json")
    data_dir = os.path.join(os.path.dirname(__file__), "data", "camera_management")
    
    print("🔄 Starting camera migration...")
    print(f"📁 Old database: {old_db_path}")
    print(f"📁 New data directory: {data_dir}")
    
    # Check if old database exists
    if not os.path.exists(old_db_path):
        print("❌ Old camera database not found. Nothing to migrate.")
        return
    
    # Load old camera data
    try:
        with open(old_db_path, 'r') as f:
            old_data = json.load(f)
        
        camera_streams = old_data.get('camera_streams', {})
        print(f"📊 Found {len(camera_streams)} cameras in old system")
        
        if not camera_streams:
            print("ℹ️  No cameras to migrate.")
            return
            
    except Exception as e:
        print(f"❌ Error reading old database: {e}")
        return
    
    # Initialize enhanced camera service
    try:
        service = EnhancedCameraService(data_dir)
        print("✅ Enhanced camera service initialized")
    except Exception as e:
        print(f"❌ Error initializing enhanced camera service: {e}")
        return
    
    # Load existing cameras to avoid duplicates
    existing_cameras = service._load_cameras()
    existing_urls = {camera.rtsp_url for camera in existing_cameras}
    existing_ips = {camera.ip_address for camera in existing_cameras}
    
    print(f"📊 Found {len(existing_cameras)} cameras in enhanced system")
    
    # Migrate cameras
    migrated_count = 0
    skipped_count = 0
    
    for old_id, rtsp_url in camera_streams.items():
        try:
            # Extract IP address
            ip_address = extract_ip_from_url(rtsp_url)
            
            # Check for duplicates
            if rtsp_url in existing_urls:
                print(f"⏭️  Skipping camera {old_id}: URL already exists ({rtsp_url})")
                skipped_count += 1
                continue
                
            if ip_address and ip_address in existing_ips:
                print(f"⏭️  Skipping camera {old_id}: IP already exists ({ip_address})")
                skipped_count += 1
                continue
            
            # Generate new ID
            new_id = max([c.id for c in existing_cameras], default=0) + 1
            
            # Create enhanced camera
            enhanced_camera = EnhancedCamera(
                id=new_id,
                name=f"Migrated Camera {old_id}",
                rtsp_url=rtsp_url,
                collection_id="default",
                collection_name="Default Collection",
                ip_address=ip_address,
                status="inactive",
                created_at=datetime.now(),
                error_count=0,
                is_active=False
            )
            
            # Add to existing cameras list
            existing_cameras.append(enhanced_camera)
            
            print(f"✅ Migrated camera {old_id} -> {new_id}: {rtsp_url}")
            migrated_count += 1
            
        except Exception as e:
            print(f"❌ Error migrating camera {old_id}: {e}")
            continue
    
    # Save migrated cameras
    if migrated_count > 0:
        try:
            service._save_cameras(existing_cameras)
            print(f"💾 Saved {migrated_count} migrated cameras")
        except Exception as e:
            print(f"❌ Error saving migrated cameras: {e}")
            return
    
    # Update collection camera count
    try:
        collections = service._load_collections()
        default_collection = next((c for c in collections if c.id == "default"), None)
        if default_collection:
            default_collection.camera_count = len([c for c in existing_cameras if c.collection_id == "default"])
            service._save_collections(collections)
            print("✅ Updated collection camera counts")
    except Exception as e:
        print(f"⚠️  Warning: Could not update collection counts: {e}")
    
    # Summary
    print("\n📊 Migration Summary:")
    print(f"   ✅ Migrated: {migrated_count} cameras")
    print(f"   ⏭️  Skipped: {skipped_count} cameras (duplicates)")
    print(f"   📊 Total in enhanced system: {len(existing_cameras)} cameras")
    
    if migrated_count > 0:
        print("\n🎉 Migration completed successfully!")
        print("💡 You can now use the enhanced camera management system.")
        print("💡 The old database file has been preserved for backup.")
    else:
        print("\n✅ No migration needed - all cameras already in enhanced system.")

def backup_old_database():
    """Create a backup of the old database"""
    old_db_path = os.path.join(os.path.dirname(__file__), "database", "cameras.json")
    
    if os.path.exists(old_db_path):
        backup_path = old_db_path + f".backup.{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            import shutil
            shutil.copy2(old_db_path, backup_path)
            print(f"💾 Created backup: {backup_path}")
        except Exception as e:
            print(f"⚠️  Warning: Could not create backup: {e}")

if __name__ == "__main__":
    print("🚀 Camera Migration Tool")
    print("=" * 50)
    
    # Create backup first
    backup_old_database()
    
    # Run migration
    migrate_cameras()
    
    print("\n" + "=" * 50)
    print("✅ Migration process completed!")
