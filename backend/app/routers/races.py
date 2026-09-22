from fastapi import APIRouter, HTTPException
from app.engine.data_loader import (
    list_available_races, get_race_meta, is_locally_cached,
    load_qualifying_results, load_gap_history, load_sector_times,
    load_telemetry, load_weather_data, load_stint_data,
)
from app.engine import championship as champ_engine

router = APIRouter(tags=["races"])


@router.get("/races")
async def get_races():
    """List all available race sessions (2016-2026, ~180+ events)."""
    races = list_available_races()
    return [
        {**r, "cached": is_locally_cached(r["race_id"])}
        for r in races
    ]


@router.get("/races/{race_id}")
async def get_race_detail(race_id: str):
    """Return metadata for a single race."""
    meta = get_race_meta(race_id)
    if meta is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    return {**meta, "cached": is_locally_cached(race_id)}


@router.get("/races/{race_id}/qualifying")
async def get_qualifying(race_id: str):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        return load_qualifying_results(race_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/races/{race_id}/gaps")
async def get_gap_history(race_id: str):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        data = load_gap_history(race_id)
        return {**data, "race_id": race_id}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/races/{race_id}/sectors")
async def get_sector_times(race_id: str, driver: str):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        laps = load_sector_times(race_id, driver.upper())
        return {"driver_code": driver.upper(), "laps": laps}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/races/{race_id}/telemetry")
async def get_telemetry(race_id: str, driver: str, lap: int):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        points = load_telemetry(race_id, driver.upper(), lap)
        return {"driver_code": driver.upper(), "lap": lap, "points": points}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/races/{race_id}/weather")
async def get_weather(race_id: str):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        frames = load_weather_data(race_id)
        return {"race_id": race_id, "frames": frames}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/races/{race_id}/stints")
async def get_stints(race_id: str):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        return load_stint_data(race_id)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/championship/{year}/drivers")
async def get_driver_championship(year: int):
    if year < 2018 or year > 2026:
        raise HTTPException(status_code=400, detail="Year must be 2018-2026")
    try:
        return champ_engine.get_driver_standings(year)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))


@router.get("/championship/{year}/constructors")
async def get_constructor_championship(year: int):
    if year < 2018 or year > 2026:
        raise HTTPException(status_code=400, detail="Year must be 2018-2026")
    try:
        return champ_engine.get_constructor_standings(year)
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))
