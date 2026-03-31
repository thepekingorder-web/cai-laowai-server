#!/usr/bin/env python3
"""
Build cai-laowai/data/faces-pool.json (runs on GitHub Actions — nothing required on your laptop).

Uses RandomUser with large `results` per request to avoid rate limits. One portrait URL = one row.
"""
from __future__ import annotations

import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.client import IncompleteRead
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "faces-pool.json"

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

NAT_FETCH_ONLY = {"IN": "in", "IR": "ir"}
RESTRICTED = frozenset(NAT_FETCH_ONLY.keys())

BATCH = 500
SLEEP_S = 0.35
MAX_RETRIES = 5
MAX_PAGES_NAT = 12
MAX_PAGES_GLOBAL = 45
UA = "goteyes-cai-laowai-pool/3.0"


def fetch(qs: dict) -> list[dict]:
    url = "https://randomuser.me/api/?" + urllib.parse.urlencode(qs)
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    for attempt in range(MAX_RETRIES):
        try:
            with urllib.request.urlopen(req, context=ctx, timeout=120) as r:
                return json.loads(r.read().decode()).get("results") or []
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(2.5 * (attempt + 1))
            else:
                time.sleep(0.8)
        except (
            urllib.error.URLError,
            ssl.SSLError,
            OSError,
            json.JSONDecodeError,
            IncompleteRead,
        ):
            time.sleep(0.8)
    return []


def main() -> None:
    want = int(sys.argv[1]) if len(sys.argv) > 1 else 1600
    want = max(100, min(want, 8000))

    seen: set[str] = set()
    entries: list[dict] = []

    def push(nat: str, pic: str) -> None:
        nat = nat.upper()
        if nat not in NAT_TO_ZH or not pic or pic in seen:
            return
        seen.add(pic)
        entries.append({"img": pic, "code": nat, "zh": NAT_TO_ZH[nat]})

    per_nat_cap = max(30, min(100, want // 12))

    for code_u, nat_param in NAT_FETCH_ONLY.items():
        n_here = 0
        for page in range(MAX_PAGES_NAT):
            if len(entries) >= want or n_here >= per_nat_cap:
                break
            rows = fetch(
                {
                    "results": str(BATCH),
                    "seed": str(page * 41 + (3 if code_u == "IN" else 7)),
                    "nat": nat_param,
                    "noinfo": "",
                }
            )
            before = len(entries)
            for row in rows:
                nat = (row.get("nat") or "").upper()
                if nat != code_u:
                    continue
                pic = (row.get("picture") or {}).get("large")
                if pic:
                    push(nat, pic)
            n_here += len(entries) - before
            time.sleep(SLEEP_S)
            print("nat", code_u, "page", page, "total", len(entries), flush=True)

    for page in range(MAX_PAGES_GLOBAL):
        if len(entries) >= want:
            break
        rows = fetch({"results": str(BATCH), "seed": str(page * 97 + 1), "noinfo": ""})
        for row in rows:
            nat = (row.get("nat") or "").upper()
            if nat not in NAT_TO_ZH or nat in RESTRICTED:
                continue
            pic = (row.get("picture") or {}).get("large")
            if pic:
                push(nat, pic)
        time.sleep(SLEEP_S)
        if page % 5 == 0:
            print("global page", page, "total", len(entries), flush=True)

    payload = {
        "version": int(datetime.now(timezone.utc).timestamp()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "randomuser.me",
        "notes": "Prototype; regenerate via GitHub Action.",
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print("Wrote", len(entries), "entries ->", OUT, flush=True)


if __name__ == "__main__":
    main()

# --- Optional: run this on GitHub (Actions → New workflow) so the pool updates without your laptop.
# Save as .github/workflows/cai-laowai-pool.yml and push with a token that allows "workflow" scope.
#
#   on: { workflow_dispatch: {}, schedule: [ { cron: "0 6 * * 1" } ] }
#   permissions: { contents: write }
#   jobs:
#     build-pool:
#       runs-on: ubuntu-latest
#       steps:
#         - uses: actions/checkout@v4
#         - uses: actions/setup-python@v5
#           with: { python-version: "3.12" }
#         - run: python3 cai-laowai/tools/build_faces_pool.py 1600
#         - uses: stefanzweifel/git-auto-commit-action@v5
#           with:
#             commit_message: "chore(cai-laowai): refresh faces-pool.json"
#             file_pattern: cai-laowai/data/faces-pool.json
