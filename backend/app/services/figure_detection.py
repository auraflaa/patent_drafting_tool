"""YOLO figure detection over rendered PDF pages.

Renders each page with PyMuPDF, runs a document-layout ONNX detector, and
returns figure candidates with bounding boxes in PDF points ([l,b,r,t]) plus
JPEG crops. The recommended weights are YOLOv10-b trained on DocLayNet
(Apache-2.0): input (1,3,640,640) RGB /255 letterboxed, output (1,300,6)
[xmin,ymin,xmax,ymax,score,class] already post-NMS.

Any decoded-box YOLO export works as long as it follows that contract;
raw grid heads are refused (they would need model-specific decoding).

Without `YOLO_MODEL_PATH` this module is inert: `detect_pdf_figures`
returns [] and the pipeline uses embedded images and direct uploads only.
"""
from __future__ import annotations

import logging
import threading

from app.core.config import settings
from app.services.ingestion import Figure, _prepare_image

logger = logging.getLogger(__name__)

_SESSION = None
_SESSION_PATH = ""
# First detection wins the build: two uploads racing an empty cache must not
# construct (and leak) two sessions, and a path change mid-flight must not
# interleave with a read of the cached one.
_SESSION_LOCK = threading.Lock()


def _session():
    global _SESSION, _SESSION_PATH
    path = settings.yolo_model_path
    with _SESSION_LOCK:
        if _SESSION is not None and _SESSION_PATH == path:
            return _SESSION
        import onnxruntime as ort

        providers = ["CPUExecutionProvider"]
        if settings.yolo_provider == "cuda":
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        try:
            session = ort.InferenceSession(path, providers=providers)
        except Exception:
            # CUDA unavailable or misconfigured: CPU always works.
            session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
        _SESSION = session
        _SESSION_PATH = path
        return session


def _class_names() -> list[str]:
    return [
        name.strip() for name in settings.yolo_classes.split(",") if name.strip()
    ]


def _figure_class_ids() -> set[int]:
    wanted = {
        name.strip()
        for name in settings.yolo_figure_classes.split(",")
        if name.strip()
    }
    return {
        index for index, name in enumerate(_class_names()) if name in wanted
    }


def _letterbox(image, size: int):
    """Scale-and-pad a BGR image to a square tensor input, RGB /255."""
    import cv2
    import numpy as np

    height, width = image.shape[:2]
    scale = min(size / width, size / height)
    resized = cv2.resize(
        image,
        (max(1, int(width * scale)), max(1, int(height * scale))),
        interpolation=cv2.INTER_LINEAR,
    )
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    top = (size - resized.shape[0]) // 2
    left = (size - resized.shape[1]) // 2
    canvas[top : top + resized.shape[0], left : left + resized.shape[1]] = resized
    tensor = canvas[:, :, ::-1].transpose(2, 0, 1).astype("float32") / 255.0
    return tensor[None, ...], scale, left, top


