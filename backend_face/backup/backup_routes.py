"""
Backup API Routes
=================
SuperAdmin-only endpoints for Redis backup management.
"""

import os
import logging
from fastapi import APIRouter, HTTPException, Request, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional

logger = logging.getLogger(__name__)

router = APIRouter()

# Lazy-loaded service instances
_backup_service = None
_backup_scheduler = None


def _get_service():
    """Get or create the backup service instance."""
    global _backup_service
    if _backup_service is None:
        from .backup_service import RedisBackupService
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_password = os.getenv("REDIS_PASSWORD", None)
        redis_db = int(os.getenv("REDIS_DB", "0"))
        _backup_service = RedisBackupService(
            redis_host=redis_host,
            redis_port=redis_port,
            redis_password=redis_password,
            redis_db=redis_db
        )
    return _backup_service


def _get_scheduler():
    """Get or create the backup scheduler instance."""
    global _backup_scheduler
    if _backup_scheduler is None:
        from .backup_scheduler import BackupScheduler
        _backup_scheduler = BackupScheduler(_get_service())
    return _backup_scheduler


def _require_admin_or_superadmin(request: Request):
    """Enforce SuperAdmin or Admin role. Raises 403 if not authorized."""
    user = request.scope.get("user", {})
    role = user.get("role")
    if role not in ["SuperAdmin", "Admin"]:
        username = user.get("username", "unknown")
        logger.warning(f"[BACKUP-ACCESS-DENIED] User '{username}' (role={role}) attempted backup operation")
        raise HTTPException(status_code=403, detail="Only SuperAdmin or Admin can access backup management")
    return user


# ─────────────────────────── LIST BACKUPS ───────────────────────────

@router.get("/list")
async def list_backups(request: Request):
    """List all available backup files."""
    user = _require_admin_or_superadmin(request)
    try:
        service = _get_service()
        backups = service.list_backups()
        if user.get("role") == "Admin":
            company_id = user.get("company_id")
            backups = [b for b in backups if company_id in b.get("tenant_ids", [])]
        return {"backups": backups, "total": len(backups)}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[BACKUP-API] List error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── TRIGGER BACKUP ───────────────────────────

class TriggerBackupRequest(BaseModel):
    compress: bool = False

@router.post("/trigger")
async def trigger_backup(request: Request, body: TriggerBackupRequest = TriggerBackupRequest()):
    """Trigger a manual backup of all tenant data."""
    user = _require_admin_or_superadmin(request)
    try:
        service = _get_service()
        role = user.get("role")
        tenant_id = user.get("company_id") if role == "Admin" else None
        
        result = service.create_backup(compress=body.compress, tenant_id=tenant_id)
        
        # Log the manual action
        scheduler = _get_scheduler()
        scheduler.log_manual_action("trigger_backup", user.get("username", "unknown"), {
            "filename": result.get("filename"),
            "total_keys": result.get("total_keys"),
            "compressed": body.compress,
            "tenant_id": tenant_id
        })
        
        return result
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[BACKUP-API] Trigger error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── DOWNLOAD BACKUP ───────────────────────────

@router.get("/download/{filename}")
async def download_backup(request: Request, filename: str):
    """Download a specific backup file."""
    user = _require_admin_or_superadmin(request)
    try:
        service = _get_service()
        if user.get("role") == "Admin":
            backups = service.list_backups()
            binfo = next((b for b in backups if b.get("filename") == filename), None)
            if not binfo or user.get("company_id") not in binfo.get("tenant_ids", []):
                raise HTTPException(status_code=403, detail="Access denied")
        filepath = service._resolve_filepath(filename)
        
        # Log download
        scheduler = _get_scheduler()
        scheduler.log_manual_action("download_backup", user.get("username", "unknown"), {
            "filename": filename
        })
        
        media_type = "application/gzip" if filename.endswith(".gz") else "application/json"
        return FileResponse(
            filepath,
            media_type=media_type,
            filename=filename
        )
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Backup file not found: {filename}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[BACKUP-API] Download error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── PREVIEW BACKUP ───────────────────────────

@router.get("/preview/{filename}")
async def preview_backup(request: Request, filename: str):
    """Preview the contents of a backup file without restoring."""
    user = _require_admin_or_superadmin(request)
    try:
        service = _get_service()
        if user.get("role") == "Admin":
            backups = service.list_backups()
            binfo = next((b for b in backups if b.get("filename") == filename), None)
            if not binfo or user.get("company_id") not in binfo.get("tenant_ids", []):
                raise HTTPException(status_code=403, detail="Access denied")
        return service.preview_backup(filename)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Backup file not found: {filename}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"[BACKUP-API] Preview error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── FULL RESTORE ───────────────────────────

