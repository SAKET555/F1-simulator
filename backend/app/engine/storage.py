"""
Persistent pickle cache for processed race data.

After a race is loaded from FastF1 and processed, we serialise the
cleaned DataFrame to  cache/processed/{race_id}.pkl.
Subsequent loads (even after server restarts) skip the FastF1 network
call entirely and read the pickle directly.
"""
from __future__ import annotations

import logging
import pickle
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

# Bump whenever the shape/derivation of the cached DataFrame changes, so
# pickles built under an older, since-corrected pipeline are treated as
# stale and transparently rebuilt instead of silently reused. (v2: adds
# Time_s — cumulative session-elapsed time straight from FastF1 — after
# discovering that re-deriving it by summing LapTime_s produced gap-to-
# leader values 5-6x too large, because the opening lap has no LapTime.)
CACHE_VERSION = 2


def _path(race_id: str) -> Path:
    from app.core.config import settings
    return Path(settings.cache_dir) / "processed" / f"{race_id}.pkl"


def exists(race_id: str) -> bool:
    return _path(race_id).exists()


def save(race_id: str, df: pd.DataFrame, total_laps: int) -> None:
    p = _path(race_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as fh:
        pickle.dump({"df": df, "total_laps": total_laps, "version": CACHE_VERSION}, fh,
                    protocol=pickle.HIGHEST_PROTOCOL)
    log.info("Stored processed data for %s (%d laps, %d rows)",
             race_id, total_laps, len(df))


def load(race_id: str) -> tuple[pd.DataFrame, int] | None:
    p = _path(race_id)
    if not p.exists():
        return None
    try:
        with open(p, "rb") as fh:
            data = pickle.load(fh)
        if data.get("version") != CACHE_VERSION:
            log.info("Processed cache for %s is stale (schema changed) — will re-fetch", race_id)
            return None
        log.info("Loaded processed data for %s from persistent cache", race_id)
        return data["df"], data["total_laps"]
    except Exception as exc:
        log.warning("Processed cache corrupt for %s (%s) — will re-fetch", race_id, exc)
        p.unlink(missing_ok=True)
        return None
