#!/usr/bin/env python3
"""
Build cai-laowai/data/faces-pool.json.

RandomUser documents that **pictures are not affected by nat** — only metadata is. Portrait
URLs are a shared global library (~100×2), so this file is a **placeholder** until you
curate labels in pool-review.html or host your own photos.

We still assign at most one row per portrait URL. Country order is **shuffled each round**
so AU (alphabetically first) does not claim almost every unique index.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.client import IncompleteRead
from collections import defaultdict
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

BATCH = 250
SLEEP_S = 0.35
MAX_RETRIES = 5
MAX_ROUNDS = 200
# Max new unique portraits per country per outer round (RandomUser has ~197 unique URLs total).
NEW_PER_COUNTRY_PER_ROUND = 5
UA = "cai-laowai-pool/4.1-roundrobin"


def api_nat(code_upper: str) -> str:
    if code_upper == "GB":
        return "gb"
    return code_upper.lower()


def portrait_id(pic: str) -> str:
    m = re.search(r"/(men|women)/(\d+)\.jpg", pic)
    if m:
        return f"ru-{m.group(1)}-{m.group(2)}"
    return "ru-" + hashlib.sha256(pic.encode()).hexdigest()[:12]


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
    want = int(sys.argv[1]) if len(sys.argv) > 1 else 1400
    want = max(100, min(want, 8000))

    seen: set[str] = set()
    entries: list[dict] = []
    codes = list(NAT_TO_ZH.keys())

    def push(nat: str, pic: str) -> bool:
        nat = nat.upper()
        if nat not in NAT_TO_ZH or not pic or pic in seen:
            return False
        seen.add(pic)
        entries.append(
            {
                "id": portrait_id(pic),
                "img": pic,
                "code": nat,
                "zh": NAT_TO_ZH[nat],
                "reviewed": True,
                "note": "",
            }
        )
        return True

    # RandomUser reuses ~200 stock photos; shuffle order + cap new rows per country per round
    # so we do not exhaust unique URLs under only a few nats.
    for rnd in range(MAX_ROUNDS):
        if len(entries) >= want:
            break
        before_round = len(entries)
        order = codes[:]
        random.shuffle(order)
        round_added: dict[str, int] = defaultdict(int)
        for i, code_u in enumerate(order):
            if len(entries) >= want:
                break
            rows = fetch(
                {
                    "results": str(BATCH),
                    "seed": str(rnd * 97 + i * 13),
                    "nat": api_nat(code_u),
                    "noinfo": "",
                }
            )
            for row in rows:
                if round_added[code_u] >= NEW_PER_COUNTRY_PER_ROUND:
                    break
                nat = (row.get("nat") or "").upper()
                if nat != code_u:
                    continue
                pic = (row.get("picture") or {}).get("large")
                if pic and push(nat, pic):
                    round_added[code_u] += 1
        time.sleep(SLEEP_S)
        print("round", rnd, "total", len(entries), flush=True)
        if len(entries) == before_round:
            break

    payload = {
        "version": int(datetime.now(timezone.utc).timestamp()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "randomuser.me",
        "pool_policy": "shuffle_plus_per_round_nat_cap",
        "notes": (
            "RandomUser: pictures are NOT tied to nat (see their docs). "
            "Curate in /pool-review.html or replace with self-hosted photos."
        ),
        "entries": entries,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print("Wrote", len(entries), "entries ->", OUT, flush=True)


if __name__ == "__main__":
    main()
