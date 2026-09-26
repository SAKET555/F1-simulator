"""
Download and cache every past race so replay, analytics and the insight search
work offline and instantly.

Run from the backend folder:

    python scripts/cache_all_races.py            # everything not yet cached
    python scripts/cache_all_races.py 2023 2024  # only these seasons

It is safe to stop and restart: races already cached are skipped. Upcoming
races and any race dated today (possibly still running) are skipped too.
Each race is fetched once through FastF1 and stored as a processed lap table,
then its insights are built so "Ask the season" covers it as well.
"""
from __future__ import annotations

import logging
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.getLogger("fastf1").setLevel(logging.ERROR)
logging.basicConfig(level=logging.WARNING)


def main(years: set[int]) -> int:
    from app.engine import insights, storage
    from app.engine.data_loader import list_available_races, load_session_laps

    today = date.today().isoformat()
    races = [r for r in list_available_races() if not years or r["year"] in years]
    todo = [r for r in races if not storage.exists(r["race_id"]) and (r.get("event_date") or "9999") < today]
    print(f"{len(races)} races in scope, {len(todo)} to fetch", flush=True)

    failed: list[tuple[str, str]] = []
    started = time.time()
    for n, r in enumerate(todo, 1):
        rid = r["race_id"]
        t0 = time.time()
        try:
            load_session_laps(rid)
            insights.race_insights(rid)
            status = "ok"
        except Exception as exc:                       # one bad race must not stop the rest
            failed.append((rid, f"{type(exc).__name__}: {str(exc)[:120]}"))
            status = f"FAILED ({type(exc).__name__})"
        elapsed = time.time() - started
        eta = elapsed / n * (len(todo) - n)
        print(f"[{n}/{len(todo)}] {rid} {r['event_name']}: {status} in {time.time() - t0:.0f}s "
              f"· ETA {eta / 60:.0f} min", flush=True)

    print(f"\nDone in {(time.time() - started) / 60:.0f} min. {len(todo) - len(failed)} cached, {len(failed)} failed.")
    for rid, why in failed:
        print(f"  {rid}: {why}")
    return 0


if __name__ == "__main__":
    sys.exit(main({int(a) for a in sys.argv[1:]}))
