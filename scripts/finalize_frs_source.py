"""Apply deterministic release source fixes before validation.

The GitHub connector replaces whole UTF-8 files, so this idempotent script is used by
CI for a few surgical edits in large backend/frontend modules. CI commits the result only
after Python compilation and the React production build both pass.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"Expected source fragment not found in {path}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def main() -> int:
    changed = False

    changed |= replace_once(
        ROOT / "backend_face" / "face_pipeline.py",
        '"embedding": match.get("embedding") or (embeddings[0] if embeddings else None),',
        '"embedding": match.get("embedding") if match.get("embedding") is not None else (embeddings[0] if embeddings else None),',
    )

    changed |= replace_once(
        ROOT / "backend_face" / "db" / "core.py",
        'def _adapt_sql(sql: str) -> str:\n    return sql.replace("?", "%s") if _IS_POSTGRES else sql\n',
        'def _adapt_sql(sql: str) -> str:\n    if not _IS_POSTGRES:\n        return sql\n    adapted = sql.replace("?", "%s")\n    # SQLite NOCASE is not valid PostgreSQL syntax. Keep ordering portable.\n    adapted = adapted.replace("ORDER BY name COLLATE NOCASE", "ORDER BY LOWER(name), name")\n    return adapted\n',
    )

    changed |= replace_once(
        ROOT / "backend_face" / "main.py",
        '@app.on_event("startup")\nasync def startup_event():\n    start_license_checker()\n',
        '@app.on_event("startup")\nasync def startup_event():\n    try:\n        from auth.bootstrap import bootstrap_admin_from_env\n        bootstrap_admin_from_env()\n    except Exception as exc:\n        logger.error(f"Admin bootstrap check failed: {exc}")\n\n    start_license_checker()\n',
    )

    changed |= replace_once(
        ROOT / "backend_face" / "main.py",
        '    await ws_manager.connect(websocket, company_id)\n    try:\n',
        '    if not await ws_manager.connect(websocket, company_id):\n        return\n    try:\n',
    )

    event_api = ROOT / "backend_face" / "event" / "event_api.py"
    changed |= replace_once(
        event_api,
        """def _filter_assigned_cameras(request: Request, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    assigned = _user(request).get("assigned_cameras") or []
    if not assigned or _user(request).get("role") == "SuperAdmin":
        return events
    allowed = {str(value).lower() for value in assigned}
    return [
        event for event in events
        if str(event.get("camera_id") or "").lower() in allowed
        or str(event.get("camera_name") or "").lower() in allowed
    ]
""",
        """def _filter_assigned_cameras(request: Request, events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    user = _user(request)
    role = user.get("role")
    if role in {"SuperAdmin", "Admin"}:
        return events
    assigned = user.get("assigned_cameras") or []
    if not assigned:
        return []
    allowed = {str(value).lower() for value in assigned}
    return [
        event for event in events
        if str(event.get("camera_id") or "").lower() in allowed
        or str(event.get("camera_name") or "").lower() in allowed
    ]
""",
    )

    changed |= replace_once(
        event_api,
        """@router.get("/cameras")
async def event_cameras(request: Request):
    tenant = _tenant(request, allow_all_superadmin=True)
    if tenant is None:
        rows = fetch_all("SELECT DISTINCT name FROM cameras WHERE name IS NOT NULL ORDER BY name")
    else:
        rows = fetch_all("SELECT DISTINCT name FROM cameras WHERE company_id=? AND name IS NOT NULL ORDER BY name", (tenant,))
    return {"cameras": [row["name"] for row in rows]}
""",
        """@router.get("/cameras")
async def event_cameras(request: Request):
    tenant = _tenant(request, allow_all_superadmin=True)
    user = _user(request)
    if tenant is None:
        rows = fetch_all("SELECT DISTINCT id,name FROM cameras WHERE name IS NOT NULL ORDER BY name")
    else:
        rows = fetch_all("SELECT DISTINCT id,name FROM cameras WHERE company_id=? AND name IS NOT NULL ORDER BY name", (tenant,))
    if user.get("role") == "Supervisor":
        assigned = {str(value).lower() for value in user.get("assigned_cameras") or []}
        rows = [row for row in rows if str(row.get("id") or "").lower() in assigned or str(row.get("name") or "").lower() in assigned]
    return {"cameras": [row["name"] for row in rows]}
""",
    )

    user_management = ROOT / "frontend" / "src" / "components" / "admin" / "UserManagement.js"

    changed |= replace_once(
        user_management,
        """  const availableMenus = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'registration', label: 'Registration' },
    { id: 'gallery', label: 'Gallery' },
    { id: 'events', label: 'Events' },
    { id: 'video', label: 'Video Processing' },
    { id: 'camera', label: 'Camera Management' },
    { id: 'stream-viewer', label: 'Stream Viewer' },
    { id: 'users', label: 'User Management' },
    { id: 'settings', label: 'Settings' },
  ];

  const { user: currentUser, token } = useAuthStore();
""",
        """  const availableMenus = [
    { id: 'dashboard', label: 'Dashboard' },
    { id: 'registration', label: 'Employees' },
    { id: 'matching', label: 'Face Matching' },
    { id: 'gallery', label: 'Face Gallery' },
    { id: 'events', label: 'Recognition Events' },
    { id: 'attendance', label: 'Attendance & Reports' },
    { id: 'holiday-calendar', label: 'Holiday Calendar' },
    { id: 'camera', label: 'Camera Management' },
    { id: 'stream-viewer', label: 'Live View' },
    { id: 'video', label: 'Video Processing' },
    { id: 'users', label: 'User Management' },
    { id: 'settings', label: 'Settings' },
    { id: 'backup', label: 'Backup' },
  ];

  const { user: currentUser, token } = useAuthStore();
  const supervisorCapableMenus = new Set(['dashboard', 'registration', 'events', 'attendance', 'camera', 'stream-viewer']);
  const normalizedCurrentMenus = new Set((currentUser?.assigned_menus || []).map((menu) => {
    if (menu === 'cameras') return 'camera';
    if (menu === 'attendance-report' || menu === 'day-report' || menu === 'week-report' || menu === 'month-report') return 'attendance';
    return menu;
  }));
  const assignableMenus = currentUser?.role === 'SuperAdmin'
    ? availableMenus
    : availableMenus.filter((menu) => supervisorCapableMenus.has(menu.id) && (normalizedCurrentMenus.size === 0 || normalizedCurrentMenus.has(menu.id)));
""",
    )

    changed |= replace_once(
        user_management,
        """                        <button className="action-btn delete" onClick={() => handleDelete(user.username)} title="Delete">
                          <Trash2 size={16} />
                        </button>
""",
        """                        {currentUser.role === 'SuperAdmin' && (
                          <button className="action-btn delete" onClick={() => handleDelete(user.username)} title="Delete permanently">
                            <Trash2 size={16} />
                          </button>
                        )}
""",
    )

    changed |= replace_once(
        user_management,
        """                          required={!isEditing}
                          placeholder={isEditing ? "Leave blank to keep current" : "Enter password"}
""",
        """                          required={!isEditing}
                          minLength={12}
                          placeholder={isEditing ? "Leave blank to keep current" : "Minimum 12 characters"}
""",
    )

    changed |= replace_once(
        user_management,
        "{availableMenus.map(menu => {",
        "{assignableMenus.map(menu => {",
    )

    print("source fixes applied" if changed else "source fixes already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
