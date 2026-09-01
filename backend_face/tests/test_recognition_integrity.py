from __future__ import annotations

import sys
import unittest
from collections import deque
from pathlib import Path

import numpy as np

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class DetectionIntegrityTests(unittest.TestCase):
    def test_overlapping_boxes_collapse_to_one(self):
        from recognition.detection_guard import dedupe_face_detections

        items = [
            {"bbox": (100, 100, 220, 250), "det_conf": 0.92},
            {"bbox": (118, 110, 232, 252), "det_conf": 0.81},
        ]
        kept = dedupe_face_detections(items)
        self.assertEqual(len(kept), 1)
        self.assertAlmostEqual(kept[0]["det_conf"], 0.92)

    def test_two_separate_faces_are_kept(self):
        from recognition.detection_guard import dedupe_face_detections

        items = [
            {"bbox": (50, 50, 150, 180), "det_conf": 0.91},
            {"bbox": (220, 50, 320, 180), "det_conf": 0.90},
        ]
        self.assertEqual(len(dedupe_face_detections(items)), 2)


class IdentityIntegrityTests(unittest.TestCase):
    def test_track_does_not_switch_employee(self):
        from recognition.identity_guard import update_track_identity

        logesh = np.zeros(128, dtype=np.float32)
        ram = np.ones(128, dtype=np.float32) * 0.5
        track = {"history": deque(maxlen=6), "confirmed_name": None}

        for _ in range(4):
            update_track_identity(
                track,
                {"name": "logesh", "embedding": logesh},
                quality=0.8,
                min_quality=0.2,
                confirm_frames=4,
                window=6,
                min_side=140,
                recognition_min=64,
            )
        self.assertEqual(track.get("confirmed_name"), "logesh")

        for _ in range(2):
            update_track_identity(
                track,
                {"name": "ram", "embedding": ram},
                quality=0.8,
                min_quality=0.2,
                confirm_frames=4,
                window=6,
                min_side=140,
                recognition_min=64,
            )
        self.assertIsNone(track.get("confirmed_name"))
        self.assertTrue(track.get("identity_blocked"))

        for _ in range(8):
            update_track_identity(
                track,
                {"name": "ram", "embedding": ram},
                quality=0.8,
                min_quality=0.2,
                confirm_frames=4,
                window=6,
                min_side=140,
                recognition_min=64,
            )
        self.assertIsNone(track.get("confirmed_name"))

    def test_dlib_requires_runner_up_separation(self):
        from recognition.identity_guard import conservative_dlib_match

        query = np.zeros(128, dtype=np.float64)
        logesh_templates = np.vstack([
            np.ones(128) * 0.020,
            np.ones(128) * 0.021,
            np.ones(128) * 0.022,
        ])
        ram_templates = np.vstack([
            np.ones(128) * 0.021,
            np.ones(128) * 0.022,
            np.ones(128) * 0.023,
        ])
        matrix = np.vstack([logesh_templates, ram_templates])
        indices = {"logesh": np.array([0, 1, 2]), "ram": np.array([3, 4, 5])}
        result = conservative_dlib_match([query], matrix, indices, threshold=0.42, required_margin=0.07)
        self.assertIsNone(result.get("name"))


class EvidenceIntegrityTests(unittest.TestCase):
    def test_large_sharp_crop_beats_small_blur(self):
        import cv2
        from recognition.evidence_quality import evidence_score

        sharp = np.zeros((180, 180, 3), dtype=np.uint8)
        sharp[::4, :, :] = 255
        sharp[:, ::4, :] = 255
        blurred = cv2.GaussianBlur(sharp, (31, 31), 10)

        large = evidence_score(sharp, (0, 0, 150, 150))
        small = evidence_score(blurred, (0, 0, 55, 55))
        self.assertGreater(large, small)


if __name__ == "__main__":
    unittest.main()
