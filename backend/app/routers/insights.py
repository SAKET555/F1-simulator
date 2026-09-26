"""
Insight catalogue and season Q&A endpoints. Heavy pandas / index work runs in
a worker thread so it can't stall the replay websocket.
"""
import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from app.engine import insights, rag
from app.engine.data_loader import get_race_meta

router = APIRouter(tags=["insights"])


@router.get("/races/{race_id}/insights")
async def race_insight_list(race_id: str):
    if get_race_meta(race_id) is None:
        raise HTTPException(status_code=404, detail=f"Race '{race_id}' not found")
    try:
        result = await asyncio.to_thread(insights.race_insights, race_id)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Could not build insights: {exc}")
    return {**result, "categories": insights.CATEGORIES}


@router.get("/seasons/{year}/insights")
async def season_insight_list(year: int):
    result = await asyncio.to_thread(insights.season_insights, year)
    if not result["races_analysed"]:
        raise HTTPException(status_code=404, detail=f"No locally cached races for {year}")
    return result


@router.get("/rag/coverage")
async def rag_coverage():
    return await asyncio.to_thread(rag.coverage)


@router.get("/rag/search")
async def rag_search(
    q: str = Query(..., min_length=2, max_length=200),
    year: Optional[int] = Query(None, ge=2000, le=2100),
    limit: int = Query(8, ge=1, le=25),
):
    return await asyncio.to_thread(rag.search, q, year, limit)
