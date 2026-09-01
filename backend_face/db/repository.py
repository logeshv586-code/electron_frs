from __future__ import annotations

import hashlib
import json
import math
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import numpy as np

from .core import db_connection, fetch_all, fetch_one, init_database, is_postgres

init_database()

TIMEZONE_NAME = os.getenv("FRS_TIMEZONE", "Asia/Kolkata")
try:
    LOCAL_TZ = ZoneInfo(TIMEZONE_NAME)
except Exception:
    LOCAL_TZ = timezone.utc


def _sql(sql: str) -> str:
    return sql.replace("?", "%s") if is_postgres() else sql


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: Optional[datetime] = None) -> str:
    value = value or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(timezone.utc).isoformat()


def parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def local_date_for(value: Optional[datetime] = None) -> str:
    value = value or utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=LOCAL_TZ)
    return value.astimezone(LOCAL_TZ).date().isoformat()


def vector_to_blob(vector: Sequence[float]) -> bytes:
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    return arr.tobytes()


def blob_to_vector(blob: Any) -> np.ndarray:
    if blob is None:
        return np.empty((0,), dtype=np.float32)
    if isinstance(blob, memoryview):
        blob = blob.tobytes()
    return np.frombuffer(bytes(blob), dtype=np.float32).copy()


def _dict_row(row: Any) -> Dict[str, Any]:
    return dict(row) if row is not None else {}


def _execute(conn, sql: str, params: Sequence[Any] = ()):
    cur = conn.cursor()
    cur.execute(_sql(sql), tuple(params))
    return cur


def _executemany(conn, sql: str, rows: Iterable[Sequence[Any]]):
    cur = conn.cursor()
    cur.executemany(_sql(sql), list(rows))
    return cur


# ---------------------------------------------------------------------------
# Generic KV persistence (auth/settings/licensing compatibility)
# ---------------------------------------------------------------------------

def get_kv_namespace(namespace: str) -> Dict[str, Any]:
    rows = fetch_all("SELECT key, value_json FROM app_kv WHERE namespace=?", (namespace,))
    result: Dict[str, Any] = {}
    for row in rows:
        try:
            result[row["key"]] = json.loads(row["value_json"])
        except Exception:
            result[row["key"]] = row["value_json"]
    return result


def set_kv_namespace(namespace: str, values: Dict[str, Any]) -> None:
    now = iso_utc()
    with db_connection() as conn:
        _execute(conn, "DELETE FROM app_kv WHERE namespace=?", (namespace,))
        if values:
            _executemany(
                conn,
                "INSERT INTO app_kv(namespace,key,value_json,updated_at) VALUES(?,?,?,?)",
                [
                    (namespace, str(key), json.dumps(value, ensure_ascii=False, default=str), now)
                    for key, value in values.items()
                ],
            )


def get_kv(namespace: str, key: str, default: Any = None) -> Any:
    row = fetch_one("SELECT value_json FROM app_kv WHERE namespace=? AND key=?", (namespace, key))
    if not row:
        return default
    try:
        return json.loads(row["value_json"])
    except Exception:
        return row["value_json"]


def set_kv(namespace: str, key: str, value: Any) -> None:
    now = iso_utc()
    payload = json.dumps(value, ensure_ascii=False, default=str)
    with db_connection() as conn:
        if is_postgres():
            _execute(
                conn,
                """
                INSERT INTO app_kv(namespace,key,value_json,updated_at) VALUES(?,?,?,?)
                ON CONFLICT(namespace,key) DO UPDATE SET value_json=EXCLUDED.value_json, updated_at=EXCLUDED.updated_at
                """,
                (namespace, key, payload, now),
            )
        else:
            _execute(
                conn,
                "INSERT OR REPLACE INTO app_kv(namespace,key,value_json,updated_at) VALUES(?,?,?,?)",
                (namespace, key, payload, now),
            )


def delete_kv(namespace: str, key: str) -> None:
    with db_connection() as conn:
        _execute(conn, "DELETE FROM app_kv WHERE namespace=? AND key=?", (namespace, key))


# ---------------------------------------------------------------------------
# Persons and face templates
# ---------------------------------------------------------------------------

