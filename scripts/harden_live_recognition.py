"""Apply conservative live-recognition hardening after the base production finalizer.

This script is intentionally idempotent and is executed by the release workflow. It
keeps large source edits deterministic while ensuring the committed production branch
contains the actual finalized code after validation.
"""
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
    pipeline = ROOT / "backend_face" / "face_pipeline.py"
    registration = ROOT / "backend_face" / "registration" / "reg.py"
    streaming = ROOT / "backend_face" / "camera_management" / "streaming.py"
    save_face = ROOT / "backend_face" / "save_face.py"
    vector_store = ROOT / "backend_face" / "recognition" / "vector_store.py"

    # ------------------------------------------------------------------
    # Safer defaults: far faces may be detected, but identity is withheld
    # unless the face is sufficiently large/clear and strongly separated.
    # ------------------------------------------------------------------
    for old, new in (
        ('DEFAULT_RECOGNITION_MIN_PX = int(os.getenv("FACE_RECOGNITION_MIN_PX", "56"))',
         'DEFAULT_RECOGNITION_MIN_PX = int(os.getenv("FACE_RECOGNITION_MIN_PX", "64"))'),
        ('DEFAULT_ATTENDANCE_MIN_PX = int(os.getenv("FACE_ATTENDANCE_MIN_PX", "72"))',
         'DEFAULT_ATTENDANCE_MIN_PX = int(os.getenv("FACE_ATTENDANCE_MIN_PX", "88"))'),
        ('DEFAULT_DISTANCE_THRESHOLD = float(os.getenv("FACE_MATCH_DISTANCE", "0.46"))',
         'DEFAULT_DISTANCE_THRESHOLD = float(os.getenv("FACE_MATCH_DISTANCE", "0.42"))'),
        ('DEFAULT_DISTANT_THRESHOLD = float(os.getenv("FACE_DISTANT_MATCH_DISTANCE", "0.42"))',
         'DEFAULT_DISTANT_THRESHOLD = float(os.getenv("FACE_DISTANT_MATCH_DISTANCE", "0.37"))'),
        ('DEFAULT_MATCH_MARGIN = float(os.getenv("FACE_MATCH_MARGIN", "0.04"))',
         'DEFAULT_MATCH_MARGIN = float(os.getenv("FACE_MATCH_MARGIN", "0.07"))'),
        ('DEFAULT_CONFIRM_FRAMES = int(os.getenv("FACE_CONFIRM_FRAMES", "3"))',
         'DEFAULT_CONFIRM_FRAMES = int(os.getenv("FACE_CONFIRM_FRAMES", "4"))'),
        ('DEFAULT_CONFIRM_WINDOW = int(os.getenv("FACE_CONFIRM_WINDOW", "5"))',
         'DEFAULT_CONFIRM_WINDOW = int(os.getenv("FACE_CONFIRM_WINDOW", "6"))'),
    ):
        changed |= replace_once(pipeline, old, new)

    changed |= replace_once(
        pipeline,
        '''def _dedupe_boxes(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted(items, key=lambda d: (float(d.get("det_conf") or 0), _box_size(d["bbox"])[0] * _box_size(d["bbox"])[1]), reverse=True)
    kept = []
    for item in ordered:
        if any(_iou(item["bbox"], other["bbox"]) >= 0.55 for other in kept):
            continue
        kept.append(item)
    return kept
''',
        '''def _dedupe_boxes(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    from recognition.detection_guard import dedupe_face_detections
    return dedupe_face_detections(items)
''',
    )

    changed |= replace_once(
        pipeline,
        '''def _thresholds(company_id: str, min_side: int) -> Tuple[float, float, int, int, float, float, int, int]:
    cfg = _settings(company_id)
    recognition_min = int(cfg.get("min_recognition_face_px", DEFAULT_RECOGNITION_MIN_PX))
    attendance_min = int(cfg.get("min_attendance_face_px", DEFAULT_ATTENDANCE_MIN_PX))
    base = float(cfg.get("known_distance_threshold", DEFAULT_DISTANCE_THRESHOLD))
    distant = float(cfg.get("distant_distance_threshold", DEFAULT_DISTANT_THRESHOLD))
    # Smaller faces must pass a LOWER distance (stricter), never a looser one.
    threshold = distant if min_side < 90 else base
    margin = float(cfg.get("match_margin", DEFAULT_MATCH_MARGIN))
    min_quality = float(cfg.get("min_quality", 0.18))
    attendance_quality = float(cfg.get("min_attendance_quality", 0.24))
    confirm = max(2, int(cfg.get("confirmation_frames", DEFAULT_CONFIRM_FRAMES)))
    window = max(confirm, int(cfg.get("confirmation_window", DEFAULT_CONFIRM_WINDOW)))
    return threshold, margin, recognition_min, attendance_min, min_quality, attendance_quality, confirm, window
''',
        '''def _thresholds(company_id: str, min_side: int) -> Tuple[float, float, int, int, float, float, int, int]:
    cfg = _settings(company_id)
    recognition_min = int(cfg.get("min_recognition_face_px", DEFAULT_RECOGNITION_MIN_PX))
    attendance_min = int(cfg.get("min_attendance_face_px", DEFAULT_ATTENDANCE_MIN_PX))
    base = float(cfg.get("known_distance_threshold", DEFAULT_DISTANCE_THRESHOLD))
    distant = float(cfg.get("distant_distance_threshold", DEFAULT_DISTANT_THRESHOLD))
    threshold = distant if min_side < 96 else base
    base_margin = float(cfg.get("match_margin", DEFAULT_MATCH_MARGIN))
    margin = max(base_margin, 0.10) if min_side < 96 else base_margin
    configured_quality = float(cfg.get("min_quality", 0.24))
    min_quality = max(configured_quality, 0.30) if min_side < 96 else configured_quality
    attendance_quality = max(float(cfg.get("min_attendance_quality", 0.32)), 0.32)
    confirm = max(3, int(cfg.get("confirmation_frames", DEFAULT_CONFIRM_FRAMES)))
    if min_side < 96:
        confirm = max(confirm, 5)
    window = max(confirm + 1, int(cfg.get("confirmation_window", DEFAULT_CONFIRM_WINDOW)))
    return threshold, margin, recognition_min, attendance_min, min_quality, attendance_quality, confirm, window
''',
    )

    old_dlib = '''    threshold, required_margin, *_ = _thresholds(company_id, min_side)
    indices = bank.get("person_indices") or {}
    best_result = None
    for embedding in embeddings:
        if matrix.shape[1] != embedding.shape[0]:
            continue
        distances = np.linalg.norm(matrix - embedding.reshape(1, -1), axis=1)
        people = []
        for person, idx in indices.items():
            person_distances = np.sort(distances[idx])
            if person_distances.size == 0:
                continue
            minimum = float(person_distances[0])
            hits = int(np.sum(person_distances <= threshold))
            top_count = min(2, person_distances.size)
            score_distance = float(np.mean(person_distances[:top_count]))
            people.append((score_distance, minimum, person, hits, int(person_distances.size)))
        if not people:
            continue
        people.sort(key=lambda x: (x[0], x[1]))
        score_distance, minimum, person, hits, template_count = people[0]
        second_score = people[1][0] if len(people) > 1 else 1.0
        margin = float(second_score - score_distance)

        required_hits = 2 if template_count >= 3 else 1
        # A person with only one enrollment template receives an extra strict penalty.
        effective_threshold = threshold - 0.02 if template_count == 1 else threshold
        accepted = minimum <= effective_threshold and hits >= required_hits and (len(people) == 1 or margin >= required_margin)
        result = {
            "name": person if accepted else None,
            "distance": minimum,
            "score_distance": score_distance,
            "confidence": float(np.clip(1.0 - minimum, 0.0, 1.0)),
            "embedding": embedding,
            "margin": margin,
            "hits": hits,
            "threshold": effective_threshold,
        }
        if accepted and (best_result is None or minimum < best_result["distance"]):
            best_result = result
        elif best_result is None:
            best_result = result
    return best_result or {"name": None, "distance": None, "confidence": 0.0, "embedding": embeddings[0] if embeddings else None, "margin": 0.0, "hits": 0}
'''
    new_dlib = '''    threshold, required_margin, *_ = _thresholds(company_id, min_side)
    from recognition.identity_guard import conservative_dlib_match
    return conservative_dlib_match(
        embeddings,
        matrix,
        bank.get("person_indices") or {},
        threshold,
        required_margin,
    )
'''
    changed |= replace_once(pipeline, old_dlib, new_dlib)

    old_update = '''def _update_identity(track: Dict[str, Any], match: Dict[str, Any], quality: float, company_id: str, min_side: int) -> None:
    threshold, margin_req, _, _, min_quality, _, confirm_frames, window = _thresholds(company_id, min_side)
    history: deque = track["history"]
    # Resize history if tenant settings changed.
    if history.maxlen != window:
        history = deque(list(history)[-window:], maxlen=window)
        track["history"] = history

    candidate = match.get("name") if quality >= min_quality else None
    history.append(candidate)
    confirmed = track.get("confirmed_name")

    if confirmed:
        if candidate and candidate != confirmed and match.get("distance") is not None and match.get("margin", 0) >= margin_req:
            track["conflict_streak"] = int(track.get("conflict_streak", 0)) + 1
        elif candidate == confirmed:
            track["conflict_streak"] = 0
        # Revoke a label after two strong contradictory observations. This prevents
        # a tracker ID swap in a crowd from carrying the previous person's name.
        if track.get("conflict_streak", 0) >= 2:
            track["confirmed_name"] = None
            track["confirmed_at"] = None
            track["history"].clear()
            track["history"].append(candidate)
            track["conflict_streak"] = 0
        return

    counts = Counter(name for name in history if name)
    if not counts:
        return
    name, count = counts.most_common(1)[0]
    if count >= confirm_frames:
        # Competing identities inside the confirmation window make the track ambiguous.
        competitors = sum(v for k, v in counts.items() if k != name)
        if competitors <= 1:
            track["confirmed_name"] = name
            track["confirmed_at"] = time.time()
            track["conflict_streak"] = 0
'''
    new_update = '''def _update_identity(track: Dict[str, Any], match: Dict[str, Any], quality: float, company_id: str, min_side: int) -> None:
    _, _, recognition_min, _, min_quality, _, confirm_frames, window = _thresholds(company_id, min_side)
    from recognition.identity_guard import update_track_identity
    update_track_identity(
        track,
        match,
        quality=quality,
        min_quality=min_quality,
        confirm_frames=confirm_frames,
        window=window,
        min_side=min_side,
        recognition_min=recognition_min,
    )
'''
    changed |= replace_once(pipeline, old_update, new_update)

    changed |= replace_once(
        pipeline,
        '''    # One physical identity may appear at most once in one frame. If two distinct
    # boxes resolve to the same employee, only the strongest observation keeps the
    # identity; the other remains Unknown until subsequent frames disambiguate it.
''',
        '''    # Final duplicate suppression: raw detector NMS is repeated after tracking so
    # one physical face can never render or persist two overlapping result boxes.
    from recognition.detection_guard import suppress_overlapping_results
    results = suppress_overlapping_results(results)

    # One physical identity may appear at most once in one frame. If two distinct
    # boxes resolve to the same employee, only the strongest observation keeps the
    # identity; the other remains Unknown until subsequent frames disambiguate it.
''',
    )

    # ------------------------------------------------------------------
    # Best-evidence selection: prefer native face pixels and focus, not an
    # arbitrary current frame. This improves long-distance review captures.
    # ------------------------------------------------------------------
    changed |= replace_once(
        streaming,
        '''        item = {
            "crop": crop,
            "bbox": tuple(bbox),
            "score": self._focus_score(crop),
            "timestamp": time.time(),
        }
''',
        '''        try:
            from recognition.evidence_quality import evidence_score
            best_score = evidence_score(crop, tuple(bbox))
        except Exception:
            best_score = self._focus_score(crop)
        item = {
            "crop": crop,
            "bbox": tuple(bbox),
            "score": best_score,
            "timestamp": time.time(),
        }
''',
    )

    changed |= replace_once(
        save_face,
        'def _prepare_crop(face_crop_bgr: np.ndarray, target_width: int = 320, max_upscale: float = 4.0) -> np.ndarray:',
        'def _prepare_crop(face_crop_bgr: np.ndarray, target_width: int = 384, max_upscale: float = 3.0) -> np.ndarray:',
    )
    changed |= replace_once(
        save_face,
        '''    try:
        lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
        l, a, b = cv2.split(lab)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        image = cv2.cvtColor(cv2.merge([clahe.apply(l), a, b]), cv2.COLOR_LAB2BGR)
    except Exception:
        pass
    return image
''',
        '''    try:
        from recognition.evidence_quality import enhance_for_review
        image = enhance_for_review(image)
    except Exception:
        pass
    return image
''',
    )
    for old, new in (
        ('MIN_KNOWN_SAVE_CONFIDENCE = float(os.getenv("FACE_MIN_KNOWN_SAVE_CONFIDENCE", "0.50"))',
         'MIN_KNOWN_SAVE_CONFIDENCE = float(os.getenv("FACE_MIN_KNOWN_SAVE_CONFIDENCE", "0.55"))'),
        ('    target_width: Optional[int] = 320,', '    target_width: Optional[int] = 384,'),
        ('    max_upscale: float = 4.0,', '    max_upscale: float = 3.0,'),
        ('    jpeg_quality: int = 94,', '    jpeg_quality: int = 96,'),
    ):
        changed |= replace_once(save_face, old, new)

    # ------------------------------------------------------------------
    # Enrollment: fewer synthetic variants, stronger native-image quality,
    # and a wider cross-person collision rejection band.
    # ------------------------------------------------------------------
    for old, new in (
        ('DUPLICATE_DISTANCE = float(os.getenv("FRS_DUPLICATE_FACE_DISTANCE", "0.40"))',
         'DUPLICATE_DISTANCE = float(os.getenv("FRS_DUPLICATE_FACE_DISTANCE", "0.44"))'),
        ('MIN_ENROLL_FACE_PX = int(os.getenv("FRS_MIN_ENROLL_FACE_PX", "100"))',
         'MIN_ENROLL_FACE_PX = int(os.getenv("FRS_MIN_ENROLL_FACE_PX", "120"))'),
    ):
        changed |= replace_once(registration, old, new)

    changed |= replace_once(
        registration,
        '''    candidates: List[Tuple[str, np.ndarray]] = [
        ("original", face),
        ("rot_m8", _rotate(face, -8)),
        ("rot_m4", _rotate(face, -4)),
        ("rot_p4", _rotate(face, 4)),
        ("rot_p8", _rotate(face, 8)),
        ("dim", _adjust(face, 0.86, -4)),
        ("bright", _adjust(face, 1.12, 5)),
        ("contrast_low", _adjust(face, 0.92, 8)),
        ("contrast_high", _adjust(face, 1.10, -6)),
        ("clahe", _clahe(face)),
    ]
''',
        '''    candidates: List[Tuple[str, np.ndarray]] = [
        ("original", face),
        ("rot_m4", _rotate(face, -4)),
        ("rot_p4", _rotate(face, 4)),
        ("dim", _adjust(face, 0.90, -2)),
        ("bright", _adjust(face, 1.08, 3)),
        ("clahe", _clahe(face)),
    ]
''',
    )

    changed |= replace_once(
        registration,
        '''            seen_embeddings.append(embedding)
            quality = _face_quality(variant)
            prepared.append((f"real{real_index:02d}_{aug_name}", variant, embedding, quality))
''',
        '''            quality = _face_quality(variant)
            if quality < 0.28 and aug_name != "original":
                continue
            seen_embeddings.append(embedding)
            prepared.append((f"real{real_index:02d}_{aug_name}", variant, embedding, quality))
''',
    )

    changed |= replace_once(
        registration,
        '''    faces = [_detect_standardized_face(image) for image in images]
    base_embedding = encode_face_image(faces[0], num_jitters=3)
''',
        '''    faces = [_detect_standardized_face(image) for image in images]
    face_qualities = [_face_quality(face) for face in faces]
    if max(face_qualities or [0.0]) < 0.34:
        raise ValueError("Enrollment face quality is too low. Use a sharper, better-lit and closer image.")
    base_embedding = encode_face_image(faces[int(np.argmax(face_qualities))], num_jitters=3)
''',
    )

    # ------------------------------------------------------------------
    # ArcFace: the top person must have multiple qualifying templates and
    # stronger separation from the runner-up, especially at distance.
    # ------------------------------------------------------------------
    for old, new in (
        ('base_threshold = float(os.getenv("FRS_ARCFACE_COSINE_THRESHOLD", "0.55"))',
         'base_threshold = float(os.getenv("FRS_ARCFACE_COSINE_THRESHOLD", "0.62"))'),
        ('distant_threshold = float(os.getenv("FRS_ARCFACE_DISTANT_COSINE_THRESHOLD", "0.60"))',
         'distant_threshold = float(os.getenv("FRS_ARCFACE_DISTANT_COSINE_THRESHOLD", "0.68"))'),
        ('required_margin = float(os.getenv("FRS_ARCFACE_MARGIN", "0.08"))',
         'required_margin = float(os.getenv("FRS_ARCFACE_MARGIN", "0.10"))'),
    ):
        changed |= replace_once(vector_store, old, new)

    changed |= replace_once(
        vector_store,
        '''        ranked = sorted(
            ((max(values), float(np.mean(sorted(values, reverse=True)[:2])), person, len(values))
             for person, values in per_person.items()),
            reverse=True,
        )
        best_similarity, score_similarity, person, hits = ranked[0]
        second_similarity = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = float(score_similarity - second_similarity)
        accepted = best_similarity >= threshold and (len(ranked) == 1 or margin >= required_margin)
''',
        '''        ranked = sorted(
            ((max(values), float(np.mean(sorted(values, reverse=True)[:2])), person,
              int(sum(value >= threshold for value in values)), len(values))
             for person, values in per_person.items()),
            reverse=True,
        )
        best_similarity, score_similarity, person, hits, template_count = ranked[0]
        second_similarity = ranked[1][1] if len(ranked) > 1 else 0.0
        margin = float(score_similarity - second_similarity)
        required_hits = 1 if template_count == 1 else 2
        effective_threshold = threshold + (0.04 if template_count == 1 else 0.0)
        accepted = bool(
            best_similarity >= effective_threshold
            and score_similarity >= effective_threshold - 0.02
            and hits >= required_hits
            and (len(ranked) == 1 or margin >= required_margin)
        )
''',
    )
    changed |= replace_once(
        vector_store,
        '            "threshold": threshold,\n',
        '            "threshold": effective_threshold,\n',
    )

    print("live recognition hardening applied" if changed else "live recognition hardening already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
