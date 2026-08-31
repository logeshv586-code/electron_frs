from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

_BACKEND_DIR = Path(__file__).resolve().parents[1]
_DATA_DIR = _BACKEND_DIR / "data"
_DATA_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_PATH = Path(os.getenv("FRS_SQLITE_PATH", str(_DATA_DIR / "frs.db"))).resolve()
_IS_POSTGRES = DATABASE_URL.lower().startswith(("postgresql://", "postgres://"))
_INIT_LOCK = threading.Lock()
_INITIALIZED = False


def is_postgres() -> bool:
    return _IS_POSTGRES


def _adapt_sql(sql: str) -> str:
    return sql.replace("?", "%s") if _IS_POSTGRES else sql


@contextmanager
def db_connection():
    """Open a transaction against PostgreSQL when DATABASE_URL is set, otherwise SQLite.

    SQLite is deliberately kept as the zero-config Electron/on-prem fallback. Production
    deployments should set DATABASE_URL to PostgreSQL.
    """
    if _IS_POSTGRES:
        try:
            import psycopg
            from psycopg.rows import dict_row
        except Exception as exc:  # pragma: no cover - deployment dependency
            raise RuntimeError(
                "DATABASE_URL points to PostgreSQL but psycopg is not installed. "
                "Install requirements.txt."
            ) from exc
        conn = psycopg.connect(DATABASE_URL, row_factory=dict_row)
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    else:
        SQLITE_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(SQLITE_PATH), timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 30000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _row_to_dict(row: Any) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def execute(sql: str, params: Sequence[Any] = ()) -> int:
    init_database()
    with db_connection() as conn:
        cur = conn.cursor()
        cur.execute(_adapt_sql(sql), tuple(params))
        return int(cur.rowcount or 0)


def executemany(sql: str, rows: Iterable[Sequence[Any]]) -> int:
    init_database()
    rows = list(rows)
    if not rows:
        return 0
    with db_connection() as conn:
        cur = conn.cursor()
        cur.executemany(_adapt_sql(sql), rows)
        return int(cur.rowcount or 0)


def fetch_one(sql: str, params: Sequence[Any] = ()) -> Optional[Dict[str, Any]]:
    init_database()
    with db_connection() as conn:
        cur = conn.cursor()
        cur.execute(_adapt_sql(sql), tuple(params))
        return _row_to_dict(cur.fetchone())


def fetch_all(sql: str, params: Sequence[Any] = ()) -> List[Dict[str, Any]]:
    init_database()
    with db_connection() as conn:
        cur = conn.cursor()
        cur.execute(_adapt_sql(sql), tuple(params))
        return [_row_to_dict(row) for row in cur.fetchall()]


def _ddl_blob() -> str:
    return "BYTEA" if _IS_POSTGRES else "BLOB"


def _run_ddl(conn, sql: str) -> None:
    cur = conn.cursor()
    cur.execute(_adapt_sql(sql))


