from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from typing import Dict, List, Optional
import os
import json
import cv2
import pandas as pd
from pydantic import BaseModel
import shutil
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
try:
    import face_recognition
except Exception as e:
    print(f"Failed to import face_recognition: {e}")
    face_recognition = None

try:
    from retinaface import RetinaFace
except Exception as e:
    print(f"Failed to import retinaface: {e}")
    RetinaFace = None

try:
    from deepface import DeepFace
except Exception as e:
    print(f"Failed to import deepface: {e}")
    DeepFace = None
from .aug import detect_face, augment_face
import numpy as np
import io
import re
from typing import Tuple

# Configure paths and constants
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
GALLERY_DIR = os.path.join(DATA_DIR, "gallery")
METADATA_FILE = os.path.join(DATA_DIR, "metadata.json")

# Standard sizes for face images
FACE_WIDTH = 224
FACE_HEIGHT = 224

# Create necessary directories
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(GALLERY_DIR, exist_ok=True)

# Initialize FastAPI app
app = FastAPI()

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.options("/{path:path}")
async def options_handler(path: str):
    """
    Handle OPTIONS requests for CORS preflight checks.
    This ensures that browsers don't get 405 Method Not Allowed errors
    when checking permissions before making actual requests.
    """
    return JSONResponse(
        content={"message": "OK"},
        status_code=200,
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
            "Access-Control-Allow-Headers": "*",
        },
    )

class PersonDetails(BaseModel):
    name: str  # Only name is required
    emp_id: str | None = None
    email: str | None = None
    phone: str | None = None
    role: str | None = "User"
    department: str | None = None
    designation: str | None = None
    joining_date: str | None = None
    status: str | None = "Active"
    age: str | None = None  # Optional
    gender: str | None = None  # Optional
    created_by: str | None = "system"

class RegistrationResponse(BaseModel):
    status: str
    message: str
    person_dir: Optional[str] = None
    error: Optional[str] = None
    age_range: Optional[str] = None
    age_source: Optional[str] = None

class MetadataManager:
    @staticmethod
    def load_metadata():
        """Load metadata from file"""
        try:
            if os.path.exists(METADATA_FILE):
                with open(METADATA_FILE, 'r') as f:
                    return json.load(f)
            return {
                "persons": {},
                "last_updated": datetime.now().isoformat(),
                "total_registered": 0
            }
        except Exception as e:
            print(f"Error loading metadata: {e}")
            return {
                "persons": {},
                "last_updated": datetime.now().isoformat(),
                "total_registered": 0
            }

    @staticmethod
    def save_metadata(metadata):
        """Save metadata to file"""
        try:
            with open(METADATA_FILE, 'w') as f:
                json.dump(metadata, f, indent=4)
            return True
        except Exception as e:
            print(f"Error saving metadata: {e}")
            return False

    @staticmethod
    def get_statistics(company_id: Optional[str] = None):
        """Get registration statistics filtered by company"""
        try:
            if os.path.exists(METADATA_FILE):
                with open(METADATA_FILE, 'r') as f:
                    metadata = json.load(f)
            else:
                metadata = {}
        except Exception:
            metadata = {}

        # Helper to extract persons from mixed/flat/nested metadata
        persons = {}
        if isinstance(metadata, dict):
            # Check for nested "persons" key first
            if "persons" in metadata and isinstance(metadata["persons"], dict):
                for k, v in metadata["persons"].items():
                    if isinstance(v, dict) and 'name' in v:
                        persons[k] = v
            
            # Also check top level for flat/mixed entries
            for k, v in metadata.items():
                if k == "persons": continue
                if isinstance(v, dict) and 'name' in v:
                    persons[k] = v
        
        # Filter by company_id
        if company_id:
            persons = {k: v for k, v in persons.items() if v.get("company_id") == company_id}
        
        # Count by category
        categories = {}
        today_count = 0
        today_str = datetime.now().strftime("%Y-%m-%d")
        
        for data in persons.values():
            category = data.get("category", "unknown")
            if not category: 
                category = "unknown"
            category = category.lower()
            categories[category] = categories.get(category, 0) + 1
            
            reg_date = data.get("registration_date", "")
            if reg_date and reg_date.startswith(today_str):
                today_count += 1
        
        # Count by gender
        genders = {}
        for data in persons.values():
            gender = data.get("gender", "Unspecified")
            genders[gender] = genders.get(gender, 0) + 1
        
        return {
            "total_registered": len(persons),
            "categories": categories,
            "genders": genders,
            "last_updated": datetime.now().isoformat(),
            "registered_today": today_count
        }

