import cv2
import os
import albumentations as A

def detect_face(image_path):
    # Load Haar Cascade for face detection
    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
    image = cv2.imread(image_path)

    if image is None:
        raise ValueError("Image not found! Please check the path.")
    
    # Convert to grayscale for detection
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50))

    if len(faces) == 0:
        raise ValueError("No faces detected in the image!")
    
    # Assume the first detected face is the target (for simplicity)
    x, y, w, h = faces[0]
    face = image[y:y+h, x:x+w]  # Crop the face region
    return face

def augment_face(face, output_dir, num_images=50):
    # Define augmentation pipeline using Albumentations
    transform = A.Compose([
        A.HorizontalFlip(p=0.5),
        A.Rotate(limit=30, p=0.5),
        A.RandomBrightnessContrast(p=0.5),
        A.GaussianBlur(p=0.5),
        A.GaussNoise(p=0.5),
        A.Resize(224, 224),  # Resize the face to a fixed size
    ])

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # Apply augmentations and save augmented faces
    for i in range(num_images):
        augmented = transform(image=face)["image"]
        output_path = os.path.join(output_dir, f"{i + 1}.jpg")
        cv2.imwrite(output_path, augmented)

    return True
