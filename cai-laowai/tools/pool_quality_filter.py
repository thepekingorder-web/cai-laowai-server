#!/usr/bin/env python3
"""
Scan pool photos and remove:
  - grayscale / black-and-white images
  - cartoons, drawings, illustrations (non-photographic)
  - images without a clear single face

Writes a cleaned faces-pool.json and optionally deletes rejected files.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ASSETS = ROOT / "assets"
DEFAULT_JSON = DATA / "faces-pool.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_face_check import close_detector, is_profile_portrait  # noqa: E402


def is_grayscale(img: np.ndarray, sat_threshold: float = 18.0) -> bool:
    """True if the image is effectively black-and-white (very low saturation)."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    mean_sat = float(np.mean(hsv[:, :, 1]))
    return mean_sat < sat_threshold


def is_cartoon_or_drawing(img: np.ndarray) -> tuple[bool, str]:
    """Heuristic: cartoons/drawings tend to have large flat-color regions and few color gradients."""
    h, w = img.shape[:2]
    area = h * w
    if area < 100:
        return True, "tiny"

    small = cv2.resize(img, (256, 256), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 200)
    edge_ratio = float(np.count_nonzero(edges)) / (256 * 256)

    quant = (small // 32) * 32
    pixels = quant.reshape(-1, 3)
    unique_colors = len(np.unique(pixels, axis=0))

    sat_std = float(np.std(hsv[:, :, 1]))
    val_std = float(np.std(hsv[:, :, 2]))

    lap = cv2.Laplacian(gray, cv2.CV_64F)
    texture_var = float(np.var(lap))

    if unique_colors < 60 and texture_var < 400:
        return True, f"flat_colors:{unique_colors},texture:{texture_var:.0f}"

    if edge_ratio > 0.18 and unique_colors < 120:
        return True, f"cartoon_edges:{edge_ratio:.2f},colors:{unique_colors}"

    if texture_var < 150 and sat_std < 25:
        return True, f"low_texture:{texture_var:.0f},sat_std:{sat_std:.0f}"

    return False, "photo"


def main() -> None:
    path = DEFAULT_JSON
    if not path.exists():
        print(f"No pool file: {path}")
        sys.exit(2)

    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = list(raw.get("entries") or [])
    total_before = len(entries)
    print(f"Pool has {total_before} photos. Scanning each one...\n")

    kept: list[dict] = []
    removed: list[tuple[str, str, str]] = []

    try:
        for row in tqdm(entries, desc="Checking photos", unit="img"):
            rel = (row.get("file") or "").lstrip("/")
            entry_id = row.get("id", "?")
            if not rel:
                removed.append((entry_id, rel, "no_file"))
                continue

            img_path = ASSETS / rel
            if not img_path.is_file():
                removed.append((entry_id, rel, "missing_file"))
                continue

            data = np.fromfile(str(img_path), dtype=np.uint8)
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if img is None or img.size == 0:
                removed.append((entry_id, rel, "unreadable"))
                continue

            if is_grayscale(img):
                removed.append((entry_id, rel, "black_and_white"))
                continue

            is_cart, cart_reason = is_cartoon_or_drawing(img)
            if is_cart:
                removed.append((entry_id, rel, f"cartoon_or_drawing:{cart_reason}"))
                continue

            face_ok, face_reason = is_profile_portrait(img_path)
            if not face_ok:
                removed.append((entry_id, rel, f"no_clear_face:{face_reason}"))
                continue

            kept.append(row)
    finally:
        close_detector()

    print(f"\n{'='*50}")
    print(f"BEFORE: {total_before} photos")
    print(f"KEPT:   {len(kept)} photos")
    print(f"REMOVED: {len(removed)} photos")
    print(f"{'='*50}")

    if removed:
        reasons = Counter()
        for _, _, r in removed:
            bucket = r.split(":")[0]
            reasons[bucket] += 1
        print("\nRemoval reasons:")
        for reason, count in reasons.most_common():
            print(f"  {reason}: {count}")

        print(f"\nRemoved files:")
        for eid, rel, reason in removed:
            print(f"  {rel}  ({reason})")

    confirm = input(f"\nSave? This removes {len(removed)} entries from the pool. [y/N] ")
    if confirm.strip().lower() != "y":
        print("Cancelled.")
        return

    for _, rel, _ in removed:
        p = ASSETS / rel
        if p.is_file():
            p.unlink()
            print(f"  Deleted {rel}")

    raw["entries"] = kept
    raw["version"] = int(datetime.now(timezone.utc).timestamp())
    raw["generated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(
        json.dumps(raw, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"\nSaved {len(kept)} entries to {path}")


if __name__ == "__main__":
    main()