# Helper functions
def is_face_already_registered(image_input, company_id: Optional[str] = None) -> bool:
    """
    Check if the face is already registered
    Args:
        image_input: Can be either a file path (str) or a numpy array (RGB image)
        company_id: Optional company ID to scope the duplicate check
    """
    try:
        # Handle input image
        if isinstance(image_input, str):
            new_image = face_recognition.load_image_file(image_input)
        else:
            new_image = image_input  # Already a numpy array in RGB format
            
        new_face_encoding = face_recognition.face_encodings(new_image)

        if not new_face_encoding:
            return False

        new_face_encoding = new_face_encoding[0]

        if company_id:
            # Multi-tenant structure: data/gallery/{company_id}/{person_name}
            tenant_gallery = os.path.join(GALLERY_DIR, company_id)
            if not os.path.exists(tenant_gallery):
                return False
            search_dirs = [os.path.join(tenant_gallery, d) for d in os.listdir(tenant_gallery) if os.path.isdir(os.path.join(tenant_gallery, d))]
        else:
            # Fallback to global search in DATA_DIR (legacy)
            search_dirs = [os.path.join(DATA_DIR, d) for d in os.listdir(DATA_DIR) if os.path.isdir(os.path.join(DATA_DIR, d))]

        # Check each person's directory
        for person_dir in search_dirs:
            # Skip non-directory entries
            if not os.path.isdir(person_dir):
                continue

            for image_name in os.listdir(person_dir):
                if not image_name.lower().endswith(('.png', '.jpg', '.jpeg')):
                    continue

                image_path = os.path.join(person_dir, image_name)
                known_image = face_recognition.load_image_file(image_path)
                known_face_encoding = face_recognition.face_encodings(known_image)

                if not known_face_encoding:
                    continue

                matches = face_recognition.compare_faces(
                    [known_face_encoding[0]], 
                    new_face_encoding, 
                    tolerance=0.48
                )

                if True in matches:
                    return True

        return False
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error checking face: {str(e)}")

def get_unique_name(name: str) -> str:
    """Get a unique name for the person"""
    try:
        with open(METADATA_FILE, 'r') as f:
            person_data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        person_data = {}

    suffix = 1
    unique_name = name
    while unique_name in person_data:
        unique_name = f"{name}_{suffix}"
        suffix += 1

    return unique_name

def save_gallery_data(person_id: str, data: dict):
    """Save gallery data to JSON"""
    try:
        if os.path.exists(METADATA_FILE):
            with open(METADATA_FILE, 'r') as f:
                gallery_data = json.load(f)
        else:
            gallery_data = {}
        
        gallery_data[person_id] = data
        
        with open(METADATA_FILE, 'w') as f:
            json.dump(gallery_data, f, indent=4)
    except Exception as e:
        print(f"Error saving gallery data: {e}")

class DemographicsEstimator:
    @classmethod
    def estimate_demographics(cls, face_bgr: np.ndarray) -> dict:
        """
        Estimate age and gender from a face image using DeepFace.
        """
        try:
            if DeepFace is None:
                return {}
            
            # DeepFace's default age model is notoriously sensitive to facial hair (texture bias).
            # To solve this without washing out real age features (like for older clean-shaven people),
            # we run a dual-pass estimation and compare the results.
            
            # Pass 1: Raw face (Best for clean-shaven people)
            raw_results = DeepFace.analyze(
                img_path=face_bgr, 
                actions=['age', 'gender'],
                detector_backend='opencv',
                enforce_detection=False,
                silent=True
            )
            
            # Pass 2: Moderately filtered face (Smooths stubble but preserves major structures)
            # Settings optimized to drop beard-biased age significantly while preserving natural aging
            filtered_face = cv2.bilateralFilter(face_bgr, 15, 100, 100)
            clean_results = DeepFace.analyze(
                img_path=filtered_face, 
                actions=['age'],
                detector_backend='opencv',
                enforce_detection=False,
                silent=True
            )
            
            def extract_age(res):
                if isinstance(res, list) and len(res) > 0:
                    return res[0].get('age')
                elif isinstance(res, dict):
                    return res.get('age')
                return None

            raw_age = extract_age(raw_results)
            clean_age = extract_age(clean_results)
            
            # Logic to handle beard bias vs natural aging:
            # - A beard often causes a massive (+15-20 year) overestimation.
            # - Natural wrinkles caused by age typically only fluctuate by <10 years under this filter.
            if raw_age is not None and clean_age is not None:
                diff = raw_age - clean_age
                if raw_age > 30 and diff > 12:
                    # High discrepancy (>12 years) strongly indicates a texture bias (beard).
                    # We use the clean/filtered value (+1 year buffer).
                    age = int(clean_age + 1)
                else:
                    # Small discrepancy or already young person. 
                    # Trust the raw image more to avoid underestimating truly older people.
                    age = raw_age
            else:
                age = raw_age or clean_age
            
            # Use Pass 1 for gender (gender is much more stable)
            results = raw_results
            
            if results:
                # DeepFace analyze with enforce_detection=False could return list or dict depending on version
                if isinstance(results, list) and len(results) > 0:
                    res_dict = results[0]
                elif isinstance(results, dict):
                    res_dict = results
                else:
                    res_dict = {}

                age = res_dict.get('age')
                # dominant_gender is typically 'Man' or 'Woman' in DeepFace
                gender = res_dict.get('dominant_gender') 
                
                # Normalize gender string to match our frontend/db conventions
                normalized_gender = None
                if gender:
                    if isinstance(gender, dict):
                        # Some versions return dict of probabilities, we need the max
                        gender = max(gender, key=gender.get)
                    if isinstance(gender, str):
                        if 'Man' in gender or 'man' in gender or 'Male' in gender:
                            normalized_gender = 'Male'
                        elif 'Woman' in gender or 'woman' in gender or 'Female' in gender:
                            normalized_gender = 'Female'
                        else:
                            normalized_gender = gender

                # Ensure age is a raw integer, some versions might return numpy float/int
                try:
                    final_age = int(round(float(age))) if age is not None else None
                except Exception:
                    final_age = None

                return {
                    "age": final_age,
                    "gender": normalized_gender
                }
            
            return {}
        except Exception as e:
            import traceback
            print(f"Error in DemographicsEstimator.estimate_demographics: {e}")
            traceback.print_exc()
            return {}

