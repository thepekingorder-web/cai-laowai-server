"""
猜老外 (cai-laowai) — standalone app. No GotEyes / cameras / WhatsApp code.
"""
from __future__ import annotations

import json
import logging
import mimetypes
import sys
import threading
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
GAME = ROOT / "cai-laowai"
DATA = GAME / "data"
ASSETS = GAME / "assets"

_TOOLS = str(GAME / "tools")
if _TOOLS not in sys.path:
    sys.path.insert(0, _TOOLS)
from countries_bundle import COUNTRIES  # noqa: E402

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="cai-laowai")

_MIN_PER_COUNTRY = 3
_MIN_TOTAL = 500


@app.get("/")
def root_page():
    p = GAME / "index.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="index.html missing")
    return FileResponse(str(p), media_type="text/html; charset=utf-8")


@app.get("/pool-review.html")
def pool_review_page():
    p = GAME / "pool-review.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="pool-review.html missing")
    return FileResponse(str(p), media_type="text/html; charset=utf-8")


@app.get("/pool-qa.html")
def pool_qa_page():
    """One-by-one photo review: country + reviewed; download JSON for the repo."""
    p = GAME / "pool-qa.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="pool-qa.html missing")
    return FileResponse(str(p), media_type="text/html; charset=utf-8")


