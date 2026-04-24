import sys
import os
import traceback

# Add project root to sys.path
project_root = r"c:\Users\e629\Desktop\faceattendance\backend_face"
sys.path.append(project_root)

try:
    import cv2
    print(f"OpenCV version: {cv2.__version__}")
except ImportError as e:
    print(f"OpenCV import failed: {e}")

try:
    import face_recognition
    print("face_recognition imported successfully")
except ImportError as e:
    print(f"face_recognition import failed: {e}")

try:
    from insightface.app import FaceAnalysis
    print("insightface imported successfully")
except ImportError as e:
    print(f"insightface import failed: {e}")

try:
    from face_pipeline import init as init_face_pipeline
    data_dir = os.path.join(project_root, "data")
    
    print("Initializing face pipeline on GPU (ctx=0)...")
    init_face_pipeline(data_dir, ctx=0, det_size=(1280, 1280))
    print("Face pipeline initialized successfully on GPU")
except Exception as e:
    print(f"Face pipeline GPU initialization failed: {e}")
    try:
        print("Falling back to CPU (ctx=-1)...")
        init_face_pipeline(data_dir, ctx=-1, det_size=(1280, 1280))
        print("Face pipeline initialized successfully on CPU")
    except Exception as e2:
        print(f"Face pipeline CPU initialization failed: {e2}")
        traceback.print_exc()
