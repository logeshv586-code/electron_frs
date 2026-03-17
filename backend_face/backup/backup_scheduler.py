"""
Backup Scheduler
================
Handles monthly automated backups and retention policy enforcement.
"""

import os
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


class BackupScheduler:
    """Schedules monthly backups and enforces retention policy."""

    def __init__(self, backup_service, retention_days: int = 90, max_backups: int = 3):
        """
        Args:
            backup_service: Instance of RedisBackupService
            retention_days: Delete backups older than this many days (default: 90)
            max_backups: Minimum number of backups to keep regardless of age (default: 3)
        """
        self.backup_service = backup_service
        self.retention_days = retention_days
        self.max_backups = max_backups
        self._timer = None
        self._running = False
        self._log_file = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "data", "backup_logs.json"
        )
        os.makedirs(os.path.dirname(self._log_file), exist_ok=True)

    def start(self):
        """Start the scheduler. Schedules next backup for 1st of next month."""
        if self._running:
            logger.warning("[SCHEDULER] Already running")
            return

        self._running = True
        self._schedule_next()
        logger.info("[SCHEDULER] Backup scheduler started")

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        logger.info("[SCHEDULER] Backup scheduler stopped")

    def _schedule_next(self):
        """Schedule the next backup run for the 1st of next month at 02:00 AM."""
        if not self._running:
            return

        now = datetime.now()
        
        # Calculate 1st of next month
        if now.month == 12:
            next_run = datetime(now.year + 1, 1, 1, 2, 0, 0)
        else:
            next_run = datetime(now.year, now.month + 1, 1, 2, 0, 0)

        delay_seconds = (next_run - now).total_seconds()
        
        # Don't allow negative delays
        if delay_seconds < 0:
            delay_seconds = 60  # Fallback: run in 1 minute

        self._timer = threading.Timer(delay_seconds, self._run_backup)
        self._timer.daemon = True
        self._timer.start()

        logger.info(f"[SCHEDULER] Next backup scheduled for {next_run.isoformat()} ({delay_seconds:.0f}s from now)")

    def _run_backup(self):
        """Execute the scheduled backup."""
        log_entry = {
            "type": "scheduled",
            "start_time": datetime.utcnow().isoformat(),
            "status": "started"
        }

        try:
            logger.info("[SCHEDULER] Starting scheduled monthly backup...")
            result = self.backup_service.create_backup()
            
            log_entry.update({
                "status": "success",
                "end_time": datetime.utcnow().isoformat(),
                "total_keys": result.get("total_keys", 0),
                "filename": result.get("filename", ""),
                "errors_count": result.get("errors_count", 0),
                "duration_seconds": result.get("duration_seconds", 0)
            })

            logger.info(f"[SCHEDULER] Monthly backup completed: {result.get('filename')}")

        except Exception as e:
            log_entry.update({
                "status": "failed",
                "end_time": datetime.utcnow().isoformat(),
                "error": str(e)
            })
            logger.error(f"[SCHEDULER] Monthly backup failed: {e}")

        # Save log
        self._append_log(log_entry)

        # Enforce retention policy
        try:
            self.enforce_retention()
        except Exception as e:
            logger.error(f"[SCHEDULER] Retention enforcement failed: {e}")

        # Schedule next run
        self._schedule_next()

    def enforce_retention(self) -> Dict[str, Any]:
        """
        Delete backups older than retention_days.
        Always keeps at least max_backups files.
        
        Returns:
            dict with details of deleted files
        """
        backups = self.backup_service.list_backups()
        
        if len(backups) <= self.max_backups:
            logger.info(f"[RETENTION] Only {len(backups)} backups exist, keeping all (minimum: {self.max_backups})")
            return {"deleted": [], "kept": len(backups)}

        cutoff_date = datetime.utcnow() - timedelta(days=self.retention_days)
        deleted = []

        # Sort by date (oldest first) and keep the newest max_backups
        sorted_backups = sorted(backups, key=lambda b: b.get("modified_at", ""), reverse=False)
        
        for backup in sorted_backups:
            # Never delete if we'd go below minimum
            remaining = len(backups) - len(deleted)
            if remaining <= self.max_backups:
                break

            try:
                modified = datetime.fromisoformat(backup["modified_at"])
                if modified < cutoff_date:
                    filepath = os.path.join(self.backup_service.backup_dir, backup["filename"])
                    if os.path.exists(filepath):
                        os.remove(filepath)
                        deleted.append(backup["filename"])
                        logger.info(f"[RETENTION] Deleted old backup: {backup['filename']}")
            except (ValueError, OSError) as e:
                logger.warning(f"[RETENTION] Error processing {backup['filename']}: {e}")

        result = {
            "deleted": deleted,
            "deleted_count": len(deleted),
            "kept": len(backups) - len(deleted),
            "retention_days": self.retention_days,
            "cutoff_date": cutoff_date.isoformat()
        }

        logger.info(f"[RETENTION] Deleted {len(deleted)} old backups, kept {result['kept']}")
        return result

    # ─────────────────────────── LOGGING ───────────────────────────

    def _append_log(self, entry: Dict[str, Any]):
        """Append a log entry to the backup logs file."""
        import json
        logs = self.get_logs()
        logs.append(entry)

        # Keep only last 100 log entries
        if len(logs) > 100:
            logs = logs[-100:]

        try:
            with open(self._log_file, "w", encoding="utf-8") as f:
                json.dump(logs, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[SCHEDULER] Failed to write log: {e}")

    def log_manual_action(self, action: str, user: str, details: Dict[str, Any]):
        """Log a manual backup action (trigger, restore, download, etc.)."""
        entry = {
            "type": "manual",
            "action": action,
            "user": user,
            "timestamp": datetime.utcnow().isoformat(),
            **details
        }
        self._append_log(entry)

    def get_logs(self) -> List[Dict[str, Any]]:
        """Get all backup log entries."""
        import json
        if not os.path.exists(self._log_file):
            return []
        try:
            with open(self._log_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
