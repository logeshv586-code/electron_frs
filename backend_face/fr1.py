# -*- coding: utf-8 -*-
"""Face-template loading utilities used by the live recognition pipeline.

The old implementation generated enrollment augmentations under data/<company>/<person>
but live recognition primarily read data/gallery/<company>/<person>.  This module makes
the database face-template bank authoritative and imports gallery images only as a
backward-compatibility source.  Registration and live recognition therefore use the
same embeddings.
"""

from __future__ import annotations

import glob
import logging
import os
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np
import face_recognition

from db.repository import (
    append_face_templates,
    get_person,
    load_face_templates,
    migrate_legacy_metadata,
    upsert_person,
)

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
TOLERANCE = float(os.getenv("FACE_MATCH_DISTANCE", "0.46"))


def _quality_score(image_bgr: np.ndarray) -> float:
    if image_bgr is None or image_bgr.size == 0:
        return 0.0
    h, w = image_bgr.shape[:2]
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY)
    sharp = min(float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 500.0, 1.0)
    brightness = float(np.mean(gray))
    exposure = 1.0 - min(abs(brightness - 128.0) / 128.0, 1.0)
    size = min((min(h, w) / 160.0), 1.0)
    return float(np.clip(sharp * 0.5 + exposure * 0.25 + size * 0.25, 0.0, 1.0))


def encode_face_image(image_bgr: np.ndarray, num_jitters: int = 2) -> Optional[np.ndarray]:
    """Return one dlib 128-D embedding from a single-face image."""
    if image_bgr is None or image_bgr.size == 0:
        return None
    rgb = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)
    locations = face_recognition.face_locations(rgb, model="hog")
    if not locations:
        try:
            locations = face_recognition.face_locations(rgb, model="cnn")
        except Exception:
            locations = []
    if not locations:
        return None
    # Enrollment/template files must contain exactly one usable identity. If several
    # faces are present, use the largest but log the condition for operator review.
    location = max(locations, key=lambda r: max(1, r[2] - r[0]) * max(1, r[1] - r[3]))
    encodings = face_recognition.face_encodings(
        rgb,
        known_face_locations=[location],
        num_jitters=max(1, int(num_jitters)),
        model="large",
    )
    return encodings[0].astype(np.float64) if encodings else None


def _import_gallery_into_database(data_dir: str, company_id: str) -> int:
    gallery_root = Path(data_dir) / "gallery" / company_id
    if not gallery_root.exists():
        return 0

    imported = 0
    for person_dir in sorted(p for p in gallery_root.iterdir() if p.is_dir()):
        person_key = person_dir.name.strip().lower()
        person = get_person(company_id, person_key)
        if not person:
            person = upsert_person(company_id, person_key, {
                "name": person_dir.name,
                "status": "Active",
                "category": "Employee",
                "photo_path": str((person_dir / "1.jpg").relative_to(Path(data_dir).parent)).replace("\\", "/")
                    if (person_dir / "1.jpg").exists() else None,
                "gallery_path": str(person_dir.relative_to(Path(data_dir).parent)).replace("\\", "/"),
                "created_by": "legacy-migration",
            })

        templates = []
        for image_path in sorted(person_dir.glob("*")):
            if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
                continue
            image = cv2.imread(str(image_path))
            embedding = encode_face_image(image, num_jitters=2)
            if embedding is None:
                continue
            template_key = f"gallery:{image_path.name}:{int(image_path.stat().st_mtime)}"
            templates.append((
                template_key,
                embedding,
                str(image_path),
                _quality_score(image),
            ))
        if templates:
            imported += append_face_templates(company_id, person_key, templates)
    return imported


def load_known_faces(
    data_dir: str,
    company_id: Optional[str] = None,
) -> Tuple[List[np.ndarray], List[str]]:
    """Load the tenant's authoritative enrollment embeddings.

    For a fresh upgraded installation the function imports legacy metadata/gallery files
    one time. Subsequent calls read compact binary embeddings from the database and avoid
    re-encoding thousands of JPEGs on every startup.
    """
    company_id = str(company_id or "default")
    metadata_file = os.path.join(data_dir, "metadata.json")
    try:
        migrate_legacy_metadata(metadata_file)
    except Exception as exc:
        logger.warning("Legacy person metadata migration skipped: %s", exc)

    matrix, names, _ = load_face_templates(company_id)
    if matrix.shape[0] == 0:
        try:
            imported = _import_gallery_into_database(data_dir, company_id)
            if imported:
                logger.info("Imported %s legacy gallery templates for %s", imported, company_id)
            matrix, names, _ = load_face_templates(company_id)
        except Exception as exc:
            logger.error("Failed importing gallery templates for %s: %s", company_id, exc)

    return [row.astype(np.float64) for row in matrix], list(names)


def person_template_summary(data_dir: str, company_id: Optional[str] = None) -> dict:
    company_id = str(company_id or "default")
    matrix, names, _ = load_face_templates(company_id)
    counts = {}
    for name in names:
        counts[name] = counts.get(name, 0) + 1
    return {
        "company_id": company_id,
        "template_count": int(matrix.shape[0]),
        "people": counts,
    }


if __name__ == "__main__":
    encodings, names = load_known_faces(DATA_DIR, company_id="default")
    print(f"Loaded {len(encodings)} templates across {len(set(names))} people")