def _pool_progress_payload() -> dict:
    p = DATA / "faces-pool.json"
    if not p.exists():
        return {"error": "No faces-pool.json yet."}
    raw = json.loads(p.read_text(encoding="utf-8"))
    entries = list(raw.get("entries") or [])
    codes_top100 = [c[0] for c in COUNTRIES]
    top_set = set(codes_top100)
    counts = Counter(e.get("code") or "?" for e in entries)
    in_top100 = sum(1 for e in entries if e.get("code") in top_set)
    countries_with_any = len([c for c in codes_top100 if counts.get(c, 0) > 0])
    missing_min = [c for c in codes_top100 if counts.get(c, 0) < _MIN_PER_COUNTRY]
    ok_total = len(entries) >= _MIN_TOTAL
    ok_cov = len(missing_min) == 0
    pct_total = min(100, int(round(100 * len(entries) / max(_MIN_TOTAL, 1))))
    pct_cov = min(100, int(round(100 * (len(codes_top100) - len(missing_min)) / len(codes_top100))))
    log_path = GAME / "tools" / "import_grow.log"
    log_hint = ""
    if log_path.exists():
        m = log_path.stat().st_mtime
        log_hint = datetime.fromtimestamp(m, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return {
        "error": None,
        "total": len(entries),
        "in_top100": in_top100,
        "countries_represented": countries_with_any,
        "below_min_count": len(missing_min),
        "missing_min": missing_min,
        "counts": counts,
        "min_total": _MIN_TOTAL,
        "min_per": _MIN_PER_COUNTRY,
        "top100_n": len(codes_top100),
        "ok_total": ok_total,
        "ok_cov": ok_cov,
        "pct_total": pct_total,
        "pct_cov": pct_cov,
        "generated_at": raw.get("generated_at", ""),
        "pool_policy": raw.get("pool_policy", ""),
        "log_mtime": log_hint,
    }


@app.get("/pool-progress", response_class=HTMLResponse)
def pool_progress_page():
    """Human-readable face-pool stats; refreshes every 15s."""
    d = _pool_progress_payload()
    if d.get("error"):
        body = f"<p>{escape(d['error'])}</p>"
    else:
        missing = d["missing_min"]
        preview = ", ".join(
            f"{c} ({d['counts'].get(c, 0)})" for c in missing[:30]
        )
        more = f" …and {len(missing) - 30} more." if len(missing) > 30 else ""
        total_ok = "Yes — you have at least 500 photos." if d["ok_total"] else "Not yet — keep importing."
        cov_ok = (
            f"Yes — all {d['top100_n']} countries have at least {_MIN_PER_COUNTRY} photos."
            if d["ok_cov"]
            else f"Not yet — {d['below_min_count']} countries still need more photos."
        )
        body = f"""
<p style="font-size:1.35rem;line-height:1.5"><strong>{d['total']}</strong> profile photos are in the pool right now.</p>
<p>Your targets: <strong>{d['min_total']}</strong> photos total, and at least <strong>{d['min_per']}</strong> per country for each of the <strong>{d['top100_n']}</strong> countries we track.</p>
<p><strong>Toward {d['min_total']} total:</strong> about <strong>{d['pct_total']}%</strong> — {total_ok}</p>
<p><strong>Country coverage:</strong> <strong>{d['countries_represented']}</strong> countries have at least one photo. <strong>{d['top100_n'] - d['below_min_count']}</strong> countries already meet the “{d['min_per']}+ photos” rule ({d['pct_cov']}% of the list). {cov_ok}</p>
<p><strong>All {d['total']} rows</strong> are tagged with one of those top-{d['top100_n']} country codes.</p>
<p style="opacity:0.85">Pool file last built: <code>{escape(str(d.get('generated_at') or '?'))}</code><br/>
Policy: <code>{escape(str(d.get('pool_policy') or '?'))}</code></p>
"""
        if missing:
            body += f"<h3>Countries still under {d['min_per']} photos</h3><p>{escape(preview)}{escape(more)}</p>"
        if d.get("log_mtime"):
            body += f"<p style=\"opacity:0.85\">Import log last touched: <strong>{escape(d['log_mtime'])}</strong> (if an import is running, this time should keep moving).</p>"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <meta http-equiv="refresh" content="15"/>
  <title>Face pool progress</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 42rem; margin: 2rem auto; padding: 0 1rem; color: #111; }}
    h1 {{ font-size: 1.5rem; }}
    code {{ font-size: 0.9em; }}
    a {{ color: #0b5; }}
  </style>
</head>
<body>
  <h1>Face pool progress</h1>
  <p>This page reloads every <strong>15 seconds</strong> so you can leave it open while importing.</p>
  {body}
  <hr/>
  <p><a href="/data/faces-pool.json">Raw pool JSON</a> · <a href="/pool-review.html">Pool review UI</a> · <a href="/">Game</a></p>
</body>
</html>"""
    return HTMLResponse(html)


@app.get("/ui-test.html")
def ui_test_page():
    p = GAME / "ui-test.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="ui-test.html missing")
    return FileResponse(str(p), media_type="text/html; charset=utf-8")


@app.get("/data/faces-manifest.json")
def faces_manifest():
    p = DATA / "faces-manifest.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="faces-manifest.json missing")
    return FileResponse(str(p), media_type="application/json; charset=utf-8")


@app.get("/data/faces-pool.json")
def faces_pool():
    p = DATA / "faces-pool.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="faces-pool.json missing")
    return FileResponse(
        str(p),
        media_type="application/json; charset=utf-8",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/data/countries.json")
def countries_json():
    p = DATA / "countries.json"
    if not p.exists():
        raise HTTPException(status_code=404, detail="countries.json missing")
    return FileResponse(str(p), media_type="application/json; charset=utf-8")


def _safe_asset_file(resource_path: str) -> Optional[Path]:
    """Resolve a path under cai-laowai/assets; return file path or None."""
    if not resource_path or "\x00" in resource_path:
        return None
    rel = Path(resource_path)
    if rel.is_absolute() or any(p == ".." for p in rel.parts):
        return None
    try:
        base = ASSETS.resolve()
    except OSError:
        return None
    candidate = (base / rel).resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


@app.get("/assets/{resource_path:path}")
def serve_asset(resource_path: str):
    """Serve self-hosted face images (explicit route — more reliable than StaticFiles on some hosts)."""
    target = _safe_asset_file(resource_path)
    if target is None:
        raise HTTPException(status_code=404, detail="Not Found")
    mime, _ = mimetypes.guess_type(str(target))
    return FileResponse(
        str(target),
        media_type=mime or "application/octet-stream",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@app.get("/api/health/assets")
def health_assets():
    """Deploy check: face files must exist on disk or the game shows broken images."""
    faces = ASSETS / "faces"
    n = 0
    if faces.is_dir():
        n = sum(1 for p in faces.iterdir() if p.is_file())
    return {
        "ok": n > 0,
        "assets_dir": str(ASSETS),
        "assets_exists": ASSETS.is_dir(),
        "face_files": n,
        "game_dir": str(GAME),
    }


@app.on_event("startup")
def _log_assets_on_startup() -> None:
    faces = ASSETS / "faces"
    n = sum(1 for p in faces.glob("*") if p.is_file()) if faces.is_dir() else 0
    logger.warning(
        "cai-laowai assets: ASSETS=%s exists=%s files_in_faces/=%s",
        ASSETS,
        ASSETS.is_dir(),
        n,
    )


_stats_lock = threading.Lock()
_STATS_PATH = DATA / "game-stats.json"
# One bucket per raw score (12 rounds → scores 0…12 inclusive).
_SCORE_BUCKETS = 13


def _load_stats() -> dict:
    default = {"total_plays": 0, "by_score": [0] * _SCORE_BUCKETS}
    if not _STATS_PATH.exists():
        return default
    try:
        with open(_STATS_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        bs = data.get("by_score")
        if not isinstance(bs, list):
            data["by_score"] = [0] * _SCORE_BUCKETS
        else:
            if len(bs) < _SCORE_BUCKETS:
                data["by_score"] = bs + [0] * (_SCORE_BUCKETS - len(bs))
            elif len(bs) > _SCORE_BUCKETS:
                data["by_score"] = bs[:_SCORE_BUCKETS]
        data["total_plays"] = int(data.get("total_plays", 0))
        return data
    except Exception:
        return default


def _save_stats(data: dict) -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    with open(_STATS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def _histogram_median(by_score: list) -> Optional[float]:
    total = sum(by_score)
    if total == 0:
        return None
    target = (total - 1) / 2.0
    acc = 0.0
    for i, c in enumerate(by_score):
        acc += c
        if acc > target:
            return float(i)
    return float(_SCORE_BUCKETS - 1)


def _histogram_mean(by_score: list) -> Optional[float]:
    total = sum(by_score)
    if total == 0:
        return None
    acc = 0.0
    for i, c in enumerate(by_score):
        acc += float(i) * float(c)
    return acc / float(total)


class StatsRecord(BaseModel):
    score: int


@app.post("/api/stats/record")
def stats_record(body: StatsRecord):
    if body.score < 0 or body.score >= _SCORE_BUCKETS:
        raise HTTPException(
            status_code=400, detail=f"score must be 0–{_SCORE_BUCKETS - 1}"
        )
    with _stats_lock:
        data = _load_stats()
        data["total_plays"] = int(data.get("total_plays", 0)) + 1
        bs = data["by_score"]
        bs[body.score] = bs[body.score] + 1
        try:
            _save_stats(data)
        except OSError:
            pass
    return {"ok": True}


@app.get("/api/stats/summary")
def stats_summary():
    with _stats_lock:
        data = _load_stats()
    bs = data.get("by_score", [0] * _SCORE_BUCKETS)
    total = int(data.get("total_plays", 0))
    med = _histogram_median(bs)
    mean = _histogram_mean(bs)
    return {
        "total_plays": total,
        "by_score": bs,
        "median_score": med,
        "mean_score": mean,
        "rounds_per_game": _SCORE_BUCKETS - 1,
    }


