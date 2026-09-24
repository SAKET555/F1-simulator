"""
Async replay engine.
Reads lap-by-lap data from the data_loader and emits RaceState frames
over a WebSocket at the requested speed multiplier.
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
from typing import AsyncGenerator, Optional

import pandas as pd

from app.engine.data_loader import load_session_laps, get_race_meta
from app.schemas.race import CarState, RaceState

log = logging.getLogger(__name__)

# Guards against bad compound values already baked into older processed-cache
# pickles (e.g. the literal string "NAN" instead of a real null) — anything
# outside this set gets coerced to "UNKNOWN" rather than failing CarState.
_VALID_COMPOUNDS = {"SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", "UNKNOWN"}

# Simulated real-world gap between laps when watching live (seconds).
# At 1× speed we'd wait ~90 s per lap; we expose 2×/5×/10× multipliers.
_BASE_LAP_INTERVAL_S: float = 5.0   # wall-clock seconds at 1× (demo-friendly)


# Sent in place of a real (finite) gap for retired cars, so the JSON payload
# stays valid (float("inf") serializes to the non-standard "Infinity" token,
# which JS's JSON.parse rejects) while still tripping the frontend's existing
# "gap > 9999 => OUT" display rule.
_RETIRED_GAP_SENTINEL: float = 99_999.0


def _build_car_states(
    lap_group: pd.DataFrame,
    all_laps: pd.DataFrame,
    lap_number: int,
) -> list[CarState]:
    """
    Build ordered list of CarState objects for a given lap snapshot.
    Ordering uses cumulative lap time to derive position.

    Drivers who retired before `lap_number` (no further lap rows recorded)
    are classified after every still-running car, ordered by how far they
    got before retiring — not by their frozen partial cumulative time, which
    would otherwise make an early DNF look like it's "leading" once the
    field races past whatever tiny time they'd accumulated before stopping.
    """
    # All unique drivers in the session (includes DNFs)
    all_drivers = (
        all_laps[["DriverNumber", "Driver", "Team"]]
        .drop_duplicates("DriverNumber")
    )

    # Each driver's most recent recorded lap at or before this lap number —
    # "how far have they got by now". cumulative_time_s comes straight from
    # that row's Time_s (FastF1's own cumulative session-elapsed time), not
    # from summing LapTime_s: the opening lap has no LapTime (no previous
    # lap to diff against), so summing silently drops each driver's own —
    # differing — opening-lap duration and throws gap-to-leader off by
    # hundreds of seconds. This same lookup also covers retirees, who have
    # no row for lap_number itself — their last known state carries forward.
    as_of = (
        all_laps[all_laps["LapNumber"] <= lap_number]
        .sort_values("LapNumber")
        .groupby("DriverNumber")
        .tail(1)
        .rename(columns={"LapNumber": "as_of_lap", "Compound": "compound_asof", "TyreLife": "tyre_life_asof"})
        [["DriverNumber", "as_of_lap", "Time_s", "compound_asof", "tyre_life_asof"]]
    )

    cum = all_drivers.merge(as_of, on="DriverNumber", how="left")
    cum["cumulative_time_s"] = cum["Time_s"].fillna(float("inf"))

    # A driver who's a lap (or more) down still finishes the race — the
    # leader takes the chequered flag first, so a lapped car's very last
    # lap row is always short of `total_laps` even though they're a normal
    # classified finisher, not a DNF. Using "no row at lap_number" alone to
    # mean "retired" wrongly flagged every lapped car as a DNF (e.g. 2021
    # Abu Dhabi showed only 11 finishers when 15 actually finished). Use the
    # FIA's own classification rule instead: a car that completes at least
    # 90% of the race distance is classified as a finisher regardless of how
    # many laps down it ended up; only a car that falls short of that before
    # lap_number is a genuine retirement.
    total_laps = int(all_laps["LapNumber"].max())
    finish_threshold = max(1, math.ceil(0.9 * total_laps))
    last_lap_by_driver = all_laps.groupby("DriverNumber")["LapNumber"].max()
    cum["last_lap"] = cum["DriverNumber"].map(last_lap_by_driver).fillna(0).astype(int)
    cum["retired"] = (cum["last_lap"] < lap_number) & (cum["last_lap"] < finish_threshold)

    # Running order first (by race time); retirees after, ranked by who got
    # furthest (more elapsed session time at their last lap = further into
    # the race), which is how real F1 classifies a DNF.
    running = cum[~cum["retired"]].sort_values("cumulative_time_s", ascending=True)
    retirees = cum[cum["retired"]].sort_values("cumulative_time_s", ascending=False)
    cum = pd.concat([running, retirees], ignore_index=True)
    cum["position"] = range(1, len(cum) + 1)

    leader_time = running["cumulative_time_s"].min() if len(running) else 0.0
    if leader_time == float("inf") or pd.isna(leader_time):
        leader_time = 0.0

    # Merge with current-lap tyre/pit details (drop duplicate name cols first)
    lap_info = lap_group.drop(columns=["Driver", "Team"], errors="ignore")
    merged = cum.merge(lap_info, on="DriverNumber", how="left")

    cars: list[CarState] = []
    for _, row in merged.iterrows():
        retired = bool(row["retired"])
        raw_cum = row["cumulative_time_s"]
        cum_s = float(raw_cum) if raw_cum != float("inf") and pd.notna(raw_cum) else 0.0

        # Prefer this lap's own tyre data; fall back to the as-of snapshot —
        # covers retirees and any driver missing an exact row at lap_number.
        compound_val = row.get("Compound")
        if pd.isna(compound_val):
            compound_val = row.get("compound_asof")
        tyre_life_val = row.get("TyreLife")
        if pd.isna(tyre_life_val):
            tyre_life_val = row.get("tyre_life_asof")

        raw_compound = str(compound_val).upper() if pd.notna(compound_val) else "UNKNOWN"
        is_in_pit_val = row.get("IsPitIn")

        state = CarState(
            car_id=int(row["DriverNumber"]),
            driver_code=str(row.get("Driver", "UNK"))[:3].upper(),
            team=str(row.get("Team", "Unknown")),
            position=int(row["position"]),
            lap_number=lap_number,
            lap_time_s=float(row["LapTime_s"]) if pd.notna(row.get("LapTime_s")) else None,
            cumulative_time_s=cum_s,
            gap_to_leader_s=(
                _RETIRED_GAP_SENTINEL if retired
                else (round(cum_s - leader_time, 3) if cum_s > 0 else 0.0)
            ),
            tire_compound=raw_compound if raw_compound in _VALID_COMPOUNDS else "UNKNOWN",
            tire_age_laps=int(tyre_life_val) if pd.notna(tyre_life_val) else 0,
            is_in_pit=(bool(is_in_pit_val) if pd.notna(is_in_pit_val) else False) and not retired,
            pit_count=_count_pit_stops(all_laps, str(row["DriverNumber"]), lap_number),
            retired=retired,
        )
        cars.append(state)

    return sorted(cars, key=lambda c: c.position)


def _count_pit_stops(all_laps: pd.DataFrame, driver_number: str, up_to_lap: int) -> int:
    mask = (
        (all_laps["DriverNumber"].astype(str) == driver_number)
        & (all_laps["LapNumber"] <= up_to_lap)
        & (all_laps["IsPitIn"] == True)
    )
    return int(mask.sum())


async def replay_race(
    race_id: str,
    speed_multiplier: float = 2.0,
    start_lap: int = 1,
) -> AsyncGenerator[RaceState, None]:
    """
    Async generator that yields RaceState objects lap by lap.
    Honors speed_multiplier (2, 5, 10) to throttle emission.
    """
    laps_df, total_laps = await asyncio.to_thread(load_session_laps, race_id)
    meta = get_race_meta(race_id) or {}
    session_name = f"{meta.get('year', '')} {meta.get('event_name', race_id)}"
    interval = _BASE_LAP_INTERVAL_S / max(speed_multiplier, 0.1)

    for lap_number in range(start_lap, total_laps + 1):
        lap_group = laps_df[laps_df["LapNumber"] == lap_number].copy()
        if lap_group.empty:
            continue

        cars = _build_car_states(lap_group, laps_df, lap_number)
        state = RaceState(
            race_id=race_id,
            lap=lap_number,
            total_laps=total_laps,
            session_name=session_name,
            cars=cars,
            timestamp_ms=time.time() * 1000,
        )
        yield state
        await asyncio.sleep(interval)
