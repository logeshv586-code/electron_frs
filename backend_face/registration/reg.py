from __future__ import annotations

import io
import logging
import os
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np
import pandas as pd
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

from db.repository import (
    delete_person,
    get_person,
    list_persons,
    load_face_templates,
    replace_face_templates,
    upsert_person,
    write_audit,
)
from fr1 import encode_face_image

logger = logging.getLogger(__name__)

BACKEND_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BACKEND_DIR / "data"
GALLERY_DIR = DATA_DIR / "gallery"
GALLERY_DIR.mkdir(parents=True, exist_ok=True)

FACE_WIDTH = 224
FACE_HEIGHT = 224
MAX_TEMPLATES_PER_PERSON = max(6, int(os.getenv("FRS_MAX_FACE_TEMPLATES", "12")))
DUPLICATE_DISTANCE = float(os.getenv("FRS_DUPLICATE_FACE_DISTANCE", "0.40"))
MIN_ENROLL_FACE_PX = int(os.getenv("FRS_MIN_ENROLL_FACE_PX", "100"))

app = FastAPI(title="FRS Registration")


class RegistrationResponse(BaseModel):
    status: str
    message: str
    person_dir: Optional[str] = None
    error: Optional[str] = None
    age_range: Optional[str] = None
    age_source: Optional[str] = None
    template_count: Optional[int] = None


class StatusUpdate(BaseModel):
    status: str


def _company_id(request: Request) -> str:
    user = request.scope.get("user", {}) or {}
    company = user.get("company_id")
    if user.get("role") == "SuperAdmin":
        company = request.query_params.get("company_id") or company or "default"
    return str(company or "default")


def _person_key(name: str) -> str:
    value = name.strip().lower().replace(" ", "_")
    value = re.sub(r"[^\w\-_.]", "", value)
    return value or uuid.uuid4().hex[:12]


def _decode_image(data: bytes) -> np.ndarray:
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None or image.size == 0:
        raise ValueError("Invalid image file")
    return image


def _face_quality(face: np.ndarray) -> float:
    if face is None or face.size == 0:
        return 0.0
    gray = cv2.cvtColor(face, cv2.COLOR_BGR2GRAY)
    sharp = min(float(cv2.Laplacian(gray, cv2.CV_64F).var()) / 500.0, 1.0)
    mean = float(np.mean(gray))
    exposure = max(0.0, 1.0 - abs(mean - 128.0) / 128.0)
    return float(np.clip(sharp * 0.68 + exposure * 0.32, 0.0, 1.0))


def _detect_standardized_face(image: np.ndarray) -> np.ndarray:
    """Crop one enrollment face with a strict minimum size.

    Enrollment is intentionally stricter than CCTV detection. A poor enrollment image
    degrades every later attendance decision, so operators are asked to provide a clear
    photo instead of manufacturing detail with aggressive upscaling.
    """
    try:
        import face_recognition
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        locations = face_recognition.face_locations(rgb, model="hog")
        if not locations:
            try:
                locations = face_recognition.face_locations(rgb, model="cnn")
            except Exception:
                locations = []
    except Exception as exc:
        raise ValueError(f"Face detector unavailable: {exc}")

    if not locations:
        raise ValueError("No face detected. Use a clear, well-lit, near-frontal enrollment photo.")
    if len(locations) > 1:
        raise ValueError("Enrollment image must contain exactly one person.")

    top, right, bottom, left = locations[0]
    face_w, face_h = right - left, bottom - top
    if min(face_w, face_h) < MIN_ENROLL_FACE_PX:
        raise ValueError(f"Enrollment face is too small ({min(face_w, face_h)} px). Use a closer image of at least {MIN_ENROLL_FACE_PX} px face width/height.")

    h, w = image.shape[:2]
    pad_x, pad_y = int(face_w * 0.28), int(face_h * 0.28)
    left = max(0, left - pad_x); right = min(w, right + pad_x)
    top = max(0, top - pad_y); bottom = min(h, bottom + pad_y)
    crop = image[top:bottom, left:right].copy()
    if crop.size == 0:
        raise ValueError("Could not crop enrollment face")
    return cv2.resize(crop, (FACE_WIDTH, FACE_HEIGHT), interpolation=cv2.INTER_LANCZOS4)


def _rotate(image: np.ndarray, angle: float) -> np.ndarray:
    h, w = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(image, matrix, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT_101)


