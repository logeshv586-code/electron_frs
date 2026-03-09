import cv2
import numpy as np
from PyQt6.QtCore import QObject, pyqtSignal
from core.face_recognition import FaceRecognitionSystem

class FrameProcessor(QObject):
    face_detected = pyqtSignal(dict)
    processed_frame = pyqtSignal(object)

    def __init__(self):
        super().__init__()
        self.face_recognition = FaceRecognitionSystem()
        self.min_confidence = 60  # Minimum confidence threshold

    def process_frame(self, frame):
        # Process the frame for face detection and recognition
        results = self.face_recognition.process_frame(frame)
        
        # Draw rectangles and labels on the frame
        annotated_frame = frame.copy()
        for result in results:
            if result["confidence"] >= self.min_confidence:
                self._draw_face_box(
                    annotated_frame,
                    result["location"],
                    result["name"],
                    result["confidence"]
                )
                # Emit face detection event
                self.face_detected.emit(result)

        # Emit the processed frame
        self.processed_frame.emit(annotated_frame)

    def _draw_face_box(self, frame, location, name, confidence):
        left, top, right, bottom = location
        
        # Draw rectangle around face
        cv2.rectangle(frame, (left, top), (right, bottom), (0, 255, 0), 2)
        
        # Create label with name and confidence
        label = f"{name} ({confidence:.1f}%)"
        
        # Calculate label position
        label_y = top - 10 if top - 10 > 10 else top + 10
        
        # Add black background for text
        (label_w, label_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.8, 1)
        cv2.rectangle(frame, (left, label_y - label_h), 
                     (left + label_w, label_y + 10), (0, 0, 0), cv2.FILLED)
        
        # Add text
        cv2.putText(frame, label, (left, label_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 1)

    def set_confidence_threshold(self, threshold):
        """Update the confidence threshold for face detection"""
        self.min_confidence = threshold
