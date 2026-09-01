from __future__ import annotations

import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from db.core import db_connection, is_postgres

logger = logging.getLogger(__name__)
_SCHEMA_LOCK = threading.Lock()
_SCHEMA_READY = False
_SCHEMA_FAILED = False


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _vector_blob(vector: Sequence[float]) -> bytes:
    return np.asarray(vector, dtype=np.float32).reshape(-1).tobytes()


def _blob_vector(value) -> np.ndarray:
    if value is None:
        return np.empty((0,), dtype=np.float32)
    if isinstance(value, np.ndarray):
        return value.astype(np.float32).reshape(-1)
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return np.frombuffer(value, dtype=np.float32).copy()
    try:
        return np.asarray(value, dtype=np.float32).reshape(-1)
    except Exception:
        return np.empty((0,), dtype=np.float32)


def ensure_vector_schema() -> bool:
    global _SCHEMA_READY, _SCHEMA_FAILED
    if _SCHEMA_READY:
        return True
    if _SCHEMA_FAILED:
        return False
    with _SCHEMA_LOCK:
        if _SCHEMA_READY:
            return True
        try:
            with db_connection() as conn:
                cur = conn.cursor()
                if is_postgres():
                    cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS face_vectors_512 (
                            id TEXT PRIMARY KEY,
                            company_id TEXT NOT NULL,
                            person_key TEXT NOT NULL,
                            template_key TEXT NOT NULL,
                            embedding vector(512) NOT NULL,
                            source_path TEXT,
                            quality REAL,
                            model_version TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            UNIQUE(company_id, person_key, template_key)
                        )
                        """
                    )
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_face_vectors_company ON face_vectors_512(company_id)")
                    cur.execute(
                        "CREATE INDEX IF NOT EXISTS idx_face_vectors_hnsw ON face_vectors_512 USING hnsw (embedding vector_cosine_ops)"
                    )
                else:
                    cur.execute(
                        """
                        CREATE TABLE IF NOT EXISTS face_vectors_512 (
                            id TEXT PRIMARY KEY,
                            company_id TEXT NOT NULL,
                            person_key TEXT NOT NULL,
                            template_key TEXT NOT NULL,
                            embedding BLOB NOT NULL,
                            source_path TEXT,
                            quality REAL,
                            model_version TEXT NOT NULL,
                            created_at TEXT NOT NULL,
                            UNIQUE(company_id, person_key, template_key)
                        )
                        """
                    )
                    cur.execute("CREATE INDEX IF NOT EXISTS idx_face_vectors_company ON face_vectors_512(company_id)")
            _SCHEMA_READY = True
            return True
        except Exception as exc:
            _SCHEMA_FAILED = True
            logger.error("ArcFace vector schema unavailable: %s", exc)
            return False


def _register_pgvector(conn) -> None:
    if not is_postgres():
        return
    from pgvector.psycopg import register_vector
    register_vector(conn)


def replace_person_vectors(
    company_id: str,
    person_key: str,
    templates: Iterable[Tuple[str, Sequence[float], Optional[str], float]],
    model_version: str,
) -> int:
    if not ensure_vector_schema():
        return 0
    company_id = str(company_id or "default")
    person_key = str(person_key)
    rows = []
    for template_key, embedding, source_path, quality in templates:
        vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
        if vector.size != 512:
            continue
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-8:
            continue
        vector = vector / norm
        rows.append((str(template_key), vector, source_path, float(quality or 0.0)))

    with db_connection() as conn:
        if is_postgres():
            _register_pgvector(conn)
        cur = conn.cursor()
        placeholder = "%s" if is_postgres() else "?"
        cur.execute(
            f"DELETE FROM face_vectors_512 WHERE company_id={placeholder} AND person_key={placeholder}",
            (company_id, person_key),
        )
        inserted = 0
        for template_key, vector, source_path, quality in rows:
            params = (
                str(uuid.uuid4()), company_id, person_key, template_key,
                vector if is_postgres() else _vector_blob(vector),
                source_path, quality, model_version, _iso_now(),
            )
            values = ",".join([placeholder] * 9)
            cur.execute(
                f"INSERT INTO face_vectors_512(id,company_id,person_key,template_key,embedding,source_path,quality,model_version,created_at) VALUES({values})",
                params,
            )
            inserted += 1
    return inserted


def load_arcface_bank(company_id: str) -> Dict[str, object]:
    if not ensure_vector_schema():
        return {"matrix": np.empty((0, 512), dtype=np.float32), "names": [], "person_indices": {}, "model": "arcface-512"}
    company_id = str(company_id or "default")
    with db_connection() as conn:
        if is_postgres():
            _register_pgvector(conn)
        cur = conn.cursor()
        placeholder = "%s" if is_postgres() else "?"
        cur.execute(
            f"SELECT person_key, embedding FROM face_vectors_512 WHERE company_id={placeholder} ORDER BY person_key,template_key",
            (company_id,),
        )
        rows = cur.fetchall()

    vectors: List[np.ndarray] = []
    names: List[str] = []
    for row in rows:
        if isinstance(row, dict):
            name, raw = row.get("person_key"), row.get("embedding")
        else:
            name, raw = row[0], row[1]
        vector = _blob_vector(raw)
        if vector.size != 512:
            continue
        norm = float(np.linalg.norm(vector))
        if norm <= 1e-8:
            continue
        vectors.append(vector / norm)
        names.append(str(name))
    matrix = np.vstack(vectors).astype(np.float32) if vectors else np.empty((0, 512), dtype=np.float32)
    names_array = np.asarray(names, dtype=object)
    indices = {name: np.flatnonzero(names_array == name) for name in sorted(set(names))}
    return {"matrix": matrix, "names": names, "person_indices": indices, "model": "arcface-512"}


def search_arcface(company_id: str, embedding: Sequence[float], top_k: int = 25) -> List[Dict[str, object]]:
    if not ensure_vector_schema():
        return []
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    if vector.size != 512:
        return []
    norm = float(np.linalg.norm(vector))
    if norm <= 1e-8:
        return []
    vector = vector / norm
    company_id = str(company_id or "default")
    top_k = max(2, min(int(top_k), 100))

    if is_postgres():
        with db_connection() as conn:
            _register_pgvector(conn)
            cur = conn.cursor()
            cur.execute(
                """
                SELECT person_key,template_key,quality,model_version,
                       1 - (embedding <=> %s) AS similarity
                FROM face_vectors_512
                WHERE company_id=%s
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (vector, company_id, vector, top_k),
            )
            rows = cur.fetchall()
        return [dict(row) if isinstance(row, dict) else {
            "person_key": row[0], "template_key": row[1], "quality": row[2],
            "model_version": row[3], "similarity": float(row[4]),
        } for row in rows]

    bank = load_arcface_bank(company_id)
    matrix = bank["matrix"]
    names = bank["names"]
    if matrix.shape[0] == 0:
        return []
    similarities = matrix @ vector
    order = np.argsort(similarities)[::-1][:top_k]
    return [
        {"person_key": names[int(i)], "template_key": "local", "quality": None,
         "model_version": "arcface-512", "similarity": float(similarities[int(i)])}
        for i in order
    ]