def _adjust(image: np.ndarray, alpha: float = 1.0, beta: float = 0.0) -> np.ndarray:
    return cv2.convertScaleAbs(image, alpha=alpha, beta=beta)


def _clahe(image: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    eq = cv2.createCLAHE(clipLimit=1.8, tileGridSize=(8, 8)).apply(l)
    return cv2.cvtColor(cv2.merge([eq, a, b]), cv2.COLOR_LAB2BGR)


def _augmentation_candidates(face: np.ndarray) -> List[Tuple[str, np.ndarray]]:
    """Controlled template augmentation, not model training.

    Dlib is a pretrained descriptor. Registration creates a tenant-specific template
    bank from the real face plus mild pose/light transformations. These exact embeddings
    are what the live matcher searches; they are no longer written to an unused folder.
    """
    candidates: List[Tuple[str, np.ndarray]] = [
        ("original", face),
        ("rot_m8", _rotate(face, -8)),
        ("rot_m4", _rotate(face, -4)),
        ("rot_p4", _rotate(face, 4)),
        ("rot_p8", _rotate(face, 8)),
        ("dim", _adjust(face, 0.86, -4)),
        ("bright", _adjust(face, 1.12, 5)),
        ("contrast_low", _adjust(face, 0.92, 8)),
        ("contrast_high", _adjust(face, 1.10, -6)),
        ("clahe", _clahe(face)),
    ]
    return candidates


def _build_templates(real_faces: Sequence[np.ndarray]) -> List[Tuple[str, np.ndarray, np.ndarray, float]]:
    prepared: List[Tuple[str, np.ndarray, np.ndarray, float]] = []
    seen_embeddings: List[np.ndarray] = []
    for real_index, real_face in enumerate(real_faces):
        for aug_name, variant in _augmentation_candidates(real_face):
            embedding = encode_face_image(variant, num_jitters=2 if aug_name == "original" else 1)
            if embedding is None:
                continue
            # Avoid storing dozens of essentially identical synthetic descriptors.
            if seen_embeddings:
                nearest = min(float(np.linalg.norm(embedding - other)) for other in seen_embeddings)
                if nearest < 0.008 and aug_name != "original":
                    continue
            seen_embeddings.append(embedding)
            quality = _face_quality(variant)
            prepared.append((f"real{real_index:02d}_{aug_name}", variant, embedding, quality))
            if len(prepared) >= MAX_TEMPLATES_PER_PERSON:
                return prepared
    return prepared


def _nearest_registered(company_id: str, embedding: np.ndarray) -> Tuple[Optional[str], Optional[float]]:
    matrix, names, _ = load_face_templates(company_id)
    if matrix.shape[0] == 0:
        return None, None
    if matrix.shape[1] != embedding.shape[0]:
        return None, None
    distances = np.linalg.norm(matrix - embedding.reshape(1, -1), axis=1)
    index = int(np.argmin(distances))
    return names[index], float(distances[index])


def _write_person_templates(company_id: str, person_key: str, templates) -> Tuple[Path, int]:
    person_dir = GALLERY_DIR / company_id / person_key
    if person_dir.exists():
        shutil.rmtree(person_dir, ignore_errors=True)
    person_dir.mkdir(parents=True, exist_ok=True)

    db_templates = []
    for index, (template_key, image, embedding, quality) in enumerate(templates):
        filename = f"template_{index:02d}_{template_key}.jpg"
        path = person_dir / filename
        if not cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 96]):
            continue
        db_templates.append((template_key, embedding, str(path), quality))
    replace_face_templates(company_id, person_key, db_templates)
    try:
        from recognition.arcface import get_arcface_engine
        from recognition.vector_store import replace_person_vectors
        arcface = get_arcface_engine()
        if arcface.available:
            arc_templates = []
            for index, (template_key, image, _dlib_embedding, quality) in enumerate(templates):
                vector = arcface.embed_crop(image)
                source = person_dir / f"template_{index:02d}_{template_key}.jpg"
                if vector is not None and source.exists():
                    arc_templates.append((template_key, vector, str(source), quality))
            replace_person_vectors(company_id, person_key, arc_templates, arcface.model_version)
        try:
            from face_pipeline import clear_company_embeddings_cache
            clear_company_embeddings_cache(company_id)
        except Exception:
            pass
        try:
            from cache.redis_cache import get_event_cache
            get_event_cache().invalidate_face_bank(company_id)
        except Exception:
            pass
    except Exception as exc:
        logger.warning("ArcFace enrollment vectors were not updated: %s", exc)
    return person_dir, len(db_templates)


