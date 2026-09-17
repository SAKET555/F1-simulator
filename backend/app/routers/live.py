"""
Live F1 timing endpoints using the free OpenF1 API.
No authentication required — https://openf1.org

REST:
  GET  /api/live/session    → current session or {"live": false}

WebSocket:
  WS   /ws/live             → streams race_state + prediction frames
                              every ~5 s while the race is active
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.engine.openf1 import get_live_session, stream_live

log = logging.getLogger(__name__)

router = APIRouter(tags=["live"])


@router.get("/api/live/session")
async def live_session_status():
    """
    Check whether a Formula 1 race is currently happening.

    Returns  { live: true,  session: {...} }   during an active race.
    Returns  { live: false, session: null  }   otherwise.
    """
    session = await get_live_session()
    return {"live": session is not None, "session": session}


@router.websocket("/ws/live")
async def live_websocket(websocket: WebSocket):
    """
    WebSocket endpoint for live F1 race data.

    Connects to OpenF1 and polls every 5 s.
    Emits the same  race_state / prediction / race_end / info  messages
    as the historical replay endpoint so the frontend requires no changes.
    """
    await websocket.accept()
    log.info("WS /ws/live accepted")
    try:
        await stream_live(websocket)
    except WebSocketDisconnect:
        log.info("WS /ws/live disconnected")
    except RuntimeError as exc:
        if "websocket" in str(exc).lower():
            log.info("WS /ws/live client closed early")
        else:
            log.exception("WS /ws/live runtime error: %s", exc)
    except Exception as exc:
        log.exception("WS /ws/live error: %s", exc)
    finally:
        log.info("WS /ws/live closed")
