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
    # Cumulative session-elapsed time at which this lap was completed, as
    # FastF1/the FIA timing feed computed it directly — kept alongside
    # LapTime_s because the two are NOT interchangeable: the opening lap of
    # a race has no LapTime (there's no previous lap to diff against, so
    # FastF1 leaves it NaN), so summing LapTime_s across laps silently drops
    # each driver's own — differing — opening-lap duration. Using Time_s
    # directly for "how far has this driver got" avoids re-deriving (and
    # subtly corrupting) a number FastF1 already computed correctly.
    laps["Time_s"] = laps["Time"].dt.total_seconds()

    # FastF1 sometimes leaves the literal string "nan" (not a real null) in
    # this column, which .fillna() doesn't catch — it only slips through
    # str.upper() as "NAN" and then fails CarState's tire_compound schema.
    # Normalize by whitelist instead, so any unrecognized value (NaN, "nan",
    # empty string, junk) safely falls back to "UNKNOWN".
    laps["Compound"] = (
        laps["Compound"]
        .fillna("UNKNOWN")
        .astype(str)
        .str.upper()
        .replace({
            "HYPERSOFT": "SOFT", "ULTRASOFT": "SOFT",
            "SUPERSOFT": "SOFT", "SUPERHARD": "HARD",
        })
    )
    _valid_compounds = {"SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", "UNKNOWN"}
    laps.loc[~laps["Compound"].isin(_valid_compounds), "Compound"] = "UNKNOWN"
    laps["IsPitOut"] = laps["PitOutTime"].notna()
    laps["IsPitIn"]  = laps["PitInTime"].notna()
    laps["TyreLife"] = laps["TyreLife"].fillna(0).astype(int)

    total_laps = int(laps["LapNumber"].max())

    keep = ["DriverNumber", "Driver", "Team",
            "LapNumber", "LapTime_s", "Time_s",
            "Compound", "TyreLife", "IsPitIn", "IsPitOut"]
    laps = laps[keep].reset_index(drop=True)

    log.info("Loaded %d lap rows, total_laps=%d — saving to processed cache",
             len(laps), total_laps)

    # Save permanently so next load is instant
    storage.save(race_id, laps, total_laps)

    return laps, total_laps


@lru_cache(maxsize=8)
def load_qualifying_results(race_id: str) -> list[dict]:
    """Return qualifying results sorted by grid position."""
    _ensure_cache_dir()
    meta = get_race_meta(race_id)
    if meta is None:
        raise ValueError(f"Unknown race_id: {race_id!r}")
    try:
        session = fastf1.get_session(meta["year"], meta["round_number"], "Q")
        session.load(telemetry=False, weather=False, messages=False)
        results = []
        if hasattr(session, "results") and session.results is not None and len(session.results) > 0:
            res = session.results
            for _, row in res.iterrows():
                q1 = row.get("Q1")
                q2 = row.get("Q2")
                q3 = row.get("Q3")
                pos_val = row.get("Position")
                try:
                    pos = int(pos_val) if pd.notna(pos_val) else 99
                except (ValueError, TypeError):
                    pos = 99
                results.append({
                    "position": pos,
                    "driver_code": str(row.get("Abbreviation", "")),
                    "team": str(row.get("TeamName", "")),
                    "q1_s": q1.total_seconds() if pd.notna(q1) and hasattr(q1, "total_seconds") else None,
                    "q2_s": q2.total_seconds() if pd.notna(q2) and hasattr(q2, "total_seconds") else None,
                    "q3_s": q3.total_seconds() if pd.notna(q3) and hasattr(q3, "total_seconds") else None,
                })
            return sorted(results, key=lambda r: r["position"])
        return []
    except Exception as e:
        log.warning("Could not load qualifying for %s: %s", race_id, e)
        return []


@lru_cache(maxsize=8)
def load_gap_history(race_id: str) -> dict:
    """Return gap-to-leader data for all drivers across all laps."""
    laps_df, total_laps = load_session_laps(race_id)

    all_drivers = laps_df["Driver"].dropna().unique().tolist()
    lap_numbers = sorted(laps_df["LapNumber"].unique())

    cum_times: dict[str, dict[int, float]] = {d: {} for d in all_drivers}

    for drv in all_drivers:
        drv_laps = laps_df[laps_df["Driver"] == drv].sort_values("LapNumber")
        cumulative = 0.0
        for _, row in drv_laps.iterrows():
            lt = row["LapTime_s"]
            if pd.notna(lt) and lt > 0:
                cumulative += lt
                cum_times[drv][int(row["LapNumber"])] = cumulative

    gaps_matrix = []
    for lap in lap_numbers:
        times_this_lap = {drv: cum_times[drv][lap] for drv in all_drivers if lap in cum_times[drv]}
        if not times_this_lap:
            gaps_matrix.append([-1.0] * len(all_drivers))
            continue
        leader_time = min(times_this_lap.values())
        row_gaps = []
        for drv in all_drivers:
            t = times_this_lap.get(drv)
            row_gaps.append(round(t - leader_time, 3) if t is not None else -1.0)
        gaps_matrix.append(row_gaps)

    return {
        "laps": [int(l) for l in lap_numbers],
        "drivers": list(all_drivers),
        "gaps_matrix": gaps_matrix,
    }