def _age_range(age_value: Optional[str]) -> str:
    if not age_value:
        return "N/A"
    try:
        age = int(float(str(age_value)))
    except Exception:
        return "N/A"
    lower = max(0, (age // 5) * 5)
    return f"{lower}-{lower + 5}"


def _register_person(
    *, company_id: str, creator: str, name: str, images: Sequence[np.ndarray], details: Dict[str, str]
) -> RegistrationResponse:
    if not images:
        raise ValueError("At least one enrollment image is required")
    faces = [_detect_standardized_face(image) for image in images]
    base_embedding = encode_face_image(faces[0], num_jitters=3)
    if base_embedding is None:
        raise ValueError("Could not create a face embedding from the enrollment image")

    nearest_name, nearest_distance = _nearest_registered(company_id, base_embedding)
    if nearest_name and nearest_distance is not None and nearest_distance <= DUPLICATE_DISTANCE:
        existing = get_person(company_id, nearest_name)
        existing_label = (existing or {}).get("name") or nearest_name
        raise ValueError(f"This face is already or very likely registered as '{existing_label}' (distance {nearest_distance:.3f}).")

    person_key = _person_key(name)
    if get_person(company_id, person_key):
        raise ValueError("A person with this name/key already exists in this company")

    templates = _build_templates(faces)
    if len(templates) < 3:
        raise ValueError("Enrollment quality is insufficient to build a reliable template bank. Use a clearer photo.")

    # Person row first so face_templates FK can reference it.
    person_dir = GALLERY_DIR / company_id / person_key
    person_data = {
        "name": name.strip(),
        "emp_id": details.get("emp_id") or "",
        "email": details.get("email") or "",
        "phone": details.get("phone") or "",
        "role": details.get("role") or "User",
        "department": details.get("department") or "",
        "designation": details.get("designation") or "",
        "joining_date": details.get("joining_date") or "",
        "status": details.get("status") or "Active",
        "category": details.get("category") or "Employee",
        "age": details.get("age") or "",
        "gender": details.get("gender") or "",
        "created_by": creator,
        "registration_date": datetime.now(timezone.utc).isoformat(),
        "gallery_path": str(person_dir.relative_to(BACKEND_DIR)).replace("\\", "/"),
        "photo_path": str((person_dir / f"template_00_{templates[0][0]}.jpg").relative_to(BACKEND_DIR)).replace("\\", "/"),
        "metadata": {"template_backend": "dlib-128", "template_count": len(templates)},
    }
    upsert_person(company_id, person_key, person_data)
    try:
        person_dir, template_count = _write_person_templates(company_id, person_key, templates)
    except Exception:
        delete_person(company_id, person_key)
        raise

    # Refresh the live tenant cache immediately; no restart/retrain step required.
    try:
        from face_pipeline import clear_company_embeddings_cache
        clear_company_embeddings_cache(company_id)
    except Exception:
        pass

    write_audit(
        "PERSON_REGISTERED",
        username=creator,
        company_id=company_id,
        entity_type="person",
        entity_id=person_key,
        details={"template_count": template_count},
    )
    return RegistrationResponse(
        status="success",
        message=f"Successfully registered {name} with {template_count} live recognition templates",
        person_dir=str(person_dir),
        age_range=_age_range(details.get("age")),
        age_source="manual" if details.get("age") else "not-collected",
        template_count=template_count,
    )


@app.post("/register/single", response_model=RegistrationResponse)
async def register_single(
    request: Request,
    image: UploadFile = File(...),
    name: str = Form(...),
    emp_id: str = Form(""),
    email: str = Form(""),
    phone: str = Form(""),
    role: str = Form("User"),
    department: str = Form(""),
    designation: str = Form(""),
    joining_date: str = Form(""),
    status: str = Form("Active"),
    age: str = Form(""),
    gender: str = Form(""),
    category: str = Form("Employee"),
):
    if not image.filename or Path(image.filename).suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
        raise HTTPException(status_code=400, detail="Upload a JPEG, PNG or WebP face image")
    try:
        raw = await image.read()
        source = _decode_image(raw)
        user = request.scope.get("user", {}) or {}
        return _register_person(
            company_id=_company_id(request),
            creator=user.get("username") or "system",
            name=name,
            images=[source],
            details={
                "emp_id": emp_id, "email": email, "phone": phone, "role": role,
                "department": department, "designation": designation, "joining_date": joining_date,
                "status": status, "age": age, "gender": gender, "category": category,
            },
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Single registration failed")
        raise HTTPException(status_code=500, detail=f"Registration failed: {exc}")


def _normalize_column(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).lower())


def _row_value(row, aliases: Sequence[str], default=""):
    normalized = {_normalize_column(col): col for col in row.index}
    for alias in aliases:
        column = normalized.get(_normalize_column(alias))
        if column is not None:
            value = row[column]
            if pd.notna(value):
                return str(value).strip()
    return default


def _match_upload_to_person(filename: str, names: Sequence[str]) -> Optional[str]:
    normalized_path = filename.replace("\\", "/").strip("/")
    parts = normalized_path.split("/")
    if len(parts) > 1:
        folder = parts[-2].strip()
        for name in names:
            if folder.lower() == name.lower():
                return name
    stem = Path(parts[-1]).stem.lower()
    # Prefer exact name, then name_1/name-2 style prefixes.
    for name in sorted(names, key=len, reverse=True):
        key = name.lower()
        if stem == key or stem.startswith(key + "_") or stem.startswith(key + "-"):
            return name
    return None


@app.post("/register/bulk", response_model=List[RegistrationResponse])
async def register_bulk(
    request: Request,
    excel_file: UploadFile = File(...),
    image_files: List[UploadFile] = File(...),
):
    try:
        excel_bytes = await excel_file.read()
        df = pd.read_excel(io.BytesIO(excel_bytes))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not read Excel file: {exc}")

    names = []
    row_details: Dict[str, Dict[str, str]] = {}
    for _, row in df.iterrows():
        name = _row_value(row, ["name", "Employee Full Name", "Full Name"])
        if not name:
            continue
        names.append(name)
        row_details[name] = {
            "emp_id": _row_value(row, ["emp_id", "Employee ID", "Employee Details"]),
            "email": _row_value(row, ["email", "Email"]),
            "phone": _row_value(row, ["phone", "Phone Number"]),
            "role": _row_value(row, ["role", "Roles"], "User"),
            "department": _row_value(row, ["department", "Department"]),
            "designation": _row_value(row, ["designation", "Designation"]),
            "joining_date": _row_value(row, ["joining_date", "Joining Date"]),
            "status": _row_value(row, ["status", "Status"], "Active"),
            "age": _row_value(row, ["age", "Age"]),
            "gender": _row_value(row, ["gender", "Gender"]),
            "category": _row_value(row, ["category", "Category"], "Employee"),
        }
    if not names:
        raise HTTPException(status_code=400, detail="Excel must contain a Name or Employee Full Name column with data")

    grouped: Dict[str, List[np.ndarray]] = {name: [] for name in names}
    for upload in image_files:
        if not upload.filename:
            continue
        person_name = _match_upload_to_person(upload.filename, names)
        if not person_name:
            continue
        try:
            grouped[person_name].append(_decode_image(await upload.read()))
        except Exception:
            continue

    company_id = _company_id(request)
    creator = (request.scope.get("user", {}) or {}).get("username") or "system"
    responses: List[RegistrationResponse] = []
    for name in names:
        if not grouped[name]:
            responses.append(RegistrationResponse(status="error", message=f"No matching image found for {name}", error="image missing"))
            continue
        try:
            # Real multi-view bulk folders are preferred. At most the first five real
            # images are used; controlled augmentations then fill the compact template bank.
            response = _register_person(
                company_id=company_id,
                creator=creator,
                name=name,
                images=grouped[name][:5],
                details=row_details[name],
            )
            responses.append(response)
        except Exception as exc:
            responses.append(RegistrationResponse(status="error", message=f"Failed to register {name}: {exc}", error=str(exc)))
    return responses


def _person_to_gallery(person: Dict) -> Dict:
    person_key = person["person_key"]
    company_id = person["company_id"]
    person_dir = GALLERY_DIR / company_id / person_key
    images = sorted([p.name for p in person_dir.glob("*.jpg")]) if person_dir.exists() else []
    image_filename = images[0] if images else None
    metadata = {}
    try:
        import json
        metadata = json.loads(person.get("metadata_json") or "{}")
    except Exception:
        pass
    return {
        "name": person.get("name"),
        "emp_id": person.get("emp_id") or "",
        "email": person.get("email") or "",
        "phone": person.get("phone") or "",
        "role": person.get("role") or "User",
        "department": person.get("department") or "",
        "designation": person.get("designation") or "",
        "joining_date": person.get("joining_date") or "",
        "status": person.get("status") or "Active",
        "age": person.get("age") or "N/A",
        "age_range": _age_range(person.get("age")),
        "gender": person.get("gender") or "N/A",
        "category": person.get("category") or "Employee",
        "registration_date": person.get("registration_date"),
        "company_id": company_id,
        "gallery_path": person.get("gallery_path"),
        "photo_path": person.get("photo_path"),
        "image_filename": image_filename,
        "image_url": f"/api/gallery/image/{company_id}/{person_key}/{image_filename}" if image_filename else None,
        "template_count": int(metadata.get("template_count") or len(images)),
    }


@app.get("/registered-faces", response_model=Dict)
@app.get("/gallery", response_model=Dict)
async def get_gallery(request: Request, name: Optional[str] = None, category: Optional[str] = None):
    company_id = _company_id(request)
    result = {}
    for person in list_persons(company_id):
        if name and name.lower() not in str(person.get("name") or "").lower():
            continue
        if category and category.lower() != "all" and category.lower() != "all categories":
            if category.lower() != str(person.get("category") or "").lower():
                continue
        result[person["person_key"]] = _person_to_gallery(person)
    return result


@app.get("/metadata/statistics")
async def metadata_statistics(request: Request):
    persons = list_persons(_company_id(request))
    categories: Dict[str, int] = {}
    genders: Dict[str, int] = {}
    today = datetime.now(timezone.utc).date().isoformat()
    registered_today = 0
    for person in persons:
        cat = str(person.get("category") or "unknown").lower()
        categories[cat] = categories.get(cat, 0) + 1
        gender = str(person.get("gender") or "Unspecified")
        genders[gender] = genders.get(gender, 0) + 1
        if str(person.get("registration_date") or "").startswith(today):
            registered_today += 1
    return {
        "total_registered": len(persons),
        "categories": categories,
        "genders": genders,
        "registered_today": registered_today,
    }


@app.put("/metadata/person/{person_id}/status")
async def update_person_status(person_id: str, body: StatusUpdate, request: Request):
    company_id = _company_id(request)
    person = get_person(company_id, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    status = body.status.strip().title()
    if status not in {"Active", "Inactive"}:
        raise HTTPException(status_code=400, detail="Status must be Active or Inactive")
    merged = dict(person)
    merged["status"] = status
    try:
        import json
        merged["metadata"] = json.loads(person.get("metadata_json") or "{}")
    except Exception:
        merged["metadata"] = {}
    upsert_person(company_id, person_id, merged)
    try:
        from face_pipeline import clear_company_embeddings_cache
        clear_company_embeddings_cache(company_id)
    except Exception:
        pass
    write_audit(
        "PERSON_STATUS_CHANGED",
        username=(request.scope.get("user", {}) or {}).get("username"),
        company_id=company_id,
        entity_type="person",
        entity_id=person_id,
        details={"status": status},
    )
    return {"success": True, "status": status}


@app.delete("/metadata/person/{person_id}")
async def delete_registered_person(person_id: str, request: Request):
    company_id = _company_id(request)
    person = get_person(company_id, person_id)
    if not person:
        raise HTTPException(status_code=404, detail="Person not found")
    if not delete_person(company_id, person_id):
        raise HTTPException(status_code=404, detail="Person not found")

    shutil.rmtree(GALLERY_DIR / company_id / person_id, ignore_errors=True)
    known_root = BACKEND_DIR / "captured_faces" / "known" / company_id
    if known_root.exists():
        for camera_dir in known_root.iterdir():
            if camera_dir.is_dir():
                shutil.rmtree(camera_dir / person_id, ignore_errors=True)
    try:
        from face_pipeline import clear_company_embeddings_cache
        clear_company_embeddings_cache(company_id)
    except Exception:
        pass
    write_audit(
        "PERSON_DELETED",
        username=(request.scope.get("user", {}) or {}).get("username"),
        company_id=company_id,
        entity_type="person",
        entity_id=person_id,
    )
    return {"success": True, "message": "Person and active biometric templates deleted"}
