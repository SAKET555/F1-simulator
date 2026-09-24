"""
Analytics endpoints: pandas-derived statistics (JSON) and matplotlib charts
and circuit layouts rendered as PNG. All blocking work runs in a worker
thread so it can't stall the live race websocket.
"""
import asyncio

from fastapi import APIRouter, HTTPException, Response

from app.engine import analytics, circuits
from app.engine.data_loader import get_race_meta

router = APIRouter(tags=["analytics"])

_PNG_HEADERS = {"Cache-Control": "public, max-age=3600"}


def _require_race(race_id: str) -> None:
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")


@router.get("/races/{race_id}/analytics/summary")
async def analytics_summary(race_id: str):
    _require_race(race_id)
    try:
        return await asyncio.to_thread(analytics.summary, race_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not build analytics: {exc}")


@router.get("/races/{race_id}/analytics/charts")
async def analytics_chart_list(race_id: str):
    _require_race(race_id)
    return analytics.chart_list()


@router.get("/races/{race_id}/analytics/charts/{chart_id}.png")
async def analytics_chart(race_id: str, chart_id: str):
    _require_race(race_id)
    try:
        png = await asyncio.to_thread(analytics.render_chart, race_id, chart_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not render chart: {exc}")
    if png is None:
        raise HTTPException(status_code=404, detail=f"Unknown chart '{chart_id}'")
    return Response(content=png, media_type="image/png", headers=_PNG_HEADERS)


@router.get("/races/{race_id}/circuit.png")
async def circuit_image(race_id: str):
    _require_race(race_id)
    png = await asyncio.to_thread(circuits.circuit_image, race_id)
    if png is None:
        raise HTTPException(
            status_code=404,
            detail="No position data is archived for this circuit yet, so its layout can't be drawn.",
        )
    return Response(content=png, media_type="image/png", headers=_PNG_HEADERS)
