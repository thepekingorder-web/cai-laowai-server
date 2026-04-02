#!/usr/bin/env python3
"""
Import from Wikimedia Commons → cai-laowai/assets/faces/ + faces-pool.json.

• Prioritizes countries below --min-per-country, then fills to --min-total (round-robin).
• Default: --seed-zeros runs first (1 image per country with 0 rows, wider license match).
• Keeps only single-human, portrait-scale faces (MediaPipe) unless --no-face-check.
• Progress: tqdm bars + per-accept lines.

  python3 cai-laowai/tools/import_commons_faces.py \\
    --min-per-country 3 --min-total 500 --max-new-per-run 2500 --workers 12

  # If Commons + strict portraits are too slow, try:
  #   --relaxed-face
  # or tune: --face-min-area 0.022 --face-min-short-side 140 --allow-dominant-face

Re-run without --replace-pool to merge; dedupes by source_url and file path.
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

from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ASSETS_FACES = ROOT / "assets" / "faces"
OUT_JSON = DATA / "faces-pool.json"

# Set in main() before any write_pool_json (policy + notes for this run).
_pool_export_meta: dict[str, str] = {}
_row_note_import: str = "commons import — profile filter; verify country in pool-review"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from countries_bundle import COUNTRIES, categories_for, population_index  # noqa: E402
from profile_face_check import close_detector, is_profile_portrait, title_likely_non_portrait  # noqa: E402

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
UA = (
    "cai-laowai-commons-import/2.1 (educational game; "
    "https://github.com/thepekingorder-web/cai-laowai-server)"
)
ALLOW_LICENSE = re.compile(
    r"cc\s*by|cc0|public\s*domain|pd-|gnu\s*free|no\s*restrictions|"
    r"attribution",
    re.I,
)
# Extra matches for --seed-zeros only (still free to adapt if SA/GFDL; never NC/ND).
ALLOW_LICENSE_SEED = re.compile(
    r"gfdl|gnu\s*free\s*documentation|free\s*documentation\s*license|"
    r"free\s*art\s*license|\bfal\b|cc\s*by-sa|cc-by-sa|share\s*alike|"
    r"open\s*government|ogl\b|expat|mit\s*license|bsd\s*license",
    re.I,
)
DISALLOW_LICENSE = re.compile(r"non-commercial|noncommercial|nc-|no\s*deriv|nd\b", re.I)
DISALLOW_LICENSE_SEED = re.compile(
    r"all\s*rights\s*reserved|copyrighted\s*free\s*use|fair\s*use|"
    r"permission\s*required|do\s*not\s*copy",
    re.I,
)

INFO_CHUNK = 45


def api_post(params: dict, api_delay: float) -> dict:
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
            time.sleep(api_delay)
            with urllib.request.urlopen(req, context=ctx, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))
        except Exception as ex:
            last = ex
            time.sleep(0.6 * (attempt + 1))
    assert last is not None
    raise last


def category_file_titles(category: str, limit: int, api_delay: float) -> list[str]:
    titles: list[str] = []
    cmcontinue: str | None = None
    cat = category if category.startswith("Category:") else f"Category:{category}"
    guard = 0
    while len(titles) < limit and guard < 25:
        guard += 1
        chunk = min(500, limit - len(titles))
        params: dict[str, str | int] = {
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
        data = api_post(params, api_delay)
        q = data.get("query", {})
        for m in q.get("categorymembers", []):
            t = m.get("title")
            if t and t.startswith("File:"):
                titles.append(t)
        cmcontinue = data.get("continue", {}).get("cmcontinue")
        if not cmcontinue:
            break
    return titles[:limit]


def imageinfo_for_titles(titles: list[str], api_delay: float) -> dict[str, dict]:
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
        data = api_post(params, api_delay)
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


def license_ok(meta: dict) -> bool:
    blob = " ".join(str(meta.get(k, "")) for k in ("LicenseShortName", "UsageTerms", "License"))
    if DISALLOW_LICENSE.search(blob):
        return False
    return bool(ALLOW_LICENSE.search(blob))


def license_ok_seed(meta: dict) -> bool:
    """Wider net for countries with 0 photos; still blocks NC/ND and obvious no-redistribution."""
    blob = " ".join(str(meta.get(k, "")) for k in ("LicenseShortName", "UsageTerms", "License"))
    if DISALLOW_LICENSE.search(blob) or DISALLOW_LICENSE_SEED.search(blob):
        return False
    if ALLOW_LICENSE.search(blob) or ALLOW_LICENSE_SEED.search(blob):
        return True
    return False


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


def count_by_code(entries: list[dict]) -> Counter[str]:
    return Counter((e.get("code") or "") for e in entries)


def country_phase_need(
    entries: list[dict], min_per: int, min_total: int, phase: str
) -> list[tuple[str, str, str, int]]:
    """
    Return list of (code, zh, en, need) for this phase.
    phase 'min': each country below min_per (population order).
    phase 'fill': each country gets need=1 while total < min_total (one sweep).
    """
    counts = count_by_code(entries)
    out: list[tuple[str, str, str, int]] = []
    if phase == "min":
        for code, zh, en in COUNTRIES:
            have = counts.get(code, 0)
            need = max(0, min_per - have)
            if need > 0:
                out.append((code, zh, en, need))
        return out
    if phase == "fill":
        if len(entries) >= min_total:
            return []
        for code, zh, en in COUNTRIES:
            out.append((code, zh, en, 1))
        return out
    raise ValueError(phase)


def gather_pending_rows(
    code: str,
    zh: str,
    en: str,
    need: int,
    candidate_mult: int,
    api_delay: float,
    seen_files: set[str],
    seen_commons: set[str],
    *,
    license_fn=license_ok,
    row_note: str | None = None,
    skip_title_filter: bool = False,
) -> list[tuple[str, Path, dict]]:
    want_titles = min(500, max(need * candidate_mult, need * 10))
    titles: list[str] = []
    for cat in categories_for(code, en):
        if len(titles) >= want_titles:
            break
        try:
            more = category_file_titles(cat, limit=want_titles - len(titles), api_delay=api_delay)
        except Exception as ex:
            tqdm.write(f"{code} {cat} category error: {ex}")
            continue
        for t in more:
            if t not in titles:
                titles.append(t)

    if not titles:
        return []

    try:
        infos = imageinfo_for_titles(titles, api_delay=api_delay)
    except Exception as ex:
        tqdm.write(f"{code} imageinfo error: {ex}")
        return []

    pending: list[tuple[str, Path, dict]] = []
    for title, info in infos.items():
        if len(pending) >= max(need * 20, 96):
            break
        if not skip_title_filter and title_likely_non_portrait(title.replace("File:", "")):
            continue
        meta = info["meta"]
        mime = info.get("mime") or ""
        if "svg" in mime or "image/gif" in mime:
            continue
        if not license_fn(meta):
            continue
        page_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
            title.replace(" ", "_")
        )
        if page_url in seen_commons:
            continue
        slug = slug_from_title(title)
        fname = f"{code.lower()}-{slug}.jpg"
        rel = f"faces/{fname}"
        if rel in seen_files:
            continue
        dest = ASSETS_FACES / fname
        lic = str(meta.get("LicenseShortName") or meta.get("License") or "See source")[:80]
        note = row_note if row_note is not None else _row_note_import
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
            "note": note,
        }
        pending.append((info["thumb"], dest, row))

    return pending


def write_pool_json(entries: list[dict]) -> None:
    policy = _pool_export_meta.get("pool_policy") or "self_hosted_faces_100_countries_profile_v1"
    notes = _pool_export_meta.get("notes") or (
        "Images from Wikimedia Commons; single-face portrait filter on import. "
        "Set reviewed:true in pool-review after QA. See cai-laowai/ATTRIBUTION.md."
    )
    payload = {
        "version": int(datetime.now(timezone.utc).timestamp()),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "wikimedia-commons",
        "pool_policy": policy,
        "notes": notes,
        "entries": entries,
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def download_and_maybe_accept(
    pending: list[tuple[str, Path, dict]],
    need: int,
    workers: int,
    face_check: bool,
    face_kw: dict,
) -> list[dict]:
    """Download candidates in parallel, then portrait-check sequentially (avoids thread + MediaPipe issues)."""
    accepted: list[dict] = []
    if not pending:
        return accepted

    batch = pending[: max(need * 10, 48)]
    results: list[tuple[bool, Path, dict]] = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futs = {pool.submit(download_to_path, url, dest): (dest, row) for url, dest, row in batch}
        for fut in as_completed(futs):
            dest, row = futs[fut]
            try:
                ok_dl = fut.result()
            except Exception:
                ok_dl = False
            results.append((ok_dl, dest, row))

    with tqdm(total=len(results), desc="    tries", leave=False, unit="img") as pbar:
        for ok_dl, dest, row in results:
            if len(accepted) >= need:
                break
            if not ok_dl:
                pbar.update(1)
                continue
            if face_check:
                good, reason = is_profile_portrait(dest, **face_kw)
                if not good:
                    dest.unlink(missing_ok=True)
                    pbar.update(1)
                    pbar.set_postfix_str(reason[:20], refresh=False)
                    continue
            accepted.append(row)
            pbar.update(1)
            pbar.set_postfix_str(f"+{row['code']}", refresh=False)
            tqdm.write(f"  accept {row['code']} {dest.name}")
    return accepted


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-per-country", type=int, default=3, help="minimum photos per top-100 country")
    ap.add_argument("--min-total", type=int, default=500, help="minimum rows in pool when filling")
    ap.add_argument(
        "--max-new-per-run",
        type=int,
        default=2500,
        help="stop after this many NEW rows accepted this run",
    )
    ap.add_argument("--candidate-mult", type=int, default=8)
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--api-delay", type=float, default=0.1)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--replace-pool", action="store_true")
    ap.add_argument("--no-face-check", action="store_true", help="skip MediaPipe portrait filter")
    ap.add_argument(
        "--face-min-area",
        type=float,
        default=0.032,
        help="min face bbox area as fraction of image (lower = allow smaller / farther faces)",
    )
    ap.add_argument(
        "--face-max-area",
        type=float,
        default=0.72,
        help="max face bbox area fraction (raise slightly for tight headshots)",
    )
    ap.add_argument(
        "--face-min-short-side",
        type=int,
        default=180,
        help="reject images whose shorter side is below this (pixels)",
    )
    ap.add_argument(
        "--allow-dominant-face",
        action="store_true",
        help="if exactly 2 faces and the smaller is tiny vs the larger, keep the larger",
    )
    ap.add_argument(
        "--relaxed-face",
        action="store_true",
        help="shortcut: looser min area/short side + allow-dominant-face (still single main face)",
    )
    ap.add_argument(
        "--population-order",
        action="store_true",
        help="visit short countries in population order (default: breadth-first — fewest photos first, "
        "then smaller-list countries before megadiverse ones)",
    )
    ap.add_argument(
        "--no-seed-zeros",
        action="store_true",
        help="skip the opening pass that tries to add 1 photo per country with 0 rows (wider license match)",
    )
    ap.add_argument(
        "--relaxed-license",
        action="store_true",
        help="use wider license matcher (same as seed pass) for every row — noisier; QA recommended",
    )
    ap.add_argument(
        "--relaxed-title",
        action="store_true",
        help="skip title heuristics that reject group shots, cartoons, etc. — more junk; use with QA",
    )
    args = ap.parse_args()
    if args.relaxed_face:
        args.face_min_area = min(args.face_min_area, 0.022)
        args.face_min_short_side = min(args.face_min_short_side, 140)
        args.allow_dominant_face = True

    existing: list[dict] = []
    if not args.replace_pool and OUT_JSON.exists():
        try:
            existing = json.loads(OUT_JSON.read_text(encoding="utf-8")).get("entries") or []
        except Exception:
            existing = []

    seen_files = {e.get("file") for e in existing if e.get("file")}
    seen_commons = {e.get("source_url", "") for e in existing}
    entries = list(existing)
    total_new = 0
    api_delay = max(0.0, args.api_delay)
    face_check = not args.no_face_check
    face_kw = {
        "min_face_area": args.face_min_area,
        "max_face_area": args.face_max_area,
        "min_short_side_px": args.face_min_short_side,
        "allow_dominant_face": args.allow_dominant_face,
    }

    lic_fn = license_ok_seed if args.relaxed_license else license_ok
    title_kw = {"skip_title_filter": args.relaxed_title}

    global _pool_export_meta, _row_note_import
    if args.no_face_check:
        pol = "self_hosted_faces_100_countries_bulk_noface_v1"
        note_bits = [
            "Bulk Commons import WITHOUT portrait ML filter (speed run). "
            "Expect some group shots/non-portraits — run tools/prune_non_profile_faces.py "
            "and/or pool-qa.html. See cai-laowai/ATTRIBUTION.md.",
        ]
        if args.relaxed_license:
            pol += "_relaxed_license"
            note_bits.append("Relaxed license matcher (--relaxed-license).")
        if args.relaxed_title:
            pol += "_relaxed_title"
            note_bits.append("Title heuristics off (--relaxed-title); more non-portraits possible.")
        _pool_export_meta = {"pool_policy": pol, "notes": " ".join(note_bits)}
        _row_note_import = "commons bulk import — no portrait filter; QA country + image"
        if args.relaxed_license or args.relaxed_title:
            _row_note_import += "; relaxed filters"
    else:
        _pool_export_meta = {}
        _row_note_import = "commons import — profile filter; verify country in pool-review"

    try:
        if args.dry_run:
            counts = count_by_code(entries)
            need_min = country_phase_need(entries, args.min_per_country, args.min_total, "min")
            print("Dry run — would process (code, need):", need_min[:15], "…" if len(need_min) > 15 else "")
            print("Countries below min:", sum(1 for c in counts if c and counts[c] < args.min_per_country))
            print("Total entries:", len(entries), "target min_total:", args.min_total)
            zc = sum(1 for c, _, _ in COUNTRIES if counts.get(c, 0) == 0)
            print("Zero-coverage countries:", zc, "(seed pass would run)" if not args.no_seed_zeros else "")
            return

        if not args.no_seed_zeros:
            counts = count_by_code(entries)
            zeros = [(c, zh, en) for c, zh, en in COUNTRIES if counts.get(c, 0) == 0]
            if zeros and total_new < args.max_new_per_run:
                zeros.sort(key=lambda t: -population_index(t[0]))
                seed_note = (
                    "commons seed (zero-coverage) — wider license match; double-check attribution & country"
                )
                for code, zh, en in tqdm(zeros, desc="Seed 1× zero-coverage countries", unit="cty"):
                    if total_new >= args.max_new_per_run:
                        break
                    need_run = 1
                    pending = gather_pending_rows(
                        code,
                        zh,
                        en,
                        need_run,
                        max(args.candidate_mult, 12),
                        api_delay,
                        seen_files,
                        seen_commons,
                        license_fn=license_ok_seed,
                        row_note=seed_note,
                        **title_kw,
                    )
                    accepted = download_and_maybe_accept(
                        pending, need_run, args.workers, face_check, face_kw
                    )
                    for row in accepted:
                        entries.append(row)
                        seen_files.add(row["file"])
                        seen_commons.add(row["source_url"])
                        total_new += 1
                    if len(accepted) < need_run:
                        tqdm.write(f"{code} seed only {len(accepted)}/{need_run}")
                    write_pool_json(entries)

        fill_stalls = 0
        while total_new < args.max_new_per_run:
            counts = count_by_code(entries)
            below_min = [(c, zh, en) for c, zh, en in COUNTRIES if counts.get(c, 0) < args.min_per_country]

            if below_min:
                work = [(c, zh, en, args.min_per_country - counts[c]) for c, zh, en in below_min]
                if not args.population_order:
                    work.sort(key=lambda w: (counts.get(w[0], 0), -population_index(w[0])))
                phase_label = f"min>={args.min_per_country} ({len(below_min)} countries short)"
            elif len(entries) < args.min_total:
                work = [(c, zh, en, 1) for c, zh, en in COUNTRIES]
                if not args.population_order:
                    work.sort(key=lambda w: (counts.get(w[0], 0), -population_index(w[0])))
                phase_label = f"fill toward {args.min_total} (pool {len(entries)})"
            else:
                print("Pool already meets min-per-country and min-total.")
                break

            before = total_new
            desc = f"Import [{phase_label}]"
            for code, zh, en, need in tqdm(work, desc=desc, unit="cty"):
                if total_new >= args.max_new_per_run:
                    break
                counts_now = count_by_code(entries)
                if below_min and counts_now.get(code, 0) >= args.min_per_country:
                    continue
                if not below_min and len(entries) >= args.min_total:
                    break
                rem = args.max_new_per_run - total_new
                need_run = min(need, rem)

                pending = gather_pending_rows(
                    code,
                    zh,
                    en,
                    need_run,
                    args.candidate_mult,
                    api_delay,
                    seen_files,
                    seen_commons,
                    license_fn=lic_fn,
                    **title_kw,
                )
                accepted = download_and_maybe_accept(
                    pending, need_run, args.workers, face_check, face_kw
                )

                for row in accepted:
                    entries.append(row)
                    seen_files.add(row["file"])
                    seen_commons.add(row["source_url"])
                    total_new += 1

                if len(accepted) < need_run:
                    tqdm.write(f"{code} only {len(accepted)}/{need_run} (candidates / license / portrait)")

                write_pool_json(entries)

            gained = total_new - before
            if gained == 0:
                fill_stalls += 1
                if fill_stalls >= 4:
                    if below_min:
                        tqdm.write(
                            "Stopping: min-per-country sweeps made no progress (check categories, licenses, or network)."
                        )
                    else:
                        tqdm.write("Stopping: fill sweeps made no progress (Commons exhausted or rate-limited).")
                    break
            else:
                fill_stalls = 0
    finally:
        close_detector()

    write_pool_json(entries)
    print("Wrote", len(entries), "entries (", total_new, "new this run) ->", OUT_JSON)


if __name__ == "__main__":
    main()
