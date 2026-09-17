"""
OpenF1 live-timing client  —  https://openf1.org
100 % free, no API key required.

During an active F1 race weekend this module:
  1. Detects the live session via /v1/sessions?session_key=latest
  2. Polls /v1/laps, /v1/stints, /v1/intervals, /v1/drivers every
     POLL_INTERVAL seconds
  3. Converts the raw JSON to CarState objects (same schema used by
     the replay engine) and yields them to the WebSocket router

Between race weekends get_live_session() returns None and callers
fall back to the historical replay mode.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta

import httpx

from app.engine.calendar import CIRCUIT_LAPS, guess_laps
from app.schemas.race import CarState, RaceState

log = logging.getLogger(__name__)

OPENF1_BASE   = "https://api.openf1.org/v1"
POLL_INTERVAL = 5.0          # seconds between OpenF1 polls
_client_timeout = httpx.Timeout(12.0)


# ── Helpers ──────────────────────────────────────────────────────────────────

async def _get(path: str, **params) -> list[dict]:
    url = f"{OPENF1_BASE}/{path}"
    try:
        async with httpx.AsyncClient(timeout=_client_timeout) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            return r.json()
    except Exception as exc:
        log.warning("OpenF1 GET %s failed: %s", path, exc)
        return []


def _parse_dt(s: str) -> datetime | None:
    """Parse ISO-8601 string to UTC datetime."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ── Public API ────────────────────────────────────────────────────────────────

async def get_live_session() -> dict | None:
    """
    Return the current live race session dict, or None if no race is active.

    A session is considered live if:
      • session_name == "Race"
      • date_start <= now <= date_end + 60 min buffer
    """
    sessions = await _get("sessions", session_key="latest")
    if not sessions:
        return None

    session = sessions[-1]
    if session.get("session_name") != "Race":
        return None

    now = datetime.now(timezone.utc)
    start = _parse_dt(session.get("date_start", ""))
    end   = _parse_dt(session.get("date_end", ""))

    if start and end:
        if not (start <= now <= end + timedelta(hours=1)):
            return None         # session exists but is past (or future)
    elif start and not end:
        if now < start or now > start + timedelta(hours=4):
            return None

    return session


async def get_drivers(session_key: int) -> dict[int, dict]:
    """Return {driver_number: driver_info} for the session."""
    raw = await _get("drivers", session_key=session_key)
    return {int(d["driver_number"]): d for d in raw if "driver_number" in d}


async def get_live_snapshot(session_key: int) -> tuple[list[dict], list[dict], list[dict]]:
    """Fetch laps, stints and intervals concurrently."""
    laps, stints, intervals = await asyncio.gather(
        _get("laps",      session_key=session_key),
        _get("stints",    session_key=session_key),
        _get("intervals", session_key=session_key),
    )
    return laps, stints, intervals


