from __future__ import annotations

import base64
import io
import logging
import mimetypes
import os
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


class EvidenceStore:
    """Evidence storage abstraction.

    filesystem is the default for a standalone Electron/on-prem install. Set
    FRS_EVIDENCE_STORAGE=s3 with FRS_S3_BUCKET to use AWS S3 or a compatible MinIO
    endpoint through FRS_S3_ENDPOINT_URL.
    """

    def __init__(self) -> None:
        self.backend = os.getenv("FRS_EVIDENCE_STORAGE", "filesystem").strip().lower()
        self.bucket = os.getenv("FRS_S3_BUCKET", "").strip()
        self.prefix = os.getenv("FRS_S3_PREFIX", "frs-evidence").strip().strip("/")
        self.endpoint_url = os.getenv("FRS_S3_ENDPOINT_URL", "").strip() or None
        self.region = os.getenv("FRS_S3_REGION", "").strip() or None
        self.delete_local_after_upload = os.getenv("FRS_S3_DELETE_LOCAL", "0").strip().lower() in {"1", "true", "yes"}
        self._client = None
        self._error: Optional[str] = None

    @property
    def enabled(self) -> bool:
        return self.backend in {"s3", "minio"} and bool(self.bucket)

    def _get_client(self):
        if not self.enabled:
            return None
        if self._client is not None:
            return self._client
        if self._error:
            return None
        try:
            import boto3
            kwargs = {}
            if self.endpoint_url:
                kwargs["endpoint_url"] = self.endpoint_url
            if self.region:
                kwargs["region_name"] = self.region
            self._client = boto3.client("s3", **kwargs)
            return self._client
        except Exception as exc:
            self._error = str(exc)
            logger.error("S3/MinIO evidence client unavailable: %s", exc)
            return None

    def object_key_for_path(self, local_path: Path) -> str:
        parts = list(local_path.parts)
        if "captured_faces" in parts:
            index = parts.index("captured_faces")
            relative = "/".join(parts[index + 1:])
        elif "gallery" in parts:
            index = parts.index("gallery")
            relative = "gallery/" + "/".join(parts[index + 1:])
        else:
            relative = local_path.name
        return f"{self.prefix}/{relative}" if self.prefix else relative

    def store_file(self, local_path: Path) -> str:
        path = Path(local_path)
        if not self.enabled:
            return str(path)
        client = self._get_client()
        if client is None:
            logger.warning("Object storage configured but unavailable; retaining local evidence %s", path)
            return str(path)
        key = self.object_key_for_path(path)
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        try:
            client.upload_file(str(path), self.bucket, key, ExtraArgs={"ContentType": content_type})
            uri = f"s3://{self.bucket}/{key}"
            if self.delete_local_after_upload:
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
            return uri
        except Exception as exc:
            logger.error("Evidence upload failed for %s: %s", path, exc)
            return str(path)

    @staticmethod
    def is_object_uri(value: Optional[str]) -> bool:
        return bool(value and str(value).startswith("s3://"))

    @staticmethod
    def _parse_uri(uri: str) -> Tuple[str, str]:
        value = str(uri)
        if not value.startswith("s3://"):
            raise ValueError("Unsupported evidence URI")
        body = value[5:]
        bucket, key = body.split("/", 1)
        return bucket, key

    def read_uri(self, uri: str) -> Tuple[bytes, str]:
        bucket, key = self._parse_uri(uri)
        client = self._get_client()
        if client is None:
            raise FileNotFoundError("Object storage unavailable")
        response = client.get_object(Bucket=bucket, Key=key)
        data = response["Body"].read()
        content_type = response.get("ContentType") or mimetypes.guess_type(key)[0] or "application/octet-stream"
        return data, content_type

    def tenant_from_uri(self, uri: str) -> Optional[str]:
        try:
            _, key = self._parse_uri(uri)
            parts = key.split("/")
            if self.prefix:
                prefix_parts = self.prefix.split("/")
                if parts[:len(prefix_parts)] == prefix_parts:
                    parts = parts[len(prefix_parts):]
            if parts and parts[0] in {"known", "unknown"} and len(parts) >= 2:
                return parts[1]
            if parts and parts[0] == "gallery" and len(parts) >= 2:
                return parts[1]
        except Exception:
            pass
        return None

    @staticmethod
    def encode_uri_token(uri: str) -> str:
        return base64.urlsafe_b64encode(uri.encode("utf-8")).decode("ascii").rstrip("=")

    @staticmethod
    def decode_uri_token(token: str) -> str:
        padding = "=" * (-len(token) % 4)
        return base64.urlsafe_b64decode((token + padding).encode("ascii")).decode("utf-8")

    def api_url(self, uri: str) -> str:
        return f"/api/storage/evidence/{self.encode_uri_token(uri)}"


_store = EvidenceStore()


def get_evidence_store() -> EvidenceStore:
    return _store
