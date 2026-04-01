#!/usr/bin/env python3
"""Print faces-pool coverage vs top-100 countries (countries_bundle) and min totals.

Browser tools (server must be running, e.g. uvicorn app:app --port 8000):
  Progress summary: http://127.0.0.1:8000/pool-progress
  Manual photo + country QA: http://127.0.0.1:8000/pool-qa.html
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
DEFAULT_JSON = DATA / "faces-pool.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from countries_bundle import COUNTRIES  # noqa: E402


def load_pool(path: Path) -> tuple[dict, list[dict]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw, list(raw.get("entries") or [])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-path", type=Path, default=DEFAULT_JSON)
    ap.add_argument("--min-per-country", type=int, default=3)
    ap.add_argument("--min-total", type=int, default=500)
    args = ap.parse_args()

    path = args.json_path
    if not path.exists():
        print(f"No pool file: {path}")
        sys.exit(2)

    raw, entries = load_pool(path)
    codes_top100 = [c[0] for c in COUNTRIES]
    top_set = set(codes_top100)
    counts = Counter(e.get("code") or "?" for e in entries)

    in_top100 = sum(1 for e in entries if e.get("code") in top_set)
    other = len(entries) - in_top100

    missing_min = [c for c in codes_top100 if counts.get(c, 0) < args.min_per_country]
    below_min_count = len(missing_min)

    print("── Faces pool status ──")
    print(f"File: {path}")
    print(f"Generated: {raw.get('generated_at', '?')}")
    print(f"Policy: {raw.get('pool_policy', '?')}")
    print()
    print(f"Profile rows in JSON: {len(entries)}")
    print(f"  • Assigned to top-100 list: {in_top100}")
    if other:
        print(f"  • Other / unknown codes: {other}")
    print(f"Distinct countries (top-100 set): {len([c for c in codes_top100 if counts.get(c, 0) > 0])}")
    print()
    print(f"Target: ≥{args.min_total} photos, each of top-{len(codes_top100)} ≥{args.min_per_country}.")
    print(f"Countries below {args.min_per_country} in top-100: {below_min_count}")
    if missing_min:
        preview = ", ".join(f"{c}({counts[c]})" for c in missing_min[:25])
        more = f" … +{len(missing_min) - 25} more" if len(missing_min) > 25 else ""
        print(f"  Missing: {preview}{more}")
    print()
    ok_total = len(entries) >= args.min_total
    ok_cov = below_min_count == 0
    print(f"Meets min total ({args.min_total}): {'yes' if ok_total else 'no'}")
    print(f"Meets per-country ({args.min_per_country}): {'yes' if ok_cov else 'no'}")
    if ok_total and ok_cov:
        sys.exit(0)
    sys.exit(1)


if __name__ == "__main__":
    main()
