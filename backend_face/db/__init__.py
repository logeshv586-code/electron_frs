"""Database-backed persistence for the Face Recognition System."""

from .core import init_database, db_connection, fetch_all, fetch_one, execute, executemany

__all__ = [
    "init_database",
    "db_connection",
    "fetch_all",
    "fetch_one",
    "execute",
    "executemany",
]
