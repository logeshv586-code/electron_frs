from __future__ import annotations

import os
import time
from collections import Counter, deque
from typing import Any, Dict, List, Optional

import numpy as np


def conservative_dlib_match(
    embeddings: List[np.ndarray],
    matrix: np.ndarray,
    person_indices: Dict[str, np.ndarray],
    threshold: float,
    required_margin: float,
) -> Dict[str, Any]:
    """Return a match only when multiple pieces of evidence agree.

    One unusually close synthetic template is not sufficient. The winning person must
    have a strong minimum distance, a strong robust top-template score, enough template
    hits, and clear separation from the second-best person.
    """
    if not embeddings or matrix is None or matrix.size == 0 or not person_indices:
        return {"name": None, "distance": None, "confidence": 0.0, "embedding": embeddings[0] if embeddings else None, "margin": 0.0, "hits": 0}

    best_result: Optional[Dict[str, Any]] = None
    robust_slack = float(os.getenv("FACE_ROBUST_DISTANCE_SLACK", "0.008"))
    minimum_margin_ratio = float(os.getenv("FACE_MINIMUM_MARGIN_RATIO", "0.55"))

    for embedding in embeddings:
        vector = np.asarray(embedding, dtype=np.float64).reshape(-1)
        if matrix.ndim != 2 or matrix.shape[1] != vector.size:
            continue
        distances = np.linalg.norm(matrix - vector.reshape(1, -1), axis=1)
        people = []
        for person, indices in person_indices.items():
            person_distances = np.sort(distances[indices])
            if person_distances.size == 0:
                continue
            minimum = float(person_distances[0])
            top_count = min(3, int(person_distances.size))
            robust = float(np.mean(person_distances[:top_count]))
            hits = int(np.sum(person_distances <= threshold))
            template_count = int(person_distances.size)
            people.append((robust, minimum, person, hits, template_count))
        if not people:
            continue

        people.sort(key=lambda value: (value[0], value[1]))
        robust, minimum, person, hits, template_count = people[0]
        second_robust = people[1][0] if len(people) > 1 else 1.0
        second_minimum = people[1][1] if len(people) > 1 else 1.0
        robust_margin = float(second_robust - robust)
        minimum_margin = float(second_minimum - minimum)

        required_hits = 1 if template_count == 1 else 2
        effective_threshold = threshold - (0.025 if template_count == 1 else 0.0)
        accepted = bool(
            minimum <= effective_threshold
            and robust <= effective_threshold + robust_slack
            and hits >= required_hits
            and (
                len(people) == 1
                or (
                    robust_margin >= required_margin
                    and minimum_margin >= required_margin * minimum_margin_ratio
                )
            )
        )
        result = {
            "name": person if accepted else None,
            "distance": minimum,
            "score_distance": robust,
            "confidence": float(np.clip(1.0 - robust, 0.0, 1.0)),
            "embedding": vector,
            "margin": robust_margin,
            "minimum_margin": minimum_margin,
            "hits": hits,
            "threshold": effective_threshold,
            "model_version": "dlib-128-consensus-v3",
        }
        if accepted and (best_result is None or robust < float(best_result.get("score_distance") or 9.0)):
            best_result = result
        elif best_result is None:
            best_result = result

    return best_result or {"name": None, "distance": None, "confidence": 0.0, "embedding": embeddings[0] if embeddings else None, "margin": 0.0, "hits": 0}


def _blend_anchor(track: Dict[str, Any], embedding: Any) -> None:
    if embedding is None:
        return
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    if vector.size not in {128, 512} or not np.all(np.isfinite(vector)):
        return
    current = track.get("identity_anchor")
    if isinstance(current, np.ndarray) and current.size == vector.size:
        if vector.size == 512:
            current = current / max(float(np.linalg.norm(current)), 1e-8)
            vector = vector / max(float(np.linalg.norm(vector)), 1e-8)
        mixed = current * 0.80 + vector * 0.20
        if vector.size == 512:
            mixed = mixed / max(float(np.linalg.norm(mixed)), 1e-8)
        track["identity_anchor"] = mixed.astype(np.float32)
    else:
        if vector.size == 512:
            vector = vector / max(float(np.linalg.norm(vector)), 1e-8)
        track["identity_anchor"] = vector.astype(np.float32)


