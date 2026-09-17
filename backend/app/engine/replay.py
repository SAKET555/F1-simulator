"""
Async replay engine.
Reads lap-by-lap data from the data_loader and emits RaceState frames
over a WebSocket at the requested speed multiplier.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import AsyncGenerator, Optional

import pandas as pd

from app.engine.data_loader import load_session_laps, get_race_meta
from app.schemas.race import CarState, RaceState

log = logging.getLogger(__name__)

# Simulated real-world gap between laps when watching live (seconds).
# At 1× speed we'd wait ~90 s per lap; we expose 2×/5×/10× multipliers.
_BASE_LAP_INTERVAL_S: float = 5.0   # wall-clock seconds at 1× (demo-friendly)


def _build_car_states(
    lap_group: pd.DataFrame,
    all_laps: pd.DataFrame,
    lap_number: int,
) -> list[CarState]:
    """
    Build ordered list of CarState objects for a given lap snapshot.
    Ordering uses cumulative lap time to derive position.
    """
    # All unique drivers in the session (includes DNFs)
    all_drivers = (
        all_laps[["DriverNumber", "Driver", "Team"]]
        .drop_duplicates("DriverNumber")
    )

    # Cumulative valid lap times up to this lap
    past_valid = all_laps[
        (all_laps["LapNumber"] <= lap_number) & (all_laps["LapTime_s"].notna())
    ]
    cum = (
        past_valid.groupby("DriverNumber", sort=False)["LapTime_s"]
        .sum()
        .reset_index()
        .rename(columns={"LapTime_s": "cumulative_time_s"})
    )

    # Left-join so DNF / backmarker drivers still appear; placed last
    cum = all_drivers.merge(cum, on="DriverNumber", how="left")
    cum["cumulative_time_s"] = cum["cumulative_time_s"].fillna(float("inf"))
    cum.sort_values("cumulative_time_s", inplace=True)
    cum["position"] = range(1, len(cum) + 1)

    leader_time = cum["cumulative_time_s"].iloc[0]
    if leader_time == float("inf"):
        leader_time = 0.0

    # Merge with current-lap tyre/pit details (drop duplicate name cols first)
    lap_info = lap_group.drop(columns=["Driver", "Team"], errors="ignore")
    merged = cum.merge(lap_info, on="DriverNumber", how="left")

    cars: list[CarState] = []
    driver_meta: dict[str, dict] = {}
    for _, row in merged.iterrows():
        driver_meta[str(row["DriverNumber"])] = {
            "driver_code": str(row.get("Driver", "UNK"))[:3].upper(),
            "team": str(row.get("Team", "Unknown")),
        }
        raw_cum = row["cumulative_time_s"]
        cum_s = float(raw_cum) if raw_cum != float("inf") else 0.0
        state = CarState(
            car_id=int(row["DriverNumber"]),
            driver_code=str(row.get("Driver", "UNK"))[:3].upper(),
            team=str(row.get("Team", "Unknown")),
            position=int(row["position"]),
            lap_number=lap_number,
            lap_time_s=float(row["LapTime_s"]) if pd.notna(row.get("LapTime_s")) else None,
            cumulative_time_s=cum_s,
            gap_to_leader_s=round(cum_s - leader_time, 3) if cum_s > 0 else 0.0,
            tire_compound=str(row.get("Compound", "UNKNOWN")) if pd.notna(row.get("Compound")) else "UNKNOWN",
            tire_age_laps=int(row["TyreLife"]) if pd.notna(row.get("TyreLife")) else 0,
            is_in_pit=bool(row.get("IsPitIn", False)),
            pit_count=_count_pit_stops(all_laps, str(row["DriverNumber"]), lap_number),
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
    laps_df, total_laps = load_session_laps(race_id)
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
