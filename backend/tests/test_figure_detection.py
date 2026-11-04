"""Tests for YOLO figure detection and deterministic screening.

The detector runs against a stub ONNX session so no weights are needed; the
screening tests use synthetic images.
"""
import numpy as np
import pytest

from app.services import extraction_store, figure_detection, figure_quality, ingestion


def _jpeg(width: int = 400, height: int = 300, value: int = 240) -> bytes:
    import cv2

    image = np.full((height, width, 3), value, dtype=np.uint8)
    cv2.rectangle(image, (10, 10), (width - 10, height - 10), (20, 20, 20), 3)
    ok, buffer = cv2.imencode(".jpg", image)
    assert ok
    return buffer.tobytes()


def _pdf_bytes(pages: int = 1) -> bytes:
    import fitz

    with fitz.open() as pdf:
        for _ in range(pages):
            pdf.new_page(width=595, height=842)
        return pdf.tobytes()


class _StubSession:
    def __init__(self, rows):
        self._rows = rows

    def get_inputs(self):
        return [type("Input", (), {"name": "images"})()]

    def run(self, _outputs, _feeds):
        return [np.array([self._rows], dtype=np.float32)]


def _configure(monkeypatch):
    monkeypatch.setattr(
        figure_detection.settings,
        "yolo_classes",
        "Caption,Footnote,Formula,List-item,Page-footer,Page-header,"
        "Picture,Section-header,Table,Text,Title",
    )
    monkeypatch.setattr(figure_detection.settings, "yolo_figure_classes", "Picture,Table")
    monkeypatch.setattr(figure_detection.settings, "yolo_confidence", 0.35)
    monkeypatch.setattr(figure_detection.settings, "yolo_input_size", 640)
    monkeypatch.setattr(figure_detection.settings, "yolo_max_pages", 5)
    monkeypatch.setattr(figure_detection.settings, "yolo_provider", "cpu")
    monkeypatch.setattr(figure_detection, "_SESSION", None)
    monkeypatch.setattr(figure_detection, "_SESSION_PATH", "")


