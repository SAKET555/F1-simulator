"""
F1 Championship standings calculator.

Built entirely from our own already-verified per-race classification
(_build_car_states, via the persistently-cached load_session_laps) rather
than FastF1's session.results table. That table is populated from Ergast,
which fails for nearly every session in this environment — and, per
FastF1's own warning, is expected to fail for any "recent" session even
with full network access. When it fails, session.results["Position"]
comes back NaN for every single driver, which silently gave every driver
0 points in every race (on top of taking 20+ seconds per season, loading
every race a second time with its own separate FastF1 session.load()
call). Our own position/retirement logic already correctly derives
classification from the raw lap timing data — verified against FastF1's
official per-lap Position column across every cached race — so we reuse
it here instead of a second, less reliable, much slower source.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from typing import Optional

from app.engine import storage

log = logging.getLogger(__name__)

POINTS = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}
FL_POINT = 1


def _race_points(race_id: str) -> Optional[list[dict]]:
    """Points awarded to each driver for one race, using our own classification."""
    try:
        from app.engine.data_loader import load_session_laps
        from app.engine.replay import _build_car_states

        laps_df, _ = load_session_laps(race_id)
    except Exception as exc:
        log.debug("Could not load %s for championship: %s", race_id, exc)
        return None

    last_lap = int(laps_df["LapNumber"].max())
    cars = _build_car_states(laps_df[laps_df["LapNumber"] == last_lap].copy(), laps_df, last_lap)

    fastest_driver = None
    if laps_df["LapTime_s"].notna().any():
        fastest_driver = str(laps_df.loc[laps_df["LapTime_s"].idxmin(), "Driver"])

    entries = []
    for c in sorted(cars, key=lambda c: c.position):
        # A genuine DNF (our `retired`, which already applies the FIA's
        # 90%-of-distance classification rule) scores nothing; a car that's
        # merely laps down but still classified scores for its position.
        pts = 0.0 if c.retired else float(POINTS.get(c.position, 0))
        if fastest_driver == c.driver_code and pts > 0 and c.position <= 10:
            pts += FL_POINT
        entries.append({
            "driver_code": c.driver_code,
            "team": c.team,
            "position": c.position,
            "retired": c.retired,
            "points": pts,
        })
    return entries


def _race_points_cached(race_id: str) -> Optional[list[dict]]:
    """
    Points for one race, persisted individually (not as one big per-season
    blob) so that computing a season's standings is resumable: a race
    already scored on an earlier request — even for a *different* season
    query, or via the single-race points endpoint — is never redone, and a
    slow/failed race elsewhere in the calendar doesn't waste the ones that
    already succeeded.
    """
    cache_key = f"race_points_{race_id}"
    cached = storage.load_extra(cache_key)
    if cached is not None:
        return cached
    entries = _race_points(race_id)
    if entries is not None:
        storage.save_extra(cache_key, entries)
    return entries


def _season_races(year: int, up_to_round: Optional[int] = None) -> list[dict]:
    """This season's race metadata, in round order, optionally truncated."""
    from app.engine.calendar import build_catalogue

    races = sorted((r for r in build_catalogue() if r["year"] == year), key=lambda r: r["round_number"])
    if up_to_round is not None:
        races = [r for r in races if r["round_number"] <= up_to_round]
    return races


_LOAD_WORKERS = 6   # each race load is mostly disk I/O + pandas parsing, not
                     # CPU-bound Python, so threads (not processes) parallelize
                     # this well despite the GIL


def _season_breakdown(year: int, up_to_round: Optional[int] = None) -> list[dict]:
    """
    Points earned per race, in round order, up to `up_to_round` if given.
    The races this hasn't seen before (nothing to do on a warm cache) are
    loaded concurrently — computing a full, cold season is otherwise ~20
    sequential race loads, which measured close to a minute; a thread pool
    cuts that roughly in proportion to _LOAD_WORKERS since the races are
    fully independent of each other.
    """
    races = _season_races(year, up_to_round)
    with ThreadPoolExecutor(max_workers=_LOAD_WORKERS) as pool:
        results = list(pool.map(lambda r: _race_points_cached(r["race_id"]), races))

    breakdown = []
    for race_meta, entries in zip(races, results):
        if entries is None:
            continue
        breakdown.append({
            "race_id": race_meta["race_id"],
            "round_number": race_meta["round_number"],
            "event_name": race_meta["event_name"],
            "points": entries,
        })
    return breakdown


@lru_cache(maxsize=32)
def get_driver_standings(year: int, through_round: Optional[int] = None) -> list[dict]:
    """
    Driver championship standings for `year`. With `through_round`, only
    races up to and including that round count — i.e. standings as of a
    specific point in the season, not necessarily the final result.
    """
    drivers: dict[str, dict] = {}
    for race in _season_breakdown(year, through_round):
        for entry in race["points"]:
            drv = entry["driver_code"]
            if drv not in drivers:
                drivers[drv] = {
                    "driver_code": drv, "team": entry["team"],
                    "points": 0.0, "wins": 0, "podiums": 0,
                }
            drivers[drv]["points"] += entry["points"]
            drivers[drv]["team"] = entry["team"]
            if not entry["retired"]:
                if entry["position"] == 1:
                    drivers[drv]["wins"] += 1
                if entry["position"] <= 3:
                    drivers[drv]["podiums"] += 1

    sorted_drivers = sorted(drivers.values(), key=lambda d: -d["points"])
    for i, d in enumerate(sorted_drivers):
        d["position"] = i + 1
    return sorted_drivers


@lru_cache(maxsize=32)
def get_constructor_standings(year: int, through_round: Optional[int] = None) -> list[dict]:
    """Constructor championship standings — same `through_round` semantics as above."""
    driver_standings = get_driver_standings(year, through_round)
    teams: dict[str, dict] = {}
    for d in driver_standings:
        team = d["team"]
        if team not in teams:
            teams[team] = {"team": team, "points": 0.0, "wins": 0}
        teams[team]["points"] += d["points"]
        teams[team]["wins"] += d["wins"]
    sorted_teams = sorted(teams.values(), key=lambda t: -t["points"])
    for i, t in enumerate(sorted_teams):
        t["position"] = i + 1
    return sorted_teams


def get_race_points(race_id: str) -> Optional[dict]:
    """
    Points each driver earned in one specific race, plus the driver and
    constructor standings immediately *after* that race (not the final
    season result) — what "the championship after this race" means.
    """
    from app.engine.data_loader import get_race_meta

    meta = get_race_meta(race_id)
    if meta is None:
        return None
    year, round_number = meta["year"], meta["round_number"]

    entries = _race_points_cached(race_id)
    if entries is None:
        return None

    return {
        "race_id": race_id,
        "event_name": meta["event_name"],
        "round_number": round_number,
        "points_this_race": sorted(entries, key=lambda e: e["position"]),
        "driver_standings_after": get_driver_standings(year, round_number),
        "constructor_standings_after": get_constructor_standings(year, round_number),
    }