def bucket_age_range(age: int, width: int = 5, min_age: int = 18) -> str:
    if age < min_age:
        age = min_age
    offset = age - min_age
    bucket_idx = offset // width
    lower = min_age + width * bucket_idx
    upper = lower + width
    return f"{lower}-{upper}"

class FaceProcessor:
    @staticmethod
    def standardize_face(image):
        """Standardize face image to fixed size with proper alignment using RetinaFace"""
        try:
            # Convert to RGB if needed
            if len(image.shape) == 3 and image.shape[2] == 3:
                rgb_image = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            else:
                rgb_image = image

            # Detect faces using RetinaFace for high accuracy
            if RetinaFace is not None:
                faces = RetinaFace.detect_faces(rgb_image)
            else:
                faces = None
            
            if not faces or not isinstance(faces, dict):
                # Fallback to face_recognition if RetinaFace fails
                if face_recognition is None:
                    return None
                face_locations = face_recognition.face_locations(rgb_image)
                if not face_locations:
                    return None
                face_location = max(face_locations, key=lambda rect: (rect[2] - rect[0]) * (rect[1] - rect[3]))
                top, right, bottom, left = face_location
            else:
                # Get the largest face by area
                best_face = None
                max_area = 0
                for face_id in faces:
                    area = faces[face_id]['facial_area'] # [x1, y1, x2, y2]
                    face_area = (area[2] - area[0]) * (area[3] - area[1])
                    if face_area > max_area:
                        max_area = face_area
                        best_face = area
                
                if not best_face:
                    return None
                
                # RetinaFace returns [x1, y1, x2, y2]
                left, top, right, bottom = best_face

            # Calculate padding to maintain aspect ratio
            face_width = right - left
            face_height = bottom - top
            
            # Add padding to make it square while maintaining the face centered
            if face_width > face_height:
                # Width is larger, add padding to height
                padding_y = (face_width - face_height) // 2
                top = max(0, top - padding_y)
                bottom = min(rgb_image.shape[0], bottom + padding_y)
            else:
                # Height is larger, add padding to width
                padding_x = (face_height - face_width) // 2
                left = max(0, left - padding_x)
                right = min(rgb_image.shape[1], right + padding_x)

            # Add extra padding around the square
            padding = int(min(right - left, bottom - top) * 0.3)
            height, width = image.shape[:2]
            
            top = max(0, top - padding)
            bottom = min(height, bottom + padding)
            left = max(0, left - padding)
            right = min(width, right + padding)

            # Crop and resize face
            face = image[top:bottom, left:right]
            
            # Ensure high-quality resizing
            standardized_face = cv2.resize(face, (FACE_WIDTH, FACE_HEIGHT), 
                                         interpolation=cv2.INTER_LANCZOS4)
            
            return standardized_face
        except Exception as e:
            print(f"Error in standardize_face: {e}")
            return None

    @staticmethod
    def detect_and_crop_face(image_input):
        """Detect and crop face from image input (can be path or numpy array)"""
        try:
            if isinstance(image_input, str):
                img = cv2.imread(image_input)
                if img is None:
                    return None
            else:
                img = image_input

            # Standardize the input image size if it's too large
            max_dimension = 1200  # Maximum dimension to process
            height, width = img.shape[:2]
            if max(height, width) > max_dimension:
                scale = max_dimension / max(height, width)
                new_width = int(width * scale)
                new_height = int(height * scale)
                img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_AREA)

            return FaceProcessor.standardize_face(img)
        except Exception as e:
            print(f"Error in detect_and_crop_face: {e}")
            return None

    @staticmethod
    def augment_face(face_image, output_dir):
        """Generate 50 augmented versions of the face image"""
        try:
            os.makedirs(output_dir, exist_ok=True)
            final_paths = []
            
            # Ensure face_image is standardized
            standardized_face = cv2.resize(face_image, (FACE_WIDTH, FACE_HEIGHT))
            
            # Save the original face as 1.jpg
            first_path = os.path.join(output_dir, "1.jpg")
            cv2.imwrite(first_path, standardized_face)
            final_paths.append(first_path)
            
            # Generate 49 more augmented images
            orig_img = standardized_face.copy()
            for i in range(2, 51):
                # Apply random augmentations
                # Rotation
                angle = np.random.randint(-15, 15)
                M = cv2.getRotationMatrix2D((FACE_WIDTH/2, FACE_HEIGHT/2), angle, 1)
                rotated = cv2.warpAffine(orig_img, M, (FACE_WIDTH, FACE_HEIGHT))
                
                # Scale
                scale = np.random.uniform(0.9, 1.1)
                scaled = cv2.resize(rotated, None, fx=scale, fy=scale)
                scaled = cv2.resize(scaled, (FACE_WIDTH, FACE_HEIGHT))
                
                # Brightness and contrast
                alpha = np.random.uniform(0.7, 1.3)
                beta = np.random.randint(-30, 30)
                adjusted = cv2.convertScaleAbs(scaled, alpha=alpha, beta=beta)
                
                # Save the augmented image
                aug_path = os.path.join(output_dir, f"{i}.jpg")
                cv2.imwrite(aug_path, adjusted)
                final_paths.append(aug_path)

            return final_paths
        except Exception as e:
            print(f"Error in augment_face: {e}")
            return []

    @staticmethod
    def process_bulk_registration(excel_path, root_data_dir, output_base_dir):
        """Process bulk registration using Excel data and folder structure."""
        VALID_CATEGORIES = [
            'criminal', 'offender', 'chainsnatching',
            'eve teasing', 'unknown', 'eagleemployee'
        ]

        try:
            # Read Excel file
            df = pd.read_excel(excel_path)
            print(f"Read Excel file with columns: {df.columns.tolist()}")  # Debug print

            if 'name' not in df.columns:
                raise ValueError("Excel MUST have a 'name' column")

            # Clean up the data
            df['name'] = df['name'].str.strip()
            df = df.dropna(subset=['name'])
            
            # Ensure required columns exist
            df['age'] = df.get('age', '')
            df['gender'] = df.get('gender', '')
            df['category'] = df.get('category', 'unknown')
            for col in ['emp_id', 'email', 'phone', 'role', 'department', 'designation', 'zone', 'status']:
                df[col] = df.get(col, '')

            # Convert category to lowercase and validate
            df['category'] = df['category'].str.lower()
            df['category'] = df['category'].apply(
                lambda x: x if x in VALID_CATEGORIES else 'unknown'
            )

            if len(df) == 0:
                raise ValueError("No valid names found in the Excel file")

            registration_results = {}
            all_augmented_images = []

            # Process each person
            for _, row in df.iterrows():
                person_name = row['name']
                print(f"Processing person: {person_name}")  # Debug print

                # Look for person's folder
                person_folder = os.path.join(root_data_dir, person_name)
                if not os.path.exists(person_folder):
                    print(f"No folder found for {person_name} at {person_folder}")  # Debug print
                    registration_results[person_name] = {'status': 'failed', 'reason': 'folder missing'}
                    continue

                try:
                    # Prepare person details
                    person_details = {
                        'name': person_name,
                        'age': str(row['age']).strip() if pd.notna(row['age']) else '',
                        'gender': str(row['gender']).strip() if pd.notna(row['gender']) else '',
                        'category': str(row['category']).strip() if pd.notna(row['category']) else 'unknown',
                        'emp_id': str(row['emp_id']).strip() if pd.notna(row['emp_id']) else '',
                        'email': str(row['email']).strip() if pd.notna(row['email']) else '',
                        'phone': str(row['phone']).strip() if pd.notna(row['phone']) else '',
                        'role': str(row['role']).strip() if pd.notna(row['role']) else 'User',
                        'department': str(row['department']).strip() if pd.notna(row['department']) else '',
                        'designation': str(row['designation']).strip() if pd.notna(row['designation']) else '',
                        'zone': str(row['zone']).strip() if pd.notna(row['zone']) else '',
                        'status': str(row['status']).strip() if pd.notna(row['status']) else 'Active'
                    }

                    # Get all images from person's folder
                    image_files = [
                        f for f in os.listdir(person_folder)
                        if f.lower().endswith(('.jpg', '.jpeg', '.png'))
                    ]

                    if not image_files:
                        registration_results[person_name] = {'status': 'failed', 'reason': 'no images found'}
                        continue

                    # Process first image to check for duplicates
                    first_image_path = os.path.join(person_folder, image_files[0])
                    first_image = face_recognition.load_image_file(first_image_path)
                    
                    if is_face_already_registered(first_image):
                        registration_results[person_name] = {'status': 'failed', 'reason': 'duplicate face'}
                        continue

                    # Create output directory for this person
                    safe_name = re.sub(r'[^\w\-_\. ]', '', person_name)
                    output_dir = os.path.join(output_base_dir, safe_name)
                    os.makedirs(output_dir, exist_ok=True)

                    # Process all images for the person
                    person_augmented = []
                    for img_file in image_files:
                        img_path = os.path.join(person_folder, img_file)
                        try:
                            face = FaceProcessor.detect_and_crop_face(img_path)
                            if face is not None:
                                augmented = FaceProcessor.augment_face(face, output_dir)
                                person_augmented.extend(augmented)
                        except Exception as e:
                            print(f"Error processing image {img_path}: {e}")

                    if person_augmented:
                        registration_results[person_name] = {
                            'status': 'success',
                            'images': len(person_augmented),
                            'details': person_details
                        }
                        all_augmented_images.extend(person_augmented)

                        # Create gallery directory and copy first image
                        gallery_dir = os.path.join(GALLERY_DIR, safe_name)
                        os.makedirs(gallery_dir, exist_ok=True)
                        shutil.copy2(
                            os.path.join(output_dir, "1.jpg"),
                            os.path.join(gallery_dir, "1.jpg")
                        )
                    else:
                        registration_results[person_name] = {
                            'status': 'failed',
                            'reason': 'no valid faces detected'
                        }

                except Exception as e:
                    print(f"Error processing person {person_name}: {e}")
                    registration_results[person_name] = {
                        'status': 'failed',
                        'reason': str(e)
                    }

            return registration_results, all_augmented_images

        except Exception as e:
            print(f"Error in bulk registration: {e}")
            return {}, []

