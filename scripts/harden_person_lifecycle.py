from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"Expected source fragment not found in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def main() -> int:
    changed = False
    vector_store = ROOT / "backend_face" / "recognition" / "vector_store.py"
    face_pipeline = ROOT / "backend_face" / "face_pipeline.py"
    registration = ROOT / "backend_face" / "registration" / "reg.py"

    changed |= replace_once(
        vector_store,
        """    return inserted\n\n\ndef load_arcface_bank(company_id: str) -> Dict[str, object]:\n""",
        """    return inserted\n\n\ndef delete_person_vectors(company_id: str, person_key: str) -> int:\n    \"\"\"Permanently remove all ArcFace templates for one tenant/person.\"\"\"\n    if not ensure_vector_schema():\n        return 0\n    company_id = str(company_id or \"default\")\n    person_key = str(person_key).strip().lower()\n    with db_connection() as conn:\n        cur = conn.cursor()\n        placeholder = \"%s\" if is_postgres() else \"?\"\n        cur.execute(\n            f\"DELETE FROM face_vectors_512 WHERE company_id={placeholder} AND person_key={placeholder}\",\n            (company_id, person_key),\n        )\n        return max(int(cur.rowcount or 0), 0)\n\n\ndef load_arcface_bank(company_id: str) -> Dict[str, object]:\n""",
    )

    changed |= replace_once(
        vector_store,
        """        cur.execute(\n            f\"SELECT person_key, embedding FROM face_vectors_512 WHERE company_id={placeholder} ORDER BY person_key,template_key\",\n            (company_id,),\n        )\n""",
        """        cur.execute(\n            f\"\"\"\n            SELECT fv.person_key, fv.embedding\n            FROM face_vectors_512 fv\n            JOIN persons p\n              ON p.company_id=fv.company_id AND p.person_key=fv.person_key\n            WHERE fv.company_id={placeholder}\n              AND LOWER(COALESCE(p.status,'active'))='active'\n            ORDER BY fv.person_key,fv.template_key\n            \"\"\",\n            (company_id,),\n        )\n""",
    )

    changed |= replace_once(
        vector_store,
        """                SELECT person_key,template_key,quality,model_version,\n                       1 - (embedding <=> %s) AS similarity\n                FROM face_vectors_512\n                WHERE company_id=%s\n                ORDER BY embedding <=> %s\n                LIMIT %s\n""",
        """                SELECT fv.person_key,fv.template_key,fv.quality,fv.model_version,\n                       1 - (fv.embedding <=> %s) AS similarity\n                FROM face_vectors_512 fv\n                JOIN persons p\n                  ON p.company_id=fv.company_id AND p.person_key=fv.person_key\n                WHERE fv.company_id=%s\n                  AND LOWER(COALESCE(p.status,'active'))='active'\n                ORDER BY fv.embedding <=> %s\n                LIMIT %s\n""",
    )

    changed |= replace_once(
        face_pipeline,
        """def clear_company_embeddings_cache(company_id: str) -> None:\n    with embedding_lock:\n        company_embeddings.pop(str(company_id or \"default\"), None)\n\n\ndef load_company_embeddings(company_id: str) -> Dict[str, Any]:\n""",
        """def clear_company_embeddings_cache(company_id: str) -> None:\n    with embedding_lock:\n        company_embeddings.pop(str(company_id or \"default\"), None)\n\n\ndef invalidate_person_tracking(company_id: str, person_key: str) -> None:\n    \"\"\"Immediately revoke an identity already latched on live tracks.\n\n    Stream tracking is intentionally short lived, but registration status/delete must\n    take effect immediately instead of waiting for a track timeout.\n    \"\"\"\n    person_key = str(person_key or \"\").strip().lower()\n    if not person_key:\n        return\n    with tracking_lock:\n        for tracks in person_tracking.values():\n            for track in tracks.values():\n                if str(track.get(\"confirmed_name\") or \"\").strip().lower() == person_key:\n                    track[\"confirmed_name\"] = None\n                    track[\"confirmed_at\"] = None\n                    track[\"identity_blocked\"] = True\n                    track[\"identity_block_reason\"] = \"person-disabled-or-deleted\"\n                    track[\"conflict_streak\"] = 0\n                    history = track.get(\"history\")\n                    if hasattr(history, \"clear\"):\n                        history.clear()\n\n\ndef load_company_embeddings(company_id: str) -> Dict[str, Any]:\n""",
    )

    changed |= replace_once(
        registration,
        """    upsert_person(company_id, person_id, merged)\n    try:\n        from face_pipeline import clear_company_embeddings_cache\n        clear_company_embeddings_cache(company_id)\n    except Exception:\n        pass\n""",
        """    upsert_person(company_id, person_id, merged)\n    try:\n        from face_pipeline import clear_company_embeddings_cache, invalidate_person_tracking\n        clear_company_embeddings_cache(company_id)\n        if status != \"Active\":\n            invalidate_person_tracking(company_id, person_id)\n    except Exception:\n        pass\n    try:\n        from cache.redis_cache import get_event_cache\n        get_event_cache().invalidate_face_bank(company_id)\n    except Exception:\n        pass\n""",
    )

    changed |= replace_once(
        registration,
        """    if not delete_person(company_id, person_id):\n        raise HTTPException(status_code=404, detail=\"Person not found\")\n\n    shutil.rmtree(GALLERY_DIR / company_id / person_id, ignore_errors=True)\n""",
        """    try:\n        from recognition.vector_store import delete_person_vectors\n        delete_person_vectors(company_id, person_id)\n    except Exception as exc:\n        logger.warning(\"Could not purge ArcFace vectors for %s/%s: %s\", company_id, person_id, exc)\n\n    if not delete_person(company_id, person_id):\n        raise HTTPException(status_code=404, detail=\"Person not found\")\n\n    shutil.rmtree(GALLERY_DIR / company_id / person_id, ignore_errors=True)\n""",
    )

    changed |= replace_once(
        registration,
        """    try:\n        from face_pipeline import clear_company_embeddings_cache\n        clear_company_embeddings_cache(company_id)\n    except Exception:\n        pass\n    write_audit(\n        \"PERSON_DELETED\",\n""",
        """    try:\n        from face_pipeline import clear_company_embeddings_cache, invalidate_person_tracking\n        clear_company_embeddings_cache(company_id)\n        invalidate_person_tracking(company_id, person_id)\n    except Exception:\n        pass\n    try:\n        from cache.redis_cache import get_event_cache\n        get_event_cache().invalidate_face_bank(company_id)\n    except Exception:\n        pass\n    write_audit(\n        \"PERSON_DELETED\",\n""",
    )

    print("person lifecycle hardening applied" if changed else "person lifecycle hardening already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
