"""
Redis Backup Service
====================
Core service for backing up and restoring multi-tenant Redis data.
Uses SCAN (never KEYS) for non-blocking operations.
"""

import os
import json
import base64
import logging
import gzip
from datetime import datetime
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# Default backup directory
BACKUP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backups")


class RedisBackupService:
    """Manages Redis backup and restore operations for multi-tenant data."""

    def __init__(self, redis_host: Optional[str] = None, redis_port: Optional[int] = None,
                 redis_password: Optional[str] = None, redis_db: Optional[int] = None,
                 backup_dir: Optional[str] = None):
        self.backup_dir = backup_dir or BACKUP_DIR
        env_config = self._redis_config_from_env()
        self.redis_host = redis_host or env_config["host"]
        self.redis_port = int(redis_port or env_config["port"])
        self.redis_password = redis_password if redis_password is not None else env_config["password"]
        self.redis_db = int(redis_db if redis_db is not None else env_config["db"])
        self._redis = None

        # Ensure backup directory exists
        os.makedirs(self.backup_dir, exist_ok=True)

    @staticmethod
    def _redis_config_from_env() -> Dict[str, Any]:
        """Read Redis connection settings from REDIS_URL or REDIS_* env vars."""
        redis_url = os.getenv("REDIS_URL")
        if redis_url:
            parsed = urlparse(redis_url)
            return {
                "host": parsed.hostname or "127.0.0.1",
                "port": parsed.port or 6379,
                "password": parsed.password or None,
                "db": int((parsed.path or "/0").lstrip("/") or "0")
            }

        return {
            "host": os.getenv("REDIS_HOST", "127.0.0.1"),
            "port": int(os.getenv("REDIS_PORT", "6379")),
            "password": os.getenv("REDIS_PASSWORD") or None,
            "db": int(os.getenv("REDIS_DB", "0"))
        }

    def _get_redis(self):
        """Lazy Redis connection with error handling."""
        if self._redis is None:
            try:
                import redis

                self._redis = redis.Redis(
                    host=self.redis_host,
                    port=self.redis_port,
                    password=self.redis_password,
                    db=self.redis_db,
                    socket_connect_timeout=2,
                    socket_timeout=5,
                    decode_responses=False
                )

                # Test connection
                self._redis.ping()

                logger.info(f"[BACKUP] Connected to Redis at {self.redis_host}:{self.redis_port}")

            except ImportError:
                logger.error("[BACKUP] redis package not installed. Run: pip install redis")
                raise RuntimeError("Redis package not installed")

            except Exception as e:
                self._redis = None
                logger.error(f"[BACKUP] Failed to connect to Redis: {e}")
                raise RuntimeError(f"Redis connection failed: {e}")

        return self._redis

    def _safe_decode(self, value: bytes) -> str:
        """Safely decode bytes to string, using base64 for binary data."""
        if value is None:
            return None
        try:
            return value.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            return base64.b64encode(value).decode("ascii")

    def _safe_decode_dict(self, d: dict) -> dict:
        """Decode a dict of bytes to strings."""
        return {self._safe_decode(k): self._safe_decode(v) for k, v in d.items()}

    def _safe_decode_list(self, items: list) -> list:
        """Decode a list of bytes to strings."""
        return [self._safe_decode(item) for item in items]

    # ─────────────────────────── BACKUP ───────────────────────────

    def create_backup(self, compress: bool = False, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Create a full backup of all tenant data from Redis (or specific tenant if provided).
        Uses SCAN to avoid blocking.
        
        Returns:
            dict with backup metadata (filename, keys_count, etc.)
        """
        r = self._get_redis()
        start_time = datetime.utcnow()
        
        backup_data = {
            "metadata": {
                "created_at": start_time.isoformat(),
                "redis_host": self.redis_host,
                "redis_port": self.redis_port,
                "redis_db": self.redis_db,
                "version": "1.0",
                "total_keys": 0,
                "tenant_ids": [],
                "errors": []
            },
            "data": {}
        }

        tenant_ids = set()
        total_keys = 0
        errors = []
        cursor = 0

        # Use SCAN to iterate all tenant:* keys
        match_pattern = f"tenant:{tenant_id}:*" if tenant_id else "tenant:*"
        while True:
            cursor, keys = r.scan(cursor=cursor, match=match_pattern, count=500)
            
            for key_bytes in keys:
                key = self._safe_decode(key_bytes)
                try:
                    key_type = r.type(key_bytes).decode("utf-8")
                    
                    entry = {"type": key_type}

                    if key_type == "string":
                        val = r.get(key_bytes)
                        entry["value"] = self._safe_decode(val)
                    elif key_type == "hash":
                        val = r.hgetall(key_bytes)
                        entry["value"] = self._safe_decode_dict(val)
                    elif key_type == "list":
                        val = r.lrange(key_bytes, 0, -1)
                        entry["value"] = self._safe_decode_list(val)
                    elif key_type == "set":
                        val = r.smembers(key_bytes)
                        entry["value"] = self._safe_decode_list(list(val))
                    elif key_type == "zset":
                        val = r.zrange(key_bytes, 0, -1, withscores=True)
                        entry["value"] = [
                            {"member": self._safe_decode(member), "score": score}
                            for member, score in val
                        ]
                    else:
                        entry["value"] = None
                        entry["note"] = f"Unsupported type: {key_type}"

                    # Store TTL if set
                    ttl = r.ttl(key_bytes)
                    if ttl and ttl > 0:
                        entry["ttl"] = ttl

                    backup_data["data"][key] = entry
                    total_keys += 1

                    # Extract tenant_id
                    parts = key.split(":")
                    if len(parts) >= 2:
                        tenant_ids.add(parts[1])

                except Exception as e:
                    error_msg = f"Error backing up key '{key}': {str(e)}"
                    errors.append(error_msg)
                    logger.warning(f"[BACKUP] {error_msg}")
                    # Continue processing other keys

            if cursor == 0:
                break

        end_time = datetime.utcnow()

        # Update metadata
        backup_data["metadata"]["total_keys"] = total_keys
        backup_data["metadata"]["tenant_ids"] = sorted(list(tenant_ids))
        backup_data["metadata"]["errors"] = errors
        backup_data["metadata"]["completed_at"] = end_time.isoformat()
        backup_data["metadata"]["duration_seconds"] = (end_time - start_time).total_seconds()

        # Generate filename (never overwrite existing)
        prefix = f"backup_{tenant_id}_" if tenant_id else "backup_"
        filename = f"{prefix}{datetime.now().strftime('%Y_%m')}.json"
        filepath = os.path.join(self.backup_dir, filename)
        
        # If file exists, add timestamp suffix
        if os.path.exists(filepath):
            filename = f"{prefix}{datetime.now().strftime('%Y_%m_%d_%H%M%S')}.json"
            filepath = os.path.join(self.backup_dir, filename)

        # Write to file
        if compress:
            filename = filename.replace(".json", ".json.gz")
            filepath = os.path.join(self.backup_dir, filename)
            with gzip.open(filepath, "wt", encoding="utf-8") as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)
        else:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(backup_data, f, indent=2, ensure_ascii=False)

        result = {
            "status": "success",
            "filename": filename,
            "filepath": filepath,
            "total_keys": total_keys,
            "tenant_count": len(tenant_ids),
            "tenant_ids": sorted(list(tenant_ids)),
            "errors_count": len(errors),
            "duration_seconds": (end_time - start_time).total_seconds(),
            "file_size_bytes": os.path.getsize(filepath),
            "created_at": start_time.isoformat()
        }

        logger.info(f"[BACKUP] Completed: {total_keys} keys from {len(tenant_ids)} tenants -> {filename} ({len(errors)} errors)")
        return result

    # ─────────────────────────── LIST ───────────────────────────

    def list_backups(self) -> List[Dict[str, Any]]:
        """List all available backup files, sorted DESC by date."""
        backups = []

        if not os.path.exists(self.backup_dir):
            return backups

        for filename in os.listdir(self.backup_dir):
            if not (filename.endswith(".json") or filename.endswith(".json.gz")):
                continue

            filepath = os.path.join(self.backup_dir, filename)
            stat = os.stat(filepath)

            # Try to extract metadata without loading full file
            metadata = {}
            try:
                data = self._load_backup(filepath)
                if "metadata" in data:
                    metadata = data["metadata"]
            except Exception as e:
                logger.warning(f"[BACKUP] Failed to read metadata from {filename}: {e}")

            backups.append({
                "filename": filename,
                "file_size_bytes": stat.st_size,
                "file_size_readable": self._format_size(stat.st_size),
                "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(),
                "total_keys": metadata.get("total_keys", "N/A"),
                "tenant_ids": metadata.get("tenant_ids", []),
                "created_at": metadata.get("created_at", "N/A"),
                "duration_seconds": metadata.get("duration_seconds", "N/A"),
                "errors_count": len(metadata.get("errors", []))
            })

        # Sort by modified date DESC
        backups.sort(key=lambda b: b["modified_at"], reverse=True)
        return backups

    def delete_backup(self, filename: str) -> Dict[str, Any]:
        """Delete a backup file from disk after validating the filename."""
        filepath = self._resolve_filepath(filename)
        file_size = os.path.getsize(filepath)
        os.remove(filepath)
        logger.info(f"[BACKUP] Deleted backup file: {filename}")
        return {
            "status": "success",
            "filename": filename,
            "deleted_bytes": file_size
        }

    # ─────────────────────────── PREVIEW ───────────────────────────

    def preview_backup(self, filename: str) -> Dict[str, Any]:
        """Preview contents of a backup file without restoring."""
        filepath = self._resolve_filepath(filename)
        data = self._load_backup(filepath)

        metadata = data.get("metadata", {})
        keys = list(data.get("data", {}).keys())
        
        # Group keys by tenant
        tenants = {}
        for key in keys:
            parts = key.split(":")
            tenant_id = parts[1] if len(parts) >= 2 else "unknown"
            if tenant_id not in tenants:
                tenants[tenant_id] = {"key_count": 0, "sample_keys": []}
            tenants[tenant_id]["key_count"] += 1
            if len(tenants[tenant_id]["sample_keys"]) < 5:
                tenants[tenant_id]["sample_keys"].append(key)

        return {
            "filename": filename,
            "metadata": metadata,
            "total_keys": len(keys),
            "sample_keys": keys[:20],
            "tenants": tenants
        }

    # ─────────────────────────── RESTORE ───────────────────────────

    def restore_full(self, filename: str, overwrite: bool = False, confirm: bool = False) -> Dict[str, Any]:
        """
        Full system restore from a backup file.
        
        Args:
            filename: Backup file to restore from
            overwrite: If True, overwrite existing keys
            confirm: Must be True to actually execute (safety check)
        """
        if not confirm:
            return {
                "status": "confirmation_required",
                "message": "Set confirm=true to execute full restore. This will restore ALL keys."
            }

        r = self._get_redis()
        filepath = self._resolve_filepath(filename)
        data = self._load_backup(filepath)

        restored = 0
        skipped = 0
        errors = []

        for key, entry in data.get("data", {}).items():
            try:
                key_bytes = key.encode("utf-8")
                
                # Check if key exists
                if not overwrite and r.exists(key_bytes):
                    skipped += 1
                    continue

                self._restore_key(r, key_bytes, entry)
                restored += 1

            except Exception as e:
                error_msg = f"Error restoring key '{key}': {str(e)}"
                errors.append(error_msg)
                logger.warning(f"[RESTORE] {error_msg}")

        result = {
            "status": "success",
            "restored_keys": restored,
            "skipped_keys": skipped,
            "errors_count": len(errors),
            "errors": errors[:20],  # Limit error details
            "source_file": filename
        }

        logger.info(f"[RESTORE-FULL] Restored {restored} keys, skipped {skipped}, errors {len(errors)} from {filename}")
        return result

    def restore_tenant(self, filename: str, tenant_id: str, overwrite: bool = False,
                       confirm: bool = False) -> Dict[str, Any]:
        """
        Restore only a specific tenant's data from a backup file.
        Only keys matching tenant:{tenant_id}:* are restored.
        """
        if not confirm:
            return {
                "status": "confirmation_required",
                "message": f"Set confirm=true to restore tenant '{tenant_id}'. Only tenant:{tenant_id}:* keys will be affected."
            }

        r = self._get_redis()
        filepath = self._resolve_filepath(filename)
        data = self._load_backup(filepath)

        prefix = f"tenant:{tenant_id}:"
        restored = 0
        skipped = 0
        errors = []

        for key, entry in data.get("data", {}).items():
            if not key.startswith(prefix):
                continue

            try:
                key_bytes = key.encode("utf-8")
                
                if not overwrite and r.exists(key_bytes):
                    skipped += 1
                    continue

                self._restore_key(r, key_bytes, entry)
                restored += 1

            except Exception as e:
                error_msg = f"Error restoring key '{key}': {str(e)}"
                errors.append(error_msg)
                logger.warning(f"[RESTORE-TENANT] {error_msg}")

        result = {
            "status": "success",
            "tenant_id": tenant_id,
            "restored_keys": restored,
            "skipped_keys": skipped,
            "errors_count": len(errors),
            "errors": errors[:20],
            "source_file": filename
        }

        logger.info(f"[RESTORE-TENANT] tenant={tenant_id}: restored {restored}, skipped {skipped}, errors {len(errors)}")
        return result

    def _restore_key(self, r, key_bytes: bytes, entry: Dict[str, Any]):
        """Restore a single key to Redis based on its type."""
        key_type = entry.get("type", "string")
        value = entry.get("value")
        ttl = entry.get("ttl")

        # Delete existing key first for clean restore
        r.delete(key_bytes)

        if key_type == "string":
            r.set(key_bytes, value.encode("utf-8") if isinstance(value, str) else value)
        elif key_type == "hash":
            if value and isinstance(value, dict):
                encoded = {k.encode("utf-8"): v.encode("utf-8") for k, v in value.items()}
                r.hset(key_bytes, mapping=encoded)
        elif key_type == "list":
            if value and isinstance(value, list):
                for item in value:
                    r.rpush(key_bytes, item.encode("utf-8") if isinstance(item, str) else item)
        elif key_type == "set":
            if value and isinstance(value, list):
                for item in value:
                    r.sadd(key_bytes, item.encode("utf-8") if isinstance(item, str) else item)
        elif key_type == "zset":
            if value and isinstance(value, list):
                for item in value:
                    r.zadd(key_bytes, {
                        item["member"].encode("utf-8"): item["score"]
                    })

        # Restore TTL if present
        if ttl and ttl > 0:
            r.expire(key_bytes, ttl)

    # ─────────────────────────── TENANT DELETION ───────────────────────────

    def delete_tenant_live(self, tenant_id: str, confirm: bool = False) -> Dict[str, Any]:
        """
        Delete all live Redis keys for a specific tenant.
        Does NOT touch any backup files.
        """
        if not confirm:
            return {
                "status": "confirmation_required",
                "message": f"Set confirm=true to delete all live keys for tenant '{tenant_id}'. Backups will NOT be affected."
            }

        r = self._get_redis()
        pattern = f"tenant:{tenant_id}:*"
        deleted = 0
        errors = []
        cursor = 0

        while True:
            cursor, keys = r.scan(cursor=cursor, match=pattern.encode("utf-8"), count=500)
            
            for key in keys:
                try:
                    r.delete(key)
                    deleted += 1
                except Exception as e:
                    errors.append(f"Failed to delete {self._safe_decode(key)}: {str(e)}")

            if cursor == 0:
                break

        result = {
            "status": "success",
            "tenant_id": tenant_id,
            "deleted_keys": deleted,
            "errors_count": len(errors),
            "backups_affected": False
        }

        logger.info(f"[DELETE-TENANT] Deleted {deleted} live keys for tenant={tenant_id}")
        return result

    # ─────────────────────────── DELETED TENANTS ───────────────────────────

    def get_deleted_tenants(self) -> List[Dict[str, Any]]:
        """
        Find tenants that exist in backups but not in live Redis.
        These are recoverable deleted tenants.
        """
        live_tenants = set()
        live_status = "available"
        live_error = None

        try:
            r = self._get_redis()

            # Get live tenant IDs from Redis
            cursor = 0
            while True:
                cursor, keys = r.scan(cursor=cursor, match="tenant:*", count=500)
                for key in keys:
                    parts = self._safe_decode(key).split(":")
                    if len(parts) >= 2:
                        live_tenants.add(parts[1])
                if cursor == 0:
                    break
        except RuntimeError as e:
            live_status = "unavailable"
            live_error = str(e)
            logger.warning(f"[DELETED-TENANTS] Redis unavailable; returning backup-only tenant data: {e}")

        # Get tenant IDs from all backups
        backup_tenants = {}
        for backup_info in self.list_backups():
            for tid in backup_info.get("tenant_ids", []):
                if tid not in backup_tenants:
                    backup_tenants[tid] = []
                backup_tenants[tid].append({
                    "filename": backup_info["filename"],
                    "created_at": backup_info["created_at"]
                })

        # Find deleted tenants (in backups but not live)
        deleted = []
        for tid, available_backups in backup_tenants.items():
            if live_status == "unavailable" or tid not in live_tenants:
                deleted.append({
                    "tenant_id": tid,
                    "available_in_backups": available_backups,
                    "backup_count": len(available_backups),
                    "live_status": live_status,
                    "live_error": live_error
                })

        return deleted

    # ─────────────────────────── HELPERS ───────────────────────────

    def _resolve_filepath(self, filename: str) -> str:
        """Resolve and validate a backup filename to full path. Prevents path traversal."""
        # Security: strip directory components
        safe_name = os.path.basename(filename)
        if safe_name != filename:
            raise ValueError(f"Invalid filename: '{filename}' — path traversal not allowed")
        
        filepath = os.path.join(self.backup_dir, safe_name)
        
        # Ensure resolved path is within backup directory
        if not os.path.abspath(filepath).startswith(os.path.abspath(self.backup_dir)):
            raise ValueError("Path traversal detected")
        
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Backup file not found: {safe_name}")
        
        return filepath

    def _load_backup(self, filepath: str) -> Dict[str, Any]:
        """Load a backup file (supports both JSON and gzipped JSON)."""
        if filepath.endswith(".json.gz"):
            with gzip.open(filepath, "rt", encoding="utf-8") as f:
                return json.load(f)
        else:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)

    @staticmethod
    def _format_size(size_bytes: int) -> str:
        """Format file size to human readable string."""
        for unit in ["B", "KB", "MB", "GB"]:
            if size_bytes < 1024:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024
        return f"{size_bytes:.1f} TB"
