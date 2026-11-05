"""Deterministic figure screening.

Every figure candidate — OpenDataLoader crop, embedded DOCX/PPTX image,
direct image upload, or YOLO-detected region — passes through `screen`
before it is stored. The checks are purely geometric and statistical:

* too small (below `min_figure_edge_px` on either side, or tiny byte size);
* blank (near-zero pixel variance — a white page region or empty box);
* extreme aspect ratio (page-spanning rules, not drawings);
* duplicate (same perceptual hash as a candidate already stored for the
  patent).

The vision pass (Phase 5) and the user ("Use anyway") refine this later;
screening only rejects what is clearly not a drawing.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def average_hash(image) -> str:
    """8x8 average hash of a BGR image as 16 hex chars."""
    import cv2

    small = cv2.resize(image, (8, 8), interpolation=cv2.INTER_AREA)
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    mean = float(gray.mean())
    bits = (gray > mean).flatten()
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:016x}"


def screen(
    image_bytes: bytes,
    *,
    min_edge_px: int,
    known_hashes: set[str] | None = None,
) -> tuple[bool, str, str]:
    """Return (usable, reason, perceptual_hash) for one candidate image."""
    import cv2
    import numpy as np

    if not image_bytes or len(image_bytes) < 5_000:
        return False, "file too small to be a drawing", ""
    decoded = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
    if decoded is None:
        return False, "unreadable image", ""
    height, width = decoded.shape[:2]
    if min(height, width) < min_edge_px:
        return (
            False,
            f"too small ({width}x{height}px, minimum edge {min_edge_px}px)",
            "",
        )
    if max(height, width) / max(1, min(height, width)) > 5:
        return False, "extreme aspect ratio", ""
    gray = cv2.cvtColor(decoded, cv2.COLOR_BGR2GRAY)
    if float(gray.std()) < 4.0:
        return False, "blank", ""
    digest = average_hash(decoded)
    if known_hashes is not None and digest in known_hashes:
        return False, "duplicate", digest
    return True, "", digest