@lru_cache(maxsize=8)
def load_sector_times(race_id: str, driver_code: str) -> list[dict]:
    """Return sector times per lap for a specific driver."""
    _ensure_cache_dir()
    meta = get_race_meta(race_id)
    if meta is None:
        raise ValueError(f"Unknown race_id: {race_id!r}")
    try:
        session = fastf1.get_session(meta["year"], meta["round_number"], "R")
        session.load(telemetry=False, weather=False, messages=False)
        drv_laps = session.laps.pick_driver(driver_code)
        results = []
        for _, row in drv_laps.iterrows():
            s1 = row.get("Sector1Time")
            s2 = row.get("Sector2Time")
            s3 = row.get("Sector3Time")
            results.append({
                "lap": int(row["LapNumber"]) if pd.notna(row["LapNumber"]) else 0,
                "s1_s": s1.total_seconds() if pd.notna(s1) and hasattr(s1, "total_seconds") else None,
                "s2_s": s2.total_seconds() if pd.notna(s2) and hasattr(s2, "total_seconds") else None,
                "s3_s": s3.total_seconds() if pd.notna(s3) and hasattr(s3, "total_seconds") else None,
            })
        return sorted(results, key=lambda r: r["lap"])
    except Exception as e:
        log.warning("Could not load sector times for %s %s: %s", race_id, driver_code, e)
        return []


@lru_cache(maxsize=4)
def load_telemetry(race_id: str, driver_code: str, lap_number: int) -> list[dict]:
    """Return car telemetry for a specific driver lap."""
    _ensure_cache_dir()
    meta = get_race_meta(race_id)
    if meta is None:
        raise ValueError(f"Unknown race_id: {race_id!r}")
    try:
        session = fastf1.get_session(meta["year"], meta["round_number"], "R")
        session.load(telemetry=True, weather=False, messages=False)
        drv_laps = session.laps.pick_driver(driver_code)
        lap_rows = drv_laps[drv_laps["LapNumber"] == lap_number]
        if lap_rows.empty:
            return []
        tel = lap_rows.iloc[0].get_car_data().add_distance()
        points = []
        for _, row in tel.iterrows():
            t = row.get("Time")
            points.append({
                "time_s": t.total_seconds() if hasattr(t, "total_seconds") else float(t),
                "speed_kmh": float(row.get("Speed", 0) or 0),
                "throttle": float(row.get("Throttle", 0) or 0) / 100.0,
                "brake": bool(row.get("Brake", False)),
                "gear": int(row.get("nGear", 0) or 0),
                "rpm": int(row.get("RPM", 0) or 0),
                "drs": int(row.get("DRS", 0) or 0),
                "x": float(row.get("X", 0) or 0),
                "y": float(row.get("Y", 0) or 0),
            })
        return points
    except Exception as e:
        log.warning("Could not load telemetry for %s %s lap %d: %s", race_id, driver_code, lap_number, e)
        return []


@lru_cache(maxsize=8)
def load_weather_data(race_id: str) -> list[dict]:
    """Return weather data sampled per approximate lap."""
    _ensure_cache_dir()
    meta = get_race_meta(race_id)
    if meta is None:
        raise ValueError(f"Unknown race_id: {race_id!r}")
    try:
        session = fastf1.get_session(meta["year"], meta["round_number"], "R")
        session.load(telemetry=False, weather=True, messages=False)
        weather = session.weather_data
        if weather is None or weather.empty:
            return []
        _, total_laps = load_session_laps(race_id)
        results = []
        for _, row in weather.iterrows():
            t = row.get("Time")
            t_secs = t.total_seconds() if hasattr(t, "total_seconds") else 0
            approx_lap = max(1, int(t_secs / 135.0))
            results.append({
                "lap": min(approx_lap, total_laps),
                "air_temp_c": float(row.get("AirTemp", 25.0) or 25.0),
                "track_temp_c": float(row.get("TrackTemp", 35.0) or 35.0),
                "rainfall": bool(row.get("Rainfall", False)),
                "humidity": float(row.get("Humidity", 50.0) or 50.0),
                "wind_speed_ms": float(row.get("WindSpeed", 0.0) or 0.0),
            })
        by_lap: dict[int, dict] = {}
        for r in results:
            by_lap[r["lap"]] = r
        return [by_lap[l] for l in sorted(by_lap.keys())]
    except Exception as e:
        log.warning("Could not load weather for %s: %s", race_id, e)
        return []


def load_stint_data(race_id: str) -> list[dict]:
    """Return stint summary per driver."""
    laps_df, total_laps = load_session_laps(race_id)
    result = []
    for drv, grp in laps_df.groupby("Driver"):
        grp = grp.sort_values("LapNumber")
        stints: list[dict] = []
        current_compound: str | None = None
        stint_start: int | None = None

        for _, row in grp.iterrows():
            lap = int(row["LapNumber"])
            compound = row["Compound"]
            if current_compound is None:
                current_compound = compound
                stint_start = lap
            elif compound != current_compound or bool(row["IsPitOut"]):
                stints.append({
                    "compound": current_compound,
                    "start_lap": stint_start,
                    "end_lap": lap - 1,
                    "laps": lap - (stint_start or lap),
                })
                current_compound = compound
                stint_start = lap

        if current_compound and stint_start is not None:
            stints.append({
                "compound": current_compound,
                "start_lap": stint_start,
                "end_lap": int(grp["LapNumber"].max()),
                "laps": int(grp["LapNumber"].max()) - stint_start + 1,
            })
        result.append({"driver_code": str(drv), "stints": stints})
    return result
