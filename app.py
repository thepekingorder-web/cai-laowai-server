"""
猜老外 (cai-laowai) — standalone app. No GotEyes / cameras / WhatsApp code.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent
GAME = ROOT / "cai-laowai"
DATA = GAME / "data"
ASSETS = GAME / "assets"

app = FastAPI(title="cai-laowai")


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
    return FileResponse(str(p), media_type="application/json; charset=utf-8")


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


if ASSETS.is_dir():
    app.mount("/assets", StaticFiles(directory=str(ASSETS)), name="assets")
