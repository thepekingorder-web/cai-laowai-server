#!/usr/bin/env python3
"""Write ../data/countries.json from countries_bundle.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from countries_bundle import COUNTRIES  # noqa: E402

out = {
    "version": 1,
    "countries": [{"code": c, "zh": z, "en": e} for c, z, e in COUNTRIES],
}
path = ROOT / "data" / "countries.json"
path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print("Wrote", len(COUNTRIES), "countries ->", path)
