import os

# Base directory for the application
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Directories for storing face images
KNOWN_FACES_DIR = os.path.join(BASE_DIR, "captured_faces", "known")
UNKNOWN_FACES_DIR = os.path.join(BASE_DIR, "captured_faces", "unknown")

# Create directories if they don't exist
os.makedirs(KNOWN_FACES_DIR, exist_ok=True)
os.makedirs(UNKNOWN_FACES_DIR, exist_ok=True)

# API settings
API_HOST = "localhost"
API_PORT = 8000
API_PREFIX = "/api" 