# Endpoints
@app.post("/register/single", response_model=RegistrationResponse)
async def register_single(
    request: Request,
    image: UploadFile = File(...),
    name: str = Form(...),
    age: str | None = Form(None),
    gender: str | None = Form(None),
    emp_id: str | None = Form(None),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    role: str | None = Form(None),
    department: str | None = Form(None),
    designation: str | None = Form(None),
    joining_date: str | None = Form(None),
    status: str | None = Form(None)
):
    """Register a single person with face image"""
    print(f"--- Registration Request ---")
    print(f"Name: {name!r}")
    print(f"Emp ID: {emp_id!r}")
    print(f"Age: {age!r}")
    print(f"Gender: {gender!r}")
    try:
        # Validate image file type
        if not image.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            raise HTTPException(
                status_code=400,
                detail="Invalid file type. Please upload a PNG or JPEG image."
            )

        # Read image directly into memory
        contents = await image.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        
        if img is None:
            raise HTTPException(
                status_code=400,
                detail="Failed to read image file. Please ensure it's a valid image."
            )
        
        # Detect and standardize face
        face = FaceProcessor.detect_and_crop_face(img)
        if face is None:
            raise HTTPException(
                status_code=400,
                detail="No face detected in the image. Please ensure the face is clearly visible, well-lit, and looking towards the camera."
            )
        
        # Convert to format needed by face_recognition for duplicate check
        rgb_face = cv2.cvtColor(face, cv2.COLOR_BGR2RGB)
        
        # Get creator and company from scope
        current_user = request.scope.get("user", {})
        creator = current_user.get("username", "system")
        company_id = current_user.get("company_id")

        if is_face_already_registered(rgb_face, company_id=company_id):
            raise HTTPException(
                status_code=400,
                detail="This face is already registered in the system."
            )

        # Get creator and company from scope
        current_user = request.scope.get("user", {})
        creator = current_user.get("username", "system")
        company_id = current_user.get("company_id")

        # Get unique name and create directories
        unique_name = get_unique_name(name.lower())
        person_dir = os.path.join(DATA_DIR, unique_name)
        
        # Multi-tenant gallery structure
        if company_id:
            gallery_dir = os.path.join(GALLERY_DIR, company_id, unique_name)
        else:
            gallery_dir = os.path.join(GALLERY_DIR, unique_name)
            
        os.makedirs(gallery_dir, exist_ok=True)

        # Generate augmented images
        augmented_images = FaceProcessor.augment_face(face, person_dir)
        if not augmented_images:
            raise HTTPException(
                status_code=500,
                detail="Failed to process face images. Please try again with a different photo."
            )

        # Save standardized original image to gallery
        original_path = os.path.join(gallery_dir, "1.jpg")
        cv2.imwrite(original_path, face)

        # Determine age and range (manual overrides AI)
        demographics = DemographicsEstimator.estimate_demographics(face)
        predicted_age = demographics.get("age")
        predicted_gender = demographics.get("gender")
        
        manual_age_val = None
        if age:
            age_str = str(age).strip().lower()
            if age_str not in ("", "null", "undefined", "none"):
                try:
                    manual_age_val = int(age_str)
                except Exception:
                    manual_age_val = None
                    
        final_age_val = manual_age_val if manual_age_val is not None else predicted_age
        age_source = "manual" if manual_age_val is not None else ("ai" if predicted_age is not None else "unknown")
        age_range = bucket_age_range(final_age_val) if isinstance(final_age_val, int) else "N/A"
        
        # Determine gender (manual overrides AI)
        final_gender = gender if gender and gender.strip() != "" else (predicted_gender if predicted_gender else "N/A")

        # Update JSON data
        try:
            with open(METADATA_FILE, 'r') as f:
                person_data = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            person_data = {}

        registration_time = datetime.now().isoformat()
        person_data[unique_name] = {
            "name": name,
            "emp_id": emp_id.strip() if emp_id else "",
            "email": email.strip() if email else "",
            "phone": phone.strip() if phone else "",
            "role": role.strip() if role else "User",
            "department": department.strip() if department else "",
            "designation": designation.strip() if designation else "",
            "joining_date": joining_date.strip() if joining_date else "",
            "status": status.strip() if status else "Active",
            "age": str(final_age_val) if isinstance(final_age_val, int) else "N/A",
            "gender": final_gender,
            "registration_date": registration_time,
            "gallery_path": os.path.relpath(gallery_dir, BASE_DIR).replace('\\', '/'),
            "photo_path": os.path.relpath(original_path, BASE_DIR).replace('\\', '/'),
            "age_range": age_range,
            "age_source": age_source,
            "predicted_age": predicted_age if isinstance(predicted_age, int) else None,
            "predicted_gender": predicted_gender,
            "created_by": creator,
            "company_id": company_id
        }

        with open(METADATA_FILE, 'w') as f:
            json.dump(person_data, f, indent=4)

        return RegistrationResponse(
            status="success",
            message=f"Successfully registered {name}",
            person_dir=person_dir,
            age_range=age_range,
            age_source=age_source
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Registration failed: {str(e)}"
        )

