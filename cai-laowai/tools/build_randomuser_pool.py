#!/usr/bin/env python3
"""
Build a large human-only pool from RandomUser.me (prototype; legal TBD).

Uses `seed` + `results` so we get many distinct API rows. Each row keeps the API’s
`nat` as the correct answer — stereotypes sometimes line up, often they don’t.

Dedupes by (portrait URL, nat) so the same face can appear with different countries
(drives home the end message).

Usage:
  python3 cai-laowai/tools/build_randomuser_pool.py [target_entries]

Writes: cai-laowai/data/faces-manifest.json
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.client import IncompleteRead
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "faces-manifest.json"

NAT_TO_ZH = {
    "AU": "澳大利亚",
    "BR": "巴西",
    "CA": "加拿大",
    "CH": "瑞士",
    "DE": "德国",
    "DK": "丹麦",
    "ES": "西班牙",
    "FI": "芬兰",
    "FR": "法国",
    "GB": "英国",
    "IE": "爱尔兰",
    "IN": "印度",
    "IR": "伊朗",
    "MX": "墨西哥",
    "NL": "荷兰",
    "NO": "挪威",
    "NZ": "新西兰",
    "RS": "塞尔维亚",
    "TR": "土耳其",
    "UA": "乌克兰",
    "US": "美国",
}

EXCLUDE_NAT = frozenset({"CN", "HK", "MO"})
RESULTS_PER_CALL = 8
SLEEP_S = 0.2
MAX_RETRIES = 5
MAX_SEED = 30000


def fetch(seed: int, n: int) -> list[dict]:
    q = urllib.parse.urlencode({"results": str(n), "seed": str(seed), "noinfo": ""})
    url = f"https://randomuser.me/api/?{q}"
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "goteyes-cai-laowai-pool/1.0"})
    for _ in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=90) as r:
                return json.loads(r.read().decode()).get("results") or []
        except (
            urllib.error.URLError,
            ssl.SSLError,
            OSError,
            json.JSONDecodeError,
            IncompleteRead,
        ):
            time.sleep(0.9)
    return []


def main() -> None:
    want = int(sys.argv[1]) if len(sys.argv) > 1 else 2800
    seen_pics: set[str] = set()
    entries: list[dict] = []

    for seed in range(MAX_SEED):
        if len(entries) >= want:
            break
        batch = fetch(seed, RESULTS_PER_CALL)
        for row in batch:
            nat = (row.get("nat") or "").upper()
            if nat in EXCLUDE_NAT or nat not in NAT_TO_ZH:
                continue
            pic = (row.get("picture") or {}).get("large")
            if not pic:
                continue
            if pic in seen_pics:
                continue
            seen_pics.add(pic)
            entries.append({"img": pic, "code": nat, "zh": NAT_TO_ZH[nat]})
            if len(entries) >= want:
                break
        if seed % 250 == 0 and seed:
            print("seed", seed, "entries", len(entries))
        time.sleep(SLEEP_S)

    manifest = {
        "version": 3,
        "source": "randomuser.me",
        "notes": (
            "Prototype: RandomUser.me humans only. Each portrait URL appears at most once; "
            "country is that API row's nat. Production: cleared assets + real licensing."
        ),
        "country_labels": NAT_TO_ZH,
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(manifest, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print("wrote", OUT, "entries", len(entries), "mb", round(OUT.stat().st_size / 1e6, 2))


if __name__ == "__main__":
    main()
