"""Apply deterministic release source fixes before validation.

The GitHub connector replaces whole UTF-8 files, so this idempotent script is used by
CI for a few surgical edits in large backend modules. CI commits the result only after
Python compilation and the React production build both pass.
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

    print("source fixes applied" if changed else "source fixes already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
