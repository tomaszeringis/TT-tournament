"""
Vision Calibration — table geometry and homography computation.

Provides:
- CalibrationState with validity/health tracking
- Homography computation from 4 image-space corners to normalized table space
- Calibration UI helpers for Streamlit
"""

from __future__ import annotations

import dataclasses
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class CalibrationState:
    """Health and validity state for table calibration."""

    valid: bool = False
    stale: bool = False
    invalid: bool = False
    last_updated_monotonic: float = 0.0
    last_updated_utc: Optional[datetime] = None
    homography: Optional[np.ndarray] = field(default=None, repr=False)
    table_corners: Optional[List[Tuple[float, float]]] = field(default=None, repr=False)
    net_line_y: Optional[float] = None
    player_a_side: str = "top"
    player_b_side: str = "bottom"
    error: Optional[str] = None

    def mark_valid(self, homography: np.ndarray, table_corners: List[Tuple[float, float]]) -> None:
        self.valid = True
        self.stale = False
        self.invalid = False
        self.homography = homography
        self.table_corners = list(table_corners)
        self.last_updated_monotonic = time.monotonic()
        self.last_updated_utc = datetime.now(timezone.utc)
        self.error = None

    def mark_invalid(self, reason: str) -> None:
        self.valid = False
        self.invalid = True
        self.error = reason

    def mark_stale(self) -> None:
        self.valid = False
        self.stale = True


def compute_homography(
    table_corners: List[Tuple[float, float]],
) -> Optional[np.ndarray]:
    """Compute homography from 4 camera-pixel corners to normalized table space.

    Args:
        table_corners: 4 points in camera pixel coordinates, ordered as:
            top-left, top-right, bottom-right, bottom-left.

    Returns:
        3x3 homography matrix, or None if the corners are degenerate.
    """
    if len(table_corners) != 4:
        return None

    src = np.array(table_corners, dtype=np.float32)
    dst = np.array(
        [[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0]],
        dtype=np.float32,
    )

    if cv2 is None:
        logger.debug("OpenCV is unavailable; cannot compute homography")
        return None

    try:
        homography, _ = cv2.findHomography(src, dst, method=0)
        return homography
    except Exception as exc:
        logger.debug("Homography computation failed: %s", exc)
        return None


def validate_calibration(corners: List[Tuple[float, float]]) -> Optional[str]:
    """Validate that 4 corners form a usable convex quadrilateral.

    Returns:
        None if valid, otherwise a rejection reason string.
    """
    if len(corners) != 4:
        return "Exactly 4 corners are required"

    pts = np.array(corners, dtype=np.float32)
    if pts.shape != (4, 2):
        return "Each corner must be an (x, y) pair"

    area = 0.0
    for i in range(4):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % 4]
        area += x1 * y2 - x2 * y1
    area = abs(area) / 2.0

    if area < 1000.0:
        return "Corners form a degenerate quadrilateral (area too small)"

    cross_sum = 0.0
    for i in range(4):
        x1, y1 = pts[i] - pts[(i + 1) % 4]
        x2, y2 = pts[(i + 2) % 4] - pts[(i + 1) % 4]
        cross_sum += x1 * y2 - x2 * y1

    if abs(cross_sum) < 1e-6:
        return "Corners are collinear or self-intersecting"

    return None


def transform_point(
    homography: np.ndarray,
    x: float,
    y: float,
) -> Optional[Tuple[float, float]]:
    """Map a camera-pixel point to normalized table coordinates.

    Args:
        homography: 3x3 homography matrix.
        x, y: Point in camera pixel space.

    Returns:
        (x, y) in normalized table space [0, 1], or None if transform fails.
    """
    if cv2 is None:
        return None

    try:
        src = np.array([[x, y]], dtype=np.float32)
        dst = cv2.perspectiveTransform(src, homography)
        return float(dst[0][0][0]), float(dst[0][0][1])
    except Exception as exc:
        logger.debug("Point transform failed: %s", exc)
        return None


# Lazy import of cv2 to keep module import-safe when OpenCV is absent.
try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None  # type: ignore
