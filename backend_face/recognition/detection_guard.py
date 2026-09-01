from __future__ import annotations

import os
from typing import Any, Dict, List, Tuple


def _area(box: Tuple[int, int, int, int]) -> float:
    x1, y1, x2, y2 = box
    return float(max(0, x2 - x1) * max(0, y2 - y1))


def _intersection(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    return float(max(0, x2 - x1) * max(0, y2 - y1))


def _iou(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    inter = _intersection(a, b)
    if inter <= 0:
        return 0.0
    union = max(_area(a) + _area(b) - inter, 1.0)
    return inter / union


def _containment(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> float:
    inter = _intersection(a, b)
    smaller = max(min(_area(a), _area(b)), 1.0)
    return inter / smaller


def _center(box: Tuple[int, int, int, int]) -> Tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _center_inside(inner: Tuple[int, int, int, int], outer: Tuple[int, int, int, int]) -> bool:
    cx, cy = _center(inner)
    return outer[0] <= cx <= outer[2] and outer[1] <= cy <= outer[3]


def same_physical_face(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> bool:
    """Conservative duplicate test for detector boxes around one physical face.

    Crowd boxes are allowed to overlap. A box is suppressed only when IoU is high, or
    when most of the smaller box is contained inside the other and their centers agree.
    """
    iou_limit = float(os.getenv("FACE_NMS_IOU", "0.38"))
    containment_limit = float(os.getenv("FACE_NMS_CONTAINMENT", "0.72"))
    if _iou(a, b) >= iou_limit:
        return True
    containment = _containment(a, b)
    return containment >= containment_limit and (_center_inside(a, b) or _center_inside(b, a))


def _detection_rank(item: Dict[str, Any]) -> Tuple[float, float]:
    box = tuple(item.get("bbox") or (0, 0, 0, 0))
    return (float(item.get("det_conf") or 0.0), _area(box))


def dedupe_face_detections(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted(items, key=_detection_rank, reverse=True)
    kept: List[Dict[str, Any]] = []
    for item in ordered:
        box = tuple(item.get("bbox") or (0, 0, 0, 0))
        if any(same_physical_face(box, tuple(other.get("bbox") or (0, 0, 0, 0))) for other in kept):
            continue
        kept.append(item)
    # Keep detector spatial order stable for downstream tracking/UI.
    return sorted(kept, key=lambda item: (item["bbox"][0], item["bbox"][1]))


def suppress_overlapping_results(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Second safety net after tracking/recognition: one result box per physical face."""
    def rank(item: Dict[str, Any]) -> Tuple[int, int, float, float, float]:
        return (
            1 if item.get("current_match_is_confirmed") else 0,
            1 if item.get("name") not in {None, "Unknown"} else 0,
            float(item.get("quality") or 0.0),
            float(item.get("det_conf") or 0.0),
            _area(tuple(item.get("bbox") or (0, 0, 0, 0))),
        )

    kept: List[Dict[str, Any]] = []
    for item in sorted(items, key=rank, reverse=True):
        box = tuple(item.get("bbox") or (0, 0, 0, 0))
        if any(same_physical_face(box, tuple(other.get("bbox") or (0, 0, 0, 0))) for other in kept):
            item["duplicate_box_suppressed"] = True
            continue
        kept.append(item)
    return sorted(kept, key=lambda item: (item["bbox"][0], item["bbox"][1]))
