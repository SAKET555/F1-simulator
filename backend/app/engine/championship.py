"""F1 Championship standings calculator using FastF1 session results."""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import fastf1
import pandas as pd

from app.core.config import settings

log = logging.getLogger(__name__)

POINTS = {1: 25, 2: 18, 3: 15, 4: 12, 5: 10, 6: 8, 7: 6, 8: 4, 9: 2, 10: 1}
FL_POINT = 1


def _ensure_cache() -> None:
    Path(settings.cache_dir).mkdir(parents=True, exist_ok=True)
    fastf1.Cache.enable_cache(str(settings.cache_dir))


@lru_cache(maxsize=4)
def get_driver_standings(year: int) -> list[dict]:
    """Return driver championship standings for the given year."""
    _ensure_cache()
    from app.engine.calendar import build_catalogue

    catalogue = build_catalogue()
    year_races = [r for r in catalogue if r["year"] == year]
    if not year_races:
        return []

    drivers: dict[str, dict] = {}

    for race_meta in year_races:
        try:
            session = fastf1.get_session(year, race_meta["round_number"], "R")
            session.load(telemetry=False, weather=False, messages=False)
            if session.results is None or session.results.empty:
                continue

            fl_driver = None
            try:
                fl = session.laps.pick_fastest()
                if fl is not None and not (isinstance(fl, pd.Series) and fl.empty):
                    fl_driver = fl["Driver"] if isinstance(fl, pd.Series) else fl.iloc[0]["Driver"]
            except Exception:
                pass

            for _, row in session.results.iterrows():
                drv = str(row.get("Abbreviation", ""))
                if not drv:
                    continue
                pos_val = row.get("Position")
                try:
                    pos = int(pos_val) if pd.notna(pos_val) else 99
                except (ValueError, TypeError):
                    pos = 99

                pts = float(POINTS.get(pos, 0))
                if fl_driver == drv and pos <= 10:
                    pts += FL_POINT

                if drv not in drivers:
                    drivers[drv] = {
                        "driver_code": drv,
                        "team": str(row.get("TeamName", "")),
                        "points": 0.0,
                        "wins": 0,
                        "podiums": 0,
                    }
                drivers[drv]["points"] += pts
                if pos == 1:
                    drivers[drv]["wins"] += 1
                if pos <= 3:
                    drivers[drv]["podiums"] += 1
                if row.get("TeamName"):
                    drivers[drv]["team"] = str(row.get("TeamName", ""))

        except Exception as e:
            log.debug("Skipping %s for championship: %s", race_meta["race_id"], e)
            continue

    sorted_drivers = sorted(drivers.values(), key=lambda d: -d["points"])
    for i, d in enumerate(sorted_drivers):
        d["position"] = i + 1
    return sorted_drivers


@lru_cache(maxsize=4)
def get_constructor_standings(year: int) -> list[dict]:
    """Return constructor championship standings."""
    driver_standings = get_driver_standings(year)
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
