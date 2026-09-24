import asyncio

from fastapi import APIRouter, HTTPException
from app.engine.data_loader import load_session_laps, get_race_meta
from app.engine.monte_carlo import (
    simulate_counterfactual, simulate_race,
    calculate_undercut, calculate_optimal_stop,
)
from app.engine.replay import _build_car_states
from app.schemas.race import (
    CounterfactualRequest,
    CounterfactualResponse,
    PredictionFrame,
    UndercutRequest,
    UndercutResponse,
    OptimalStopRequest,
)

router = APIRouter(prefix="/simulate", tags=["simulate"])


@router.post("/counterfactual", response_model=CounterfactualResponse)
async def counterfactual(req: CounterfactualRequest):
    """
    Given the current race state, return revised win probabilities if
    car_id pits on pit_lap for target_compound.
    """
    if get_race_meta(req.race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{req.race_id}' not found")

    try:
        laps_df, total_laps = await asyncio.to_thread(load_session_laps, req.race_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Data load error: {exc}")

    max_lap = int(laps_df["LapNumber"].max())
    # Use the lap the frontend is currently replaying; fall back to last data lap
    current_lap = req.current_lap if req.current_lap is not None else max_lap

    if req.pit_lap <= current_lap:
        raise HTTPException(
            status_code=400,
            detail=f"pit_lap ({req.pit_lap}) must be > current_lap ({current_lap})",
        )
    if req.pit_lap > total_laps:
        raise HTTPException(
            status_code=400,
            detail=f"pit_lap ({req.pit_lap}) exceeds total_laps ({total_laps})",
        )

    lap_group = laps_df[laps_df["LapNumber"] == current_lap]
    grid_state = _build_car_states(lap_group, laps_df, current_lap)

    car_in_grid = next((c for c in grid_state if c.car_id == req.car_id), None)
    if car_in_grid is None:
        raise HTTPException(status_code=404, detail=f"Car {req.car_id} not in grid")

    original_wp, cf_wp = simulate_counterfactual(
        current_lap=current_lap,
        total_laps=total_laps,
        grid_state=grid_state,
        car_id=req.car_id,
        pit_lap=req.pit_lap,
        target_compound=req.target_compound,
        race_id=req.race_id,
    )

    delta_win = round(cf_wp.win_pct - original_wp.win_pct, 2)
    explanation = (
        f"Pitting {car_in_grid.driver_code} on lap {req.pit_lap} "
        f"for {req.target_compound} tyres changes win probability "
        f"from {original_wp.win_pct:.1f}% to {cf_wp.win_pct:.1f}% "
        f"({'(+)' if delta_win >= 0 else '(-)'} {abs(delta_win):.1f} pp)."
    )

    return CounterfactualResponse(
        car_id=req.car_id,
        driver_code=car_in_grid.driver_code,
        original_win_pct=original_wp.win_pct,
        new_win_pct=cf_wp.win_pct,
        delta_win_pct=delta_win,
        original_podium_pct=original_wp.podium_pct,
        new_podium_pct=cf_wp.podium_pct,
        delta_podium_pct=round(cf_wp.podium_pct - original_wp.podium_pct, 2),
        explanation=explanation,
    )


@router.post("/undercut", response_model=UndercutResponse)
async def undercut_analysis(req: UndercutRequest):
    if get_race_meta(req.race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{req.race_id}' not found")
    try:
        laps_df, total_laps = await asyncio.to_thread(load_session_laps, req.race_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    lap_group = laps_df[laps_df["LapNumber"] == req.current_lap]
    grid_state = _build_car_states(lap_group, laps_df, req.current_lap)

    result = calculate_undercut(
        current_lap=req.current_lap,
        total_laps=total_laps,
        grid_state=grid_state,
        car_id=req.car_id,
        target_car_id=req.target_car_id,
        pit_lap=req.pit_lap,
        target_compound=req.target_compound,
        race_id=req.race_id,
    )
    return UndercutResponse(**result)


@router.post("/optimal-stop")
async def optimal_stop(req: OptimalStopRequest):
    if get_race_meta(req.race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{req.race_id}' not found")
    try:
        laps_df, _ = await asyncio.to_thread(load_session_laps, req.race_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))

    lap_group = laps_df[laps_df["LapNumber"] == req.current_lap]
    grid_state = _build_car_states(lap_group, laps_df, req.current_lap)
    car_state = next((c for c in grid_state if c.car_id == req.car_id), None)
    if car_state is None:
        raise HTTPException(status_code=404, detail=f"Car {req.car_id} not in grid")

    windows = calculate_optimal_stop(
        current_lap=req.current_lap,
        total_laps=req.total_laps,
        car_state=car_state,
        race_id=req.race_id,
        compounds_available=list(req.compounds_available) if req.compounds_available else None,
    )
    return {"windows": windows}
