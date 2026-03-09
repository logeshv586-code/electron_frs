from fastapi import FastAPI, File, UploadFile, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import face_recognition
import logging
import os
from typing import Optional, List, Dict, Any
import numpy as np
from datetime import datetime
import cv2
import tempfile

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# Configure paths
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
logger.info(f"Data directory: {DATA_DIR}")

class MatchResult(BaseModel):
    is_match: bool
    confidence: float
    face_distance: float
    probe_name: Optional[str] = None
    gallery_name: Optional[str] = None
    timestamp: datetime
    match_details: dict = {}
    face_locations: dict = {}

class GalleryMatch(BaseModel):
    person_name: str
    confidence: float
    face_distance: float
    face_location: Dict[str, float]
    match_details: Dict[str, Any]

class GalleryImage:
    def __init__(self, name: str, encoding: np.ndarray, image_path: str):
        self.name = name
        self.encoding = encoding
        self.image_path = image_path

class FaceMatchingService:
    def __init__(self):
        self.gallery_images: List[GalleryImage] = []
        self.load_gallery()

    def load_gallery(self):
        """Load all gallery images and their encodings"""
        logger.info("Loading gallery images...")
        self.gallery_images = []

        if not os.path.exists(DATA_DIR):
            logger.warning(f"Data directory not found: {DATA_DIR}")
            return

        for person_name in os.listdir(DATA_DIR):
            person_dir = os.path.join(DATA_DIR, person_name)
            if not os.path.isdir(person_dir):
                continue

            for img_file in os.listdir(person_dir):
                if not img_file.lower().endswith(('.jpg', '.jpeg', '.png')):
                    continue

                image_path = os.path.join(person_dir, img_file)
                try:
                    # Load and encode face
                    image = face_recognition.load_image_file(image_path)
                    encodings = face_recognition.face_encodings(image)
                    
                    if encodings:
                        self.gallery_images.append(
                            GalleryImage(person_name, encodings[0], image_path)
                        )
                        logger.debug(f"Loaded face encoding for {person_name} from {img_file}")
                except Exception as e:
                    logger.error(f"Error processing gallery image {image_path}: {e}")

        logger.info(f"Loaded {len(self.gallery_images)} gallery images")

    def find_matches(self, probe_encoding: np.ndarray, 
                    min_confidence: float = 0.6,
                    max_results: int = 10) -> List[Dict]:
        """Find matches for a probe face encoding in the gallery"""
        if not self.gallery_images:
            return []

        # Calculate face distances
        face_distances = face_recognition.face_distance(
            [img.encoding for img in self.gallery_images],
            probe_encoding
        )

        # Convert distances to confidence scores (0-100%)
        confidence_scores = (1 - face_distances) * 100

        # Filter and sort matches
        matches = []
        for idx, (confidence, distance) in enumerate(zip(confidence_scores, face_distances)):
            if confidence >= min_confidence * 100:  # Convert threshold to percentage
                gallery_img = self.gallery_images[idx]
                matches.append({
                    'person_name': gallery_img.name,
                    'confidence': float(confidence),
                    'face_distance': float(distance),
                    'image_path': gallery_img.image_path
                })

        # Sort by confidence (highest first) and limit results
        matches.sort(key=lambda x: x['confidence'], reverse=True)
        return matches[:max_results]

    @staticmethod
    def detect_and_encode_face(image_path):
        """Detect and encode a face from an image file."""
        try:
            # Read image using cv2 first to get dimensions
            cv_image = cv2.imread(image_path)
            if cv_image is None:
                raise ValueError("Failed to read image")
            
            height, width = cv_image.shape[:2]
            
            # Load image for face recognition
            image = face_recognition.load_image_file(image_path)
            face_locations = face_recognition.face_locations(image)
            
            if face_locations:
                encodings = face_recognition.face_encodings(image, face_locations)
                if encodings:
                    # Convert face locations to relative coordinates
                    rel_locations = []
                    for top, right, bottom, left in face_locations:
                        rel_locations.append({
                            'top': top / height,
                            'right': right / width,
                            'bottom': bottom / height,
                            'left': left / width,
                            'width': width,
                            'height': height
                        })
                    
                    return {
                        'encoding': encodings[0],
                        'location': face_locations[0],
                        'relative_location': rel_locations[0]
                    }
            logger.warning(f"No face detected in {image_path}")
            return None
        except Exception as e:
            logger.error(f"Error encoding face: {e}")
            return None

    @staticmethod
    def compare_faces(probe_data, gallery_data, threshold=45.0):
        """Compare two face encodings using face distance."""
        if probe_data is None or gallery_data is None:
            return False, 0.0, 0.0, {}, {}
        
        try:
            # Calculate face distance
            face_distance = face_recognition.face_distance(
                [probe_data['encoding']], 
                gallery_data['encoding']
            )[0]
            
            # Calculate confidence percentage
            confidence = (1 - face_distance) * 100
            
            # Determine if it's a match based on face distance threshold
            is_match = face_distance < (threshold / 100)  # Convert threshold to 0-1 scale
            
            # Additional match details
            match_details = {
                'threshold_used': threshold,
                'face_distance': face_distance,
                'analysis_timestamp': datetime.now().isoformat()
            }
            
            # Face location details for UI display
            face_locations = {
                'probe': probe_data['relative_location'],
                'gallery': gallery_data['relative_location']
            }
            
            return is_match, confidence, face_distance, match_details, face_locations
            
        except Exception as e:
            logger.error(f"Error comparing faces: {e}")
            return False, 0.0, 0.0, {}, {}