@app.post("/register/bulk", response_model=List[RegistrationResponse])
async def register_bulk(
    request: Request,
    excel_file: UploadFile = File(...),
    image_files: List[UploadFile] = File(...),
):
    """Register multiple people using Excel file and uploaded image files"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id")
        creator = current_user.get("username", "system")
        # Create temporary directory for processing
        temp_dir = os.path.join(DATA_DIR, "temp_bulk")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Save Excel file temporarily
        excel_path = os.path.join(temp_dir, "data.xlsx")
        excel_content = await excel_file.read()
        with open(excel_path, "wb") as f:
            f.write(excel_content)
        
        # Read Excel file to get list of valid names
        df = pd.read_excel(excel_path)
        if 'name' not in df.columns:
            raise ValueError("Excel file must have a 'name' column")
        
        # Clean up the data
        df['name'] = df['name'].str.strip()
        df = df.dropna(subset=['name'])
        
        # Create a temporary data directory structure from uploaded files
        temp_data_dir = os.path.join(temp_dir, "uploaded_data")
        os.makedirs(temp_data_dir, exist_ok=True)
        
        # Process and organize uploaded files
        # Match files based on filename to person name in Excel
        for uploaded_file in image_files:
            if not uploaded_file.filename:
                continue
            
            file_content = await uploaded_file.read()
            image_filename = uploaded_file.filename.replace("\\", "/")
            
            # Get just the filename (last part of path after any /)
            actual_filename = image_filename.split("/")[-1]
            
            # Extract person name from filename (without extension)
            filename_without_ext = os.path.splitext(actual_filename)[0]
            
            # Check if this filename matches a person in Excel
            person_name = None
            for name in df['name'].values:
                if filename_without_ext == name or filename_without_ext.lower() == str(name).lower():
                    person_name = name
                    break
            
            if not person_name:
                print(f"Skipping {actual_filename} - no matching person '{filename_without_ext}' in Excel")
                continue
            
            # Create person directory
            person_dir = os.path.join(temp_data_dir, person_name)
            os.makedirs(person_dir, exist_ok=True)
            
            # Save image file
            image_path = os.path.join(person_dir, actual_filename)
            with open(image_path, "wb") as f:
                f.write(file_content)

        # Process bulk registration using the uploaded data directory
        results, augmented_images = FaceProcessor.process_bulk_registration(
            excel_path=excel_path,
            root_data_dir=temp_data_dir,
            output_base_dir=DATA_DIR
        )

        # Update metadata for successful registrations
        try:
            with open(METADATA_FILE, 'r') as f:
                metadata = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            metadata = {}

        # Convert results to response format
        response_list = []
        for person_name, result in results.items():
            if result['status'] == 'success':
                # Update metadata
                safe_name = re.sub(r'[^\w\-_\. ]', '', person_name)
                age_str = result['details'].get('age', '')
                age_int = None
                if age_str:
                    age_str = str(age_str).strip().lower()
                    if age_str not in ("", "null", "undefined", "none"):
                        try:
                            age_int = int(age_str)
                        except Exception:
                            age_int = None
                if company_id:
                    gallery_person_dir = os.path.join(GALLERY_DIR, company_id, safe_name)
                else:
                    gallery_person_dir = os.path.join(GALLERY_DIR, safe_name)
                
                gallery_face_path = os.path.join(gallery_person_dir, "1.jpg")
                predicted_age = None
                predicted_gender = None
                if age_int is None or not result['details'].get('gender', '').strip():
                    if os.path.exists(gallery_face_path):
                        try:
                            face_img = cv2.imread(gallery_face_path)
                            demographics = DemographicsEstimator.estimate_demographics(face_img)
                            predicted_age = demographics.get("age")
                            predicted_gender = demographics.get("gender")
                        except Exception:
                            pass
                            
                final_age = age_int if age_int is not None else predicted_age
                age_source = "manual" if age_int is not None else ("ai" if predicted_age is not None else "unknown")
                age_range = bucket_age_range(final_age) if isinstance(final_age, int) else "N/A"
                
                manual_gender = result['details'].get('gender', '').strip()
                final_gender = manual_gender if manual_gender != "" else (predicted_gender if predicted_gender else "N/A")
                
                metadata[safe_name] = {
                    'name': person_name,
                    'emp_id': result['details'].get('emp_id', ''),
                    'email': result['details'].get('email', ''),
                    'phone': result['details'].get('phone', ''),
                    'role': result['details'].get('role', 'User'),
                    'department': result['details'].get('department', ''),
                    'designation': result['details'].get('designation', ''),
                    'zone': result['details'].get('zone', ''),
                    'status': result['details'].get('status', 'Active'),
                    'age': str(final_age) if isinstance(final_age, int) else str(result['details'].get('age', '')) or "N/A",
                    'gender': final_gender,
                    'category': result['details']['category'],
                    'registration_date': datetime.now().isoformat(),
                    'gallery_path': os.path.relpath(os.path.join(GALLERY_DIR, safe_name), BASE_DIR).replace('\\', '/'),
                    'photo_path': os.path.relpath(os.path.join(GALLERY_DIR, safe_name, "1.jpg"), BASE_DIR).replace('\\', '/'),
                    'age_range': age_range,
                    'age_source': age_source,
                    'predicted_age': predicted_age if isinstance(predicted_age, int) else None,
                    'predicted_gender': predicted_gender,
                    'company_id': company_id,
                    'created_by': creator
                }

                # Create gallery directory and copy original image
                if company_id:
                    gallery_person_dir = os.path.join(GALLERY_DIR, company_id, safe_name)
                else:
                    gallery_person_dir = os.path.join(GALLERY_DIR, safe_name)
                    
                os.makedirs(gallery_person_dir, exist_ok=True)
                
                # Copy the first augmented image as original.jpg in gallery
                if augmented_images:
                    first_image = os.path.join(DATA_DIR, safe_name, "1.jpg")
                    if os.path.exists(first_image):
                        shutil.copy2(first_image, os.path.join(gallery_person_dir, "1.jpg"))

                response_list.append(RegistrationResponse(
                    status='success',
                    message=f"Successfully registered {person_name}",
                    person_dir=os.path.join(DATA_DIR, safe_name),
                    age_range=age_range,
                    age_source=age_source
                ))
            else:
                response_list.append(RegistrationResponse(
                    status='error',
                    message=f"Failed to register {person_name}: {result['reason']}",
                    error=result['reason']
                ))

        # Save updated metadata
        with open(METADATA_FILE, 'w') as f:
            json.dump(metadata, f, indent=4)

        # Cleanup temporary files
        shutil.rmtree(temp_dir, ignore_errors=True)

        return response_list

    except Exception as e:
        # Ensure cleanup on error
        if 'temp_dir' in locals():
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/registered-faces", response_model=Dict)
async def get_registered_faces(request: Request):
    """Get list of all registered faces"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id")
        
        with open(METADATA_FILE, 'r') as f:
            person_data = json.load(f)
        
        # Filter by company_id
        if company_id:
            person_data = {k: v for k, v in person_data.items() if v.get("company_id") == company_id}
        elif current_user.get("role") != "SuperAdmin":
            # Fallback for old data or missing company_id
            username = current_user.get("username")
            person_data = {k: v for k, v in person_data.items() if v.get("created_by") == username}
            
        return person_data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/gallery", response_model=Dict)
