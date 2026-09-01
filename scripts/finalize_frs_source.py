"""Apply deterministic release source fixes before validation.

Large source files are changed here with small idempotent transformations. GitHub Actions
runs this script, compiles the Python tree, builds React, runs production guardrail tests,
and only then commits the finalized source back to the production branch.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"Expected source fragment not found in {path}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def main() -> int:
    changed = False
    face_pipeline = ROOT / "backend_face" / "face_pipeline.py"
    repository = ROOT / "backend_face" / "db" / "repository.py"
    service = ROOT / "backend_face" / "camera_management" / "service.py"
    streaming = ROOT / "backend_face" / "camera_management" / "streaming.py"
    main_py = ROOT / "backend_face" / "main.py"
    registration = ROOT / "backend_face" / "registration" / "reg.py"
    event_api = ROOT / "backend_face" / "event" / "event_api.py"

    # ------------------------------------------------------------------
    # Face recognition: ArcFace 512-D preferred when a licensed ONNX model
    # is configured, otherwise existing dlib 128-D remains the fallback.
    # ------------------------------------------------------------------
    changed |= replace_once(
        face_pipeline,
        """    try:
        from fr1 import load_known_faces
        encodings, names = load_known_faces(data_directory, company_id=company_id)
""",
        """    try:
        from recognition.arcface import get_arcface_engine
        from recognition.backfill import backfill_arcface_gallery
        from recognition.vector_store import load_arcface_bank
        arcface = get_arcface_engine()
        if arcface.available:
            arc_bank = load_arcface_bank(company_id)
            if arc_bank.get("matrix") is None or arc_bank["matrix"].shape[0] == 0:
                backfill_arcface_gallery(data_directory, company_id)
                arc_bank = load_arcface_bank(company_id)
            if arc_bank.get("matrix") is not None and arc_bank["matrix"].shape[0] > 0:
                entry = {
                    "matrix": arc_bank["matrix"],
                    "names": list(arc_bank.get("names") or []),
                    "person_indices": arc_bank.get("person_indices") or {},
                    "loaded_at": time.time(),
                    "model": "arcface-512",
                }
                with embedding_lock:
                    company_embeddings[company_id] = entry
                return entry
    except Exception as exc:
        logger.warning("ArcFace bank unavailable for %s; using dlib fallback: %s", company_id, exc)

    try:
        from fr1 import load_known_faces
        encodings, names = load_known_faces(data_directory, company_id=company_id)
""",
    )

    changed |= replace_once(
        face_pipeline,
        """    threshold, required_margin, *_ = _thresholds(company_id, min_side)
    indices = bank.get("person_indices") or {}
""",
        """    if matrix.shape[1] == 512:
        try:
            from recognition.vector_store import match_arcface_embeddings
            return match_arcface_embeddings(embeddings, company_id, min_side)
        except Exception as exc:
            logger.warning("ArcFace vector search failed for %s: %s", company_id, exc)
            return {"name": None, "distance": None, "confidence": 0.0, "embedding": embeddings[0], "margin": 0.0, "hits": 0}

    threshold, required_margin, *_ = _thresholds(company_id, min_side)
    indices = bank.get("person_indices") or {}
""",
    )

    changed |= replace_once(
        face_pipeline,
        """        raw.append({
            "bbox": (x1, y1, x2, y2),
            "det_conf": float(getattr(face, "det_score", 0.0) or getattr(face, "score", 0.0) or 0.0),
        })
""",
        """        kps = getattr(face, "kps", None)
        raw.append({
            "bbox": (x1, y1, x2, y2),
            "det_conf": float(getattr(face, "det_score", 0.0) or getattr(face, "score", 0.0) or 0.0),
            "kps": np.asarray(kps, dtype=np.float32).reshape(-1, 2).tolist() if kps is not None else None,
        })
