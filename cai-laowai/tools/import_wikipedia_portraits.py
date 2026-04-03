#!/usr/bin/env python3
"""
Import profile photos from Wikipedia article thumbnails into the staging pool.

Instead of browsing random Wikimedia Commons uploads, this pulls the main editorial
portrait from Wikipedia articles about people from each target country. Articles
about living/modern people have much better color headshots than Commons categories.

  python3 cai-laowai/tools/import_wikipedia_portraits.py --per-country 6

Categories tried per country (in order):
  1. "21st-century {nationality} people"  — modern people, modern photos
  2. "{nationality} people"               — broader fallback
  3. Various occupation subcategories      — actors, politicians, etc.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ASSETS_FACES = ROOT / "assets" / "faces-staging"
OUT_JSON = DATA / "faces-pool-staging.json"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from profile_face_check import close_detector, is_profile_portrait, title_likely_non_portrait  # noqa: E402
from pool_quality_filter import is_grayscale, is_cartoon_or_drawing  # noqa: E402

WIKI_API = "https://en.wikipedia.org/w/api.php"
UA = "cai-laowai-wp-import/1.0 (educational game)"
THUMB_SIZE = 640
WORKERS = 10

TARGET_COUNTRIES: list[tuple[str, str, str]] = [
    ("GB", "英国", "United Kingdom"),
    ("FR", "法国", "France"),
    ("DE", "德国", "Germany"),
    ("NL", "荷兰", "Netherlands"),
    ("BE", "比利时", "Belgium"),
    ("CH", "瑞士", "Switzerland"),
    ("IE", "爱尔兰", "Ireland"),
    ("AT", "奥地利", "Austria"),
    ("NO", "挪威", "Norway"),
    ("SE", "瑞典", "Sweden"),
    ("DK", "丹麦", "Denmark"),
    ("FI", "芬兰", "Finland"),
    ("IS", "冰岛", "Iceland"),
    ("ES", "西班牙", "Spain"),
    ("IT", "意大利", "Italy"),
    ("PT", "葡萄牙", "Portugal"),
    ("GR", "希腊", "Greece"),
    ("US", "美国", "United States"),
    ("CA", "加拿大", "Canada"),
    ("ZA", "南非", "South Africa"),
    ("AU", "澳大利亚", "Australia"),
    ("NZ", "新西兰", "New Zealand"),
]

DEMONYMS: dict[str, str] = {
    "GB": "British", "FR": "French", "DE": "German", "NL": "Dutch",
    "BE": "Belgian", "CH": "Swiss", "IE": "Irish", "AT": "Austrian",
    "NO": "Norwegian", "SE": "Swedish", "DK": "Danish", "FI": "Finnish",
    "IS": "Icelandic", "ES": "Spanish", "IT": "Italian", "PT": "Portuguese",
    "GR": "Greek", "US": "American", "CA": "Canadian", "ZA": "South African",
    "AU": "Australian", "NZ": "New Zealand",
}

OCCUPATION_CATS: dict[str, list[str]] = {
    "GB": ["British male actors", "British female actors", "British politicians"],
    "FR": ["French male actors", "French female actors", "French politicians"],
    "DE": ["German male actors", "German female actors", "German politicians"],
    "US": ["American male actors", "American female actors", "American politicians"],
    "IT": ["Italian male actors", "Italian female actors"],
    "ES": ["Spanish male actors", "Spanish female actors"],
    "AU": ["Australian male actors", "Australian female actors"],
    "CA": ["Canadian male actors", "Canadian female actors"],
    "NL": ["Dutch male actors", "Dutch female actors"],
    "SE": ["Swedish male actors", "Swedish female actors"],
    "NO": ["Norwegian male actors", "Norwegian female actors"],
    "DK": ["Danish male actors", "Danish female actors"],
    "AT": ["Austrian male actors", "Austrian female actors"],
    "PT": ["Portuguese male actors", "Portuguese female actors"],
    "NZ": ["New Zealand male actors", "New Zealand female actors"],
    "ZA": ["South African male actors", "South African female actors"],
    "BE": ["Belgian male actors", "Belgian female actors"],
    "FI": ["Finnish male actors", "Finnish female actors"],
    "CH": ["Swiss male actors", "Swiss female actors"],
    "IE": ["Irish male actors", "Irish female actors"],
    "GR": ["Greek male actors", "Greek female actors"],
    "IS": ["Icelandic male actors", "Icelandic female actors"],
}


def categories_for(code: str) -> list[str]:
    d = DEMONYMS.get(code, "")
    cats = []
    if d:
        cats.append(f"21st-century {d} people")
        cats.append(f"{d} people")
    cats.extend(OCCUPATION_CATS.get(code, []))
    return cats


def api_get(params: dict) -> dict:
    params["format"] = "json"
    url = WIKI_API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    ctx = ssl.create_default_context()
    for attempt in range(3):
        try:
            time.sleep(0.15)
            with urllib.request.urlopen(req, context=ctx, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as ex:
            if attempt == 2:
                raise
            time.sleep(0.5 * (attempt + 1))
    return {}


def get_article_thumbnails(category: str, limit: int = 100) -> list[dict]:
    """Get article pages in a category with their main thumbnail image."""
    results = []
    gcmcontinue = None
    cat = category if category.startswith("Category:") else f"Category:{category}"
    guard = 0

    while len(results) < limit and guard < 8:
        guard += 1
        params: dict = {
            "action": "query",
            "generator": "categorymembers",
            "gcmtitle": cat,
            "gcmtype": "page",
            "gcmnamespace": "0",
            "gcmlimit": str(min(50, limit - len(results))),
            "prop": "pageimages|info",
            "piprop": "thumbnail|name",
            "pithumbsize": str(THUMB_SIZE),
            "inprop": "url",
        }
        if gcmcontinue:
            params["gcmcontinue"] = gcmcontinue

        data = api_get(params)
        pages = data.get("query", {}).get("pages", {})
        for _pid, page in pages.items():
            title = page.get("title", "")
            thumb = page.get("thumbnail", {})
            thumb_url = thumb.get("source", "")
            page_img = page.get("pageimage", "")
            if thumb_url and page_img:
                results.append({
                    "title": title,
                    "thumb_url": thumb_url,
                    "page_image": page_img,
                    "article_url": page.get("fullurl", ""),
                })

        gcmcontinue = data.get("continue", {}).get("gcmcontinue")
        if not gcmcontinue:
            break

    return results[:limit]


def slug_from_title(title: str) -> str:
    h = hashlib.sha256(title.encode("utf-8")).hexdigest()[:10]
    base = re.sub(r"[^\w\-]+", "-", title, flags=re.U)[:40].strip("-").lower()
    return f"{base}-{h}" if base else h


def download_to_path(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=120) as r:
            dest.write_bytes(r.read())
        return dest.stat().st_size > 800
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return False


def gather_candidates(
    code: str, need: int, seen_slugs: set[str], seen_articles: set[str],
) -> list[tuple[str, Path, dict]]:
    pending: list[tuple[str, Path, dict]] = []
    cats = categories_for(code)
    zh = dict((c, z) for c, z, _ in TARGET_COUNTRIES).get(code, code)

    for cat in cats:
        if len(pending) >= need * 30:
            break
        try:
            articles = get_article_thumbnails(cat, limit=min(200, need * 40))
        except Exception as ex:
            tqdm.write(f"  {code} {cat}: error {ex}")
            continue

        for art in articles:
            if len(pending) >= need * 30:
                break
            if art["article_url"] in seen_articles:
                continue
            if title_likely_non_portrait(art["page_image"]):
                continue

            slug = slug_from_title(art["title"])
            fname = f"{code.lower()}-{slug}.jpg"
            rel = f"faces-staging/{fname}"
            if rel in seen_slugs:
                continue

            dest = ASSETS_FACES / fname
            row = {
                "id": f"{code.lower()}-{slug}",
                "file": rel,
                "code": code,
                "zh": zh,
                "source": "wikipedia",
                "license": "See source",
                "credit": art["title"],
                "source_url": art["article_url"],
                "reviewed": False,
                "note": "wikipedia portrait import — review before merging",
            }
            pending.append((art["thumb_url"], dest, row))

    return pending


def download_and_check(
    pending: list[tuple[str, Path, dict]], need: int,
    face_check: bool, face_kw: dict,
) -> list[dict]:
    accepted: list[dict] = []
    if not pending:
        return accepted

    batch = pending[: max(need * 20, 60)]
    results: list[tuple[bool, Path, dict]] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(download_to_path, url, dest): (dest, row)
                for url, dest, row in batch}
        for fut in as_completed(futs):
            dest, row = futs[fut]
            try:
                ok_dl = fut.result()
            except Exception:
                ok_dl = False
            results.append((ok_dl, dest, row))

    for ok_dl, dest, row in results:
        if len(accepted) >= need:
            break
        if not ok_dl:
            continue

        img_data = np.fromfile(str(dest), dtype=np.uint8)
        img = cv2.imdecode(img_data, cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            dest.unlink(missing_ok=True)
            continue
        if is_grayscale(img):
            dest.unlink(missing_ok=True)
            continue
        is_cart, _ = is_cartoon_or_drawing(img)
        if is_cart:
            dest.unlink(missing_ok=True)
            continue
        if face_check:
            good, reason = is_profile_portrait(dest, **face_kw)
            if not good:
                dest.unlink(missing_ok=True)
                continue

        # Normalize to max 640px
        h, w = img.shape[:2]
        longest = max(h, w)
        if longest > 640:
            scale = 640 / longest
            img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(dest), img, [cv2.IMWRITE_JPEG_QUALITY, 88])

        accepted.append(row)
        tqdm.write(f"  + {row['code']} {row['credit']}")

    return accepted


def write_staging_pool(entries: list[dict]) -> None:
    payload = {
        "version": int(datetime.now(timezone.utc).timestamp()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "wikipedia-portraits",
        "pool_policy": "staging_wikipedia_portraits_v1",
        "notes": (
            "STAGING pool — Wikipedia article portraits for Western/English-speaking countries. "
            "Review in /staging-qa.html before merging to main pool."
        ),
        "entries": entries,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-country", type=int, default=6)
    ap.add_argument("--no-face-check", action="store_true")
    ap.add_argument("--relaxed-face", action="store_true")
    args = ap.parse_args()

    face_kw = {
        "min_face_area": 0.025,
        "max_face_area": 0.75,
        "min_short_side_px": 140,
        "allow_dominant_face": True,
    }
    if args.relaxed_face:
        face_kw["min_face_area"] = 0.015
        face_kw["min_short_side_px"] = 100

    face_check = not args.no_face_check

    # Load existing staging pool (or start fresh)
    existing: list[dict] = []
    if OUT_JSON.exists():
        try:
            existing = json.loads(OUT_JSON.read_text(encoding="utf-8")).get("entries") or []
        except Exception:
            existing = []

    # Also load main pool to cross-dedupe
    main_pool_path = DATA / "faces-pool.json"
    main_urls: set[str] = set()
    if main_pool_path.exists():
        try:
            mp = json.loads(main_pool_path.read_text(encoding="utf-8"))
            main_urls = {e.get("source_url", "") for e in mp.get("entries", []) if e.get("source_url")}
        except Exception:
            pass

    seen_slugs = {e.get("file") for e in existing if e.get("file")}
    seen_articles = {e.get("source_url", "") for e in existing} | main_urls
    entries = list(existing)
    total_new = 0

    ASSETS_FACES.mkdir(parents=True, exist_ok=True)

    counts = Counter((e.get("code") or "") for e in entries)
    work = [
        (code, zh, en, max(0, args.per_country - counts.get(code, 0)))
        for code, zh, en in TARGET_COUNTRIES
    ]
    work = [(c, z, e, n) for c, z, e, n in work if n > 0]
    work.sort(key=lambda w: counts.get(w[0], 0))

    if not work:
        print(f"All countries already have >= {args.per_country} photos.")
        return

    print(f"Source: Wikipedia article portraits")
    print(f"Target: {args.per_country} per country, {len(work)} countries need more")
    print(f"Existing staging: {len(entries)}, Face check: {'ON' if face_check else 'OFF'}")
    print(f"Cross-deduping against {len(main_urls)} main pool source URLs")
    print()

    try:
        for code, zh, en, need in tqdm(work, desc="Countries", unit="cty"):
            pending = gather_candidates(code, need, seen_slugs, seen_articles)
            accepted = download_and_check(pending, need, face_check, face_kw)

            for row in accepted:
                entries.append(row)
                seen_slugs.add(row["file"])
                seen_articles.add(row["source_url"])
                total_new += 1

            if len(accepted) < need:
                tqdm.write(f"  {code} ({en}): only {len(accepted)}/{need}")

            write_staging_pool(entries)
    finally:
        close_detector()

    # Clean orphan files
    referenced = {e["file"].replace("faces-staging/", "") for e in entries if e.get("file")}
    for f in ASSETS_FACES.iterdir():
        if f.is_file() and f.name not in referenced:
            f.unlink()

    write_staging_pool(entries)
    counts_final = Counter((e.get("code") or "") for e in entries)
    print()
    print(f"Done. {len(entries)} total ({total_new} new) -> {OUT_JSON}")
    print()
    for code, zh, en in TARGET_COUNTRIES:
        n = counts_final.get(code, 0)
        mark = "OK" if n >= args.per_country else "SHORT"
        print(f"  {code} {en:<20s} {n:>3d}  {mark}")


if __name__ == "__main__":
    main()