# Initialize face matching service
face_service = FaceMatchingService()

@app.post("/api/match/one-to-many")
async def match_face_to_gallery(
    probe: UploadFile = File(...),
    min_confidence: float = Query(0.6, ge=0.0, le=1.0),
    max_results: int = Query(10, ge=1, le=100)
):
    """
    Match a probe face against the gallery of known faces.
    Returns multiple matches above the confidence threshold.
    """
    try:
        start_time = datetime.now()

        # Read and process probe image
        contents = await probe.read()
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            temp_file.write(contents)
            temp_path = temp_file.name

        try:
            # Load probe image
            probe_image = face_recognition.load_image_file(temp_path)
            
            # Detect faces in probe image
            probe_face_locations = face_recognition.face_locations(probe_image)
            if not probe_face_locations:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid image"
                )

            # Get face encodings
            probe_encodings = face_recognition.face_encodings(
                probe_image, 
                probe_face_locations
            )

            if not probe_encodings:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid image"
                )

            # Find matches
            matches = face_service.find_matches(
                probe_encodings[0],
                min_confidence=min_confidence,
                max_results=max_results
            )

            # Prepare response
            results = []
            for match in matches:
                # Get relative face location
                height, width = probe_image.shape[:2]
                top, right, bottom, left = probe_face_locations[0]
                face_location = {
                    "top": top / height,
                    "right": right / width,
                    "bottom": bottom / height,
                    "left": left / width
                }

                results.append({
                    "person_name": match["person_name"],
                    "confidence": match["confidence"],
                    "face_distance": match["face_distance"],
                    "face_location": face_location,
                    "match_details": {
                        "threshold_used": min_confidence * 100,
                        "analysis_timestamp": start_time.isoformat(),
                        "image_path": match["image_path"]
                    }
                })

            return {
                "matches": results,
                "total_gallery_size": len(face_service.gallery_images),
                "analysis_time": (datetime.now() - start_time).total_seconds()
            }

        finally:
            # Clean up temporary file
            try:
                os.unlink(temp_path)
            except Exception as e:
                logger.error(f"Error removing temporary file: {e}")

    except Exception as e:
        logger.error(f"Error in face matching: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Face matching failed: {str(e)}"
        )

@app.post("/api/match/one-to-one", response_model=MatchResult)
async def match_faces(
    probe: UploadFile = File(...),
    gallery: UploadFile = File(...),
    threshold: float = 45.0
):
    """Perform 1:1 face matching between two uploaded images."""
    probe_temp = None
    gallery_temp = None
    
    try:
        # Create temporary files
        probe_temp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(probe.filename)[1])
        gallery_temp = tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(gallery.filename)[1])
        
        # Save uploaded files to temporary locations
        probe_content = await probe.read()
        gallery_content = await gallery.read()
        
        probe_temp.write(probe_content)
        gallery_temp.write(gallery_content)
        
        # Close the files so they can be opened by face_recognition
        probe_temp.close()
        gallery_temp.close()
        
        # Detect and encode faces
        probe_data = FaceMatchingService.detect_and_encode_face(probe_temp.name)
        gallery_data = FaceMatchingService.detect_and_encode_face(gallery_temp.name)
        
        if probe_data is None:
            raise HTTPException(status_code=400, detail="Invalid image")
        if gallery_data is None:
            raise HTTPException(status_code=400, detail="Invalid image")
        
        # Compare faces
        is_match, confidence, face_distance, match_details, face_locations = FaceMatchingService.compare_faces(
            probe_data,
            gallery_data,
            threshold
        )
        
        return MatchResult(
            is_match=is_match,
            confidence=confidence,
            face_distance=face_distance,
            probe_name=probe.filename,
            gallery_name=gallery.filename,
            timestamp=datetime.now(),
            match_details=match_details,
            face_locations=face_locations
        )
        
    except Exception as e:
        logger.error(f"Error in face matching: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
    finally:
        # Cleanup temporary files
        if probe_temp and os.path.exists(probe_temp.name):
            os.unlink(probe_temp.name)
        if gallery_temp and os.path.exists(gallery_temp.name):
            os.unlink(gallery_temp.name)

@app.get("/api/gallery/stats")
async def get_gallery_stats():
    """Get statistics about the gallery"""
    try:
        person_counts = {}
        for img in face_service.gallery_images:
            person_counts[img.name] = person_counts.get(img.name, 0) + 1

        return {
            "total_images": len(face_service.gallery_images),
            "unique_persons": len(person_counts),
            "person_counts": person_counts
        }

    except Exception as e:
        logger.error(f"Error getting gallery stats: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get gallery statistics: {str(e)}"
        )

@app.post("/api/gallery/reload")
async def reload_gallery():
    """Reload the gallery images"""
    try:
        face_service.load_gallery()
        return {"status": "success", "message": "Gallery reloaded successfully"}
    except Exception as e:
        logger.error(f"Error reloading gallery: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to reload gallery: {str(e)}"
        )

# This app can be mounted in the main application

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
