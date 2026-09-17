from fastapi import APIRouter, HTTPException
from app.engine.data_loader import list_available_races, get_race_meta, is_locally_cached

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