def detect_pdf_figures(
    pdf_bytes: bytes, *, error_out: dict | None = None
) -> list[Figure]:
    """Find figure/table regions on rendered PDF pages. Never raises.

    ``error_out``, when given, receives ``{"error": ...}`` if detection was
    attempted but failed, so callers can tell "no figures on these pages"
    apart from "the detector is broken".
    """
    if not settings.yolo_model_path:
        return []
    try:
        return _detect(pdf_bytes)
    except Exception as exc:  # noqa: BLE001 - detection is supplementary
        logger.warning(
            "yolo_detection_failed",
            extra={"event": "yolo_detection_failed", "error_type": type(exc).__name__},
            exc_info=exc,
        )
        if error_out is not None:
            error_out["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return []


def _detect(pdf_bytes: bytes) -> list[Figure]:
    import cv2

    import fitz

    wanted = _figure_class_ids()
    if not wanted:
        return []
    names = _class_names()
    session = _session()
    input_name = session.get_inputs()[0].name
    size = settings.yolo_input_size
    figures: list[Figure] = []

    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        total = len(pdf)
        # Patent drawings sit at the end of the document; scan the last
        # pages first so the cap covers them, then the front if budget
        # remains. Page numbers below are 1-based document pages.
        last = list(range(max(0, total - settings.yolo_max_pages), total))
        first = list(range(0, max(0, total - settings.yolo_max_pages)))
        order = last + first[: max(0, settings.yolo_max_pages - len(last))]
        for page_number in order:
            page = pdf[page_number]
            # Render at ~150 DPI, then letterbox to the model input.
            zoom = 150 / 72
            pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            import numpy as np

            render = np.frombuffer(pixmap.samples, dtype=np.uint8).reshape(
                pixmap.height, pixmap.width, pixmap.n
            )
            if pixmap.n == 4:
                render = cv2.cvtColor(render, cv2.COLOR_RGBA2BGR)
            elif pixmap.n == 1:
                render = cv2.cvtColor(render, cv2.COLOR_GRAY2BGR)
            tensor, scale, pad_left, pad_top = _letterbox(render, size)
            outputs = session.run(None, {input_name: tensor})
            detections = outputs[0]
            if detections.ndim == 3:
                detections = detections[0]
            # Contract: decoded [xmin,ymin,xmax,ymax,score,class] rows.
            if detections.ndim != 2 or detections.shape[1] not in (6, 7):
                logger.warning(
                    "yolo_output_rejected",
                    extra={
                        "event": "yolo_output_rejected",
                        "shape": [int(dim) for dim in detections.shape],
                    },
                )
                return figures
            page_height = page.rect.height
            for row in detections:
                score = float(row[4])
                class_id = int(row[5])
                if score < settings.yolo_confidence or class_id not in wanted:
                    continue
                # Map letterbox coords back to render pixels, then PDF points.
                rx0 = (float(row[0]) - pad_left) / scale
                ry0 = (float(row[1]) - pad_top) / scale
                rx1 = (float(row[2]) - pad_left) / scale
                ry1 = (float(row[3]) - pad_top) / scale
                rx0 = max(0, min(rx0, render.shape[1]))
                rx1 = max(0, min(rx1, render.shape[1]))
                ry0 = max(0, min(ry0, render.shape[0]))
                ry1 = max(0, min(ry1, render.shape[0]))
                if rx1 - rx0 < 8 or ry1 - ry0 < 8:
                    continue
                x0, y0 = rx0 / zoom, ry0 / zoom
                x1, y1 = rx1 / zoom, ry1 / zoom
                # PDF convention used here: [left, bottom, right, top].
                bbox = [
                    round(x0, 2),
                    round(page_height - y1, 2),
                    round(x1, 2),
                    round(page_height - y0, 2),
                ]
                crop = render[int(ry0) : int(ry1), int(rx0) : int(rx1)]
                ok, encoded = cv2.imencode(".jpg", crop)
                image = encoded.tobytes() if ok else None
                prepared = _prepare_image(image) if image else None
                kind = "table" if names[class_id].lower() == "table" else "image"
                figure = Figure(
                    page=page_number + 1,
                    bbox=bbox,
                    kind=kind,
                    confidence=round(score, 4),
                )
                if prepared is not None:
                    figure.image, figure.content_type = prepared
                figures.append(figure)
    return figures


def iou(a: list[float], b: list[float]) -> float:
    """Intersection-over-union for [l,b,r,t] boxes; 0 when either is empty."""
    if len(a) < 4 or len(b) < 4:
        return 0.0
    left, bottom = max(a[0], b[0]), max(a[1], b[1])
    right, top = min(a[2], b[2]), min(a[3], b[3])
    if right <= left or top <= bottom:
        return 0.0
    area = (right - left) * (top - bottom)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - area
    return area / union if union > 0 else 0.0


def merge_detections(
    existing: list[Figure], detected: list[Figure], *, threshold: float = 0.5
) -> list[Figure]:
    """Append detections that do not overlap an existing figure box."""
    merged = list(existing)
    for candidate in detected:
        if any(
            figure.page == candidate.page
            and iou(figure.bbox, candidate.bbox) >= threshold
            for figure in merged
        ):
            continue
        merged.append(candidate)
    return merged
