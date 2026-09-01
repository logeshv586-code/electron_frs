from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class DistributedEventCache:
    """Optional Redis dedupe/pubsub with an in-process fallback.

    Redis is used only when REDIS_URL is configured and reachable. Standalone Electron
    installs continue to work with local TTL deduplication.
    """

    def __init__(self) -> None:
        self.redis_url = os.getenv("REDIS_URL", "").strip()
        self.prefix = os.getenv("FRS_REDIS_PREFIX", "frs").strip() or "frs"
        self._client = None
        self._error_until = 0.0
        self._local: Dict[str, float] = {}
        self._lock = threading.RLock()

    def _redis(self):
        if not self.redis_url or time.time() < self._error_until:
            return None
        if self._client is not None:
            return self._client
        try:
            import redis
            client = redis.Redis.from_url(self.redis_url, socket_connect_timeout=1.0, socket_timeout=1.0, decode_responses=True)
            client.ping()
            self._client = client
            logger.info("Redis event cache connected")
            return client
        except Exception as exc:
            self._error_until = time.time() + 30.0
            logger.warning("Redis unavailable; using local event dedupe: %s", exc)
            return None

    def _key(self, company_id: str, identity: str, camera: str, bucket: int) -> str:
        raw = f"{company_id}|{identity}|{camera}|{bucket}".encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()[:24]
        return f"{self.prefix}:event:{digest}"

    def claim(self, company_id: str, identity: str, camera: str, ttl_seconds: int = 5, timestamp: Optional[float] = None) -> bool:
        ttl = max(1, int(ttl_seconds))
        now = float(timestamp if timestamp is not None else time.time())
        bucket = int(now // ttl)
        key = self._key(str(company_id), str(identity), str(camera), bucket)
        client = self._redis()
        if client is not None:
            try:
                return bool(client.set(key, "1", nx=True, ex=ttl + 2))
            except Exception:
                self._client = None
                self._error_until = time.time() + 15.0

        with self._lock:
            cutoff = now - max(ttl * 3, 15)
            for old_key, seen_at in list(self._local.items()):
                if seen_at < cutoff:
                    self._local.pop(old_key, None)
            if key in self._local:
                return False
            self._local[key] = now
            return True

    def publish(self, company_id: str, event: Dict) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            client.publish(f"{self.prefix}:recognitions:{company_id}", json.dumps(event, default=str, separators=(",", ":")))
        except Exception:
            self._client = None
            self._error_until = time.time() + 15.0

    def invalidate_face_bank(self, company_id: str) -> None:
        client = self._redis()
        if client is None:
            return
        try:
            client.publish(f"{self.prefix}:face-bank-invalidate", str(company_id))
        except Exception:
            pass


_cache = DistributedEventCache()


def get_event_cache() -> DistributedEventCache:
    return _cache