def _anchor_agrees(track: Dict[str, Any], embedding: Any) -> bool:
    anchor = track.get("identity_anchor")
    if not isinstance(anchor, np.ndarray) or embedding is None:
        return True
    vector = np.asarray(embedding, dtype=np.float32).reshape(-1)
    if anchor.size != vector.size:
        return False
    if vector.size == 512:
        a = anchor / max(float(np.linalg.norm(anchor)), 1e-8)
        b = vector / max(float(np.linalg.norm(vector)), 1e-8)
        minimum = float(os.getenv("FACE_TRACK_ARCFACE_ANCHOR_SIMILARITY", "0.68"))
        return float(np.dot(a, b)) >= minimum
    maximum = float(os.getenv("FACE_TRACK_DLIB_ANCHOR_DISTANCE", "0.40"))
    return float(np.linalg.norm(anchor.astype(np.float64) - vector.astype(np.float64))) <= maximum


def update_track_identity(
    track: Dict[str, Any],
    match: Dict[str, Any],
    *,
    quality: float,
    min_quality: float,
    confirm_frames: int,
    window: int,
    min_side: int,
    recognition_min: int,
) -> None:
    """Update identity without permitting same-track person switching.

    Once a track is confirmed as one employee, contradictory evidence can revoke the
    visible label to Unknown, but the same tracker ID is never reassigned to a different
    employee. A new person must obtain a new track and pass confirmation independently.
    """
    history = track.get("history")
    if not isinstance(history, deque) or history.maxlen != window:
        previous = list(history) if isinstance(history, deque) else []
        history = deque(previous[-window:], maxlen=window)
        track["history"] = history

    if min_side < recognition_min or quality < min_quality:
        history.append(None)
        return

    candidate = match.get("name")
    embedding = match.get("embedding")
    confirmed = track.get("confirmed_name")
    locked = track.get("identity_lock")

    if track.get("identity_blocked"):
        history.append(None)
        return

    if confirmed:
        if candidate == confirmed and _anchor_agrees(track, embedding):
            track["conflict_streak"] = 0
            track["last_good_identity_at"] = time.time()
            _blend_anchor(track, embedding)
            history.append(confirmed)
            return
        if candidate and candidate != confirmed:
            track["conflict_streak"] = int(track.get("conflict_streak") or 0) + 1
        elif candidate == confirmed and not _anchor_agrees(track, embedding):
            track["conflict_streak"] = int(track.get("conflict_streak") or 0) + 1
        else:
            # A weak/unknown frame should not make a stable identity flicker.
            history.append(None)
            return

        if int(track.get("conflict_streak") or 0) >= 2:
            track["identity_lock"] = confirmed
            track["confirmed_name"] = None
            track["confirmed_at"] = None
            track["identity_blocked"] = True
            history.clear()
        return

    # A revoked track never becomes another employee. The tracker must age out first.
    if locked and candidate != locked:
        history.append(None)
        return

    history.append(candidate)
    counts = Counter(value for value in history if value)
    if not counts:
        return
    name, count = counts.most_common(1)[0]
    competitors = sum(value for key, value in counts.items() if key != name)
    recent = [value for value in list(history)[-2:] if value]
    if count >= confirm_frames and competitors == 0 and len(recent) >= 2 and all(value == name for value in recent):
        track["confirmed_name"] = name
        track["confirmed_at"] = time.time()
        track["identity_lock"] = name
        track["identity_blocked"] = False
        track["conflict_streak"] = 0
        track["last_good_identity_at"] = time.time()
        _blend_anchor(track, embedding)
