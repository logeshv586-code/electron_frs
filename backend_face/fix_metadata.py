import os
import json
import shutil
import cv2
from datetime import datetime

# Configuration
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
GALLERY_DIR = os.path.join(DATA_DIR, "gallery")
METADATA_FILE = os.path.join(DATA_DIR, "metadata.json")

# System folders to ignore
IGNORE_FOLDERS = {
    "gallery", 
    "auth", 
    "camera_management", 
    "temp_bulk", 
    "__pycache__", 
    ".ipynb_checkpoints"
}

def fix_metadata():
    print(f"Scanning data directory: {DATA_DIR}")
    
    # Ensure gallery directory exists
    os.makedirs(GALLERY_DIR, exist_ok=True)
    
    # Load existing metadata to preserve categories/details if possible
    existing_metadata = {}
    if os.path.exists(METADATA_FILE):
        try:
            with open(METADATA_FILE, 'r') as f:
                existing_metadata = json.load(f)
            print(f"Loaded existing metadata with {len(existing_metadata)} entries")
        except Exception as e:
            print(f"Error loading existing metadata: {e}")
    
    new_metadata = {}
    persons_found = 0
    
    # Scan for person directories
    if not os.path.exists(DATA_DIR):
        print(f"Error: Data directory not found at {DATA_DIR}")
        return

    for person_name in os.listdir(DATA_DIR):
        person_dir = os.path.join(DATA_DIR, person_name)
        
        # Skip files and ignored folders
        if not os.path.isdir(person_dir) or person_name in IGNORE_FOLDERS:
            continue
            
        print(f"Processing person: {person_name}")
        
        # Find valid images
        images = [f for f in os.listdir(person_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png'))]
        
        if not images:
            print(f"  No images found for {person_name}, skipping")
            continue
            
        # Ensure gallery folder exists for this person
        person_gallery_dir = os.path.join(GALLERY_DIR, person_name)
        os.makedirs(person_gallery_dir, exist_ok=True)
        
        # Check if we need to copy an image to gallery
        gallery_image_path = os.path.join(person_gallery_dir, "1.jpg")
        if not os.path.exists(gallery_image_path):
            # Try to find 'original.jpg' or just pick the first one
            source_image = "original.jpg" if "original.jpg" in images else images[0]
            source_path = os.path.join(person_dir, source_image)
            
            try:
                shutil.copy2(source_path, gallery_image_path)
                print(f"  Copied {source_image} to gallery as 1.jpg")
            except Exception as e:
                print(f"  Error copying image: {e}")
                continue
        
        # Prepare metadata entry
        # Preserve existing details if available
        existing_entry = existing_metadata.get(person_name, {})
        
        new_metadata[person_name] = {
            "name": person_name,
            "age": existing_entry.get("age", "N/A"),
            "gender": existing_entry.get("gender", "N/A"),
            "category": existing_entry.get("category", "unknown"),
            "registration_date": existing_entry.get("registration_date", datetime.now().isoformat()),
            "gallery_path": person_gallery_dir,
            "photo_path": gallery_image_path,
            "age_range": existing_entry.get("age_range", "N/A"),
            "age_source": existing_entry.get("age_source", "unknown"),
            "predicted_age": existing_entry.get("predicted_age", None)
        }
        persons_found += 1

    # Save updated metadata
    try:
        with open(METADATA_FILE, 'w') as f:
            json.dump(new_metadata, f, indent=4)
        print(f"\nSuccess! Updated metadata.json with {persons_found} persons.")
        print(f"Metadata file location: {METADATA_FILE}")
    except Exception as e:
        print(f"Error saving metadata: {e}")

if __name__ == "__main__":
    fix_metadata()
