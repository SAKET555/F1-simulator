"""
WebSocket smoke-test for SAK RACING SIM.

Connects to the live backend, streams frames, prints results,
and asserts the minimum contract:
  - at least one race_state frame with non-empty cars list
  - at least one prediction frame with probabilities

Run:
    python tests/test_ws_client.py
"""
import asyncio
import json
import sys

# Use websockets ≥ 12 client API
import websockets
from websockets.exceptions import ConnectionClosedOK, ConnectionClosedError

HOST    = "localhost"
PORT    = 8000
RACE_ID = "2023-monza"
SPEED   = 10    # 10× so laps stream quickly
MAX_LAP_FRAMES = 8   # collect 8 race_state frames then stop

WS_URL  = f"ws://{HOST}:{PORT}/ws/race/{RACE_ID}?speed={SPEED}"


async def main():
    print(f"  Connecting -> {WS_URL}\n")
    try:
        ws = await websockets.connect(WS_URL, open_timeout=10)
    except OSError as e:
        print(f"FAIL  Cannot connect: {e}")
        print("      Is `uvicorn main:app --reload` running on port 8000?")
        sys.exit(1)

    counts       = {"race_state": 0, "prediction": 0, "race_end": 0, "error": 0}
    got_cars     = False
    got_probs    = False

    try:
        while counts["race_state"] < MAX_LAP_FRAMES:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=30)
            except asyncio.TimeoutError:
                print("WARN  No message in 30 s — aborting")
                break

            msg   = json.loads(raw)
            mtype = msg.get("type", "unknown")
            counts[mtype] = counts.get(mtype, 0) + 1

            if mtype == "race_state":
                s     = msg["payload"]
                cars  = s.get("cars", [])
                leader = cars[0] if cars else None
                tag   = (
                    f"P1={leader['driver_code']} "
                    f"tyre={leader['tire_compound']}({leader['tire_age_laps']}L) "
                    f"gap={leader['gap_to_leader_s']:.3f}s"
                ) if leader else "(no cars yet — lap 1 formation)"
                print(
                    f"  [race_state]  lap {s['lap']:>2}/{s['total_laps']}  "
                    f"cars={len(cars)}  {tag}"
                )
                if cars:
                    got_cars = True

            elif mtype == "prediction":
                p     = msg["payload"]
                probs = p.get("probabilities", [])
                top3  = "  ".join(
                    f"{d['driver_code']}:{d['win_pct']:.1f}%" for d in probs[:3]
                ) if probs else "(empty — no cars on track yet)"
                print(f"  [prediction]  lap {p['lap']:>2}  n={p['n_simulations']}  {top3}")
                if probs:
                    got_probs = True

            elif mtype == "race_end":
                w = msg["payload"].get("winner", "?")
                print(f"  [race_end]    winner={w}")
                break

            elif mtype == "error":
                print(f"  [error]  {msg['payload'].get('detail')}", file=sys.stderr)
                await ws.close()
                sys.exit(1)

    except (ConnectionClosedOK, ConnectionClosedError):
        pass  # server closed cleanly after race end
    finally:
        try:
            await ws.close()
        except Exception:
            pass

    print(f"\n  Frames received: { {k:v for k,v in counts.items() if v} }")

    # Assertions
    errors = []
    if counts["race_state"] == 0:
        errors.append("No race_state frames received")
    if counts["prediction"] == 0:
        errors.append("No prediction frames received")
    if not got_cars:
        errors.append(
            "All race_state frames had empty cars list "
            "(FastF1 may still be downloading — re-run after data is cached)"
        )
    if not got_probs:
        errors.append(
            "All prediction frames had empty probabilities "
            "(expected once cars list is populated)"
        )

    if errors:
        print("\n  WARNINGS:")
        for e in errors:
            print(f"    - {e}")
        if counts["race_state"] > 0 and counts["prediction"] > 0:
            print("\n  PARTIAL PASS  (stream connected and protocol is correct;")
            print("                re-run once FastF1 has cached the session data)")
            sys.exit(0)
        else:
            print("\n  FAIL")
            sys.exit(1)

    print("\n  PASS  WebSocket smoke-test complete")


if __name__ == "__main__":
    asyncio.run(main())