def init_database() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    with _INIT_LOCK:
        if _INITIALIZED:
            return

        blob = _ddl_blob()
        statements = [
            """
            CREATE TABLE IF NOT EXISTS app_kv (
                namespace TEXT NOT NULL,
                key TEXT NOT NULL,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(namespace, key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS persons (
                id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                person_key TEXT NOT NULL,
                name TEXT NOT NULL,
                emp_id TEXT,
                email TEXT,
                phone TEXT,
                role TEXT,
                department TEXT,
                designation TEXT,
                joining_date TEXT,
                status TEXT NOT NULL DEFAULT 'Active',
                category TEXT,
                age TEXT,
                gender TEXT,
                created_by TEXT,
                registration_date TEXT NOT NULL,
                photo_path TEXT,
                gallery_path TEXT,
                metadata_json TEXT,
                UNIQUE(company_id, person_key)
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS face_templates (
                id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                template_key TEXT NOT NULL,
                embedding {blob} NOT NULL,
                source_path TEXT,
                quality REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE,
                UNIQUE(person_id, template_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS recognition_events (
                id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                person_id TEXT,
                person_key TEXT,
                display_name TEXT,
                unknown_cluster_id TEXT,
                event_type TEXT NOT NULL,
                camera_id INTEGER,
                camera_name TEXT,
                location TEXT,
                camera_role TEXT,
                direction TEXT,
                captured_at TEXT NOT NULL,
                business_date TEXT NOT NULL,
                confidence REAL,
                distance REAL,
                quality REAL,
                face_width INTEGER,
                face_height INTEGER,
                image_path TEXT,
                source TEXT,
                model_version TEXT,
                attendance_eligible INTEGER NOT NULL DEFAULT 0,
                FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE SET NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS attendance_sessions (
                id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                person_id TEXT NOT NULL,
                business_date TEXT NOT NULL,
                first_in TEXT,
                last_out TEXT,
                first_event_id TEXT,
                last_event_id TEXT,
                status TEXT NOT NULL DEFAULT 'Present',
                updated_at TEXT NOT NULL,
                FOREIGN KEY(person_id) REFERENCES persons(id) ON DELETE CASCADE,
                UNIQUE(company_id, person_id, business_date)
            )
            """,
            f"""
            CREATE TABLE IF NOT EXISTS unknown_clusters (
                id TEXT PRIMARY KEY,
                company_id TEXT NOT NULL,
                cluster_key TEXT NOT NULL,
                centroid {blob} NOT NULL,
                sample_count INTEGER NOT NULL DEFAULT 1,
                first_seen TEXT NOT NULL,
                last_seen TEXT NOT NULL,
                best_image_path TEXT,
                best_quality REAL,
                UNIQUE(company_id, cluster_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS camera_collections (
                id TEXT PRIMARY KEY,
                company_id TEXT,
                name TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                camera_count INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS cameras (
                id INTEGER PRIMARY KEY,
                company_id TEXT,
                name TEXT NOT NULL,
                rtsp_url TEXT NOT NULL,
                collection_id TEXT,
                collection_name TEXT,
                ip_address TEXT,
                location TEXT,
                site_id TEXT,
                zone_id TEXT,
                camera_role TEXT NOT NULL DEFAULT 'BIDIRECTIONAL',
                direction TEXT NOT NULL DEFAULT 'AUTO',
                status TEXT NOT NULL DEFAULT 'inactive',
                created_at TEXT NOT NULL,
                last_seen TEXT,
                error_count INTEGER NOT NULL DEFAULT 0,
                is_active INTEGER NOT NULL DEFAULT 0
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS password_reset_tokens (
                id TEXT PRIMARY KEY,
                username TEXT NOT NULL,
                token_hash TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                used_at TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id TEXT PRIMARY KEY,
                company_id TEXT,
                username TEXT,
                action TEXT NOT NULL,
                entity_type TEXT,
                entity_id TEXT,
                details_json TEXT,
                created_at TEXT NOT NULL
            )
            """,
            "CREATE INDEX IF NOT EXISTS idx_persons_company ON persons(company_id)",
            "CREATE INDEX IF NOT EXISTS idx_templates_company ON face_templates(company_id)",
            "CREATE INDEX IF NOT EXISTS idx_events_company_time ON recognition_events(company_id, captured_at)",
            "CREATE INDEX IF NOT EXISTS idx_events_person_time ON recognition_events(person_id, captured_at)",
            "CREATE INDEX IF NOT EXISTS idx_events_unknown_cluster ON recognition_events(unknown_cluster_id)",
            "CREATE INDEX IF NOT EXISTS idx_attendance_company_date ON attendance_sessions(company_id, business_date)",
            "CREATE INDEX IF NOT EXISTS idx_unknown_company_time ON unknown_clusters(company_id, last_seen)",
            "CREATE INDEX IF NOT EXISTS idx_cameras_company ON cameras(company_id)",
            "CREATE INDEX IF NOT EXISTS idx_collections_company ON camera_collections(company_id)",
            "CREATE INDEX IF NOT EXISTS idx_reset_username ON password_reset_tokens(username)",
        ]

        with db_connection() as conn:
            for statement in statements:
                _run_ddl(conn, statement)

        _INITIALIZED = True