async def get_gallery(request: Request, name: Optional[str] = None, category: Optional[str] = None):
    """Get gallery data with image filenames, optionally filtered by name and category"""
    try:
        persons = {}

        if os.path.exists(METADATA_FILE):
            with open(METADATA_FILE, 'r') as f:
                metadata = json.load(f)

            if isinstance(metadata, dict):
                if "persons" in metadata and isinstance(metadata["persons"], dict):
                    for k, v in metadata["persons"].items():
                        if isinstance(v, dict) and 'name' in v:
                            persons[k] = v

                for k, v in metadata.items():
                    if k == "persons":
                        continue
                    if isinstance(v, dict) and 'name' in v:
                        persons[k] = v
            
            # Filter by company_id
            current_user = request.scope.get("user", {})
            company_id = current_user.get("company_id")
            if company_id:
                persons = {k: v for k, v in persons.items() if v.get("company_id") == company_id}
            elif current_user.get("role") != "SuperAdmin":
                username = current_user.get("username")
                persons = {k: v for k, v in persons.items() if v.get("created_by") == username}
        else:
            if os.path.exists(GALLERY_DIR):
                target_dirs = []
                if company_id:
                    target_dirs = [(os.path.join(GALLERY_DIR, company_id), company_id)]
                elif current_user.get("role") == "SuperAdmin":
                    # Scan all subdirectories (each is a company_id)
                    for entry in os.scandir(GALLERY_DIR):
                        if entry.is_dir():
                            target_dirs.append((entry.path, entry.name))
                else:
                    target_dirs = [(os.path.join(GALLERY_DIR, "default"), "default")]

                for tdir, t_company_id in target_dirs:
                    if not os.path.exists(tdir): continue
                    for entry in os.scandir(tdir):
                        if not entry.is_dir():
                            continue
                        persons[entry.name] = {
                            "name": entry.name,
                            "age": "N/A",
                            "gender": "N/A",
                            "category": "unknown",
                            "registration_date": None,
                            "gallery_path": os.path.relpath(entry.path, BASE_DIR).replace('\\', '/'),
                            "photo_path": os.path.relpath(os.path.join(entry.path, "1.jpg"), BASE_DIR).replace('\\', '/'),
                            "company_id": t_company_id
                        }

        processed_data = {}
        for person_id, person_data in persons.items():
            person_name = (person_data.get('name') or person_id)

            if name and name.lower() not in str(person_name).lower():
                continue

            person_category = (person_data.get('category') or 'unknown')
            if category and category.lower() != 'all' and category.lower() != str(person_category).lower():
                continue

            processed_data[person_id] = person_data.copy()
            processed_data[person_id]['name'] = person_name
            processed_data[person_id]['category'] = person_category

            photo_path = person_data.get('photo_path')
            image_filename = None
            if photo_path:
                image_filename = str(photo_path).replace('\\', '/').split('/')[-1]

            if not image_filename:
                # Determine correct folder based on person's company_id
                img_company_id = person_data.get('company_id') or company_id or 'default'
                person_folder = os.path.join(GALLERY_DIR, img_company_id, person_id)
                
                p1 = os.path.join(person_folder, "1.jpg")
                p2 = os.path.join(person_folder, "original.jpg")
                if os.path.exists(p1):
                    image_filename = "1.jpg"
                elif os.path.exists(p2):
                    image_filename = "original.jpg"
                else:
                    try:
                        folder = person_folder
                        candidates = [
                            f.name for f in os.scandir(folder)
                            if f.is_file() and f.name.lower().endswith((".jpg", ".jpeg", ".png"))
                        ]
                        candidates.sort()
                        image_filename = candidates[0] if candidates else "original.jpg"
                    except Exception:
                        image_filename = "original.jpg"

            processed_data[person_id]['image_filename'] = image_filename
            
            # Construct tenant-aware image URL
            url_company_id = company_id or "default"
            processed_data[person_id]['image_url'] = f"/api/gallery/image/{url_company_id}/{person_id}/{image_filename}"

        return processed_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metadata")
