from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from .evidence_store import get_evidence_store

router = APIRouter()


@router.get("/evidence/{token}")
async def get_evidence(request: Request, token: str):
    store = get_evidence_store()
    try:
        uri = store.decode_uri_token(token)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid evidence token")
    if not store.is_object_uri(uri):
        raise HTTPException(status_code=400, detail="Unsupported evidence reference")

    user = request.scope.get("user", {}) or {}
    role = user.get("role")
    company_id = str(user.get("company_id") or "default")
    evidence_tenant = store.tenant_from_uri(uri)
    if role != "SuperAdmin" and evidence_tenant and str(evidence_tenant) != company_id:
        raise HTTPException(status_code=403, detail="Cannot access another tenant's evidence")
    try:
        data, media_type = store.read_uri(uri)
        return Response(content=data, media_type=media_type, headers={"Cache-Control": "private, max-age=300"})
    except FileNotFoundError:
        raise HTTPException(status_code=503, detail="Evidence storage is unavailable")
    except Exception:
        raise HTTPException(status_code=404, detail="Evidence not found")
