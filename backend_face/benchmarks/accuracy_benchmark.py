from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np


def _active_probe_embedding(image: np.ndarray) -> Tuple[Optional[np.ndarray], str]:
    from recognition.arcface import get_arcface_engine
    arcface = get_arcface_engine()
    if arcface.available:
        h, w = image.shape[:2]
        vector = arcface.embed_frame(image, (0, 0, w, h), None)
        return vector, arcface.model_version
    from fr1 import encode_face_image
    return encode_face_image(image, num_jitters=1), "dlib-128"


def _match(company_id: str, embedding: np.ndarray, model: str) -> Tuple[Optional[str], float]:
    if embedding is None:
        return None, 0.0
    if embedding.size == 512:
        from recognition.vector_store import match_arcface_embeddings
        result = match_arcface_embeddings([embedding], company_id, min_side=160)
        return result.get("name"), float(result.get("confidence") or 0.0)

    from db.repository import load_face_templates
    matrix, names, _ = load_face_templates(company_id)
    if matrix.shape[0] == 0 or matrix.shape[1] != embedding.size:
        return None, 0.0
    distances = np.linalg.norm(matrix - embedding.reshape(1, -1), axis=1)
    index = int(np.argmin(distances))
    distance = float(distances[index])
    threshold = float(os.getenv("FACE_MATCH_DISTANCE", "0.46"))
    return (names[index] if distance <= threshold else None), max(0.0, 1.0 - distance)


def run_manifest(manifest_path: Path) -> Dict[str, object]:
    rows: List[Dict[str, str]] = []
    with manifest_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"company_id", "image_path", "expected_identity"}
        if not required.issubset(set(reader.fieldnames or [])):
            raise ValueError(f"Manifest requires columns: {sorted(required)}")
        rows = [dict(row) for row in reader]

    latencies: List[float] = []
    total = correct = false_accepts = false_rejects = cross_tenant = unknown_total = unknown_correct = 0
    details = []
    manifest_root = manifest_path.parent

    for row in rows:
        company_id = (row.get("company_id") or "default").strip()
        expected = (row.get("expected_identity") or "unknown").strip()
        image_path = Path(row["image_path"])
        if not image_path.is_absolute():
            image_path = (manifest_root / image_path).resolve()
        image = cv2.imread(str(image_path))
        if image is None:
            details.append({"image": str(image_path), "error": "unreadable"})
            continue
        started = time.perf_counter()
        embedding, model = _active_probe_embedding(image)
        predicted, confidence = _match(company_id, embedding, model) if embedding is not None else (None, 0.0)
        latencies.append((time.perf_counter() - started) * 1000.0)
        total += 1
        expected_unknown = expected.lower() in {"unknown", "none", "-", ""}
        if expected_unknown:
            unknown_total += 1
            if predicted is None:
                unknown_correct += 1
                correct += 1
            else:
                false_accepts += 1
        elif predicted == expected:
            correct += 1
        elif predicted is None:
            false_rejects += 1
        else:
            false_accepts += 1

        # Optional negative tenant probe. If the same image resolves inside a different
        # tenant, flag a cross-tenant isolation failure.
        negative_tenant = (row.get("negative_tenant") or "").strip()
        if negative_tenant and embedding is not None:
            negative_name, _ = _match(negative_tenant, embedding, model)
            if negative_name is not None:
                cross_tenant += 1

        details.append({
            "image": str(image_path), "company_id": company_id, "expected": expected,
            "predicted": predicted, "confidence": confidence, "model": model,
        })

    denominator = max(total, 1)
    known_total = max(total - unknown_total, 1)
    metrics = {
        "samples": total,
        "accuracy": correct / denominator,
        "false_accept_rate": false_accepts / denominator,
        "false_reject_rate": false_rejects / known_total,
        "unknown_accuracy": unknown_correct / max(unknown_total, 1),
        "cross_tenant_matches": cross_tenant,
        "latency_ms_mean": statistics.mean(latencies) if latencies else None,
        "latency_ms_p95": float(np.percentile(latencies, 95)) if latencies else None,
        "details": details,
    }
    return metrics


def certification_pass(metrics: Dict[str, object]) -> Tuple[bool, List[str]]:
    failures = []
    if float(metrics.get("false_accept_rate") or 0.0) > float(os.getenv("FRS_BENCHMARK_MAX_FAR", "0.001")):
        failures.append("false_accept_rate")
    if float(metrics.get("false_reject_rate") or 0.0) > float(os.getenv("FRS_BENCHMARK_MAX_FRR", "0.08")):
        failures.append("false_reject_rate")
    if int(metrics.get("cross_tenant_matches") or 0) != 0:
        failures.append("cross_tenant_matches")
    if int(metrics.get("samples") or 0) < int(os.getenv("FRS_BENCHMARK_MIN_SAMPLES", "100")):
        failures.append("minimum_samples")
    return not failures, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the production FRS identity benchmark manifest")
    parser.add_argument("manifest", type=Path, help="CSV with company_id,image_path,expected_identity[,negative_tenant]")
    parser.add_argument("--output", type=Path, default=Path("frs-benchmark-result.json"))
    parser.add_argument("--certify", action="store_true", help="Exit non-zero unless production thresholds pass")
    args = parser.parse_args()
    metrics = run_manifest(args.manifest)
    passed, failures = certification_pass(metrics)
    payload = {"certified": passed, "failures": failures, **metrics}
    args.output.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    print(json.dumps({key: value for key, value in payload.items() if key != "details"}, indent=2))
    return 1 if args.certify and not passed else 0


if __name__ == "__main__":
    raise SystemExit(main())
