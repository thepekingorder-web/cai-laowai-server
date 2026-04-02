#!/usr/bin/env python3
"""
Import ~100 profile photos from Wikimedia Commons for Western/English-speaking countries.

Outputs to a STAGING pool (faces-pool-staging.json + assets/faces-staging/) for manual
review before merging into the main pool.

  python3 cai-laowai/tools/import_staging_western.py

Countries: Western Europe, Northern Europe, Southern Europe, US, CA, ZA, AU, NZ.
License filtering is OFF (user indicated rights are not a concern).
MediaPipe portrait check is ON to ensure single-person color profile photos.
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

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UA = (
    "cai-laowai-commons-import/3.0 (educational game; "
    "https://github.com/thepekingorder-web/cai-laowai-server)"
)

INFO_CHUNK = 45

TARGET_COUNTRIES: list[tuple[str, str, str]] = [
    # Western Europe
    ("GB", "英国", "United Kingdom"),
    ("FR", "法国", "France"),
    ("DE", "德国", "Germany"),
    ("NL", "荷兰", "Netherlands"),
    ("BE", "比利时", "Belgium"),
    ("CH", "瑞士", "Switzerland"),
    ("IE", "爱尔兰", "Ireland"),
    ("AT", "奥地利", "Austria"),
    # Northern Europe
    ("NO", "挪威", "Norway"),
    ("SE", "瑞典", "Sweden"),
    ("DK", "丹麦", "Denmark"),
    ("FI", "芬兰", "Finland"),
    ("IS", "冰岛", "Iceland"),
    # Southern Europe
    ("ES", "西班牙", "Spain"),
    ("IT", "意大利", "Italy"),
    ("PT", "葡萄牙", "Portugal"),
    ("GR", "希腊", "Greece"),
    # English-speaking / settler
    ("US", "美国", "United States"),
    ("CA", "加拿大", "Canada"),
    ("ZA", "南非", "South Africa"),
    ("AU", "澳大利亚", "Australia"),
    ("NZ", "新西兰", "New Zealand"),
]

DEMONYMS: dict[str, str] = {
    "GB": "British",
    "FR": "French",
    "DE": "German",
    "NL": "Dutch",
    "BE": "Belgian",
    "CH": "Swiss",
    "IE": "Irish",
    "AT": "Austrian",
    "NO": "Norwegian",
    "SE": "Swedish",
    "DK": "Danish",
    "FI": "Finnish",
    "IS": "Icelandic",
    "ES": "Spanish",
    "IT": "Italian",
    "PT": "Portuguese",
    "GR": "Greek",
    "US": "American",
    "CA": "Canadian",
    "ZA": "South African",
    "AU": "Australian",
    "NZ": "New Zealand",
}

EXTRA_CATEGORIES: dict[str, list[str]] = {
    "US": ["American men", "American women"],
    "GB": ["English people", "Scottish people", "Welsh people"],
    "NL": ["Dutch men", "Dutch women", "People of the Netherlands"],
    "AU": ["Australian men", "Australian women"],
    "CA": ["Canadian men", "Canadian women"],
    "NZ": ["New Zealand men", "New Zealand women", "People of New Zealand"],
    "ZA": ["South African men", "South African women"],
    "AT": ["Austrian men", "Austrian women"],
    "SE": ["Swedish men", "Swedish women", "People of Sweden"],
    "IS": ["Icelandic men", "Icelandic women", "People of Iceland"],
    "PT": ["Portuguese men", "Portuguese women", "People of Portugal"],
    "GR": ["Greek men", "Greek women", "People of Greece"],
    "IT": ["Italian men", "Italian women"],
    "FR": ["French men", "French women"],
    "FI": ["Finnish men", "Finnish women"],
    "NO": ["Norwegian men", "Norwegian women"],
    "DK": ["Danish men", "Danish women"],
    "BE": ["Belgian men", "Belgian women"],
    "CH": ["Swiss men", "Swiss women"],
    "ES": ["Spanish men", "Spanish women"],
    "IE": ["Irish men", "Irish women"],
    "CA": ["Canadian people", "Canadian men", "Canadian women"],
}

PER_COUNTRY = 5
API_DELAY = 0.12
WORKERS = 10


def categories_for(code: str, en: str) -> list[str]:
    extra = list(EXTRA_CATEGORIES.get(code, []))
    d = DEMONYMS.get(code)
    out: list[str] = list(extra)
    if d:
        out.append(f"{d} people")
    out.append(f"People of {en}")
    out.append(f"People of the {en}")
    seen: set[str] = set()
    uniq: list[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def api_post(params: dict) -> dict:
    body = urllib.parse.urlencode(params).encode("utf-8")
    req = urllib.request.Request(
        COMMONS_API,
        data=body,
        method="POST",
        headers={
            "User-Agent": UA,
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    ctx = ssl.create_default_context()
    last: Exception | None = None
    for attempt in range(4):
        try:
            time.sleep(API_DELAY)
            with urllib.request.urlopen(req, context=ctx, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as ex:
            last = ex
            time.sleep(0.6 * (attempt + 1))
    assert last is not None
    raise last


def category_file_titles(category: str, limit: int) -> list[str]:
    titles: list[str] = []
    cmcontinue: str | None = None
    cat = category if category.startswith("Category:") else f"Category:{category}"
    guard = 0
    while len(titles) < limit and guard < 25:
        guard += 1
        chunk = min(500, limit - len(titles))
        params: dict = {
            "action": "query",
            "format": "json",
            "list": "categorymembers",
            "cmtitle": cat,
            "cmnamespace": "6",
            "cmtype": "file",
            "cmlimit": chunk,
        }
        if cmcontinue:
            params["cmcontinue"] = cmcontinue
        data = api_post(params)
        q = data.get("query", {})
        for m in q.get("categorymembers", []):
            t = m.get("title")
            if t and t.startswith("File:"):
                titles.append(t)
        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
    return titles[:limit]


def imageinfo_for_titles(titles: list[str]) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for i in range(0, len(titles), INFO_CHUNK):
        chunk = titles[i : i + INFO_CHUNK]
        params = {
            "action": "query",
            "format": "json",
            "titles": "|".join(chunk),
            "prop": "imageinfo",
            "iiprop": "url|extmetadata|mime",
            "iiurlwidth": "640",
        }
        data = api_post(params)
        pages = data.get("query", {}).get("pages", {})
        for _pid, page in pages.items():
            title = page.get("title")
            ii = (page.get("imageinfo") or [{}])[0]
            if not title or not ii.get("url"):
                continue
            thumb = ii.get("thumburl") or ii.get("url")
            meta = {}
            for k, v in (ii.get("extmetadata") or {}).items():
                if isinstance(v, dict) and "value" in v:
                    meta[k] = v["value"]
            out[title] = {"thumb": thumb, "meta": meta, "mime": ii.get("mime", "")}
    return out


def credit_line(meta: dict, title: str) -> str:
    artist = re.sub(r"<[^>]+>", "", str(meta.get("Artist") or ""))[:120]
    if artist:
        return f"{artist.strip()} — {title}"
    return title


def download_to_path(url: str, dest: Path) -> bool:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=180) as r:
            dest.write_bytes(r.read())
        return dest.stat().st_size > 800
    except (urllib.error.HTTPError, urllib.error.URLError, OSError):
        return False


def slug_from_title(title: str) -> str:
    h = hashlib.sha256(title.encode("utf-8")).hexdigest()[:10]
    base = title.replace("File:", "").rsplit(".", 1)[0]
    base = re.sub(r"[^\w\-]+", "-", base, flags=re.U)[:40].strip("-").lower()
    return f"{base}-{h}" if base else h


def gather_candidates(
    code: str, zh: str, en: str, need: int, seen_files: set[str], seen_commons: set[str],
) -> list[tuple[str, Path, dict]]:
    want_titles = min(500, max(need * 30, 150))
    titles: list[str] = []
    for cat in categories_for(code, en):
        if len(titles) >= want_titles:
            break
        try:
            more = category_file_titles(cat, limit=want_titles - len(titles))
        except Exception as ex:
            tqdm.write(f"  {code} {cat} category error: {ex}")
            continue
        for t in more:
            if t not in titles:
                titles.append(t)

    if not titles:
        return []

    try:
        infos = imageinfo_for_titles(titles)
    except Exception as ex:
        tqdm.write(f"  {code} imageinfo error: {ex}")
        return []

    pending: list[tuple[str, Path, dict]] = []
    for title, info in infos.items():
        if len(pending) >= max(need * 40, 120):
            break
        if title_likely_non_portrait(title.replace("File:", "")):
            continue
        mime = info.get("mime") or ""
        if "svg" in mime or "image/gif" in mime:
            continue
        meta = info["meta"]
        page_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
            title.replace(" ", "_")
        )
        if page_url in seen_commons:
            continue
        slug = slug_from_title(title)
        fname = f"{code.lower()}-{slug}.jpg"
        rel = f"faces-staging/{fname}"
        if rel in seen_files:
            continue
        dest = ASSETS_FACES / fname
        lic = str(meta.get("LicenseShortName") or meta.get("License") or "See source")[:80]
        row = {
            "id": f"{code.lower()}-{slug}",
            "file": rel,
            "code": code,
            "zh": zh,
            "source": "wikimedia",
            "license": lic,
            "credit": credit_line(meta, title)[:200],
            "source_url": page_url,
            "reviewed": False,
            "note": "staging import — review before merging to main pool",
        }
        pending.append((info["thumb"], dest, row))

    return pending


def download_and_check(
    pending: list[tuple[str, Path, dict]], need: int, face_check: bool, face_kw: dict,
) -> list[dict]:
    accepted: list[dict] = []
    if not pending:
        return accepted

    batch = pending[: max(need * 25, 80)]
    results: list[tuple[bool, Path, dict]] = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futs = {pool.submit(download_to_path, url, dest): (dest, row) for url, dest, row in batch}
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
            good, reason = is_profile_portrait(
                dest, **face_kw
            )
            if not good:
                dest.unlink(missing_ok=True)
                continue
        accepted.append(row)
        tqdm.write(f"  + {row['code']} {dest.name}")

    return accepted


def write_staging_pool(entries: list[dict]) -> None:
    payload = {
        "version": int(datetime.now(timezone.utc).timestamp()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "wikimedia-commons",
        "pool_policy": "staging_western_countries_profile_v1",
        "notes": (
            "STAGING pool — Western/Northern/Southern Europe + US/CA/ZA/AU/NZ. "
            "Review in pool-qa.html?pool=staging before merging to main pool."
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
    ap.add_argument("--per-country", type=int, default=PER_COUNTRY)
    ap.add_argument("--no-face-check", action="store_true")
    ap.add_argument("--relaxed-face", action="store_true")
    args = ap.parse_args()

    face_kw = {
        "min_face_area": 0.025,
        "max_face_area": 0.72,
        "min_short_side_px": 160,
        "allow_dominant_face": True,
    }
    if args.relaxed_face:
        face_kw["min_face_area"] = 0.018
        face_kw["min_short_side_px"] = 120

    face_check = not args.no_face_check

    existing: list[dict] = []
    if OUT_JSON.exists():
        try:
            existing = json.loads(OUT_JSON.read_text(encoding="utf-8")).get("entries") or []
        except Exception:
            existing = []

    seen_files = {e.get("file") for e in existing if e.get("file")}
    seen_commons = {e.get("source_url", "") for e in existing}
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
        print(f"All {len(TARGET_COUNTRIES)} countries already have >= {args.per_country} photos.")
        print(f"Total entries: {len(entries)}")
        return

    print(f"Target: {args.per_country} per country, {len(work)} countries need more photos")
    print(f"Existing staging entries: {len(entries)}")
    print(f"Face check: {'ON' if face_check else 'OFF'}")
    print()

    try:
        for code, zh, en, need in tqdm(work, desc="Countries", unit="cty"):
            pending = gather_candidates(code, zh, en, need, seen_files, seen_commons)
            accepted = download_and_check(pending, need, face_check, face_kw)

            for row in accepted:
                entries.append(row)
                seen_files.add(row["file"])
                seen_commons.add(row["source_url"])
                total_new += 1

            if len(accepted) < need:
                tqdm.write(f"  {code} ({en}): only {len(accepted)}/{need}")

            write_staging_pool(entries)
    finally:
        close_detector()

    write_staging_pool(entries)
    counts_final = Counter((e.get("code") or "") for e in entries)
    print()
    print(f"Done. {len(entries)} total entries ({total_new} new this run) -> {OUT_JSON}")
    print()
    for code, zh, en in TARGET_COUNTRIES:
        n = counts_final.get(code, 0)
        mark = "OK" if n >= args.per_country else "SHORT"
        print(f"  {code} {en:<20s} {n:>3d}  {mark}")
    print()
    print(f"Review at: /pool-qa.html?pool=staging")


if __name__ == "__main__":
    main()
