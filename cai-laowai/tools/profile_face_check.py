# -*- coding: utf-8 -*-
"""Single-human, portrait-style face check (MediaPipe Tasks: short-range + full-range fallback)."""

from __future__ import annotations

import re
import urllib.request
from pathlib import Path

import cv2
import mediapipe as mp
import numpy as np
from mediapipe.tasks.python import vision
from mediapipe.tasks.python.core import base_options as mp_base

MODEL_SHORT_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_short_range/float16/latest/blaze_face_short_range.tflite"
)
MODEL_FULL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_detector/"
    "blaze_face_full_range/float16/latest/blaze_face_full_range.tflite"
)
CACHE = Path(__file__).resolve().parent / ".cache"
MODEL_SHORT_PATH = CACHE / "blaze_face_short_range.tflite"
MODEL_FULL_PATH = CACHE / "blaze_face_full_range.tflite"

TITLE_REJECT = re.compile(
    r"(team|crowd|groupshot|group[_\s-]?photo|protesters|rally|parade|marching|"
    r"wedding\s+party|family\s+portrait|class\s+photo|graduation\s+group|"
    r"cartoon|caricature|logo|flag\s+raising|conference\s+photo|assembly)",
    re.I,
)


def title_likely_non_portrait(file_title_or_slug: str) -> bool:
    s = file_title_or_slug.replace("_", " ").replace("-", " ")
    return bool(TITLE_REJECT.search(s))


def _download(url: str, dest: Path) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 10_000:
        return dest
    with urllib.request.urlopen(url, timeout=120) as r:
        dest.write_bytes(r.read())
    return dest


def _ensure_short() -> Path:
    return _download(MODEL_SHORT_URL, MODEL_SHORT_PATH)


def _ensure_full() -> Path:
    return _download(MODEL_FULL_URL, MODEL_FULL_PATH)


_detector_short: vision.FaceDetector | None = None
_detector_full: vision.FaceDetector | None = None


def _get_short() -> vision.FaceDetector:
    global _detector_short
    if _detector_short is None:
        opts = vision.FaceDetectorOptions(
            base_options=mp_base.BaseOptions(model_asset_path=str(_ensure_short())),
            min_detection_confidence=0.55,
            min_suppression_threshold=0.3,
        )
        _detector_short = vision.FaceDetector.create_from_options(opts)
    return _detector_short


def _get_full() -> vision.FaceDetector:
    global _detector_full
    if _detector_full is None:
        opts = vision.FaceDetectorOptions(
            base_options=mp_base.BaseOptions(model_asset_path=str(_ensure_full())),
            min_detection_confidence=0.5,
            min_suppression_threshold=0.3,
        )
        _detector_full = vision.FaceDetector.create_from_options(opts)
    return _detector_full


def _imread(path: Path) -> np.ndarray | None:
    data = np.fromfile(str(path), dtype=np.uint8)
    if data.size == 0:
        return None
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    return img


def _dets_for_image(mp_image: mp.Image) -> list:
    d = _get_short().detect(mp_image).detections or []
    if len(d) == 0:
        d = _get_full().detect(mp_image).detections or []
    return d


def _det_pixel_area(d, iw: int, ih: int) -> float:
    box = d.bounding_box
    return float(box.width) * float(box.height)


def is_profile_portrait(
    image_path: Path,
    *,
    min_face_area: float = 0.032,
    max_face_area: float = 0.72,
    min_short_side_px: int = 180,
    allow_dominant_face: bool = False,
    dominant_second_max_ratio: float = 0.18,
) -> tuple[bool, str]:
    if not image_path.is_file():
        return False, "missing_file"

    img = _imread(image_path)
    if img is None or img.size == 0:
        return False, "decode"

    h, w = img.shape[:2]
    if min(h, w) < min_short_side_px:
        return False, "image_too_small"

    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
    dets = list(_dets_for_image(mp_image))

    if len(dets) == 0:
        return False, "no_face"
    if len(dets) > 1:
        if allow_dominant_face and len(dets) == 2:
            areas = [(d, _det_pixel_area(d, w, h)) for d in dets]
            areas.sort(key=lambda x: -x[1])
            a0, a1 = areas[0][1], areas[1][1]
            if a0 > 0 and a1 / a0 <= dominant_second_max_ratio:
                dets = [areas[0][0]]
            else:
                return False, "multi_face:2"
        else:
            return False, f"multi_face:{len(dets)}"

    box = dets[0].bounding_box
    fw, fh = box.width, box.height
    area = (fw * fh) / float(w * h)
    if area < min_face_area:
        return False, f"face_too_small:{area:.3f}"
    if area > max_face_area:
        return False, f"face_too_large:{area:.3f}"

    return True, "ok"


def close_detector() -> None:
    global _detector_short, _detector_full
    if _detector_short is not None:
        _detector_short.close()
        _detector_short = None
    if _detector_full is not None:
        _detector_full.close()
        _detector_full = None
