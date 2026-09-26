"""
Smoothed driver trajectory + estimated off-track excursions for one lap.
The work (possibly a FastF1 telemetry load) runs in a worker thread so it
can't stall the replay websocket.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.engine import trajectory
from app.engine.data_loader import get_race_meta

router = APIRouter(tags=["trajectory"])


@router.get("/races/{race_id}/trajectory")
async def driver_trajectory(
    race_id: str,
    driver: str = Query(..., min_length=2, max_length=4),
    lap: int = Query(..., ge=1, le=100),
    threshold_m: float = Query(trajectory.DEFAULT_THRESHOLD_M, ge=1.0, le=20.0),
):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        result = await asyncio.to_thread(trajectory.driver_trajectory, race_id, driver.upper(), lap, threshold_m)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not build trajectory: {exc}")
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No position data for this driver and lap, or no circuit reference line for this track.",
        )
    return result


@router.get("/races/{race_id}/trajectories")
async def lap_trajectories(
    race_id: str,
    lap: int = Query(..., ge=1, le=100),
    threshold_m: float = Query(trajectory.DEFAULT_THRESHOLD_M, ge=1.0, le=20.0),
):
    """Every driver's smoothed path for one lap, on a shared clock."""
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        result = await asyncio.to_thread(trajectory.lap_trajectories, race_id, lap, threshold_m)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not build trajectories: {exc}")
    if result is None:
        raise HTTPException(
            status_code=404,
            detail="No position data for this lap, or no circuit reference line for this track.",
        )
    return result
