#!/usr/bin/env python3
"""
Remove pool rows whose images fail the profile portrait check (single human face, size).

Writes a new faces-pool.json; optionally deletes rejected image files.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ASSETS = ROOT / "assets"
DEFAULT_JSON = DATA / "faces-pool.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_face_check import close_detector, is_profile_portrait  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-path", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--delete-files", action="store_true", help="Delete rejected images from assets/")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    path = args.json_path
    if not path.exists():
        print(f"No pool file: {path}")
        sys.exit(2)

    raw = json.loads(path.read_text(encoding="utf-8"))
    entries = list(raw.get("entries") or [])

    kept: list[dict] = []
    removed: list[tuple[str, str]] = []

    try:
        for row in tqdm(entries, desc="Profile check", unit="img"):
            rel = (row.get("file") or "").lstrip("/")
            if not rel:
                removed.append((row.get("id", "?"), "no_file_field"))
                continue
            img_path = (ASSETS / rel).resolve()
            if not str(img_path).startswith(str(ASSETS.resolve())):
                removed.append((row.get("id", "?"), "path_escape"))
                continue
            ok, reason = is_profile_portrait(img_path)
            if ok:
                kept.append(row)
            else:
                removed.append((row.get("id", "?"), reason))
                if args.delete_files and not args.dry_run and img_path.is_file():
                    try:
                        img_path.unlink()
                    except OSError:
                        pass
    finally:
        close_detector()

    print()
    print(f"Kept: {len(kept)}  Removed: {len(removed)}")
    if removed and len(removed) <= 40:
        for rid, r in removed:
            print(f"  - {rid}: {r}")
    elif removed:
        from collections import Counter

        c = Counter(r for _, r in removed)
        print("  Reasons:", dict(c.most_common(12)))

    if args.dry_run:
        print("Dry run — did not write JSON.")
        return

    raw["entries"] = kept
    raw["version"] = int(datetime.now(timezone.utc).timestamp())
    raw["generated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(raw, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"Wrote {len(kept)} entries -> {path}")


if __name__ == "__main__":
    main()
