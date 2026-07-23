from typing import Any, Dict, List, Optional


def compute_shot_diversity(point_events: list) -> Dict[str, Any]:
    """Compute shot diversity statistics or return unavailable-with-warning.

    Returns ``available=False`` when >80% of points lack annotations.
    """
    if not point_events:
        return {"available": False, "warning": "No point events available."}

    annotated = 0
    shot_types: List[str] = []
    placements: List[str] = []
    end_reasons: List[str] = []

    for ev in point_events:
        if hasattr(ev, "shot_type"):
            st = ev.shot_type
            pl = ev.placement
            er = ev.end_reason
        else:
            st = ev.get("shot_type")
            pl = ev.get("placement")
            er = ev.get("end_reason")

        if st:
            shot_types.append(st)
            annotated += 1
        if pl:
            placements.append(pl)
            annotated += 1
        if er:
            end_reasons.append(er)
            annotated += 1

    total_checks = len(point_events) * 3
    if total_checks == 0:
        return {"available": False, "warning": "No point events available."}

    annotation_ratio = annotated / total_checks
    if annotation_ratio < 0.2:
        return {
            "available": False,
            "warning": "Shot diversity requires point annotations.",
            "annotation_ratio": annotation_ratio,
        }

    entropy = _normalized_entropy(shot_types or placements or end_reasons)
    unique_shots = len(set(shot_types))
    unique_placements = len(set(placements))

    return {
        "available": True,
        "entropy": entropy,
        "unique_shots": unique_shots,
        "unique_placements": unique_placements,
        "annotation_ratio": annotation_ratio,
        "most_common_shot": _most_common(shot_types) if shot_types else None,
        "most_common_placement": _most_common(placements) if placements else None,
        "warning": None,
    }


def _normalized_entropy(items: List[str]) -> float:
    if not items:
        return 0.0
    counts: Dict[str, int] = {}
    for x in items:
        counts[x] = counts.get(x, 0) + 1
    n = len(items)
    from math import log
    entropy = 0.0
    for c in counts.values():
        p = c / n
        if p > 0:
            entropy -= p * log(p)
    if entropy == 0.0:
        return 0.0
    max_entropy = log(len(counts))
    if max_entropy <= 0:
        return 0.0
    return entropy / max_entropy


def _most_common(items: List[str]) -> Optional[str]:
    if not items:
        return None
    counts: Dict[str, int] = {}
    for x in items:
        counts[x] = counts.get(x, 0) + 1
    return max(counts, key=counts.get)