class RestoreFullRequest(BaseModel):
    filename: str
    overwrite: bool = False
    confirm: bool = False

@router.post("/restore/full")
async def restore_full(request: Request, body: RestoreFullRequest):
    """Restore all keys from a selected backup file."""
    user = _require_admin_or_superadmin(request)
    try:
        service = _get_service()
        if user.get("role") == "Admin":
            company_id = user.get("company_id")
            backups = service.list_backups()
            binfo = next((b for b in backups if b.get("filename") == body.filename), None)
            if not binfo or company_id not in binfo.get("tenant_ids", []):
                raise HTTPException(status_code=403, detail="Access denied")
            result = service.restore_tenant(
                filename=body.filename,
                tenant_id=company_id,
                overwrite=body.overwrite,
                confirm=body.confirm
            )
        else:
            result = service.restore_full(
                filename=body.filename,
                overwrite=body.overwrite,
                confirm=body.confirm
            )
        
        if body.confirm:
            scheduler = _get_scheduler()
            scheduler.log_manual_action("restore_full", user.get("username", "unknown"), {
                "filename": body.filename,
                "overwrite": body.overwrite,
                "restored_keys": result.get("restored_keys", 0)
            })
        
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Backup file not found: {body.filename}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[BACKUP-API] Restore error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── TENANT RESTORE ───────────────────────────

class RestoreTenantRequest(BaseModel):
    filename: str
    tenant_id: str
    overwrite: bool = False
    confirm: bool = False

@router.post("/restore/tenant")
async def restore_tenant(request: Request, body: RestoreTenantRequest):
    """Restore only keys matching a specific tenant from a backup file."""
    user = _require_admin_or_superadmin(request)
    if user.get("role") == "Admin" and body.tenant_id != user.get("company_id"):
        raise HTTPException(status_code=403, detail="You can only restore your own tenant")
    try:
        service = _get_service()
        result = service.restore_tenant(
            filename=body.filename,
            tenant_id=body.tenant_id,
            overwrite=body.overwrite,
            confirm=body.confirm
        )
        
        if body.confirm:
            scheduler = _get_scheduler()
            scheduler.log_manual_action("restore_tenant", user.get("username", "unknown"), {
                "filename": body.filename,
                "tenant_id": body.tenant_id,
                "overwrite": body.overwrite,
                "restored_keys": result.get("restored_keys", 0)
            })
        
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Backup file not found: {body.filename}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[BACKUP-API] Tenant restore error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── LOGS ───────────────────────────

@router.get("/logs")
async def get_backup_logs(request: Request):
    """View backup audit logs."""
    user = _require_admin_or_superadmin(request)
    try:
        scheduler = _get_scheduler()
        logs = scheduler.get_logs()
        if user.get("role") == "Admin":
            username = user.get("username")
            company_id = user.get("company_id")
            # Strict tenant isolation
            filtered_logs = []
            for l in logs:
                # Always show admin's own actions
                if l.get("user") == username:
                    filtered_logs.append(l)
                # Show actions strictly on this tenant (excluding global SuperAdmin actions with None)
                elif company_id and l.get("tenant_id") == company_id:
                    filtered_logs.append(l)
            logs = filtered_logs
        return {"logs": logs, "total": len(logs)}
    except Exception as e:
        logger.error(f"[BACKUP-API] Logs error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── DELETED TENANTS ───────────────────────────

@router.get("/deleted-tenants")
async def get_deleted_tenants(request: Request):
    """View tenants that exist in backups but not in live Redis."""
    user = _require_admin_or_superadmin(request)
    try:
        service = _get_service()
        deleted = service.get_deleted_tenants()
        if user.get("role") == "Admin":
            company_id = user.get("company_id")
            deleted = [t for t in deleted if t.get("tenant_id") == company_id]
        return {"deleted_tenants": deleted, "total": len(deleted)}
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        logger.error(f"[BACKUP-API] Deleted tenants error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────── RETENTION ───────────────────────────

@router.post("/enforce-retention")
async def enforce_retention(request: Request):
    """Manually enforce backup retention policy."""
    user = _require_admin_or_superadmin(request)
    try:
        scheduler = _get_scheduler()
        if user.get("role") == "Admin":
            company_id = user.get("company_id")
            result = scheduler.enforce_retention(tenant_id=company_id, retention_days=60)
        else:
            result = scheduler.enforce_retention()
        
        scheduler.log_manual_action("enforce_retention", user.get("username", "unknown"), { "result": result, "tenant_id": user.get("company_id") if user.get("role") == "Admin" else None })
        
        print(f"DEBUG: Enforce retention result: {result}")
        return result
    except Exception as e:
        logger.error(f"[BACKUP-API] Retention error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