""",
    )

    changed |= replace_once(
        face_pipeline,
        """        embeddings = _encode_variants(frame_bgr, bbox, min_side) if min_side >= recognition_min else []
        match = _match(embeddings, bank, company_id, min_side)
""",
        """        embeddings = []
        if min_side >= recognition_min:
            try:
                from recognition.arcface import get_arcface_engine
                arcface = get_arcface_engine()
                if arcface.available:
                    arc_embedding = arcface.embed_frame(frame_bgr, bbox, detection.get("kps"))
                    if arc_embedding is not None:
                        embeddings = [arc_embedding.astype(np.float64)]
            except Exception as exc:
                logger.debug("ArcFace live embedding fallback: %s", exc)
            if not embeddings:
                embeddings = _encode_variants(frame_bgr, bbox, min_side)
        match = _match(embeddings, bank, company_id, min_side)
""",
    )

    changed |= replace_once(
        face_pipeline,
        """        with tracking_lock:
            _update_identity(track, match, quality, company_id, min_side)
            confirmed = track.get("confirmed_name")

        current_match_is_confirmed = bool(confirmed and match.get("name") == confirmed)
        attendance_eligible = bool(
            current_match_is_confirmed
            and min_side >= attendance_min
            and quality >= attendance_quality
            and detection["det_conf"] >= 0.55
        )
""",
        """        with tracking_lock:
            _update_identity(track, match, quality, company_id, min_side)
            confirmed = track.get("confirmed_name")

        try:
            from recognition.liveness import get_liveness_engine
            liveness = get_liveness_engine().evaluate(track, face_crop)
        except Exception:
            liveness = {"score": 0.0, "passed": True, "mode": "unavailable", "required": False}

        stream_info = {}
        if stream_id:
            try:
                from camera_management.streaming import get_stream_manager
                stream_info = get_stream_manager().get_stream_info(stream_id) or {}
            except Exception:
                stream_info = {}
        try:
            from tracking.direction import has_virtual_line, update_track_direction
            event_direction = update_track_direction(track, bbox, frame_bgr.shape, stream_info)
            crossing_required = bool(
                str(stream_info.get("camera_role") or "BIDIRECTIONAL").upper() == "BIDIRECTIONAL"
                and str(stream_info.get("direction") or "AUTO").upper() == "AUTO"
                and has_virtual_line(stream_info)
            )
        except Exception:
            event_direction = str(stream_info.get("direction") or "AUTO").upper()
            crossing_required = False

        current_match_is_confirmed = bool(confirmed and match.get("name") == confirmed)
        attendance_eligible = bool(
            current_match_is_confirmed
            and min_side >= attendance_min
            and quality >= attendance_quality
            and detection["det_conf"] >= 0.55
            and bool(liveness.get("passed", True))
            and event_direction != "NONE"
            and (not crossing_required or event_direction in {"IN", "OUT"})
        )
""",
    )

    changed |= replace_once(
        face_pipeline,
        '"embedding": match.get("embedding") or (embeddings[0] if embeddings else None),',
        '"embedding": match.get("embedding") if match.get("embedding") is not None else (embeddings[0] if embeddings else None),',
    )

    changed |= replace_once(
        face_pipeline,
        """            "attendance_eligible": attendance_eligible,
            "current_match_is_confirmed": current_match_is_confirmed,
            "det_conf": detection["det_conf"],
""",
        """            "attendance_eligible": attendance_eligible,
            "current_match_is_confirmed": current_match_is_confirmed,
            "det_conf": detection["det_conf"],
            "liveness_score": float(liveness.get("score") or 0.0),
            "liveness_passed": bool(liveness.get("passed", True)),
            "liveness_mode": liveness.get("mode"),
            "event_direction": event_direction,
            "model_version": match.get("model_version") or ("arcface-512" if embeddings and embeddings[0].shape[0] == 512 else "dlib-128-consensus-v2"),
""",
    )

    changed |= replace_once(
        face_pipeline,
        """                        attendance_eligible=item["attendance_eligible"],
                    )