def test_detector_returns_picture_and_table_candidates(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(
        figure_detection, "_session", lambda: _StubSession(
            [
                [100, 100, 300, 300, 0.92, 6],  # Picture
                [100, 400, 300, 550, 0.81, 8],  # Table
                [0, 0, 640, 640, 0.10, 6],  # below confidence
                [0, 0, 640, 640, 0.95, 9],  # Text: not a figure class
            ]
        )
    )
    monkeypatch.setattr(figure_detection.settings, "yolo_model_path", "dummy.onnx")

    figures = figure_detection.detect_pdf_figures(_pdf_bytes())

    assert len(figures) == 2
    assert figures[0].kind == "image"
    assert figures[0].page == 1
    assert figures[0].confidence == pytest.approx(0.92)
    assert len(figures[0].bbox) == 4
    assert figures[0].image is not None
    assert figures[1].kind == "table"


def test_detector_scans_the_last_pages_first(monkeypatch):
    _configure(monkeypatch)
    seen = []

    class Session:
        def get_inputs(self):
            return [type("Input", (), {"name": "images"})()]

        def run(self, _outputs, _feeds):
            seen.append(True)
            return [np.zeros((1, 300, 6), dtype=np.float32)]

    monkeypatch.setattr(figure_detection, "_session", lambda: Session())
    monkeypatch.setattr(figure_detection.settings, "yolo_model_path", "dummy.onnx")
    monkeypatch.setattr(figure_detection.settings, "yolo_max_pages", 2)

    figures = figure_detection.detect_pdf_figures(_pdf_bytes(pages=3))

    assert figures == []
    assert len(seen) == 2  # only the last two pages were rendered


def test_detector_is_off_without_a_model_path(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(figure_detection.settings, "yolo_model_path", "")

    assert figure_detection.detect_pdf_figures(_pdf_bytes()) == []


def test_detector_refuses_a_raw_head(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(
        figure_detection, "_session", lambda: _StubSession([[0] * 85])
    )
    monkeypatch.setattr(figure_detection.settings, "yolo_model_path", "dummy.onnx")

    assert figure_detection.detect_pdf_figures(_pdf_bytes()) == []


def test_detector_never_raises(monkeypatch):
    _configure(monkeypatch)
    monkeypatch.setattr(figure_detection.settings, "yolo_model_path", "dummy.onnx")

    def explode():
        raise RuntimeError("no onnxruntime here")

    monkeypatch.setattr(figure_detection, "_session", explode)

    assert figure_detection.detect_pdf_figures(_pdf_bytes()) == []


def test_session_creation_is_thread_safe(monkeypatch):
    """Two uploads racing the first detection must build one session."""
    import threading
    import time

    _configure(monkeypatch)
    calls: list = []

    class SlowSession(_StubSession):
        def __init__(self):
            super().__init__([])
            calls.append(1)
            time.sleep(0.5)

    monkeypatch.setattr(figure_detection.settings, "yolo_model_path", "dummy.onnx")
    monkeypatch.setattr(
        "onnxruntime.InferenceSession", lambda *args, **kwargs: SlowSession()
    )
    monkeypatch.setattr(figure_detection, "_SESSION", None)
    monkeypatch.setattr(figure_detection, "_SESSION_PATH", "")

    results: list = []

    def go():
        results.append(figure_detection._session())

    threads = [threading.Thread(target=go) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert len(calls) == 1
    assert results[0] is results[1]


def test_detection_failure_is_reported_to_the_caller(monkeypatch):
    """An operator must distinguish 'no figures' from 'model broken'."""
    _configure(monkeypatch)
    monkeypatch.setattr(figure_detection.settings, "yolo_model_path", "dummy.onnx")

    def explode():
        raise RuntimeError("weights are corrupt")

    monkeypatch.setattr(figure_detection, "_session", explode)
    holder: dict = {}

    assert figure_detection.detect_pdf_figures(_pdf_bytes(), error_out=holder) == []
    assert "corrupt" in (holder.get("error") or "")


def test_merge_detections_drops_overlapping_boxes():
    existing = [ingestion.Figure(page=1, bbox=[0, 0, 100, 100])]
    detected = [
        ingestion.Figure(page=1, bbox=[10, 10, 90, 90]),  # duplicate
        ingestion.Figure(page=1, bbox=[200, 200, 300, 300]),  # new
        ingestion.Figure(page=2, bbox=[10, 10, 90, 90]),  # other page: new
    ]

    merged = figure_detection.merge_detections(existing, detected)

    assert len(merged) == 3


def test_screen_rejects_too_small_blank_and_duplicates(monkeypatch):
    monkeypatch.setattr(figure_quality, "logger", figure_quality.logger)

    ok, reason, _ = figure_quality.screen(
        _jpeg(width=40, height=30), min_edge_px=300, known_hashes=set()
    )
    assert not ok and "too small" in reason

    ok, reason, _ = figure_quality.screen(
        np.full((400, 400, 3), 200, dtype=np.uint8).tobytes(),
        min_edge_px=300,
        known_hashes=set(),
    )
    # Raw BGR bytes are not a decodable image.
    assert not ok

    import cv2

    blank = np.full((400, 400, 3), 200, dtype=np.uint8)
    # BMP is uncompressed, so a blank page passes the size gate and reaches
    # the variance check.
    _, encoded = cv2.imencode(".bmp", blank)
    ok, reason, _ = figure_quality.screen(
        encoded.tobytes(), min_edge_px=300, known_hashes=set()
    )
    assert not ok and reason == "blank"

    good = _jpeg()
    ok, reason, digest = figure_quality.screen(
        good, min_edge_px=300, known_hashes=set()
    )
    assert ok and reason == "" and digest
    ok, reason, _ = figure_quality.screen(
        good, min_edge_px=300, known_hashes={digest}
    )
    assert not ok and reason == "duplicate"


def test_save_figure_stores_screening_fields(monkeypatch):
    saved = {}

    def fake_create(collection, data, doc_id=None):
        saved.update(data)
        return {"id": "fig1", **data}

    monkeypatch.setattr(extraction_store, "create_doc", fake_create)
    monkeypatch.setattr(
        extraction_store.blobs,
        "put_blob",
        lambda data, content_type: {"id": "blob1"},
    )
    monkeypatch.setattr(extraction_store.settings, "min_figure_edge_px", 300)

    extraction_store._save_figure(
        "f1",
        "p1",
        ingestion.Figure(page=1, kind="image", image=_jpeg()),
        order=2,
        known_hashes=set(),
    )

    assert saved["usable"] == "usable"
    assert saved["display_order"] == 2
    assert saved["include_in_drawings"] is True
    assert saved["perceptual_hash"]
    assert saved["image_blob_id"] == "blob1"


def test_usable_figure_count_counts_selected_images(monkeypatch):
    monkeypatch.setattr(
        extraction_store,
        "query_docs",
        lambda collection, filters=None: [
            {"usable": "usable", "include_in_drawings": True, "has_image": True},
            {"usable": "rejected", "include_in_drawings": True, "has_image": True},
            {"usable": "usable", "include_in_drawings": False, "has_image": True},
            {"usable": "unknown", "include_in_drawings": True, "has_image": True},
        ],
    )

    assert extraction_store.usable_figure_count("p1") == 1