async def get_metadata():
    """Get all metadata"""
    try:
        return MetadataManager.load_metadata()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/metadata")
async def save_metadata(metadata: dict):
    """Save metadata"""
    try:
        if MetadataManager.save_metadata(metadata):
            return {"status": "success"}
        raise HTTPException(status_code=500, detail="Failed to save metadata")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/statistics")
async def get_statistics(request: Request):
    """Get registration statistics filtered by company"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id")
        return MetadataManager.get_statistics(company_id=company_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/metadata/person/{person_id}")
async def add_person_metadata(person_id: str, data: dict):
    """Add a new person to metadata"""
    try:
        metadata = MetadataManager.load_metadata()
        metadata.setdefault("persons", {})[person_id] = {
            "name": data.get("name", ""),
            "age": data.get("age", ""),
            "gender": data.get("gender", ""),
            "category": data.get("category", ""),
            "registration_date": datetime.now().isoformat()
        }
        if MetadataManager.save_metadata(metadata):
            return {"status": "success"}
        raise HTTPException(status_code=500, detail="Failed to save metadata")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.put("/metadata/person/{person_id}")
async def update_person_metadata(person_id: str, data: dict):
    """Update a person's metadata"""
    try:
        metadata = MetadataManager.load_metadata()
        if person_id not in metadata.get("persons", {}):
            raise HTTPException(status_code=404, detail="Person not found")
        metadata["persons"][person_id].update(data)
        if MetadataManager.save_metadata(metadata):
            return {"status": "success"}
        raise HTTPException(status_code=500, detail="Failed to save metadata")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/metadata/person/{person_id}")