def match_arcface_embeddings(embeddings: Sequence[np.ndarray], company_id: str, min_side: int) -> Dict[str, object]:
    if not embeddings:
        return {"name": None, "distance": None, "confidence": 0.0, "embedding": None, "margin": 0.0, "hits": 0}
    base_threshold = float(os.getenv("FRS_ARCFACE_COSINE_THRESHOLD", "0.55"))
    distant_threshold = float(os.getenv("FRS_ARCFACE_DISTANT_COSINE_THRESHOLD", "0.60"))
    threshold = distant_threshold if int(min_side) < 90 else base_threshold
    required_margin = float(os.getenv("FRS_ARCFACE_MARGIN", "0.08"))
    best_result: Optional[Dict[str, object]] = None

    for embedding in embeddings:
        results = search_arcface(company_id, embedding, top_k=30)
        per_person: Dict[str, List[float]] = {}
        for row in results:
            per_person.setdefault(str(row["person_key"]), []).append(float(row["similarity"]))
        if not per_person:
            continue
        ranked = sorted(
            ((max(values), float(np.mean(sorted(values, reverse=True)[:2])), person, len(values))
             for person, values in per_person.items()),
            reverse=True,
        )
        best_similarity, score_similarity, person, hits = ranked[0]
        second_similarity = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = float(score_similarity - second_similarity)
        accepted = best_similarity >= threshold and (len(ranked) == 1 or margin >= required_margin)
        result = {
            "name": person if accepted else None,
            "distance": float(1.0 - best_similarity),
            "score_distance": float(1.0 - score_similarity),
            "confidence": float(np.clip(best_similarity, 0.0, 1.0)),
            "embedding": np.asarray(embedding, dtype=np.float32),
            "margin": margin,
            "hits": int(hits),
            "threshold": threshold,
            "model_version": "arcface-512-pgvector" if is_postgres() else "arcface-512-local",
        }
        if accepted and (best_result is None or result["confidence"] > best_result["confidence"]):
            best_result = result
        elif best_result is None:
            best_result = result
    return best_result or {"name": None, "distance": None, "confidence": 0.0, "embedding": embeddings[0], "margin": 0.0, "hits": 0}
