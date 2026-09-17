"""
WebSocket endpoint  /ws/race/{race_id}

Query params:
  speed  – replay multiplier: 2 | 5 | 10  (default 2)
  start  – lap to start from              (default 1)

Protocol (server → client):
  { "type": "race_state",  "payload": RaceState }
  { "type": "prediction",  "payload": PredictionFrame }
  { "type": "race_end",    "payload": { "race_id": ..., "winner": ... } }
  { "type": "error",       "payload": { "detail": ... } }

Client → server:
  { "type": "set_speed",   "payload": { "speed": 5 } }
  { "type": "pause" }
  { "type": "resume" }
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.engine.data_loader import get_race_meta
from app.engine.monte_carlo import simulate_race
from app.engine.replay import replay_race
from app.schemas.race import PredictionFrame, RaceState

log = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


def _serialize(msg_type: str, payload: dict) -> str:
    return json.dumps({"type": msg_type, "payload": payload})


@router.websocket("/ws/race/{race_id}")
async def race_websocket(
    websocket: WebSocket,
    race_id: str,
    speed: float = 2.0,
    start: int = 1,
):
    await websocket.accept()
    log.info("WS connected: race_id=%s speed=%.0fx start_lap=%d", race_id, speed, start)

    if get_race_meta(race_id) is None:
        await websocket.send_text(
            _serialize("error", {"detail": f"Unknown race_id: {race_id}"})
        )
        await websocket.close()
        return

    paused   = False
    cur_speed = speed

    async def listen_client():
        """Background task: handle control messages from the browser."""
        nonlocal paused, cur_speed
        try:
            while True:
                raw = await websocket.receive_text()
                msg = json.loads(raw)
                mtype = msg.get("type", "")
                if mtype == "pause":
                    paused = True
                    log.debug("WS pause")
                elif mtype == "resume":
                    paused = False
                    log.debug("WS resume")
                elif mtype == "set_speed":
                    cur_speed = float(msg.get("payload", {}).get("speed", cur_speed))
                    log.debug("WS speed → %.0f", cur_speed)
        except (WebSocketDisconnect, Exception):
            pass

    listener = asyncio.create_task(listen_client())

    try:
        async for race_state in replay_race(race_id, speed_multiplier=cur_speed, start_lap=start):
            # Honour dynamic speed / pause
            while paused:
                await asyncio.sleep(0.1)

            # Emit race state
            await websocket.send_text(
                _serialize("race_state", race_state.model_dump())
            )

            # Run MC simulation and emit predictions
            probs = simulate_race(
                current_lap=race_state.lap,
                total_laps=race_state.total_laps,
                grid_state=race_state.cars,
                race_id=race_id,
                n_simulations=500,   # lighter while streaming
            )
            pred = PredictionFrame(
                lap=race_state.lap,
                probabilities=probs[:10],
                n_simulations=500,
            )
            await websocket.send_text(
                _serialize("prediction", pred.model_dump())
            )

        # Race finished
        winner = race_state.cars[0] if race_state.cars else None
        await websocket.send_text(
            _serialize("race_end", {
                "race_id": race_id,
                "winner": winner.driver_code if winner else "N/A",
                "winner_car_id": winner.car_id if winner else None,
            })
        )

    except WebSocketDisconnect:
        log.info("WS disconnected: race_id=%s", race_id)
    except RuntimeError as exc:
        # Starlette raises RuntimeError (not WebSocketDisconnect) when the client
        # closes while the server is still writing — treat it as a normal disconnect.
        if "websocket.send" in str(exc) or "response already completed" in str(exc):
            log.info("WS client closed early: race_id=%s", race_id)
        else:
            log.exception("WS runtime error for race_id=%s: %s", race_id, exc)
    except Exception as exc:
        log.exception("WS error for race_id=%s: %s", race_id, exc)
        try:
            await websocket.send_text(_serialize("error", {"detail": str(exc)}))
        except Exception:
            pass
    finally:
        listener.cancel()
        log.info("WS closed: race_id=%s", race_id)
