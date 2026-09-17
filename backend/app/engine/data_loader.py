"""
FastF1-backed data loader with:
  • Dynamic calendar from calendar.py  (2016-2026, ~180+ races)
  • Persistent processed-data cache via storage.py
    — first load downloads from FastF1 and saves a pickle
    — subsequent loads (even after server restarts) hit the pickle only
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import fastf1
import pandas as pd

from app.core.config import settings

log = logging.getLogger(__name__)

# ── catalogue (lazy-loaded) ───────────────────────────────────────────────────
_catalogue: list[dict] = []
_by_id:     dict[str, dict] = {}


def _ensure_cache_dir() -> None:
    path = Path(settings.cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(path))


def _load_catalogue() -> None:
    global _catalogue, _by_id
    if _catalogue:
        return
    from app.engine.calendar import build_catalogue
    _catalogue = build_catalogue()
    _by_id = {r["race_id"]: r for r in _catalogue}


def list_available_races() -> list[dict]:
    _load_catalogue()
    return _catalogue


def get_race_meta(race_id: str) -> dict | None:
    _load_catalogue()
    return _by_id.get(race_id)


def is_locally_cached(race_id: str) -> bool:
    """True if the processed pickle or FastF1 disk cache exists."""
    from app.engine import storage
    if storage.exists(race_id):
        return True
    meta = get_race_meta(race_id)
    if not meta:
        return False
    pattern = f"{meta['year']}_{meta['round_number']:02d}_*_Race_*"
    return any(Path(settings.cache_dir).glob(pattern))


# ── session loader ────────────────────────────────────────────────────────────

@lru_cache(maxsize=16)
def load_session_laps(race_id: str) -> tuple[pd.DataFrame, int]:
    """
    Return (laps_df, total_laps) for *race_id*.

    Load order:
      1. Processed pickle  →  instant
      2. FastF1 disk cache →  fast (no network)
      3. FastF1 network    →  slow first time, then pickled for future use

    laps_df columns:
      DriverNumber, Driver, Team, LapNumber, LapTime_s,
      Compound, TyreLife, IsPitIn, IsPitOut
    """
    from app.engine import storage

    # 1 — persistent processed cache
    cached = storage.load(race_id)
    if cached is not None:
        return cached

    # 2/3 — FastF1 (disk cache or network)
    _ensure_cache_dir()
    meta = get_race_meta(race_id)
    if meta is None:
        raise ValueError(f"Unknown race_id: {race_id!r}")

    log.info("Loading %s %s Race from FastF1 …", meta["year"], meta["event_name"])
    session = fastf1.get_session(meta["year"], meta["round_number"], "R")
    session.load(telemetry=False, weather=False, messages=False)

    laps: pd.DataFrame = session.laps.copy()
    laps = laps[laps["LapNumber"].notna()].copy()
    laps["LapNumber"] = laps["LapNumber"].astype(int)
    laps["LapTime_s"] = laps["LapTime"].dt.total_seconds()

    laps["Compound"] = (
        laps["Compound"]
        .fillna("UNKNOWN")
        .str.upper()
        .replace({
            "HYPERSOFT": "SOFT", "ULTRASOFT": "SOFT",
            "SUPERSOFT": "SOFT", "SUPERHARD": "HARD",
        })
    )
    laps["IsPitOut"] = laps["PitOutTime"].notna()
    laps["IsPitIn"]  = laps["PitInTime"].notna()
    laps["TyreLife"] = laps["TyreLife"].fillna(0).astype(int)

    total_laps = int(laps["LapNumber"].max())

    keep = ["DriverNumber", "Driver", "Team",
            "LapNumber", "LapTime_s",
            "Compound", "TyreLife", "IsPitIn", "IsPitOut"]
    laps = laps[keep].reset_index(drop=True)

    log.info("Loaded %d lap rows, total_laps=%d — saving to processed cache",
             len(laps), total_laps)

    # Save permanently so next load is instant
    storage.save(race_id, laps, total_laps)

    return laps, total_laps