""",
        """                        attendance_eligible=item["attendance_eligible"],
                        direction_override=item.get("event_direction"),
                        model_version=item.get("model_version"),
                    )
""",
    )

    changed |= replace_once(
        face_pipeline,
        """                            attendance_eligible=False,
                            unknown_cluster_id=cluster_key,
                        )
""",
        """                            attendance_eligible=False,
                            unknown_cluster_id=cluster_key,
                            direction_override=item.get("event_direction"),
                            model_version=item.get("model_version"),
                        )
""",
    )

    changed |= replace_once(
        face_pipeline,
        """            "identity_conflict": bool(item.get("identity_conflict")),
        })
""",
        """            "identity_conflict": bool(item.get("identity_conflict")),
            "liveness_score": item.get("liveness_score"),
            "liveness_passed": item.get("liveness_passed"),
            "liveness_mode": item.get("liveness_mode"),
            "direction": item.get("event_direction"),
            "model_version": item.get("model_version"),
        })
""",
    )

    # Enrollment stores both dlib fallback descriptors and ArcFace 512-D vectors.
    changed |= replace_once(
        registration,
        """    replace_face_templates(company_id, person_key, db_templates)
    return person_dir, len(db_templates)
""",
        """    replace_face_templates(company_id, person_key, db_templates)
    try:
        from recognition.arcface import get_arcface_engine
        from recognition.vector_store import replace_person_vectors
        arcface = get_arcface_engine()
        if arcface.available:
            arc_templates = []
            for index, (template_key, image, _dlib_embedding, quality) in enumerate(templates):
                vector = arcface.embed_crop(image)
                source = person_dir / f"template_{index:02d}_{template_key}.jpg"
                if vector is not None and source.exists():
                    arc_templates.append((template_key, vector, str(source), quality))
            replace_person_vectors(company_id, person_key, arc_templates, arcface.model_version)
        try:
            from face_pipeline import clear_company_embeddings_cache
            clear_company_embeddings_cache(company_id)
        except Exception:
            pass
        try:
            from cache.redis_cache import get_event_cache
            get_event_cache().invalidate_face_bank(company_id)
        except Exception:
            pass
    except Exception as exc:
        logger.warning("ArcFace enrollment vectors were not updated: %s", exc)
    return person_dir, len(db_templates)
""",
    )

    # ------------------------------------------------------------------
    # Camera persistence and stream context for virtual line crossing.
    # ------------------------------------------------------------------
    changed |= replace_once(
        repository,
        '        "direction": (data.get("direction") or "AUTO").upper(),\n        "status": data.get("status") or "inactive",',
        '        "direction": (data.get("direction") or "AUTO").upper(),\n        "line_x1": data.get("line_x1"),\n        "line_y1": data.get("line_y1"),\n        "line_x2": data.get("line_x2"),\n        "line_y2": data.get("line_y2"),\n        "in_side": (data.get("in_side") or "POSITIVE").upper(),\n        "status": data.get("status") or "inactive",',
    )

    changed |= replace_once(
        repository,
        """                    location=?,site_id=?,zone_id=?,camera_role=?,direction=?,status=?,last_seen=?,error_count=?,is_active=?
                WHERE id=?
""",
        """                    location=?,site_id=?,zone_id=?,camera_role=?,direction=?,line_x1=?,line_y1=?,line_x2=?,line_y2=?,in_side=?,status=?,last_seen=?,error_count=?,is_active=?
                WHERE id=?
""",
    )

    changed |= replace_once(
        repository,
        """                    fields["ip_address"], fields["location"], fields["site_id"], fields["zone_id"], fields["camera_role"],
                    fields["direction"], fields["status"], fields["last_seen"], fields["error_count"], fields["is_active"], camera_id,
