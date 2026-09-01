"""Finalize detector confidence and evidence deduplication rules."""
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
    pipeline = ROOT / "backend_face" / "face_pipeline.py"
    changed = False

    changed |= replace_once(
        pipeline,
        'DETECTION_MIN_FACE_PX = int(os.getenv("FACE_DETECTION_MIN_PX", "20"))\n',
        'DETECTION_MIN_FACE_PX = int(os.getenv("FACE_DETECTION_MIN_PX", "20"))\nDETECTION_MIN_CONFIDENCE = float(os.getenv("FACE_DETECTION_CONFIDENCE", "0.55"))\n',
    )

    changed |= replace_once(
        pipeline,
        '''        kps = getattr(face, "kps", None)
        raw.append({
            "bbox": (x1, y1, x2, y2),
            "det_conf": float(getattr(face, "det_score", 0.0) or getattr(face, "score", 0.0) or 0.0),
            "kps": np.asarray(kps, dtype=np.float32).reshape(-1, 2).tolist() if kps is not None else None,
        })
''',
        '''        det_conf = float(getattr(face, "det_score", 0.0) or getattr(face, "score", 0.0) or 0.0)
        if det_conf < DETECTION_MIN_CONFIDENCE:
            continue
        kps = getattr(face, "kps", None)
        raw.append({
            "bbox": (x1, y1, x2, y2),
            "det_conf": det_conf,
            "kps": np.asarray(kps, dtype=np.float32).reshape(-1, 2).tolist() if kps is not None else None,
        })
''',
    )

    changed |= replace_once(
        pipeline,
        '''    crop, _ = _crop(frame, bbox, 0.35)
    return crop


def process_frame(
''',
        '''    crop, _ = _crop(frame, bbox, 0.35)
    return crop


def _camera_name_for_stream(stream_id: Optional[str]) -> Optional[str]:
    if not stream_id:
        return stream_id
    try:
        from camera_management.streaming import get_stream_manager
        info = get_stream_manager().get_stream_info(stream_id) or {}
        return info.get("camera_name") or stream_id
    except Exception:
        return stream_id


def process_frame(
''',
    )

    changed |= replace_once(
        pipeline,
        '''                        min_interval=0,
                        source="stream",
                        camera_name=stream_id,
                        company_id=company_id,
                        identity_key=f"{item['name']}:{track_id}",
''',
        '''                        min_interval=KNOWN_IMAGE_INTERVAL_SECONDS,
                        source="stream",
                        camera_name=_camera_name_for_stream(stream_id),
                        company_id=company_id,
                        identity_key=item["name"],
''',
    )

    changed |= replace_once(
        pipeline,
        '''                            min_interval=0,
                            source="stream",
                            camera_name=camera_name,
                            company_id=company_id,
                            identity_key=f"unknown:{track_id}",
                            unknown_cluster_id=cluster_key,
''',
        '''                            min_interval=UNKNOWN_IMAGE_INTERVAL_SECONDS,
                            source="stream",
                            camera_name=camera_name,
                            company_id=company_id,
                            identity_key=cluster_key,
                            unknown_cluster_id=cluster_key,
''',
    )

    print("gallery evidence hardening applied" if changed else "gallery evidence hardening already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
