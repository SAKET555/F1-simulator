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
    from app.engine import storage
    cache_key = f"{race_id}_qualifying"
    cached = storage.load_extra(cache_key)
    if cached is not None:
        return cached

    _ensure_cache_dir()
    meta = get_race_meta(race_id)
    if meta is None:
        raise ValueError(f"Unknown race_id: {race_id!r}")
    try:
        session = fastf1.get_session(meta["year"], meta["round_number"], "Q")
        # messages=True: when Ergast is unavailable (routinely — see the
        # "Failed to load result data from Ergast!" warning FastF1 logs for
        # almost every session in this environment), FastF1 falls back to
        # calculating classification from lap times, but that fallback
        # needs race control messages to know which laps were deleted.
        # Without it, every driver comes back Position=NaN and Q1/Q2/Q3=NaT
        # (which is exactly what the app was displaying: P99 for everyone,
        # every time column blank).
        session.load(telemetry=False, weather=False, messages=True)
        results = []
        if hasattr(session, "results") and session.results is not None and len(session.results) > 0:
            res = session.results
            for _, row in res.iterrows():
                q1 = row.get("Q1")
                q2 = row.get("Q2")
                q3 = row.get("Q3")
                pos_val = row.get("Position")
                # A driver with genuinely zero recorded laps in the session
                # (crashed/withdrew before a timed lap — FastF1 itself logs
                # "No lap data for driver X" for these) has no position to
                # derive at all, not even via the lap-time fallback. Sending
                # a placeholder number (previously 99) looked like a real,
                # very-last-place classification; None/null says honestly
                # "unknown", and the frontend shows it as DNS.
                try:
                    pos = int(pos_val) if pd.notna(pos_val) else None
                except (ValueError, TypeError):
                    pos = None
                results.append({
                    "position": pos,
                    "driver_code": str(row.get("Abbreviation", "")),
                    "team": str(row.get("TeamName", "")),
                    "q1_s": q1.total_seconds() if pd.notna(q1) and hasattr(q1, "total_seconds") else None,
                    "q2_s": q2.total_seconds() if pd.notna(q2) and hasattr(q2, "total_seconds") else None,
                    "q3_s": q3.total_seconds() if pd.notna(q3) and hasattr(q3, "total_seconds") else None,
                })
            # None (no laps at all — see above) sorts after every real
            # position instead of crashing (None < None is also a TypeError,
            # so the second tuple element must never be None either).
            sorted_results = sorted(
                results,
                key=lambda r: (r["position"] is None, r["position"] or 0),
            )
            storage.save_extra(cache_key, sorted_results)
            return sorted_results
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

    # Gap-to-leader for a given lap comes straight from FastF1's own
    # cumulative Time_s at that lap (see the identical fix and full
    # explanation in replay.py's _build_car_states) rather than re-deriving
    # it by summing LapTime_s: the opening lap has no LapTime (no previous
    # lap to diff against), so summing silently drops each driver's own,
    # differing, opening-lap duration — and, separately, any lap whose
    # LapTime_s happens to include a red-flag/stoppage duration inflates
    # every driver's gap from that lap onward. Time_s isn't affected by
    # either problem.
    pivot = laps_df.pivot_table(index="LapNumber", columns="Driver", values="Time_s", aggfunc="first")
    lap_time_pivot = laps_df.pivot_table(index="LapNumber", columns="Driver", values="LapTime_s", aggfunc="first")

    gaps_matrix = []
    lap_times_matrix = []
    for lap in lap_numbers:
        row = pivot.loc[lap] if lap in pivot.index else None
        valid = row.dropna() if row is not None else None
        lt_row = lap_time_pivot.loc[lap] if lap in lap_time_pivot.index else None

        if valid is None or valid.empty:
            gaps_matrix.append([-1.0] * len(all_drivers))
        else:
            leader_time = valid.min()
            gaps_matrix.append([
                round(row.get(drv) - leader_time, 3) if pd.notna(row.get(drv)) else -1.0
                for drv in all_drivers
            ])

        # A driver's actual lap time for that lap — e.g. an inflated gap
        # from a long pit/repair stop reads very differently next to "lap
        # time: 98.8s" (normal racing pace once back out) than it does on
        # its own, where it just looks like a miscalculated number.
        lap_times_matrix.append([
            round(float(lt_row.get(drv)), 3) if lt_row is not None and pd.notna(lt_row.get(drv)) else None
            for drv in all_drivers
        ])

    return {
        "laps": [int(l) for l in lap_numbers],
        "drivers": list(all_drivers),
        "gaps_matrix": gaps_matrix,
        "lap_times_matrix": lap_times_matrix,
    }


@lru_cache(maxsize=8)
def load_sector_times(race_id: str, driver_code: str) -> list[dict]:
    """Return sector times per lap for a specific driver."""
    from app.engine import storage
    cache_key = f"{race_id}_sectors_{driver_code}"
    cached = storage.load_extra(cache_key)
    if cached is not None:
        return cached

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
        sorted_results = sorted(results, key=lambda r: r["lap"])
        storage.save_extra(cache_key, sorted_results)
        return sorted_results
    except Exception as e:
        log.warning("Could not load sector times for %s %s: %s", race_id, driver_code, e)
        return []


@lru_cache(maxsize=4)
def load_telemetry(race_id: str, driver_code: str, lap_number: int) -> list[dict]:
    """Return car telemetry for a specific driver lap."""
    from app.engine import storage
    # By far the slowest of these calls — a full telemetry load re-fetches
    # everything for the whole session (session.load(telemetry=True) isn't
    # scoped to one driver/lap), so persisting the result matters most here.
    cache_key = f"{race_id}_telemetry_{driver_code}_{lap_number}"
    cached = storage.load_extra(cache_key)
    if cached is not None:
        return cached

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
        # get_car_data() only returns RPM/Speed/Throttle/Brake/DRS/gear — it
        # has no X/Y columns at all, so reading row.get("X", 0) against it
        # always silently fell through to the 0 default, for every race,
        # regardless of whether real position data existed. That's why the
        # track map never drew anything: every point normalized to the same
        # (0, 0), collapsing to nothing recognizable. get_telemetry() merges
        # car data with the separate position-data channel, which actually
        # has X/Y (verified against real circuit-shaped coordinates for
        # multiple seasons) — a driver-lap without position data raises
        # here (caught below) rather than silently returning zeros.
        tel = lap_rows.iloc[0].get_telemetry()
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
        storage.save_extra(cache_key, points)
        return points
    except Exception as e:
        log.warning("Could not load telemetry for %s %s lap %d: %s", race_id, driver_code, lap_number, e)
        return []


@lru_cache(maxsize=8)
def load_weather_data(race_id: str) -> list[dict]:
    """Return weather data sampled per approximate lap."""
    from app.engine import storage
    cache_key = f"{race_id}_weather"
    cached = storage.load_extra(cache_key)
    if cached is not None:
        return cached

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
        frames = [by_lap[l] for l in sorted(by_lap.keys())]
        storage.save_extra(cache_key, frames)
        return frames
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
