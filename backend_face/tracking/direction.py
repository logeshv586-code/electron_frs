from __future__ import annotations

from typing import Dict, Optional, Tuple


def _center(bbox: Tuple[int, int, int, int]) -> Tuple[float, float]:
    x1, y1, x2, y2 = bbox
    return (float(x1 + x2) / 2.0, float(y1 + y2) / 2.0)


def _line_points(info: Dict, frame_shape: Tuple[int, ...]) -> Optional[Tuple[Tuple[float, float], Tuple[float, float]]]:
    try:
        values = [
            float(info.get("line_x1")), float(info.get("line_y1")),
            float(info.get("line_x2")), float(info.get("line_y2")),
        ]
    except (TypeError, ValueError):
        return None
    if not all(0.0 <= value <= 1.0 for value in values):
        return None
    h, w = frame_shape[:2]
    x1, y1, x2, y2 = values
    return ((x1 * w, y1 * h), (x2 * w, y2 * h))


def has_virtual_line(info: Dict) -> bool:
    try:
        values = [float(info.get(key)) for key in ("line_x1", "line_y1", "line_x2", "line_y2")]
    except (TypeError, ValueError):
        return False
    return all(0.0 <= value <= 1.0 for value in values) and (values[0], values[1]) != (values[2], values[3])


def _side(point: Tuple[float, float], p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
    return (p2[0] - p1[0]) * (point[1] - p1[1]) - (p2[1] - p1[1]) * (point[0] - p1[0])


def update_track_direction(
    track: Dict,
    bbox: Tuple[int, int, int, int],
    frame_shape: Tuple[int, ...],
    camera_info: Dict,
) -> str:
    role = str(camera_info.get("camera_role") or "BIDIRECTIONAL").upper()
    configured = str(camera_info.get("direction") or "AUTO").upper()
    if role == "REFERENCE_ONLY":
        return "NONE"
    if role == "ENTRY":
        return "IN"
    if role == "EXIT":
        return "OUT"
    if configured in {"IN", "OUT"}:
        return configured

    line = _line_points(camera_info, frame_shape)
    if line is None:
        return "AUTO"
    p1, p2 = line
    center = _center(bbox)
    current_value = _side(center, p1, p2)
    epsilon = max(frame_shape[0], frame_shape[1]) * 0.002
    current_side = 1 if current_value > epsilon else (-1 if current_value < -epsilon else 0)
    previous_side = int(track.get("virtual_line_side") or 0)
    if current_side:
        track["virtual_line_side"] = current_side
    track["virtual_line_center"] = center

    if previous_side == 0 or current_side == 0 or previous_side == current_side:
        return "AUTO"

    in_side = str(camera_info.get("in_side") or "POSITIVE").upper()
    in_value = 1 if in_side != "NEGATIVE" else -1
    crossing = "IN" if current_side == in_value else "OUT"
    track["last_crossing_direction"] = crossing
    track["last_crossing_center"] = center
    return crossing
