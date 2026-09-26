"""
Dynamic race calendar builder.

Uses FastF1's get_event_schedule() to fetch the full race calendar for
each year in SUPPORTED_YEARS (2016-2026, except 2022) and caches the result to
cache/calendar_cache.json.  On subsequent server starts the JSON is
read instantly — no network call.

Race IDs use the format  {year}-r{round:02d}  (e.g. "2023-r14").
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import fastf1

log = logging.getLogger(__name__)

# 2022 is left out: F1's live-timing archive refuses every 2022 file
# (HTTP 403 Access Denied, checked Sept 2026), so none of its races can be
# loaded. Add it back here if that archive opens up again.
UNAVAILABLE_YEARS: set[int] = {2022}
SUPPORTED_YEARS: list[int] = [y for y in range(2016, 2027) if y not in UNAVAILABLE_YEARS]

# Fallback lap counts for circuits where we don't get them from the schedule.
CIRCUIT_LAPS: dict[str, int] = {
    "Bahrain": 57, "Sakhir": 87, "Jeddah": 50, "Melbourne": 58,
    "Baku": 51, "Miami": 57, "Imola": 63, "Monaco": 78,
    "Barcelona": 66, "Montreal": 70, "Spielberg": 71, "Silverstone": 52,
    "Budapest": 70, "Spa": 44, "Zandvoort": 72, "Monza": 51,
    "Singapore": 62, "Suzuka": 53, "Lusail": 57, "Austin": 56,
    "Mexico City": 71, "Sao Paulo": 69, "Las Vegas": 50, "Abu Dhabi": 58,
    "Shanghai": 56, "Portimao": 66, "Istanbul": 58, "Sochi": 53,
    "Nurburgring": 60, "Mugello": 59, "Sepang": 56,
    "Hockenheim": 67, "Paul Ricard": 53, "Le Castellet": 53,
    "Yas Island": 58, "Interlagos": 69,
}


def guess_laps(location: str) -> int:
    loc_lower = location.lower()
    for key, val in CIRCUIT_LAPS.items():
        if key.lower() in loc_lower or loc_lower in key.lower():
            return val
    return 0


def race_id(year: int, round_no: int) -> str:
    return f"{year}-r{round_no:02d}"


def _cache_file() -> Path:
    from app.core.config import settings
    return Path(settings.cache_dir) / "calendar_cache.json"


def _fetch_year(year: int) -> list[dict]:
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        rows: list[dict] = []
        for _, row in schedule.iterrows():
            rn = int(row["RoundNumber"])
            if rn == 0:
                continue          # pre-season testing placeholder
            location = str(row.get("Location", ""))
            event_date = ""
            try:
                event_date = str(row["EventDate"])[:10]
            except Exception:
                pass
            rows.append({
                "race_id":      race_id(year, rn),
                "year":         year,
                "round_number": rn,
                "event_name":   str(row.get("EventName", "")),
                "circuit":      location,
                "event_date":   event_date,
                "total_laps":   guess_laps(location),
                # F1ApiSupport indicates whether lap-level data is available
                "f1_api":       bool(row.get("F1ApiSupport", True)),
            })
        log.info("  %d: %d events fetched", year, len(rows))
        return rows
    except Exception as exc:
        log.warning("  %d: schedule fetch failed — %s", year, exc)
        return []


def build_catalogue(force_refresh: bool = False) -> list[dict]:
    """
    Return the full race catalogue for SUPPORTED_YEARS.

    On first call (or force_refresh=True) fetches from FastF1 and
    writes cache/calendar_cache.json.  Subsequent calls read from
    that file instantly.
    """
    from app.core.config import settings
    from app.engine.data_loader import _ensure_cache_dir
    _ensure_cache_dir()

    cf = _cache_file()

    if not force_refresh and cf.exists():
        try:
            cached = json.loads(cf.read_text(encoding="utf-8"))
            races = [r for r in cached.get("races", []) if r["year"] in SUPPORTED_YEARS]
            if races:
                log.info("Calendar: loaded %d races from %s", len(races), cf)
                return races
        except Exception as exc:
            log.warning("Calendar cache read error: %s", exc)

    log.info("Building calendar from FastF1 for years %d-%d …",
             SUPPORTED_YEARS[0], SUPPORTED_YEARS[-1])
    all_races: list[dict] = []
    for year in SUPPORTED_YEARS:
        all_races.extend(_fetch_year(year))

    # Sort: newest season first, then chronologically within season
    all_races.sort(key=lambda r: (-r["year"], r["round_number"]))

    cf.parent.mkdir(parents=True, exist_ok=True)
    cf.write_text(
        json.dumps({
            "built_at": datetime.now(timezone.utc).isoformat(),
            "count":    len(all_races),
            "races":    all_races,
        }, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    log.info("Calendar built: %d races — saved to %s", len(all_races), cf)
    return all_races
