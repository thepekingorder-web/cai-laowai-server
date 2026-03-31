#!/usr/bin/env python3
"""
Bootstrap the 猜老外 image bank from Openverse (CC0 only).

Sourcing policy (see also faces-manifest.json "notes"):
- Primary manual adds: Unsplash / Pexels / Pixabay — use each photo’s page URL, site Download,
  and record creator + license on the manifest row.
- Openverse here: license filter cc0 only; metadata comes from the API (creator, foreign_landing_url).

This script does NOT assign “true nationality”. Game fields code/zh/look are design / curation;
a human should review each row and swap images from Unsplash/Pexels/Pixabay when ready.

Usage (from repo root):
  python3 cai-laowai/tools/fetch_openverse_cc0.py

Requires: urllib (stdlib), network.
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # cai-laowai/
ASSETS_FACES = ROOT / "assets" / "faces"
MANIFEST_PATH = ROOT / "data" / "faces-manifest.json"

API = "https://api.openverse.org/v1/images/"
# Bias toward *human* subjects; generic "portrait" pulls pets, wildlife, etc.
QUERIES = [
    "person portrait face",
    "adult human headshot",
    "woman person portrait face",
    "man person portrait face",
    "professional person headshot",
    "business person portrait",
    "human face close up",
    "person studio portrait",
]
PAGES_PER_QUERY = 2
PAGE_SIZE = 12
MAX_DOWNLOADS = 24

# Reject CC0 hits that metadata marks as animals / pets / wildlife (common cause of dogs in "portrait").
_ANIMAL = re.compile(
    r"\b(dog|dogs|puppy|puppies|pup|canine|cat|cats|kitten|kittens|kitty|feline|"
    r"pet|pets|animal|animals|wildlife|livestock|horse|horses|pony|bird|birds|parrot|"
    r"paw|paws|husky|labrador|poodle|terrier|beagle|retriever|collie|shepherd|dachshund|"
    r"bulldog|spaniel|chihuahua|corgi|pug|mastiff|hound|mutt|k9|k-9|squirrel|bunny|rabbit|"
    r"hamster|mouse|rat|reptile|snake|lizard|turtle|fish|aquarium|zoo|safari|elephant|"
    r"monkey|ape|gorilla|bear|wolf|fox|deer|cow|cattle|sheep|goat|pig|pigs|otter|seal)\b",
    re.I,
)
_JUNK = re.compile(
    r"\b(landscape|seascape|macro\s+flower|food\s+photo|architecture|building\s+exterior|"
    r"car\s+interior|screenshot|diagram|map\b|texture|pattern|abstract\s+art|sculpture|"
    r"statue|monument|product\s+shot|packshot)\b",
    re.I,
)
_HUMAN_HINT = re.compile(
    r"\b(person|people|human|man|woman|men|women|male|female|face|headshot|portrait|"
    r"model|adult|boy|girl|teen|student|worker|employee|business|office|selfie|smiling|"
    r"eyes|hair|beard|makeup|skin)\b",
    re.I,
)

# Provisional game labels — replace after human curation (Unsplash etc.).
GAME_ROTATION = [
    ("US", "美国", "white"),
    ("GB", "英国", "white"),
    ("DE", "德国", "white"),
    ("FR", "法国", "white"),
    ("BR", "巴西", "latin"),
    ("MX", "墨西哥", "latin"),
    ("NG", "尼日利亚", "black"),
    ("ZA", "南非", "black"),
    ("IN", "印度", "south_asian"),
    ("JP", "日本", "east_asian"),
    ("KR", "韩国", "east_asian"),
    ("TR", "土耳其", "mena"),
    ("EG", "埃及", "mena"),
    ("CA", "加拿大", "white"),
    ("AU", "澳大利亚", "white"),
]


def fetch_json(url: str) -> dict:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "goteyes-cai-laowai-bank/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
        return json.loads(r.read().decode())


def download_file(url: str, dest: Path) -> None:
    ctx = ssl.create_default_context()
    req = urllib.request.Request(url, headers={"User-Agent": "goteyes-cai-laowai-bank/1.0"})
    with urllib.request.urlopen(req, context=ctx, timeout=120) as r:
        dest.write_bytes(r.read())


def safe_slug(s: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9_-]+", "-", s).strip("-")[:48]
    return s or "img"


def _metadata_blob(item: dict) -> str:
    parts: list[str] = []
    for key in ("title", "description"):
        v = item.get(key)
        if v:
            parts.append(str(v))
    for t in item.get("tags") or []:
        if isinstance(t, dict) and t.get("name"):
            parts.append(str(t["name"]))
    return " ".join(parts).lower()


def looks_like_human_portrait(item: dict) -> bool:
    blob = _metadata_blob(item)
    if not blob.strip():
        return False
    if _ANIMAL.search(blob):
        return False
    if _JUNK.search(blob):
        return False
    if not _HUMAN_HINT.search(blob):
        return False
    return True


def main() -> None:
    ASSETS_FACES.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)

    if "--rebuild" in sys.argv:
        for f in ASSETS_FACES.glob("*.jpg"):
            f.unlink()
        print("cleared", ASSETS_FACES)

    seen_ids: set[str] = set()
    collected: list[dict] = []

    for q in QUERIES:
        for page in range(1, PAGES_PER_QUERY + 1):
            params = urllib.parse.urlencode(
                {
                    "q": q,
                    "license": "cc0",
                    "page_size": PAGE_SIZE,
                    "page": page,
                }
            )
            url = f"{API}?{params}"
            try:
                data = fetch_json(url)
            except (urllib.error.URLError, json.JSONDecodeError) as e:
                print(f"skip query page {q!r} p{page}: {e}")
                continue
            for item in data.get("results") or []:
                oid = item.get("id")
                if not oid or oid in seen_ids:
                    continue
                src = item.get("url")
                if not src:
                    continue
                # Hotlinking upload.wikimedia.org in bulk often returns 429; prefer Flickr/stocks or add rows manually from Unsplash/Pexels/Pixabay.
                prov = (item.get("provider") or item.get("source") or "").lower()
                if prov == "wikimedia" or "wikimedia.org" in src:
                    continue
                if not looks_like_human_portrait(item):
                    continue
                seen_ids.add(oid)
                collected.append(item)
            time.sleep(0.35)

    entries: list[dict] = []
    for i, item in enumerate(collected[:MAX_DOWNLOADS]):
        oid = item["id"]
        slug = safe_slug(oid)
        ext = ".jpg"
        fname = f"{slug}{ext}"
        rel = f"faces/{fname}"
        dest = ASSETS_FACES / fname
        if not dest.exists():
            try:
                download_file(item["url"], dest)
                print("downloaded", rel)
            except (urllib.error.URLError, OSError) as e:
                print("failed", item.get("url"), e)
                continue
        code, zh, look = GAME_ROTATION[i % len(GAME_ROTATION)]
        provider = item.get("provider") or item.get("source") or "openverse"
        entries.append(
            {
                "id": oid,
                "file": rel,
                "code": code,
                "zh": zh,
                "look": look,
                "source_url": item.get("foreign_landing_url") or item.get("url"),
                "site": f"Openverse ({provider})",
                "creator": item.get("creator") or "unknown",
                "creator_url": item.get("creator_url"),
                "license": f"CC0 {item.get('license_version') or '1.0'}".strip(),
                "license_url": item.get("license_url") or "https://creativecommons.org/publicdomain/zero/1.0/",
                "curation_status": "needs_review",
                "curation_note": "Game country/look are placeholders; replace file with Unsplash/Pexels/Pixabay after manual pick.",
            }
        )
        time.sleep(0.25)

    manifest = {
        "version": 1,
        "notes": (
            "Each entry: file is served at /cai-laowai/assets/<file>. "
            "Bootstrap script filters Openverse metadata for human portrait cues and drops animal/pet/wildlife keywords; "
            "still manually spot-check before production. "
            "For Unsplash/Pexels/Pixabay, set site + source_url to the photo page, creator from the page, "
            "license as stated. CC-BY rows require visible credits in the app. "
            "Exclude subjects that read as Chinese when curating; use neutral person portrait queries only."
        ),
        "entries": entries,
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print("wrote", MANIFEST_PATH, "entries", len(entries))


if __name__ == "__main__":
    main()