async def delete_person_metadata(person_id: str):
    """Delete a person from metadata"""
    try:
        metadata = MetadataManager.load_metadata()
        if person_id not in metadata.get("persons", {}):
            raise HTTPException(status_code=404, detail="Person not found")
        del metadata["persons"][person_id]
        if MetadataManager.save_metadata(metadata):
            return {"status": "success"}
        raise HTTPException(status_code=500, detail="Failed to save metadata")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/metadata/statistics")
async def get_metadata_statistics(request: Request):
    """Get registration statistics"""
    try:
        current_user = request.scope.get("user", {})
        company_id = current_user.get("company_id")
        return MetadataManager.get_statistics(company_id=company_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/system/reset")
async def system_reset(request: Request):
    """Reset the entire system data (Only for SuperAdmin)"""
    current_user = request.scope.get("user", {})
    if current_user.get("role") != "SuperAdmin":
        raise HTTPException(status_code=403, detail="Only SuperAdmin can perform a system reset")
    
    try:
        logger.info(f"System reset initiated by SuperAdmin: {current_user.get('username')}")
        
        # 1. Clear Gallery directory
        if os.path.exists(GALLERY_DIR):
            for item in os.listdir(GALLERY_DIR):
                item_path = os.path.join(GALLERY_DIR, item)
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                except Exception as e:
                    logger.warning(f"Failed to remove {item_path}: {e}")
        
        # 2. Clear Registration data directories in DATA_DIR
        for item in os.listdir(DATA_DIR):
            item_path = os.path.join(DATA_DIR, item)
            # Skip gallery, auth, camera_management, and metadata.json (will be reset)
            if item in ["gallery", "auth", "camera_management", "metadata.json", "embeddings_cache.pkl", "temp_bulk", "logs"]:
                continue
            try:
                if os.path.isdir(item_path):
                    shutil.rmtree(item_path)
                else:
                    # Skip critical files if any
                    pass
            except Exception as e:
                logger.warning(f"Failed to remove {item_path}: {e}")
        
        # 3. Clear temp bulk
        temp_bulk = os.path.join(DATA_DIR, "temp_bulk")
        if os.path.exists(temp_bulk):
            shutil.rmtree(temp_bulk, ignore_errors=True)

        # 4. Reset metadata.json
        empty_metadata = {
            "persons": {},
            "last_updated": datetime.now().isoformat(),
            "total_registered": 0
        }
        with open(METADATA_FILE, 'w') as f:
            json.dump(empty_metadata, f, indent=4)
            
        # 5. Clear embeddings cache
        embeddings_cache = os.path.join(DATA_DIR, "embeddings_cache.pkl")
        if os.path.exists(embeddings_cache):
            try:
                os.remove(embeddings_cache)
            except Exception as e:
                logger.warning(f"Failed to remove {embeddings_cache}: {e}")
            
        # 6. Clear captured faces
        cf_dir = os.path.join(BASE_DIR, "captured_faces")
        if os.path.exists(cf_dir):
            for sub in ["known", "unknown"]:
                sub_dir = os.path.join(cf_dir, sub)
                if os.path.exists(sub_dir):
                    for item in os.listdir(sub_dir):
                        item_path = os.path.join(sub_dir, item)
                        try:
                            if os.path.isdir(item_path):
                                shutil.rmtree(item_path)
                            else:
                                os.remove(item_path)
                        except Exception as e:
                            logger.warning(f"Failed to remove {item_path}: {e}")

        logger.info("System data reset completed successfully")
        return {"status": "success", "message": "System data cleared successfully"}
    except Exception as e:
        logger.error(f"Error during system reset: {e}")
        raise HTTPException(status_code=500, detail=f"Reset failed: {str(e)}")

# This app can be mounted in the main application

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