""",
        """                    fields["ip_address"], fields["location"], fields["site_id"], fields["zone_id"], fields["camera_role"],
                    fields["direction"], fields["line_x1"], fields["line_y1"], fields["line_x2"], fields["line_y2"], fields["in_side"],
                    fields["status"], fields["last_seen"], fields["error_count"], fields["is_active"], camera_id,
""",
    )

    changed |= replace_once(
        repository,
        """                INSERT INTO cameras(id,company_id,name,rtsp_url,collection_id,collection_name,ip_address,location,site_id,zone_id,
                    camera_role,direction,status,created_at,last_seen,error_count,is_active)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
""",
        """                INSERT INTO cameras(id,company_id,name,rtsp_url,collection_id,collection_name,ip_address,location,site_id,zone_id,
                    camera_role,direction,line_x1,line_y1,line_x2,line_y2,in_side,status,created_at,last_seen,error_count,is_active)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
""",
    )

    changed |= replace_once(
        repository,
        """                    "site_id", "zone_id", "camera_role", "direction", "status", "created_at", "last_seen", "error_count", "is_active",
""",
        """                    "site_id", "zone_id", "camera_role", "direction", "line_x1", "line_y1", "line_x2", "line_y2", "in_side",
                    "status", "created_at", "last_seen", "error_count", "is_active",
""",
    )

    changed |= replace_once(
        repository,
        '        "direction": "AUTO",\n        "site_id": None,\n        "zone_id": None,',
        '        "direction": "AUTO",\n        "site_id": None,\n        "zone_id": None,\n        "line_x1": None,\n        "line_y1": None,\n        "line_x2": None,\n        "line_y2": None,\n        "in_side": "POSITIVE",',
    )

    changed |= replace_once(
        service,
        """            camera_role=request.camera_role,
            direction=request.direction,
            status="inactive",
""",
        """            camera_role=request.camera_role,
            direction=request.direction,
            line_x1=request.line_x1,
            line_y1=request.line_y1,
            line_x2=request.line_x2,
            line_y2=request.line_y2,
            in_side=request.in_side,
            status="inactive",
""",
    )

    changed |= replace_once(
        service,
        """                    zone_id=camera.zone_id,
                )
""",
        """                    zone_id=camera.zone_id,
                    line_x1=camera.line_x1,
                    line_y1=camera.line_y1,
                    line_x2=camera.line_x2,
                    line_y2=camera.line_y2,
                    in_side=camera.in_side,
                )
""",
    )

    changed |= replace_once(
        streaming,
        """        zone_id: Optional[str] = None,
    ) -> str:
""",
        """        zone_id: Optional[str] = None,
        line_x1: Optional[float] = None,
        line_y1: Optional[float] = None,
        line_x2: Optional[float] = None,
        line_y2: Optional[float] = None,
        in_side: str = "POSITIVE",
    ) -> str:
""",
    )

    changed |= replace_once(
        streaming,
        """                "zone_id": zone_id,
                "created_at": time.time(),
""",
        """                "zone_id": zone_id,
                "line_x1": line_x1,
                "line_y1": line_y1,
                "line_x2": line_x2,
                "line_y2": line_y2,
                "in_side": (in_side or "POSITIVE").upper(),
                "created_at": time.time(),
""",
    )

    # ------------------------------------------------------------------
    # Main app production security, stream context, object evidence route.
    # ------------------------------------------------------------------
    changed |= replace_once(
        main_py,
        """                            camera_name=camera.name,
                            company_id=camera.company_id
                        )
""",
        """                            camera_name=camera.name,
                            company_id=camera.company_id,
                            location=camera.location,
                            camera_role=camera.camera_role,
                            direction=camera.direction,
                            site_id=camera.site_id,
                            zone_id=camera.zone_id,
                            line_x1=camera.line_x1,
                            line_y1=camera.line_y1,
                            line_x2=camera.line_x2,
                            line_y2=camera.line_y2,
                            in_side=camera.in_side,
                        )