def build_car_states(
    laps:      list[dict],
    stints:    list[dict],
    intervals: list[dict],
    drivers:   dict[int, dict],
    session:   dict,
) -> tuple[list[CarState], int, int]:
    """
    Convert raw OpenF1 data into CarState objects.

    Returns (cars, current_lap, total_laps_estimate).
    """
    if not laps:
        return [], 0, guess_laps(session.get("location", ""))

    total_laps = guess_laps(session.get("location", ""))
    session_id = str(session.get("session_key", "live"))

    # --- latest stint per driver ------------------------------------------
    stints_by_drv: dict[int, dict] = {}
    for s in sorted(stints, key=lambda x: x.get("stint_number", 0)):
        stints_by_drv[int(s["driver_number"])] = s

    # --- latest gap per driver (from intervals) ---------------------------
    gap_by_drv: dict[int, float] = {}
    for iv in intervals:
        dn = int(iv["driver_number"])
        g  = iv.get("gap_to_leader", "")
        try:
            gap_by_drv[dn] = abs(float(str(g).replace("+", "").replace("LAP", "99")))
        except (ValueError, TypeError):
            gap_by_drv[dn] = 0.0

    # --- cumulative lap times per driver ----------------------------------
    from collections import defaultdict
    laps_by_drv: dict[int, list[dict]] = defaultdict(list)
    for lap in laps:
        if lap.get("lap_duration") is not None:
            laps_by_drv[int(lap["driver_number"])].append(lap)

    for dn in laps_by_drv:
        laps_by_drv[dn].sort(key=lambda x: x.get("lap_number", 0))

    current_lap = max(
        (lap.get("lap_number", 0) for lap in laps),
        default=0,
    )

    cum_times: dict[int, float] = {}
    last_laps:  dict[int, dict]  = {}
    for dn, dlaps in laps_by_drv.items():
        cum_times[dn] = sum(l["lap_duration"] for l in dlaps
                            if l.get("lap_duration") is not None)
        last_laps[dn] = dlaps[-1]

    if not cum_times:
        return [], current_lap, total_laps

    # Sort by cumulative time
    sorted_drvs = sorted(cum_times.items(), key=lambda x: x[1])
    leader_cum  = sorted_drvs[0][1]

    cars: list[CarState] = []
    for pos, (dn, cum) in enumerate(sorted_drvs, 1):
        d      = drivers.get(dn, {})
        stint  = stints_by_drv.get(dn, {})
        ll     = last_laps.get(dn, {})

        lap_start       = stint.get("lap_start", 1) or 1
        age_at_start    = stint.get("tyre_age_at_start", 0) or 0
        tyre_age        = max(current_lap - lap_start + age_at_start, 0)
        compound        = str(stint.get("compound", "UNKNOWN")).upper()
        pit_count       = max(int(stint.get("stint_number", 1)) - 1, 0)

        cars.append(CarState(
            car_id            = dn,
            driver_code       = str(d.get("name_acronym", str(dn)))[:3].upper(),
            team              = str(d.get("team_name", "Unknown")),
            position          = pos,
            lap_number        = current_lap,
            lap_time_s        = float(ll["lap_duration"]) if ll.get("lap_duration") else None,
            cumulative_time_s = round(cum, 3),
            gap_to_leader_s   = round(gap_by_drv.get(dn, cum - leader_cum), 3),
            tire_compound     = compound if compound in ("SOFT","MEDIUM","HARD","INTERMEDIATE","WET") else "UNKNOWN",
            tire_age_laps     = tyre_age,
            is_in_pit         = bool(ll.get("is_pit_out_lap", False)),
            pit_count         = pit_count,
        ))

    return cars, current_lap, total_laps


async def stream_live(websocket, n_simulations: int = 300) -> None:
    """
    Poll OpenF1 and stream lap-by-lap updates to the WebSocket.
    Uses the same message protocol as the historical replay engine.
    """
    import json
    from app.engine.monte_carlo import simulate_race
    from app.schemas.race import PredictionFrame, RaceState

    def _msg(mtype: str, payload: dict) -> str:
        return json.dumps({"type": mtype, "payload": payload})

    session = await get_live_session()
    if session is None:
        await websocket.send_text(_msg("info", {
            "message": "No live F1 race is active right now. "
                       "Select a historical race from the library to replay.",
            "live": False,
        }))
        await websocket.close()
        return

    session_key = int(session["session_key"])
    race_id_str = f"live-{session_key}"
    session_name = (
        f"{session.get('year', '')} {session.get('location', '')} Grand Prix (LIVE)"
    )

    log.info("OpenF1 live stream: session_key=%d %s", session_key, session_name)

    drivers = await get_drivers(session_key)
    last_lap_sent = -1

    await websocket.send_text(_msg("info", {
        "message": f"Connected to live session: {session_name}",
        "live":    True,
        "session": session,
    }))

    try:
        while True:
            laps, stints, intervals = await get_live_snapshot(session_key)
            cars, current_lap, total_laps = build_car_states(
                laps, stints, intervals, drivers, session
            )

            if current_lap > last_lap_sent and cars:
                state = RaceState(
                    race_id      = race_id_str,
                    lap          = current_lap,
                    total_laps   = total_laps,
                    session_name = session_name,
                    cars         = cars,
                    timestamp_ms = time.time() * 1000,
                )
                await websocket.send_text(_msg("race_state", state.model_dump()))

                probs = simulate_race(
                    current_lap  = current_lap,
                    total_laps   = total_laps,
                    grid_state   = cars,
                    race_id      = race_id_str,
                    n_simulations= n_simulations,
                )
                pred = PredictionFrame(
                    lap            = current_lap,
                    probabilities  = probs[:10],
                    n_simulations  = n_simulations,
                )
                await websocket.send_text(_msg("prediction", pred.model_dump()))
                last_lap_sent = current_lap

            # Check if race is over
            if total_laps > 0 and current_lap >= total_laps:
                winner = cars[0].driver_code if cars else "N/A"
                await websocket.send_text(_msg("race_end", {
                    "race_id": race_id_str,
                    "winner":  winner,
                    "live":    True,
                }))
                break

            await asyncio.sleep(POLL_INTERVAL)

    except Exception as exc:
        log.warning("Live stream error: %s", exc)
        try:
            await websocket.send_text(_msg("error", {"detail": str(exc)}))
        except Exception:
            pass
