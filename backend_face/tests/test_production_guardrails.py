from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))


class DirectionTests(unittest.TestCase):
    def test_bidirectional_crossing(self):
        from tracking.direction import update_track_direction
        info = {
            "camera_role": "BIDIRECTIONAL", "direction": "AUTO",
            "line_x1": 0.5, "line_y1": 0.0, "line_x2": 0.5, "line_y2": 1.0,
            "in_side": "POSITIVE",
        }
        track = {}
        frame_shape = (1000, 1000, 3)
        first = update_track_direction(track, (700, 400, 800, 600), frame_shape, info)
        second = update_track_direction(track, (200, 400, 300, 600), frame_shape, info)
        self.assertEqual(first, "AUTO")
        self.assertIn(second, {"IN", "OUT"})

    def test_reference_never_marks_direction(self):
        from tracking.direction import update_track_direction
        self.assertEqual(
            update_track_direction({}, (0, 0, 100, 100), (500, 500, 3), {"camera_role": "REFERENCE_ONLY"}),
            "NONE",
        )


class SourceGuardrailTests(unittest.TestCase):
    def read(self, relative: str) -> str:
        return (ROOT / relative).read_text(encoding="utf-8")

    def test_arcface_requires_explicit_model(self):
        source = self.read("backend_face/recognition/arcface.py")
        lowered = source.lower()
        self.assertIn("FRS_ARCFACE_MODEL_PATH", source)
        self.assertNotIn("import requests", lowered)
        self.assertNotIn("import urllib", lowered)
        self.assertNotIn("urlretrieve(", lowered)
        self.assertNotIn("requests.get(", lowered)
        self.assertNotIn("requests.post(", lowered)

    def test_pgvector_is_tenant_scoped(self):
        source = self.read("backend_face/recognition/vector_store.py")
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", source)
        self.assertIn("WHERE company_id=%s", source)
        self.assertIn("vector_cosine_ops", source)

    def test_object_storage_tenant_check_exists(self):
        source = self.read("backend_face/storage/routes.py")
        self.assertIn("role != \"SuperAdmin\"", source)
        self.assertIn("evidence_tenant", source)

    def test_runtime_biometrics_are_ignored(self):
        source = self.read(".gitignore")
        self.assertIn("backend_face/captured_faces/", source)
        self.assertIn("backend_face/data/", source)

    def test_no_main_merge_workflow(self):
        workflow = self.read(".github/workflows/frs-release-validation.yml")
        self.assertNotIn("HEAD:main", workflow)
        self.assertIn("prod/frs-accuracy-light-ui", workflow)


if __name__ == "__main__":
    unittest.main()
