from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

import cv2

from recognition.arcface import get_arcface_engine
from recognition.vector_store import replace_person_vectors

logger = logging.getLogger(__name__)


def backfill_arcface_gallery(data_dir: str, company_id: str) -> int:
    engine = get_arcface_engine()
    if not engine.available:
        return 0
    root = Path(data_dir) / "gallery" / str(company_id)
    if not root.exists():
        return 0
    people = 0
    for person_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        templates: List[Tuple[str, object, str, float]] = []
        for image_path in sorted(person_dir.iterdir()):
            if image_path.suffix.lower() not in {".jpg", ".jpeg", ".png", ".bmp", ".webp"}:
                continue
            image = cv2.imread(str(image_path))
            if image is None:
                continue
            vector = engine.embed_crop(image)
            if vector is None:
                continue
            templates.append((f"gallery:{image_path.name}", vector, str(image_path), 1.0))
        if templates:
            replace_person_vectors(company_id, person_dir.name.strip().lower(), templates, engine.model_version)
            people += 1
    if people:
        logger.info("Backfilled ArcFace vectors for %s people in tenant %s", people, company_id)
    return people