def upsert_person(company_id: str, person_key: str, data: Dict[str, Any]) -> Dict[str, Any]:
    company_id = str(company_id or "default")
    person_key = str(person_key).strip().lower()
    existing = fetch_one(
        "SELECT * FROM persons WHERE company_id=? AND person_key=?",
        (company_id, person_key),
    )
    person_id = existing["id"] if existing else str(uuid.uuid4())
    registration_date = data.get("registration_date") or (existing or {}).get("registration_date") or iso_utc()
    fields = {
        "id": person_id,
        "company_id": company_id,
        "person_key": person_key,
        "name": data.get("name") or person_key,
        "emp_id": data.get("emp_id") or None,
        "email": data.get("email") or None,
        "phone": data.get("phone") or None,
        "role": data.get("role") or "User",
        "department": data.get("department") or None,
        "designation": data.get("designation") or None,
        "joining_date": data.get("joining_date") or None,
        "status": data.get("status") or "Active",
        "category": data.get("category") or "Employee",
        "age": None if data.get("age") is None else str(data.get("age")),
        "gender": data.get("gender") or None,
        "created_by": data.get("created_by") or "system",
        "registration_date": registration_date,
        "photo_path": data.get("photo_path") or None,
        "gallery_path": data.get("gallery_path") or None,
        "metadata_json": json.dumps(data.get("metadata") or {}, ensure_ascii=False, default=str),
    }
    with db_connection() as conn:
        if existing:
            _execute(
                conn,
                """
                UPDATE persons SET name=?,emp_id=?,email=?,phone=?,role=?,department=?,designation=?,joining_date=?,
                    status=?,category=?,age=?,gender=?,created_by=?,photo_path=?,gallery_path=?,metadata_json=?
                WHERE id=?
                """,
                (
                    fields["name"], fields["emp_id"], fields["email"], fields["phone"], fields["role"],
                    fields["department"], fields["designation"], fields["joining_date"], fields["status"],
                    fields["category"], fields["age"], fields["gender"], fields["created_by"], fields["photo_path"],
                    fields["gallery_path"], fields["metadata_json"], person_id,
                ),
            )
        else:
            _execute(
                conn,
                """
                INSERT INTO persons(id,company_id,person_key,name,emp_id,email,phone,role,department,designation,
                    joining_date,status,category,age,gender,created_by,registration_date,photo_path,gallery_path,metadata_json)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                tuple(fields[k] for k in (
                    "id", "company_id", "person_key", "name", "emp_id", "email", "phone", "role", "department",
                    "designation", "joining_date", "status", "category", "age", "gender", "created_by",
                    "registration_date", "photo_path", "gallery_path", "metadata_json",
                )),
            )
    return get_person(company_id, person_key) or fields


def get_person(company_id: str, person_key: str) -> Optional[Dict[str, Any]]:
    return fetch_one(
        "SELECT * FROM persons WHERE company_id=? AND person_key=?",
        (str(company_id or "default"), str(person_key).strip().lower()),
    )


def get_person_by_id(person_id: str) -> Optional[Dict[str, Any]]:
    return fetch_one("SELECT * FROM persons WHERE id=?", (person_id,))


def list_persons(company_id: Optional[str] = None, active_only: bool = False) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if company_id is not None:
        clauses.append("company_id=?")
        params.append(str(company_id))
    if active_only:
        clauses.append("LOWER(status)='active'")
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    return fetch_all("SELECT * FROM persons" + where + " ORDER BY name COLLATE NOCASE", params)


def delete_person(company_id: str, person_key: str) -> bool:
    person = get_person(company_id, person_key)
    if not person:
        return False
    with db_connection() as conn:
        _execute(conn, "DELETE FROM persons WHERE id=?", (person["id"],))
    return True


def replace_face_templates(
    company_id: str,
    person_key: str,
    templates: Sequence[Tuple[str, Sequence[float], Optional[str], Optional[float]]],
) -> int:
    person = get_person(company_id, person_key)
    if not person:
        raise ValueError(f"Person {company_id}/{person_key} does not exist")
    now = iso_utc()
    with db_connection() as conn:
        _execute(conn, "DELETE FROM face_templates WHERE person_id=?", (person["id"],))
        rows = []
        for template_key, embedding, source_path, quality in templates:
            rows.append((
                str(uuid.uuid4()), str(company_id), person["id"], str(template_key), vector_to_blob(embedding),
                source_path, float(quality) if quality is not None else None, now,
            ))
        if rows:
            _executemany(
                conn,
                """
                INSERT INTO face_templates(id,company_id,person_id,template_key,embedding,source_path,quality,created_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                rows,
            )
    return len(templates)


def append_face_templates(
    company_id: str,
    person_key: str,
    templates: Sequence[Tuple[str, Sequence[float], Optional[str], Optional[float]]],
) -> int:
    person = get_person(company_id, person_key)
    if not person:
        raise ValueError(f"Person {company_id}/{person_key} does not exist")
    now = iso_utc()
    inserted = 0
    with db_connection() as conn:
        for template_key, embedding, source_path, quality in templates:
            try:
                if is_postgres():
                    cur = _execute(
                        conn,
                        """
                        INSERT INTO face_templates(id,company_id,person_id,template_key,embedding,source_path,quality,created_at)
                        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(person_id,template_key) DO NOTHING
                        """,
                        (str(uuid.uuid4()), company_id, person["id"], template_key, vector_to_blob(embedding), source_path, quality, now),
                    )
                else:
                    cur = _execute(
                        conn,
                        """
                        INSERT OR IGNORE INTO face_templates(id,company_id,person_id,template_key,embedding,source_path,quality,created_at)
                        VALUES(?,?,?,?,?,?,?,?)
                        """,
                        (str(uuid.uuid4()), company_id, person["id"], template_key, vector_to_blob(embedding), source_path, quality, now),
                    )
                inserted += max(int(cur.rowcount or 0), 0)
            except Exception:
                continue
    return inserted


def load_face_templates(company_id: str) -> Tuple[np.ndarray, List[str], List[Dict[str, Any]]]:
    rows = fetch_all(
        """
        SELECT ft.embedding, ft.template_key, ft.quality, ft.source_path,
               p.id AS person_id, p.person_key, p.name, p.status
        FROM face_templates ft
        JOIN persons p ON p.id=ft.person_id
        WHERE ft.company_id=? AND LOWER(COALESCE(p.status,'active'))='active'
        ORDER BY p.person_key, ft.template_key
        """,
        (str(company_id or "default"),),
    )
    vectors: List[np.ndarray] = []
    names: List[str] = []
    meta: List[Dict[str, Any]] = []
    expected_dim: Optional[int] = None
    for row in rows:
        vec = blob_to_vector(row.get("embedding"))
        if vec.size == 0:
            continue
        if expected_dim is None:
            expected_dim = int(vec.size)
        if vec.size != expected_dim:
            continue
        vectors.append(vec.astype(np.float64))
        names.append(str(row["person_key"]))
        meta.append(row)
    if not vectors:
        return np.empty((0, 128), dtype=np.float64), [], []
    return np.vstack(vectors), names, meta


# ---------------------------------------------------------------------------
# Cameras and collections
# ---------------------------------------------------------------------------

def list_cameras(company_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if company_id is None:
        return fetch_all("SELECT * FROM cameras ORDER BY id")
    return fetch_all("SELECT * FROM cameras WHERE company_id=? ORDER BY id", (str(company_id),))


def get_camera(camera_id: int) -> Optional[Dict[str, Any]]:
    return fetch_one("SELECT * FROM cameras WHERE id=?", (int(camera_id),))


def get_camera_context(camera_name: Optional[str], company_id: Optional[str], camera_id: Optional[int] = None) -> Dict[str, Any]:
    row = None
    if camera_id is not None:
        row = fetch_one("SELECT * FROM cameras WHERE id=?", (int(camera_id),))
    if not row and camera_name:
        if company_id:
            row = fetch_one(
                "SELECT * FROM cameras WHERE company_id=? AND LOWER(name)=LOWER(?) ORDER BY id LIMIT 1",
                (str(company_id), str(camera_name)),
            )
        else:
            row = fetch_one("SELECT * FROM cameras WHERE LOWER(name)=LOWER(?) ORDER BY id LIMIT 1", (str(camera_name),))
    return row or {
        "id": camera_id,
        "company_id": company_id or "default",
        "name": camera_name or "default",
        "location": camera_name or "default",
        "camera_role": "BIDIRECTIONAL",
        "direction": "AUTO",
        "site_id": None,
        "zone_id": None,
        "line_x1": None,
        "line_y1": None,
        "line_x2": None,
        "line_y2": None,
        "in_side": "POSITIVE",
    }


def next_camera_id() -> int:
    row = fetch_one("SELECT MAX(id) AS max_id FROM cameras") or {}
    return int(row.get("max_id") or 0) + 1


def save_camera(data: Dict[str, Any]) -> Dict[str, Any]:
    camera_id = int(data.get("id") or next_camera_id())
    existing = get_camera(camera_id)
    fields = {
        "id": camera_id,
        "company_id": data.get("company_id"),
        "name": data.get("name") or f"Camera {camera_id}",
        "rtsp_url": data.get("rtsp_url") or data.get("streamUrl") or "0",
        "collection_id": data.get("collection_id"),
        "collection_name": data.get("collection_name"),
        "ip_address": data.get("ip_address"),
        "location": data.get("location"),
        "site_id": data.get("site_id"),
        "zone_id": data.get("zone_id"),
        "camera_role": (data.get("camera_role") or "BIDIRECTIONAL").upper(),
        "direction": (data.get("direction") or "AUTO").upper(),
        "line_x1": data.get("line_x1"),
        "line_y1": data.get("line_y1"),
        "line_x2": data.get("line_x2"),
        "line_y2": data.get("line_y2"),
        "in_side": (data.get("in_side") or "POSITIVE").upper(),
        "status": data.get("status") or "inactive",
        "created_at": data.get("created_at") or iso_utc(),
        "last_seen": data.get("last_seen"),
        "error_count": int(data.get("error_count") or 0),
        "is_active": 1 if data.get("is_active") else 0,
    }
    with db_connection() as conn:
        if existing:
            _execute(
                conn,
                """
                UPDATE cameras SET company_id=?,name=?,rtsp_url=?,collection_id=?,collection_name=?,ip_address=?,
                    location=?,site_id=?,zone_id=?,camera_role=?,direction=?,line_x1=?,line_y1=?,line_x2=?,line_y2=?,in_side=?,status=?,last_seen=?,error_count=?,is_active=?
                WHERE id=?
                """,
                (
                    fields["company_id"], fields["name"], fields["rtsp_url"], fields["collection_id"], fields["collection_name"],
                    fields["ip_address"], fields["location"], fields["site_id"], fields["zone_id"], fields["camera_role"],
                    fields["direction"], fields["line_x1"], fields["line_y1"], fields["line_x2"], fields["line_y2"], fields["in_side"],
                    fields["status"], fields["last_seen"], fields["error_count"], fields["is_active"], camera_id,
                ),
            )
        else:
            _execute(
                conn,
                """
                INSERT INTO cameras(id,company_id,name,rtsp_url,collection_id,collection_name,ip_address,location,site_id,zone_id,
                    camera_role,direction,line_x1,line_y1,line_x2,line_y2,in_side,status,created_at,last_seen,error_count,is_active)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                tuple(fields[k] for k in (
                    "id", "company_id", "name", "rtsp_url", "collection_id", "collection_name", "ip_address", "location",
                    "site_id", "zone_id", "camera_role", "direction", "line_x1", "line_y1", "line_x2", "line_y2", "in_side",
                    "status", "created_at", "last_seen", "error_count", "is_active",
                )),
            )
    return get_camera(camera_id) or fields


def delete_camera_record(camera_id: int) -> bool:
    with db_connection() as conn:
        cur = _execute(conn, "DELETE FROM cameras WHERE id=?", (int(camera_id),))
        return bool(cur.rowcount)


def list_collections(company_id: Optional[str] = None) -> List[Dict[str, Any]]:
    if company_id is None:
        return fetch_all("SELECT * FROM camera_collections ORDER BY name")
    return fetch_all("SELECT * FROM camera_collections WHERE company_id=? ORDER BY name", (str(company_id),))


def save_collection(data: Dict[str, Any]) -> Dict[str, Any]:
    collection_id = str(data.get("id") or uuid.uuid4())
    existing = fetch_one("SELECT * FROM camera_collections WHERE id=?", (collection_id,))
    fields = {
        "id": collection_id,
        "company_id": data.get("company_id"),
        "name": data.get("name") or "Collection",
        "description": data.get("description"),
        "created_at": data.get("created_at") or iso_utc(),
        "camera_count": int(data.get("camera_count") or 0),
    }
    with db_connection() as conn:
        if existing:
            _execute(
                conn,
                "UPDATE camera_collections SET company_id=?,name=?,description=?,camera_count=? WHERE id=?",
                (fields["company_id"], fields["name"], fields["description"], fields["camera_count"], collection_id),
            )
        else:
            _execute(
                conn,
                "INSERT INTO camera_collections(id,company_id,name,description,created_at,camera_count) VALUES(?,?,?,?,?,?)",
                tuple(fields[k] for k in ("id", "company_id", "name", "description", "created_at", "camera_count")),
            )
    return fetch_one("SELECT * FROM camera_collections WHERE id=?", (collection_id,)) or fields


def delete_collection_record(collection_id: str) -> bool:
    with db_connection() as conn:
        _execute(conn, "UPDATE cameras SET collection_id=NULL, collection_name=NULL WHERE collection_id=?", (collection_id,))
        cur = _execute(conn, "DELETE FROM camera_collections WHERE id=?", (collection_id,))
        return bool(cur.rowcount)


def update_collection_counts() -> None:
    collections = list_collections(None)
    with db_connection() as conn:
        for collection in collections:
            row = _execute(conn, "SELECT COUNT(*) FROM cameras WHERE collection_id=?", (collection["id"],)).fetchone()
            count = int(row[0] if not isinstance(row, dict) else list(row.values())[0])
            _execute(conn, "UPDATE camera_collections SET camera_count=? WHERE id=?", (count, collection["id"]))


# ---------------------------------------------------------------------------
# Recognition events / attendance / unknown clustering
# ---------------------------------------------------------------------------

def _resolve_business_date(captured_at: datetime, shift_start: Optional[str] = None, shift_end: Optional[str] = None) -> str:
    local_dt = captured_at.astimezone(LOCAL_TZ) if captured_at.tzinfo else captured_at.replace(tzinfo=LOCAL_TZ)
    # Overnight shifts: events after midnight but before shift end belong to the previous business date.
    if shift_start and shift_end:
        try:
            sh, sm = [int(x) for x in shift_start.split(":")[:2]]
            eh, em = [int(x) for x in shift_end.split(":")[:2]]
            start_minutes = sh * 60 + sm
            end_minutes = eh * 60 + em
            current_minutes = local_dt.hour * 60 + local_dt.minute
            if start_minutes > end_minutes and current_minutes <= end_minutes:
                return (local_dt.date() - timedelta(days=1)).isoformat()
        except Exception:
            pass
    return local_dt.date().isoformat()


def cluster_unknown(
    company_id: str,
    embedding: Sequence[float],
    quality: float,
    image_path: Optional[str] = None,
    captured_at: Optional[datetime] = None,
    threshold: float = 0.88,
    lookback_days: int = 30,
) -> str:
    captured_at = captured_at or utc_now()
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    if vector.size == 0:
        return "UNK-" + uuid.uuid4().hex[:8].upper()
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector = vector / norm

    cutoff = iso_utc(captured_at - timedelta(days=lookback_days))
    candidates = fetch_all(
        "SELECT * FROM unknown_clusters WHERE company_id=? AND last_seen>=?",
        (str(company_id), cutoff),
    )
    best = None
    best_similarity = -1.0
    for row in candidates:
        centroid = blob_to_vector(row.get("centroid"))
        if centroid.size != vector.size or centroid.size == 0:
            continue
        c_norm = float(np.linalg.norm(centroid))
        if c_norm <= 0:
            continue
        centroid = centroid / c_norm
        similarity = float(np.dot(vector, centroid))
        if similarity > best_similarity:
            best_similarity = similarity
            best = row

    now = iso_utc(captured_at)
    with db_connection() as conn:
        if best and best_similarity >= threshold:
            old = blob_to_vector(best["centroid"]).astype(np.float32)
            count = max(int(best.get("sample_count") or 1), 1)
            if old.size == vector.size:
                centroid = (old * count + vector) / float(count + 1)
                c_norm = float(np.linalg.norm(centroid))
                if c_norm > 0:
                    centroid /= c_norm
            else:
                centroid = vector
            best_quality = float(best.get("best_quality") or 0.0)
            best_image = best.get("best_image_path")
            if quality > best_quality and image_path:
                best_quality = float(quality)
                best_image = image_path
            _execute(
                conn,
                """
                UPDATE unknown_clusters SET centroid=?,sample_count=?,last_seen=?,best_image_path=?,best_quality=? WHERE id=?
                """,
                (vector_to_blob(centroid), count + 1, now, best_image, best_quality, best["id"]),
            )
            return str(best["cluster_key"])

        cluster_id = str(uuid.uuid4())
        cluster_key = "UNK-" + uuid.uuid4().hex[:8].upper()
        _execute(
            conn,
            """
            INSERT INTO unknown_clusters(id,company_id,cluster_key,centroid,sample_count,first_seen,last_seen,best_image_path,best_quality)
            VALUES(?,?,?,?,?,?,?,?,?)
            """,
            (cluster_id, str(company_id), cluster_key, vector_to_blob(vector), 1, now, now, image_path, float(quality)),
        )
        return cluster_key


def record_recognition_event(
    *,
    company_id: str,
    person_key: Optional[str],
    display_name: Optional[str],
    event_type: str,
    camera_name: Optional[str],
    camera_id: Optional[int] = None,
    location: Optional[str] = None,
    camera_role: str = "BIDIRECTIONAL",
    direction: str = "AUTO",
    captured_at: Optional[datetime] = None,
    confidence: Optional[float] = None,
    distance: Optional[float] = None,
    quality: Optional[float] = None,
    face_size: Optional[Tuple[int, int]] = None,
    image_path: Optional[str] = None,
    source: str = "stream",
    model_version: str = "dlib-128-v2",
    attendance_eligible: bool = False,
    unknown_cluster_id: Optional[str] = None,
    shift_start: Optional[str] = None,
    shift_end: Optional[str] = None,
) -> Dict[str, Any]:
    company_id = str(company_id or "default")
    captured_at = captured_at or utc_now()
    if captured_at.tzinfo is None:
        captured_at = captured_at.replace(tzinfo=LOCAL_TZ).astimezone(timezone.utc)
    business_date = _resolve_business_date(captured_at, shift_start, shift_end)
    event_id = str(uuid.uuid4())

    person = get_person(company_id, person_key) if person_key else None
    person_id = person.get("id") if person else None
    if person and not display_name:
        display_name = person.get("name")

    fw, fh = face_size or (None, None)
    with db_connection() as conn:
        _execute(
            conn,
            """
            INSERT INTO recognition_events(id,company_id,person_id,person_key,display_name,unknown_cluster_id,event_type,
                camera_id,camera_name,location,camera_role,direction,captured_at,business_date,confidence,distance,quality,
                face_width,face_height,image_path,source,model_version,attendance_eligible)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                event_id, company_id, person_id, person_key, display_name, unknown_cluster_id, event_type,
                camera_id, camera_name, location, (camera_role or "BIDIRECTIONAL").upper(), (direction or "AUTO").upper(),
                iso_utc(captured_at), business_date, confidence, distance, quality, fw, fh, image_path, source,
                model_version, 1 if attendance_eligible else 0,
            ),
        )

    if person_id and event_type.lower() == "known" and attendance_eligible:
        update_attendance_from_event(
            company_id=company_id,
            person_id=person_id,
            business_date=business_date,
            event_id=event_id,
            captured_at=captured_at,
            camera_role=camera_role,
            direction=direction,
        )

    return fetch_one("SELECT * FROM recognition_events WHERE id=?", (event_id,)) or {"id": event_id}


def update_attendance_from_event(
    *, company_id: str, person_id: str, business_date: str, event_id: str,
    captured_at: datetime, camera_role: str, direction: str,
) -> None:
    role = (camera_role or "BIDIRECTIONAL").upper()
    direction = (direction or "AUTO").upper()
    if role == "REFERENCE_ONLY":
        return
    # Direction can override a bidirectional camera when line-crossing is available.
    effective = role
    if role == "BIDIRECTIONAL" and direction in {"IN", "OUT"}:
        effective = "ENTRY" if direction == "IN" else "EXIT"

    ts = iso_utc(captured_at)
    existing = fetch_one(
        "SELECT * FROM attendance_sessions WHERE company_id=? AND person_id=? AND business_date=?",
        (company_id, person_id, business_date),
    )
    now = iso_utc()
    with db_connection() as conn:
        if not existing:
            first_in = ts if effective in {"ENTRY", "BIDIRECTIONAL"} else None
            last_out = ts if effective in {"EXIT", "BIDIRECTIONAL"} else None
            _execute(
                conn,
                """
                INSERT INTO attendance_sessions(id,company_id,person_id,business_date,first_in,last_out,first_event_id,last_event_id,status,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    str(uuid.uuid4()), company_id, person_id, business_date, first_in, last_out,
                    event_id if first_in else None, event_id if last_out else None,
                    "Present" if first_in else "Incomplete", now,
                ),
            )
            return

        first_in = existing.get("first_in")
        last_out = existing.get("last_out")
        first_event = existing.get("first_event_id")
        last_event = existing.get("last_event_id")
        if effective in {"ENTRY", "BIDIRECTIONAL"}:
            if not first_in or ts < first_in:
                first_in = ts
                first_event = event_id
        if effective in {"EXIT", "BIDIRECTIONAL"}:
            if not last_out or ts > last_out:
                last_out = ts
                last_event = event_id
        status = "Present" if first_in else "Incomplete"
        _execute(
            conn,
            """
            UPDATE attendance_sessions SET first_in=?,last_out=?,first_event_id=?,last_event_id=?,status=?,updated_at=? WHERE id=?
            """,
            (first_in, last_out, first_event, last_event, status, now, existing["id"]),
        )


def list_recognition_events(
    company_id: Optional[str],
    *,
    face_type: Optional[str] = None,
    name: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    camera: Optional[str] = None,
    limit: int = 1000,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if company_id is not None:
        clauses.append("company_id=?")
        params.append(str(company_id))
    if face_type:
        clauses.append("LOWER(event_type)=LOWER(?)")
        params.append(face_type)
    if name:
        clauses.append("LOWER(COALESCE(display_name,person_key,unknown_cluster_id,'')) LIKE ?")
        params.append("%" + name.lower() + "%")
    if from_date:
        clauses.append("business_date>=?")
        params.append(from_date)
    if to_date:
        clauses.append("business_date<=?")
        params.append(to_date)
    if camera and camera != "all_cameras":
        clauses.append("LOWER(COALESCE(camera_name,''))=LOWER(?)")
        params.append(camera)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    params.append(max(1, min(int(limit), 10000)))
    return fetch_all(
        "SELECT * FROM recognition_events" + where + " ORDER BY captured_at DESC LIMIT ?",
        params,
    )


def get_attendance_rows(company_id: str, target_date: str) -> List[Dict[str, Any]]:
    persons = list_persons(company_id, active_only=True)
    sessions = fetch_all(
        "SELECT * FROM attendance_sessions WHERE company_id=? AND business_date=?",
        (str(company_id), target_date),
    )
    by_person = {row["person_id"]: row for row in sessions}
    output: List[Dict[str, Any]] = []
    for idx, person in enumerate(persons, start=1):
        session = by_person.get(person["id"])
        first_dt = parse_dt(session.get("first_in")) if session else None
        last_dt = parse_dt(session.get("last_out")) if session else None
        working_minutes = None
        if first_dt and last_dt and last_dt >= first_dt:
            working_minutes = int((last_dt - first_dt).total_seconds() // 60)
        output.append({
            "s_no": idx,
            "person_id": person["id"],
            "person_key": person["person_key"],
            "emp_id": person.get("emp_id") or "",
            "name": person.get("name") or person["person_key"],
            "department": person.get("department") or "",
            "designation": person.get("designation") or "",
            "email": person.get("email") or "",
            "status": (session or {}).get("status") or "Absent",
            "punch_in_iso": session.get("first_in") if session else None,
            "punch_out_iso": session.get("last_out") if session else None,
            "punch_in": first_dt.astimezone(LOCAL_TZ).strftime("%I:%M %p") if first_dt else None,
            "punch_out": last_dt.astimezone(LOCAL_TZ).strftime("%I:%M %p") if last_dt else None,
            "working_minutes": working_minutes,
            "working_hours": f"{working_minutes // 60}h {working_minutes % 60}m" if working_minutes is not None else "-",
            "photo_path": person.get("photo_path") or "",
            "first_event_id": (session or {}).get("first_event_id"),
            "last_event_id": (session or {}).get("last_event_id"),
        })
    return output


def get_attendance_aggregate(company_id: str, start_date: str, end_date: str) -> List[Dict[str, Any]]:
    persons = list_persons(company_id, active_only=True)
    sessions = fetch_all(
        """
        SELECT * FROM attendance_sessions WHERE company_id=? AND business_date>=? AND business_date<=?
        ORDER BY business_date
        """,
        (str(company_id), start_date, end_date),
    )
    by_person: Dict[str, List[Dict[str, Any]]] = {}
    for session in sessions:
        by_person.setdefault(session["person_id"], []).append(session)
    try:
        total_days = (date.fromisoformat(end_date) - date.fromisoformat(start_date)).days + 1
    except Exception:
        total_days = 1
    output = []
    for idx, person in enumerate(persons, start=1):
        rows = by_person.get(person["id"], [])
        present = sum(1 for r in rows if r.get("first_in"))
        total_minutes = 0
        late_count = 0
        for row in rows:
            first = parse_dt(row.get("first_in"))
            last = parse_dt(row.get("last_out"))
            if first and last and last >= first:
                total_minutes += int((last - first).total_seconds() // 60)
        output.append({
            "s_no": idx,
            "person_id": person["id"],
            "person_key": person["person_key"],
            "emp_id": person.get("emp_id") or "",
            "name": person.get("name") or person["person_key"],
            "department": person.get("department") or "",
            "designation": person.get("designation") or "",
            "email": person.get("email") or "",
            "total_present": present,
            "total_absent": max(total_days - present, 0),
            "total_late": late_count,
            "total_working_minutes": total_minutes,
            "total_working_hours": f"{total_minutes // 60}h {total_minutes % 60}m",
            "avg_working_hours": f"{(total_minutes / present / 60):.1f}h" if present else "-",
        })
    return output


# ---------------------------------------------------------------------------
# Reset tokens and audit
# ---------------------------------------------------------------------------

def create_password_reset_token(username: str, ttl_minutes: int = 15) -> str:
    import secrets
    raw = secrets.token_urlsafe(24)
    token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    now = utc_now()
    with db_connection() as conn:
        _execute(conn, "DELETE FROM password_reset_tokens WHERE username=? AND used_at IS NULL", (username,))
        _execute(
            conn,
            "INSERT INTO password_reset_tokens(id,username,token_hash,expires_at,used_at,created_at) VALUES(?,?,?,?,?,?)",
            (str(uuid.uuid4()), username, token_hash, iso_utc(now + timedelta(minutes=ttl_minutes)), None, iso_utc(now)),
        )
    return raw


def consume_password_reset_token(username: str, raw_token: str) -> bool:
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    row = fetch_one(
        """
        SELECT * FROM password_reset_tokens WHERE username=? AND token_hash=? AND used_at IS NULL
        ORDER BY created_at DESC LIMIT 1
        """,
        (username, token_hash),
    )
    if not row:
        return False
    expires = parse_dt(row.get("expires_at"))
    if not expires or expires < utc_now():
        return False
    with db_connection() as conn:
        _execute(conn, "UPDATE password_reset_tokens SET used_at=? WHERE id=?", (iso_utc(), row["id"]))
    return True


def write_audit(
    action: str, *, username: Optional[str] = None, company_id: Optional[str] = None,
    entity_type: Optional[str] = None, entity_id: Optional[str] = None, details: Optional[Dict[str, Any]] = None,
) -> None:
    with db_connection() as conn:
        _execute(
            conn,
            "INSERT INTO audit_logs(id,company_id,username,action,entity_type,entity_id,details_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
            (
                str(uuid.uuid4()), company_id, username, action, entity_type, entity_id,
                json.dumps(details or {}, ensure_ascii=False, default=str), iso_utc(),
            ),
        )


def migrate_legacy_metadata(metadata_path: str) -> int:
    """One-way compatibility import. Legacy JSON is never authoritative after migration."""
    path = Path(metadata_path)
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return 0
    persons: Dict[str, Any] = {}
    if isinstance(payload, dict) and isinstance(payload.get("persons"), dict):
        persons.update(payload["persons"])
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key != "persons" and isinstance(value, dict) and value.get("name"):
                persons[key] = value
    imported = 0
    for key, value in persons.items():
        if not isinstance(value, dict):
            continue
        company_id = str(value.get("company_id") or "default")
        if get_person(company_id, key):
            continue
        upsert_person(company_id, key, value)
        imported += 1
    return imported
