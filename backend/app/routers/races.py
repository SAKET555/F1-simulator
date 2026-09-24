import asyncio

from fastapi import APIRouter, HTTPException
from app.engine.data_loader import (
    list_available_races, get_race_meta, is_locally_cached,
    load_qualifying_results, load_gap_history, load_sector_times,
    load_telemetry, load_weather_data, load_stint_data,
)
from app.engine import championship as champ_engine

router = APIRouter(tags=["races"])

# These all end up calling FastF1 (blocking network / disk I/O) or heavy
# pandas work on a cache miss. Running them straight inside `async def`
# freezes the whole event loop — including any open /ws/race stream —
# for as long as the call takes. asyncio.to_thread() pushes the blocking
# work onto a worker thread so the loop (and the websocket) stays live.


@router.get("/races")
async def get_races():
    """List all available race sessions (2016-2026, ~180+ events)."""
    races = await asyncio.to_thread(list_available_races)
    return await asyncio.to_thread(
        lambda: [{**r, "cached": is_locally_cached(r["race_id"])} for r in races]
    )


@router.get("/races/{race_id}")
async def get_race_detail(race_id: str):
    """Return metadata for a single race."""
    meta = get_race_meta(race_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    cached = await asyncio.to_thread(is_locally_cached, race_id)
    return {**meta, "cached": cached}


@router.get("/races/{race_id}/qualifying")
async def get_qualifying(race_id: str):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        return await asyncio.to_thread(load_qualifying_results, race_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/races/{race_id}/gaps")
async def get_gap_history(race_id: str):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        data = await asyncio.to_thread(load_gap_history, race_id)
        return {**data, "race_id": race_id}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/races/{race_id}/sectors")
async def get_sector_times(race_id: str, driver: str):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        laps = await asyncio.to_thread(load_sector_times, race_id, driver.upper())
        return {"driver_code": driver.upper(), "laps": laps}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/races/{race_id}/telemetry")
async def get_telemetry(race_id: str, driver: str, lap: int):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        points = await asyncio.to_thread(load_telemetry, race_id, driver.upper(), lap)
        return {"driver_code": driver.upper(), "lap": lap, "points": points}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/races/{race_id}/weather")
async def get_weather(race_id: str):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        frames = await asyncio.to_thread(load_weather_data, race_id)
        return {"race_id": race_id, "frames": frames}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/races/{race_id}/stints")
async def get_stints(race_id: str):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        return await asyncio.to_thread(load_stint_data, race_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/races/{race_id}/points")
async def get_race_points(race_id: str):
    """Points each driver scored in this race, plus the driver/constructor
    standings immediately after it (not the season's final result)."""
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        result = await asyncio.to_thread(champ_engine.get_race_points, race_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
    if result is None:
        raise HTTPException(status_code=503, detail=f"Could not compute points for '{race_id}'")
    return result


@router.get("/championship/{year}/drivers")
async def get_driver_championship(year: int):
    if year < 2018 or year > 2026:
        raise HTTPException(status_code=400, detail="Year must be 2018-2026")
    try:
        return await asyncio.to_thread(champ_engine.get_driver_standings, year)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/championship/{year}/constructors")
async def get_constructor_championship(year: int):
    if year < 2018 or year > 2026:
        raise HTTPException(status_code=400, detail="Year must be 2018-2026")
    try:
        return await asyncio.to_thread(champ_engine.get_constructor_standings, year)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