""",
    )

    changed |= replace_once(
        main_py,
        '@app.on_event("startup")\nasync def startup_event():\n    start_license_checker()\n',
        '@app.on_event("startup")\nasync def startup_event():\n    try:\n        from auth.bootstrap import bootstrap_admin_from_env\n        bootstrap_admin_from_env()\n    except Exception as exc:\n        logger.error(f"Admin bootstrap check failed: {exc}")\n\n    start_license_checker()\n',
    )

    changed |= replace_once(
        main_py,
        '    await ws_manager.connect(websocket, company_id)\n    try:\n',
        '    if not await ws_manager.connect(websocket, company_id):\n        return\n    try:\n',
    )

    changed |= replace_once(
        main_py,
        """app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins
    allow_credentials=True,
    allow_methods=["*"],  # Allows all methods
    allow_headers=["*"],  # Allows all headers
)
""",
        """allowed_origins = [value.strip() for value in os.getenv(
    "FRS_ALLOWED_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8005,http://127.0.0.1:8005"
).split(",") if value.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"],
    allow_headers=["Authorization", "Content-Type", "Accept"],
)
""",
    )

    changed |= replace_once(
        main_py,
        """        logger.info("✓ Event service mounted")
    except Exception as e:
""",
        """        logger.info("✓ Event service mounted")
        from storage.routes import router as storage_router
        app.include_router(storage_router, prefix="/api/storage", tags=["Evidence Storage"])
        logger.info("✓ Authenticated evidence storage service mounted")
    except Exception as e:
""",
    )

    changed |= replace_once(
        main_py,
        """    # Mount matching service
    try:
        from matching.one import app as matching_app
        app.mount("/api/matching", matching_app)
        logger.info("? Matching service mounted")
    except Exception as e:
        logger.error(f"✗ Failed to mount matching service: {e}")
""",
        """    # Legacy matching service is disabled by default because the database-backed
    # /api/events/match-face endpoint enforces tenant isolation without mutable global galleries.
    if os.getenv("FRS_ENABLE_LEGACY_MATCHING", "0").lower() in {"1", "true", "yes"}:
        try:
            from matching.one import app as matching_app
            app.mount("/api/matching", matching_app)
            logger.warning("Legacy matching service enabled explicitly")
        except Exception as e:
            logger.error(f"✗ Failed to mount legacy matching service: {e}")
""",
    )

    changed |= replace_once(
        main_py,
        """# Mount static files for gallery images and captured faces
app.mount("/static/gallery", StaticFiles(directory=GALLERY_DIR), name="gallery")
app.mount("/static/captured", StaticFiles(directory=CAPTURED_FACES_DIR), name="captured")
""",
        """# Public biometric static mounts are disabled by default. Authenticated API routes
# serve gallery/capture evidence; a development-only override is available when required.
if os.getenv("FRS_ENABLE_PUBLIC_BIOMETRIC_STATIC", "0").lower() in {"1", "true", "yes"}:
    app.mount("/static/gallery", StaticFiles(directory=GALLERY_DIR), name="gallery")
    app.mount("/static/captured", StaticFiles(directory=CAPTURED_FACES_DIR), name="captured")
""",
    )

    # Object-storage evidence is exposed through an authenticated proxy URL.
    changed |= replace_once(
        event_api,
        """def _image_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        absolute = Path(path)
""",
        """def _image_url(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    if str(path).startswith("s3://"):
        try:
            from storage.evidence_store import get_evidence_store
            return get_evidence_store().api_url(str(path))
        except Exception:
            return None
    try:
        absolute = Path(path)
""",
    )

    # Supervisor with no cameras sees no event/camera data; Admin sees its whole tenant.
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

    # Existing user-management release fixes.
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
    changed |= replace_once(user_management, "{availableMenus.map(menu => {", "{assignableMenus.map(menu => {")

    print("source fixes applied" if changed else "source fixes already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
