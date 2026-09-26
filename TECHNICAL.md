# SAK RACING SIM: Technical Guide

*How the simulator actually works, what it is built from, and where its numbers come from.*

This document is the long companion to [README.md](README.md). The README tells you how to **run** the project.
This file tells you how it **works**: every layer, every important function, the maths behind the simulations,
the data quirks that shaped the code, the things that are estimates rather than facts, and the known defects.

It is written for someone who can read Python and JavaScript but has never seen this codebase. It quotes the real
source (the code blocks are copied straight from the repository, not retyped), explains why each piece exists,
and is honest about what is approximate. Between the technical chapters you will find short **pit-wall trivia**
boxes with Formula 1 history, one for each season the app covers, because a race simulator is more fun when you
remember what actually happened on the track.

> 🏁 **Pit-wall trivia: how it all started.** The first race of the Formula One World Championship was the 1950
> British Grand Prix at Silverstone on 13 May 1950, and Giuseppe Farina won it in an Alfa Romeo. Timing then was
> done by hand with stopwatches. The data this app replays is measured to the thousandth of a second by
> transponders in the cars.

---

## Table of contents

1. [Overview and design goals](#1-overview-and-design-goals)
2. [Architecture](#2-architecture)
3. [The technology stack](#3-the-technology-stack)
4. [Repository layout, configuration and the app factory](#4-repository-layout-configuration-and-the-app-factory)
5. [Where the data comes from](#5-where-the-data-comes-from)
6. [The cache: three layers and why](#6-the-cache-three-layers-and-why)
7. [The calendar](#7-the-calendar)
8. [Turning laps into a race: the replay engine](#8-turning-laps-into-a-race-the-replay-engine)
9. [The WebSocket protocol](#9-the-websocket-protocol)
10. [Monte Carlo win probability](#10-monte-carlo-win-probability)
11. [Strategy tools: counterfactual, undercut, optimal stop](#11-strategy-tools-counterfactual-undercut-optimal-stop)
12. [The analytics engine](#12-the-analytics-engine)
13. [The insights engine](#13-the-insights-engine)
14. [Ask the season: retrieval over computed facts](#14-ask-the-season-retrieval-over-computed-facts)
15. [Circuits and the trajectory engine](#15-circuits-and-the-trajectory-engine)
16. [Championship, qualifying, sectors, weather and stints](#16-championship-qualifying-sectors-weather-and-stints)
17. [The frontend](#17-the-frontend)
18. [The design system](#18-the-design-system)
19. [API reference](#19-api-reference)
20. [Data structures reference](#20-data-structures-reference)
21. [Testing](#21-testing)
22. [Performance notes](#22-performance-notes)
23. [Known limitations and defects](#23-known-limitations-and-defects)
24. [Data-source problems we met and how we handled them](#24-data-source-problems-we-met-and-how-we-handled-them)
25. [Troubleshooting, in depth](#25-troubleshooting-in-depth)
26. [Extending the project](#26-extending-the-project)
27. [Glossary](#27-glossary)
28. [Season-by-season trivia index](#28-season-by-season-trivia-index)

---

## 1. Overview and design goals

### 1.1 What the project is

SAK Racing Sim is a two-process web application:

* A **Python backend** (FastAPI) that loads Formula 1 timing data, derives a race state for every lap, streams it to
  the browser, runs Monte Carlo simulations, computes analytics, and serves everything as JSON, PNG images and one
  WebSocket.
* A **React frontend** (Vite, Tailwind CSS, Recharts) that draws the dashboard, animates the replay, and lets you
  drive the strategy tools.

There is **no database**. Everything is derived on demand from FastF1's data and cached as files on disk. There is
no login, no server-side session, and no external service other than FastF1's own data download.

### 1.2 Design goals

The project grew feature by feature, and a few principles show up again and again in the code:

1. **Derive, do not trust.** The data source sometimes gives wrong or missing values (results tables that come
   back empty, positions that teleport, laps with no time). Wherever a number could be computed from the raw lap
   timing instead of read from a higher-level table, the code computes it. The championship module, for example,
   scores races from our own classification because FastF1's results table is unreliable here.
2. **Cache aggressively, invalidate explicitly.** A finished race never changes, so every expensive result is
   stored on disk. Each cache carries a *version number*; when a bug fix changes what a cached value means, the
   version is bumped and stale entries rebuild themselves.
3. **Never block the event loop.** FastAPI is asynchronous; the heavy work (pandas, FastF1, matplotlib) is pushed
   onto worker threads with `asyncio.to_thread`, so one slow request cannot freeze a running replay.
4. **Label estimates as estimates.** Overtakes, undercuts, pit-stop losses, tyre wear and track-limit excursions
   are inferred, not measured. The UI and the API say so wherever they appear.
5. **Small, additive modules.** Each capability lives in its own module (`insights.py`, `rag.py`,
   `trajectory.py`) with its own router and tests, so features can be added or removed without touching the
   replay and simulation core.
6. **Be honest about failure.** When a session has no data, the app says so ("no position data", "no timed
   laps") instead of drawing something misleading.

### 1.3 Non-goals

* It is **not** a live-timing product. Live data was removed (see [section 24](#24-data-source-problems-we-met-and-how-we-handled-them)).
* It is **not** a predictor. The win probabilities are a teaching model, described honestly in [section 10](#10-monte-carlo-win-probability).
* It does **not** replace official results. Classification is re-derived from lap timing and can differ from the
  FIA's official result in edge cases (penalties applied after the race, for example).
* It does **not** store or redistribute F1 data beyond your own machine's cache.

### 1.4 The project by the numbers

| Measure | Value |
|---|---|
| Races in the catalogue | 174 (2018 to 2026, excluding 2022) |
| Races cached on the author's machine | 165 (every past race that could be downloaded) |
| Backend Python modules | about 20 (engine, routers, schemas, core) |
| Frontend components | 19 |
| Analyses per race (Insights) | 45 to 48, depending on what the race contains |
| Season roll-up statistics | 16 per season |
| Rendered analytics charts | 8 per race |
| Backend tests | 24 |
| On-disk cache for everything | about 2.2 GB |

> 🏁 **Pit-wall trivia: 2018, the Halo arrives.** The Halo, the titanium bar over the cockpit, became mandatory in
> 2018. It weighs roughly 7 kg, is strong enough to bear the weight of a London double-decker bus, and drivers
> and fans complained about its looks for about a week before it started saving lives. Charles Leclerc also made
> his debut that year, with Sauber, and Lewis Hamilton clinched a fifth world title at the Mexican Grand Prix.

---

## 2. Architecture

### 2.1 The big picture

```
                    ┌───────────────────────────── your browser ─────────────────────────────┐
                    │  React app (Vite dev server :5173, or static files in production)       │
                    │                                                                         │
                    │   RaceSelector ──► App shell ──► tabs:                                  │
                    │   Overview · Charts · Analytics · Insights · Telemetry · Strategy · …   │
                    │        │                │                                               │
                    │  fetch() JSON/PNG   WebSocket /ws/race/{id}                             │
                    └────────┼────────────────┼───────────────────────────────────────────────┘
                             │                │
                    ┌────────▼────────────────▼───────────────────────────────────────────────┐
                    │  FastAPI (Uvicorn :8000)                                                │
                    │                                                                         │
                    │  routers/  races · analytics · insights · trajectory · simulate · ws    │
                    │      │                                                                  │
                    │  engine/   data_loader ─► storage (pickle cache) ◄─ calendar            │
                    │            replay ─► monte_carlo                                        │
                    │            analytics ─► insights ─► rag                                 │
                    │            circuits ─► trajectory                                       │
                    │            championship                                                 │
                    └─────────┼───────────────────────────────────────────────────────────────┘
                              │ only when something is not cached yet
                    ┌─────────▼──────────────┐        ┌────────────────────────────┐
                    │  FastF1 library         │  ───►  │  F1 live-timing archive     │
                    │  (+ its HTTP cache)     │        │  (static JSON streams)      │
                    └─────────────────────────┘        └────────────────────────────┘

                    ┌──────────────────────────────────────────────────────────────────────┐
                    │  cache/  (files on your disk)                                        │
                    │    calendar_cache.json · fastf1_http_cache.sqlite                    │
                    │    processed/{race}.pkl · processed/extra/*.pkl                      │
                    │    processed/charts/*.png · processed/insights/*.json                │
                    └──────────────────────────────────────────────────────────────────────┘
```

Two facts about this picture matter for everything that follows:

1. **The backend is stateless between requests** apart from a few in-memory `lru_cache`s. Restart it and
   nothing is lost; the disk cache is the source of truth.
2. **The frontend holds all the UI state.** The selected race, the replay speed, the active tab, the trajectory
   map's camera: none of it lives on the server.

### 2.2 Three kinds of request

| Kind | Example | How it is served |
|---|---|---|
| **Pull** (JSON) | `GET /api/races/2021-r05/insights` | An `async` handler calls a blocking engine function in a worker thread and returns the dict. |
| **Pull** (image) | `GET /api/races/2021-r05/analytics/charts/race_trace.png` | The engine renders a matplotlib figure to PNG bytes, caches them on disk and returns them. |
| **Push** (stream) | `WS /ws/race/2021-r05?speed=2` | A long-lived WebSocket. The server emits a race state and a prediction for every lap; the browser sends pause, resume and speed commands. |

### 2.3 The life of a click

Follow one user action end to end: the user clicks **Monaco 2021**.

1. `RaceSelector.jsx` calls `onSelect(race)`; `App.jsx` stores it in `selectedRace`.
2. `useRaceSocket(raceId, speed)` sees a new `raceId` and opens `ws://localhost:8000/ws/race/2021-r05?speed=2`.
3. In `ws.py`, `race_websocket` accepts the socket, checks `get_race_meta`, and starts `replay_race(...)`.
4. `replay_race` calls `load_session_laps("2021-r05")` in a worker thread:
   1. `storage.load` finds `cache/processed/2021-r05.pkl` and returns the DataFrame in a few milliseconds.
   2. (On a miss it would call FastF1, clean the data, and write the pickle.)
5. For lap 1, `_build_car_states` turns that lap's rows into an ordered list of `CarState` objects (position, gap,
   tyre, laps down, retired flag).
6. `ws.py` serialises a `race_state` message and sends it.
7. It then calls `simulate_race(...)` with 500 simulations and sends a `prediction` message.
8. `replay_race` sleeps `5.0 / speed` seconds and moves to lap 2. Repeat until the last lap, then a `race_end`.
9. In the browser, `useRaceSocket` puts each message into React state; `Leaderboard`, `WinProbabilityChart`
   and the header re-render.
10. If the user opens the **Insights** tab, `InsightsPanel` independently calls `GET /api/races/2021-r05/insights`
    and `GET /api/seasons/2021/insights`. The replay keeps running underneath.

Steps 4 to 8 are the heart of the app and are covered in chapters 6, 8, 9 and 10.

### 2.4 Module dependency map

Arrows mean "imports".

```
routers/races.py ───► engine/data_loader ─► engine/storage
                └───► engine/championship ─► engine/replay (_build_car_states)
routers/ws.py ──────► engine/replay ─────────► engine/data_loader
                └───► engine/monte_carlo
routers/simulate.py ► engine/monte_carlo, engine/replay
routers/analytics.py ► engine/analytics ─► engine/replay, engine/data_loader
                    └► engine/circuits ──► engine/analytics (colours), engine/storage
routers/insights.py ► engine/insights ───► engine/analytics
                    └► engine/rag ───────► engine/insights
routers/trajectory.py ► engine/trajectory ► engine/circuits, engine/data_loader, engine/storage
engine/calendar ◄── engine/data_loader (catalogue) ◄── nearly everything
```

Two design consequences: `data_loader` and `replay._build_car_states` are the **shared foundation** (championship,
analytics, simulate and the WebSocket all use the same classification logic), and `analytics.RaceData` is the
shared foundation for everything *statistical* (insights, and through them the search).

---

## 3. The technology stack

This chapter lists every significant dependency, the version the project pins or uses, what it does here, and why it
was chosen. Where a choice is a trade-off, both sides are given.

### 3.1 Backend

| Package | Version | Role in this project |
|---|---|---|
| **Python** | 3.11 | Language. Chosen because NumPy 1.26, pandas 2.2 and FastF1 all support it fully. |
| **FastAPI** | 0.111.0 | Web framework: routing, request validation, OpenAPI docs at `/docs`, native WebSocket support. |
| **Starlette** | 0.37.2 (via FastAPI) | The ASGI toolkit under FastAPI; provides the WebSocket and CORS middleware. |
| **Uvicorn** | 0.29.0 (`[standard]`) | The ASGI server. The `standard` extra brings `websockets` and `httptools` for speed. |
| **websockets** | 12.0 | WebSocket protocol implementation used by Uvicorn (and by the manual test client). |
| **Pydantic** | 2.7.1 | Typed request and response models (`CarState`, `RaceState`, ...). Validation runs in Rust and is fast. |
| **pydantic-settings** | 2.2.1 | Reads configuration from environment variables and `.env`. |
| **FastF1** | 3.3.7 | Downloads and parses F1 timing data into pandas DataFrames. The single source of race data. |
| **pandas** | 2.2.2 | All tabular work: lap tables, group-bys, pivots, medians. |
| **NumPy** | 1.26.4 | Vectorised Monte Carlo, splines, the search index scoring. |
| **SciPy** | 1.16 (via FastF1) | `cKDTree` for nearest-point lookups in the trajectory engine. |
| **Matplotlib** | 3.8+ | Renders the analytics charts and circuit outline server-side using the `Agg` backend (no display needed). |
| **httpx** | 0.27.0 | HTTP client (used by the retired live-timing code; kept as a general-purpose dependency). |
| **pytest / pytest-asyncio** | 8.2.0 / 0.23.6 | Test runner. |

**Why FastAPI rather than Flask or Django?** The replay is a long-lived WebSocket that must stay responsive while
other requests run. FastAPI's async model and first-class WebSocket support fit that exactly. Flask would need
extra libraries for sockets; Django's channels layer would be far heavier than needed for a single-user tool.

**Why files instead of a database?** The data is read-mostly, keyed by race, and naturally a whole pandas
DataFrame per race. A pickle per race is a direct, fast fit. There are no relational queries, no concurrent
writers that matter, and no schema migrations to manage. The cost is that there is no cross-race query engine, which is why the
insights module precomputes JSON summaries and the search module builds its own index in memory.

**Why server-side matplotlib for charts?** The eight analytics charts have dense, custom styling (shaded
neutralised laps, hollow pit markers, per-team colours and dashed teammates). Rendering in Python next to the
pandas that computes them keeps the logic in one place, and the PNGs are cached to disk so each is drawn once.
The trade-off is that those eight charts are images: they do not zoom or show tooltips. (The newer Insights charts
are drawn client-side with Recharts precisely for interactivity.)

### 3.2 Frontend

| Package | Version | Role |
|---|---|---|
| **React** | 19.2 | UI library. Function components and hooks only. |
| **Vite** | 8 | Dev server with hot reload and the production bundler. |
| **@vitejs/plugin-react** | 6 | JSX transform and fast refresh. |
| **Tailwind CSS** | 3.4 | Utility-first styling; design tokens live in `tailwind.config.js`. |
| **PostCSS + Autoprefixer** | 8 / 10 | Required by Tailwind. |
| **Recharts** | 3.10 | Declarative SVG charts: bars, lines, areas, reference areas, tooltips. |
| **lucide-react** | 1.x | Icon set (tab icons, buttons). |
| **oxlint** | 1.x | Fast linter (`npm run lint`). |

Not used, on purpose: no state-management library (React state plus a couple of custom hooks is enough), no router
(the app has two screens, and the URL hash is used only for share links), no TypeScript, no CSS-in-JS, no UI kit.

### 3.3 Data and services

| Service | Used for | Notes |
|---|---|---|
| **F1 live-timing archive** (`livetiming.formula1.com/static/...`) | The actual timing data | Fetched by FastF1, never directly by this project. Refuses 2022 (HTTP 403). |
| **Ergast / Jolpica** | Race results tables | Consulted by FastF1 3.3.7 and usually failing; the project deliberately does not depend on it. |
| **Google Fonts** | Barlow Condensed, Inter, JetBrains Mono | Loaded by `index.html`; falls back to system fonts offline. |

> 🏁 **Pit-wall trivia: 2019, a point for the fastest lap.** From 2019 to 2024 the driver who set the race's
> fastest lap earned one championship point, provided they finished in the top ten. That is why a chapter later
> in this guide discusses the championship module's `FL_POINT` constant. The rule was dropped for 2025.
> Robert Kubica also returned in 2019 with Williams, his first Formula 1 season since 2010, after a 2011 rally crash nearly
> ended his career; he appears as `KUB` in the 2019 data.

---

## 4. Repository layout, configuration and the app factory

### 4.1 Layout

```
apexsim/
├── README.md                 how to run
├── TECHNICAL.md              this file
├── LICENSE, NOTICE           Apache-2.0
├── .gitignore                ignores cache/, .venv, node_modules, dist, .env
├── cache/                    generated; can be deleted at any time
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   ├── scripts/cache_all_races.py
│   ├── app/
│   │   ├── core/    app.py, config.py
│   │   ├── routers/ analytics.py insights.py races.py simulate.py trajectory.py ws.py
│   │   ├── engine/  analytics.py calendar.py championship.py circuits.py data_loader.py
│   │   │            insights.py monte_carlo.py rag.py replay.py storage.py trajectory.py
│   │   └── schemas/ race.py
│   └── tests/       test_fastf1_import.py test_insights.py test_monte_carlo.py
│                    test_trajectory.py test_ws_client.py
└── frontend/
    ├── index.html  vite.config.js  tailwind.config.js  postcss.config.js  package.json
    ├── public/     favicon.svg icons.svg manifest.json
    └── src/
        ├── main.jsx  App.jsx  index.css
        ├── components/  (19 files, one per panel or chart)
        ├── hooks/       useRaceSocket.js useKeyboardShortcuts.js useShareableUrl.js
        └── lib/         constants.js
```

### 4.2 The entry point

*`backend/main.py`*

```python
import uvicorn
from app.core.app import create_app

app = create_app()

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
```

`main.py` does nothing but build the app. The interesting part is `create_app`:

*`backend/app/core/app.py`*

```python
def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="Real-time F1 Race & Strategy Simulator — SAK Racing Sim",
        version="2.0.0",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(races.router, prefix="/api")
    app.include_router(simulate.router, prefix="/api")
    app.include_router(analytics_router.router, prefix="/api")
    app.include_router(insights_router.router, prefix="/api")
    app.include_router(trajectory_router.router, prefix="/api")
    app.include_router(ws.router)

    @app.get("/api/health")
    async def health():
        return {"status": "ok", "app": settings.app_name, "version": "2.0.0"}

    return app
```

Things worth noticing:

* **CORS** is configured from settings so the browser (on port 5173) may call the API (on port 8000).
  `allow_credentials=True` is set but the app uses no cookies; it is harmless.
* Routers are mounted with a `/api` prefix, **except** the WebSocket router, which serves at `/ws/...`.
  (`simulate.router` carries its own `/simulate` prefix, so simulation endpoints end up at `/api/simulate/...`.)
* `health` is defined inline. It exists so scripts and monitors have something cheap to ping.

### 4.3 The lifespan hook

*`backend/app/core/app.py`*

```python
def _build_calendar_sync() -> None:
    """Runs in a thread-pool executor so it never blocks the event loop."""
    try:
        from app.engine.calendar import build_catalogue
        races_list = build_catalogue()
        log.info("Calendar ready: %d races", len(races_list))
    except Exception as exc:
        log.error("Calendar build failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Build / refresh the race calendar in a background thread at startup.
    # If calendar_cache.json already exists this returns in < 1 ms.
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(loop.run_in_executor(None, _build_calendar_sync))
    yield
```

On startup the backend schedules the calendar build on the default thread-pool executor and *does not wait for it*.
If `calendar_cache.json` exists this finishes in well under a millisecond; on the very first run it fetches
the schedule for every supported season from FastF1, which needs the internet and takes a few seconds. Requests
that arrive during that window call `build_catalogue()` themselves, so nothing fails; they just may wait.

### 4.4 Settings

*`backend/app/core/config.py`*

```python
class Settings(BaseSettings):
    app_name: str = "SAK RACING SIM"
    debug: bool = True
    cache_dir: str = str(Path(__file__).resolve().parents[3] / "cache")
    cors_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]
    pit_loss_monza: float = 22.0
    pit_loss_zandvoort: float = 24.0

    class Config:
        env_file = ".env"
```

* `cache_dir` is computed from the file's own location: `parents[3]` of `app/core/config.py` is the repository
  root, so the cache lives at `<repo>/cache`. Override with the `CACHE_DIR` environment variable.
* The class-based `Config` (rather than Pydantic v2's `model_config`) triggers a deprecation warning in the test
  output. It is harmless and left as is.
* `pit_loss_monza` and `pit_loss_zandvoort` are declared here but **not used anywhere**: the simulator has its own
  table in `monte_carlo.py`. That table has a real defect, described in [section 23](#23-known-limitations-and-defects).

> 🏁 **Pit-wall trivia: 2020, the year of the calendar puzzle.** The COVID-19 pandemic pushed the season's first
> race to July, at the Red Bull Ring in Austria, and the 2020 calendar shrank to 17 races (exactly the number the
> app has cached). To fill it the sport went to circuits that were new or long-forgotten: Mugello (Ferrari's
> 1,000th Grand Prix), the Nürburgring, Portimão and Imola. It also raced twice at Silverstone, twice at the Red Bull Ring, and
> twice at Bahrain, once on a short outer layout whose laps lasted under a minute.

---

## 5. Where the data comes from

### 5.1 The source: F1's live-timing archive

Formula 1 publishes the timing screens you see on the broadcast as a set of JSON "streams". After a session ends they
remain available as static files under `https://livetiming.formula1.com/static/<year>/<date>_<event>/<date>_<session>/`.
There is no official documentation for them and no promise that they stay available. The community library
**FastF1** exists to read them, merge them into consistent tables and cache the downloads.

This project never talks to F1's servers directly. It asks FastF1 for a `Session` and reads the tables FastF1
builds. That matters for the licensing and terms discussion in the README: the project relies on the same public
archive the library does, and does not scrape anything else.

### 5.2 What FastF1 gives us

A `Session` object (here always the *Race*, sometimes the *Qualifying* session) exposes, once loaded:

| FastF1 table | Used here for |
|---|---|
| `session.laps` | The core table: one row per driver per lap with lap time, sector times, compound, tyre life, pit-in and pit-out times, cumulative time. Everything in the replay and analytics is derived from it. |
| `session.results` | Official classification. **Not used** for races (see below); used for qualifying. |
| `session.weather_data` | Air and track temperature, humidity, wind, rain, sampled about once a minute. |
| `session.car_data` / `pos_data` | High-rate speed/throttle/brake/gear and X/Y position. Merged by `lap.get_telemetry()`. |
| `session.get_circuit_info()` | Numbered corner positions for the circuit. |

`session.load()` takes flags that decide how much is downloaded, and the project is careful with them:

| Flag | Meaning | Where we use it |
|---|---|---|
| `telemetry=False` | Skip the heavy car and position data | Loading laps for replay and analytics |
| `telemetry=True` | Download car data and positions (tens of MB per session) | Only when a telemetry or trajectory request needs it |
| `weather=True` | Weather table | The weather widget |
| `messages=True` | Race-control messages | Qualifying, because FastF1's fallback classification needs them |

### 5.3 The lap table we build

`load_session_laps` is the single entry point that produces the table everything else reads. Here it is in full:

*`backend/app/engine/data_loader.py`*

```python
@lru_cache(maxsize=16)
def load_session_laps(race_id: str) -> tuple[pd.DataFrame, int]:
    """
    Return (laps_df, total_laps) for *race_id*.

    Load order:
      1. Processed pickle  →  instant
      2. FastF1 disk cache →  fast (no network)
      3. FastF1 network    →  slow first time, then pickled for future use

    laps_df columns:
      DriverNumber, Driver, Team, LapNumber, LapTime_s,
      Compound, TyreLife, IsPitIn, IsPitOut
    """
    from app.engine import storage

    # 1 — persistent processed cache
    cached = storage.load(race_id)
    if cached is not None:
        return cached

    # 2/3 — FastF1 (disk cache or network)
    _ensure_cache_dir()
    meta = get_race_meta(race_id)
    if meta is None:
        raise ValueError(f"Unknown race_id: {race_id!r}")

    log.info("Loading %s %s Race from FastF1 …", meta["year"], meta["event_name"])
    session = fastf1.get_session(meta["year"], meta["round_number"], "R")
    session.load(telemetry=False, weather=False, messages=False)

    laps: pd.DataFrame = session.laps.copy()
    laps = laps[laps["LapNumber"].notna()].copy()
    laps["LapNumber"] = laps["LapNumber"].astype(int)
    laps["LapTime_s"] = laps["LapTime"].dt.total_seconds()
    # Cumulative session-elapsed time at which this lap was completed, as
    # FastF1/the FIA timing feed computed it directly — kept alongside
    # LapTime_s because the two are NOT interchangeable: the opening lap of
    # a race has no LapTime (there's no previous lap to diff against, so
    # FastF1 leaves it NaN), so summing LapTime_s across laps silently drops
    # each driver's own — differing — opening-lap duration. Using Time_s
    # directly for "how far has this driver got" avoids re-deriving (and
    # subtly corrupting) a number FastF1 already computed correctly.
    laps["Time_s"] = laps["Time"].dt.total_seconds()

    # FastF1 sometimes leaves the literal string "nan" (not a real null) in
    # this column, which .fillna() doesn't catch — it only slips through
    # str.upper() as "NAN" and then fails CarState's tire_compound schema.
    # Normalize by whitelist instead, so any unrecognized value (NaN, "nan",
    # empty string, junk) safely falls back to "UNKNOWN".
    laps["Compound"] = (
        laps["Compound"]
        .fillna("UNKNOWN")
        .astype(str)
        .str.upper()
        .replace({
            "HYPERSOFT": "SOFT", "ULTRASOFT": "SOFT",
            "SUPERSOFT": "SOFT", "SUPERHARD": "HARD",
        })
    )
    _valid_compounds = {"SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET", "UNKNOWN"}
    laps.loc[~laps["Compound"].isin(_valid_compounds), "Compound"] = "UNKNOWN"
    laps["IsPitOut"] = laps["PitOutTime"].notna()
    laps["IsPitIn"]  = laps["PitInTime"].notna()
    laps["TyreLife"] = laps["TyreLife"].fillna(0).astype(int)

    total_laps = int(laps["LapNumber"].max())

    keep = ["DriverNumber", "Driver", "Team",
            "LapNumber", "LapTime_s", "Time_s",
            "Compound", "TyreLife", "IsPitIn", "IsPitOut"]
    laps = laps[keep].reset_index(drop=True)

    log.info("Loaded %d lap rows, total_laps=%d — saving to processed cache",
             len(laps), total_laps)

    # Save permanently so next load is instant
    storage.save(race_id, laps, total_laps)

    return laps, total_laps
```

Read it as four stages.

**Stage 1: the persistent cache.** `storage.load(race_id)` returns the finished DataFrame from
`cache/processed/<race_id>.pkl` if it exists and its version matches. This is the path taken by every request
for an already-cached race and costs a few milliseconds.

**Stage 2: fetch.** `fastf1.get_session(year, round, "R")` followed by `session.load(telemetry=False,
weather=False, messages=False)`. This is the slow, networked step (10 to 60 seconds; FastF1's own HTTP cache makes a
repeat faster).

**Stage 3: clean.** Four transformations turn FastF1's table into the compact one the rest of the app uses:

1. `LapNumber` becomes an integer, and rows without one are dropped.
2. `LapTime` (a pandas `Timedelta`) becomes `LapTime_s`, a float of seconds; likewise `Time` becomes `Time_s`.
3. `Compound` is normalised by **whitelist**: upper-cased, historical names mapped (`HYPERSOFT`, `ULTRASOFT`,
   `SUPERSOFT` to `SOFT`; `SUPERHARD` to `HARD`) and everything not in
   `{SOFT, MEDIUM, HARD, INTERMEDIATE, WET, UNKNOWN}` forced to `UNKNOWN`. FastF1 sometimes leaves the literal
   string `"nan"` in that column, which slips past `.fillna()` and would later fail Pydantic validation.
4. `PitInTime` and `PitOutTime` become the booleans `IsPitIn` and `IsPitOut`; `TyreLife` becomes an integer.

**Stage 4: keep ten columns and store them.** The final table has exactly these columns:

| Column | Type | Meaning |
|---|---|---|
| `DriverNumber` | str | Car number, used as the unique key for a driver |
| `Driver` | str | Three-letter code, e.g. `VER` |
| `Team` | str | Team name as FastF1 spells it that year |
| `LapNumber` | int | 1-based lap |
| `LapTime_s` | float | Lap time in seconds; **NaN on lap 1** and on laps with no valid time |
| `Time_s` | float | Cumulative session-elapsed time when the lap was completed |
| `Compound` | str | Tyre compound during that lap |
| `TyreLife` | int | Laps done on this set at that lap |
| `IsPitIn` | bool | The car entered the pits on this lap |
| `IsPitOut` | bool | The car left the pits on this lap |

### 5.4 Why `Time_s` exists: a bug that shaped the design

The first version summed `LapTime_s` to get each driver's race time. It looked right and was wrong in a subtle way:
**lap 1 has no `LapTime`** (there is no previous timing line to subtract from), so summing silently dropped each
driver's own, differing, first-lap duration. Gaps to the leader came out five to six times too large. The fix was to
keep FastF1's own cumulative `Time` column as `Time_s` and use it everywhere a "how far along is this car" number
is needed. `storage.CACHE_VERSION` was bumped to 2 so old pickles rebuilt themselves; the comment above the constant
in `storage.py` records the story so nobody undoes it.

Corollary rules the code now follows:

* **Never sum `LapTime_s` to get race time.** Use `Time_s`.
* A lap's `LapTime_s` can include a red-flag stoppage; do not treat it as a pace figure without filtering.
* `Time_s` for a driver on lap *n* is comparable with another driver's `Time_s` on the same lap *n*, but a driver who
  is a lap down has an earlier snapshot, which is why the replay ranks by laps-down first (chapter 8).

### 5.5 Other data-loading functions

The remaining loaders in `data_loader.py` follow one pattern: check `storage.load_extra(key)`, otherwise fetch from
FastF1, shape the result into plain lists of dicts, store it, return it.

| Function | FastF1 call | Cache key | Notes |
|---|---|---|---|
| `load_qualifying_results` | `Q` session with `messages=True` | `{race}_qualifying` | The messages flag matters: without race-control messages FastF1 cannot classify qualifying when Ergast is unavailable, and every driver came back as position 99. |
| `load_gap_history` | none (uses the lap table) | in-memory `lru_cache` | Pivots `Time_s` by lap and driver to gaps to the leader. |
| `load_sector_times` | `R` session, laps only | `{race}_sectors_{driver}` | Sector 1, 2 and 3 times per lap. |
| `load_telemetry` | `R` session with telemetry | `{race}_telemetry_{driver}_{lap}` | The slowest call; merges car data with position data. |
| `load_weather_data` | `R` session with weather | `{race}_weather` | Sampled by an approximation, see below. |
| `load_stint_data` | none (uses the lap table) | none | Splits each driver's laps into stints. |

Two details deserve attention.

**Telemetry has X and Y only through `get_telemetry()`.** An early version used `get_car_data()`, which contains
speed, throttle, brake, gear and RPM but *no position columns at all*. The code read `row.get("X", 0)`, silently got
the default `0` for every point of every race, and the track map drew a single dot. The fix, and the version bump
that goes with it (`EXTRA_CACHE_VERSION = 3`), is described in the comment inside `load_telemetry`:

*(Full source: `backend/app/engine/data_loader.py`, `load_telemetry`.)*

**Weather is mapped to laps approximately.** `load_weather_data` assumes a lap lasts 135 seconds
(`approx_lap = t_secs / 135.0`). That is a single global constant, so at Monaco (laps of about 75 seconds) the
weather is attached to laps that are too early, and at Spa (about 105 seconds) it is a little off too. The weather
widget is a colour-coding aid, not a measurement, but it is a known approximation.

### 5.6 The FastF1 warnings you will see

Every session load prints something like:

```
WARNING  Failed to load result data from Ergast!
WARNING  No result data for this session available on Ergast! (This is expected for recent sessions)
WARNING  Failed to add first lap time from Ergast!
```

Ergast, the historical-results web service that older FastF1 versions used, was shut down at the end of 2024 and its
data now lives in a community successor called Jolpica; later FastF1 releases switched to it. The project pins
FastF1 **3.3.7**, which still tries Ergast and fails. This is the reason the project does not use `session.results`
for races: the table arrives with `Position` set to NaN for every driver. Everything that needs a classification
(the championship, the insights, the summary card) derives it from lap timing instead. The warnings are noise.

> 🏁 **Pit-wall trivia: 2021, the shortest race in history.** The 2021 Belgian Grand Prix at Spa never truly
> happened: after heavy rain the cars did a few slow laps behind the safety car, the race was stopped, and a result
> was declared on the countback with half points awarded. In this project's data that race, `2021-r12`, has **no
> timed laps at all**, so the insights engine records it as "nothing to analyse" and the season roll-ups skip it.
> That is why the 2021 roll-ups say "21 races analysed" although the season had 22.

---

## 6. The cache: three layers and why

### 6.1 Overview

There are three distinct caches, plus two derived-output caches. They are easy to confuse, so here they are side by
side:

| Layer | Where | Written by | What it holds | Invalidated by |
|---|---|---|---|---|
| **1. FastF1 HTTP cache** | `cache/fastf1_http_cache.sqlite` and `cache/<year>/...` | FastF1 itself | Raw downloaded API responses | Never (delete the folder to reset) |
| **2. Processed lap table** | `cache/processed/<race>.pkl` | `storage.save` | The cleaned 10-column DataFrame + total laps | `CACHE_VERSION` |
| **3. Extra query cache** | `cache/processed/extra/<key>.pkl` | `storage.save_extra` | Telemetry, sectors, weather, qualifying, per-race championship points, circuit outlines, corner lists | `EXTRA_CACHE_VERSION` |
| Charts | `cache/processed/charts/<race>_<chart>_v2.png` | `analytics.render_chart` | Rendered PNGs and circuit images | `ANALYTICS_VERSION` and the pickle's timestamp |
| Insights | `cache/processed/insights/<race>_v2.json` | `insights.race_insights` | The 40+ statistics and structured chart data | `INSIGHTS_VERSION` and the pickle's timestamp |
| In-memory | Python process | `functools.lru_cache` | Hot DataFrames and computed objects | Process restart |

### 6.2 The processed lap table

*`backend/app/engine/storage.py`*

```python
def save(race_id: str, df: pd.DataFrame, total_laps: int) -> None:
    p = _path(race_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as fh:
        pickle.dump({"df": df, "total_laps": total_laps, "version": CACHE_VERSION}, fh,
                    protocol=pickle.HIGHEST_PROTOCOL)
    log.info("Stored processed data for %s (%d laps, %d rows)",
             race_id, total_laps, len(df))


def load(race_id: str) -> tuple[pd.DataFrame, int] | None:
    p = _path(race_id)
    if not p.exists():
        return None
    try:
        with open(p, "rb") as fh:
            data = pickle.load(fh)
        if data.get("version") != CACHE_VERSION:
            log.info("Processed cache for %s is stale (schema changed) — will re-fetch", race_id)
            return None
        log.info("Loaded processed data for %s from persistent cache", race_id)
        return data["df"], data["total_laps"]
    except Exception as exc:
        log.warning("Processed cache corrupt for %s (%s) — will re-fetch", race_id, exc)
        p.unlink(missing_ok=True)
        return None
```

A pickle stores a dictionary `{"df": ..., "total_laps": ..., "version": ...}`. `load` returns `None` in three
situations, each of which makes the caller rebuild:

1. the file does not exist;
2. the stored `version` is not the current `CACHE_VERSION` (stale schema);
3. the file is corrupt (unpickling raised). The corrupt file is deleted so the next call rebuilds cleanly.

> **Pickle safety.** Pickle can execute code when loaded, so a cache file from an untrusted source must never be
> loaded. Here the cache is written and read only by this program on your own machine. Do not copy `cache/`
> directories from strangers.

### 6.3 The extra-query cache

*`backend/app/engine/storage.py`*

```python
def _extra_path(key: str) -> Path:
    from app.core.config import settings
    # Query params (driver codes etc.) become part of `key`, so keep it
    # filesystem-safe rather than assuming callers already sanitised it.
    safe_key = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
    return Path(settings.cache_dir) / "processed" / "extra" / f"{safe_key}.pkl"


def save_extra(key: str, value) -> None:
    p = _extra_path(key)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "wb") as fh:
        pickle.dump({"value": value, "version": EXTRA_CACHE_VERSION}, fh,
                    protocol=pickle.HIGHEST_PROTOCOL)


def load_extra(key: str):
    """Returns the cached value, or None on a miss/corrupt/stale entry."""
    p = _extra_path(key)
    if not p.exists():
        return None
    try:
        with open(p, "rb") as fh:
            data = pickle.load(fh)
        if data.get("version") != EXTRA_CACHE_VERSION:
            return None
        return data["value"]
    except Exception as exc:
        log.warning("Extra cache corrupt for %s (%s) — will re-fetch", key, exc)
        p.unlink(missing_ok=True)
        return None
```

`_extra_path` sanitises the key to filename-safe characters (query parameters such as driver codes become part of the
key). The comment block above `EXTRA_CACHE_VERSION` in the source is worth reading in full: it lists exactly which
bugs each version bump fixed (v2: qualifying returned position 99 for everyone; v3: telemetry had zero coordinates).
That habit, *documenting what a version number means at the moment you bump it*, is the project's answer to the
classic problem of a cache that quietly keeps serving a bug's output long after the bug is fixed.

### 6.4 Why not just use FastF1's cache?

FastF1's own cache stores raw HTTP responses. Loading a session from it is still 5 to 15 seconds because FastF1
re-parses and merges everything. The processed pickle skips all that: the app reads a ready-made DataFrame.
A cold race costs roughly 10 to 60 seconds; a warm one costs about 5 milliseconds.

### 6.5 Warming everything at once

`backend/scripts/cache_all_races.py` fetches every past race that is not cached, one after another:

*(Full source: `backend/scripts/cache_all_races.py`, `main`.)*

Notes on the script:

* It compares each race's `event_date` with today's date as an ISO string (`YYYY-MM-DD` sorts correctly as text),
  so a race dated today, which may still be running, is skipped.
* It builds each race's insights straight after loading it, so the search index covers the race immediately.
* A failure is caught per race and reported at the end, so one broken race does not stop the batch.
* On the author's machine 122 races downloaded in about 18 minutes (10 to 15 seconds each).

> 🏁 **Pit-wall trivia: 2021, the title decided on the last lap.** Lewis Hamilton and Max Verstappen arrived at the
> final round in Abu Dhabi level on points. A late crash brought out the safety car, the race was restarted for one
> final lap, and Verstappen, on fresher tyres, passed Hamilton to take his first title. The controversy over how the
> safety-car procedure was applied led to a change in the race-control rules and to the departure of the race
> director. The season also introduced the **sprint** format (Silverstone, Monza and Interlagos), and Saudi Arabia
> hosted its first Grand Prix in Jeddah.

---

## 7. The calendar

### 7.1 What it does

The calendar is the list of every race the app knows about: id, year, round, event name, circuit, date, lap count.
It lives in `calendar.py` and is cached in `cache/calendar_cache.json`.

*`backend/app/engine/calendar.py`*

```python
UNAVAILABLE_YEARS: set[int] = {2022}
SUPPORTED_YEARS: list[int] = [y for y in range(2016, 2027) if y not in UNAVAILABLE_YEARS]
```

### 7.2 Race ids

A race id is `"{year}-r{round:02d}"`, for example `2021-r05` (the fifth round of 2021, Monaco). It is a plain string
key used in URLs, file names and cache keys. It carries **no circuit name**, which is important to the pit-loss
defect described in chapter 23.

### 7.3 Building the catalogue

*(Full source: `backend/app/engine/calendar.py`, `_fetch_year,build_catalogue`.)*

* `_fetch_year` asks FastF1 for one season's event schedule and keeps the fields above. Testing rounds (`RoundNumber
  == 0`) are skipped. A failing season returns an empty list rather than raising, so one bad year cannot stop the
  others.
* `total_laps` is a **guess** from the circuit name using the `CIRCUIT_LAPS` table (`guess_laps`), used for display
  before a race's real lap count is known. The replay overrides it with the true count from the lap table.
* The result is sorted newest season first, then by round, and written to JSON.
* On later starts `build_catalogue` reads the JSON and filters it to `SUPPORTED_YEARS`. That filter is why removing a
  year from the list takes effect immediately even though the JSON file still contains it.

### 7.4 Why 2022 is missing

`UNAVAILABLE_YEARS = {2022}` records a fact about the outside world: F1's archive returns `403 Access Denied` for
**every** 2022 URL, including the season index. The failure is confusing at the surface because FastF1 turns it into
`KeyError: 'DriverNumber'` when it tries to build the driver table from an empty response. The project does not try
to work around it. A season that cannot be loaded is not listed. Bringing it back is a one-line change once F1's
archive allows it again.

> 🏁 **Pit-wall trivia: 2022, the season this app cannot show.** 2022 was the year the sport reinvented its cars:
> ground-effect aerodynamics returned after four decades, generating downforce through shaped underfloor tunnels,
> and cars began to "porpoise", bouncing violently at speed. Max Verstappen won 15 of 22 races, then a record. Mercedes, the eight-time constructors' champions,
> won only one race (George Russell in Brazil). It is also the season the timing archive refuses to serve.

---

## 8. Turning laps into a race: the replay engine

### 8.1 The problem

FastF1's lap table is a list of *events*: "driver 1 finished lap 14 at session time 1,412.3 s in 88.7 s on medium
tyres." A race dashboard needs a *snapshot*: "at the end of lap 14, who is in which position, how far behind the
leader, on what tyres, how many stops so far, and who has retired?" `replay.py` converts the first into the second.

The function that does it, `_build_car_states`, is the most consequential piece of logic in the project. The
WebSocket, the championship, the analytics, the insights and all three strategy endpoints call it. Getting it wrong
would silently corrupt everything, so the code is heavily commented with the reasons behind each rule. This chapter
walks through those reasons.

*`backend/app/engine/replay.py`*

```python
def _build_car_states(
    lap_group: pd.DataFrame,
    all_laps: pd.DataFrame,
    lap_number: int,
) -> list[CarState]:
    """
    Build ordered list of CarState objects for a given lap snapshot.
    Ordering uses cumulative lap time to derive position.

    Drivers who retired before `lap_number` (no further lap rows recorded)
    are classified after every still-running car, ordered by how far they
    got before retiring — not by their frozen partial cumulative time, which
    would otherwise make an early DNF look like it's "leading" once the
    field races past whatever tiny time they'd accumulated before stopping.
    """
    # All unique drivers in the session (includes DNFs)
    all_drivers = (
        all_laps[["DriverNumber", "Driver", "Team"]]
        .drop_duplicates("DriverNumber")
    )

    # Each driver's most recent recorded lap at or before this lap number —
    # "how far have they got by now". cumulative_time_s comes straight from
    # that row's Time_s (FastF1's own cumulative session-elapsed time), not
    # from summing LapTime_s: the opening lap has no LapTime (no previous
    # lap to diff against), so summing silently drops each driver's own —
    # differing — opening-lap duration and throws gap-to-leader off by
    # hundreds of seconds. This same lookup also covers retirees, who have
    # no row for lap_number itself — their last known state carries forward.
    as_of = (
        all_laps[all_laps["LapNumber"] <= lap_number]
        .sort_values("LapNumber")
        .groupby("DriverNumber")
        .tail(1)
        .rename(columns={"LapNumber": "as_of_lap", "Compound": "compound_asof", "TyreLife": "tyre_life_asof"})
        [["DriverNumber", "as_of_lap", "Time_s", "compound_asof", "tyre_life_asof"]]
    )

    cum = all_drivers.merge(as_of, on="DriverNumber", how="left")
    cum["cumulative_time_s"] = cum["Time_s"].fillna(float("inf"))

    # A driver a lap or more down has an `as_of_lap` short of `lap_number`,
    # so their Time_s is a snapshot from *earlier* in the session than
    # everyone still on the current lap. We do NOT try to project it forward
    # to make it directly time-comparable to the lead lap: that requires
    # guessing what happened in laps we have no data for, and if a safety
    # car or red flag fell in exactly that gap (which it did the one time
    # this was tried, on the exact race this logic was built against — 2021
    # Abu Dhabi), the guess is confidently wrong regardless of how the pace
    # estimate is built. Real F1 timing sidesteps this the same way: a
    # lapped car shows "+1 LAP", not a time gap. So: rank primarily by
    # `laps_down` (how current a car's data is), and only use time as a
    # tiebreaker *within* the same laps_down bucket, where it's a fair,
    # like-for-like comparison.
    total_laps = int(all_laps["LapNumber"].max())
    cum["laps_down"] = (lap_number - cum["as_of_lap"]).clip(lower=0).fillna(0).astype(int)

    # A driver who's a lap or more down can still finish the race — the
    # leader takes the chequered flag first, so a lapped car's last lap row
    # is always short of `total_laps` even though it's a normal classified
    # finisher, not a DNF. Using "no row at lap_number" alone to mean
    # "retired" wrongly flagged every lapped car as a DNF (e.g. 2021 Abu
    # Dhabi showed only 11 finishers when 15 actually finished). Use the
    # FIA's own classification rule instead: a car that completes at least
    # 90% of the race distance is classified as a finisher regardless of how
    # many laps down it ended up; only a car that falls short of that before
    # lap_number is a genuine retirement.
    finish_threshold = max(1, math.ceil(0.9 * total_laps))
    last_lap_by_driver = all_laps.groupby("DriverNumber")["LapNumber"].max()
    cum["last_lap"] = cum["DriverNumber"].map(last_lap_by_driver).fillna(0).astype(int)
    cum["retired"] = (cum["last_lap"] < lap_number) & (cum["last_lap"] < finish_threshold)

    # Running order first — by laps_down, then by time within the same
    # laps_down bucket (this is where being "on the lead lap" with
    # laps_down=0 for every currently-racing car makes the sort a normal,
    # fair time-based leaderboard again). Retirees after, ranked by who got
    # furthest, which is how real F1 classifies a DNF.
    running = cum[~cum["retired"]].sort_values(["laps_down", "cumulative_time_s"], ascending=[True, True])
    retirees = cum[cum["retired"]].sort_values("cumulative_time_s", ascending=False)
    cum = pd.concat([running, retirees], ignore_index=True)
    cum["position"] = range(1, len(cum) + 1)

    on_lead_lap = running[running["laps_down"] == 0]
    leader_time = on_lead_lap["cumulative_time_s"].min() if len(on_lead_lap) else 0.0
    if leader_time == float("inf") or pd.isna(leader_time):
        leader_time = 0.0

    # Merge with current-lap tyre/pit details (drop duplicate name cols first)
    lap_info = lap_group.drop(columns=["Driver", "Team"], errors="ignore")
    merged = cum.merge(lap_info, on="DriverNumber", how="left")

    cars: list[CarState] = []
    for _, row in merged.iterrows():
        retired = bool(row["retired"])
        raw_cum = row["cumulative_time_s"]
        cum_s = float(raw_cum) if raw_cum != float("inf") and pd.notna(raw_cum) else 0.0

        # Prefer this lap's own tyre data; fall back to the as-of snapshot —
        # covers retirees and any driver missing an exact row at lap_number.
        compound_val = row.get("Compound")
        if pd.isna(compound_val):
            compound_val = row.get("compound_asof")
        tyre_life_val = row.get("TyreLife")
        if pd.isna(tyre_life_val):
            tyre_life_val = row.get("tyre_life_asof")

        raw_compound = str(compound_val).upper() if pd.notna(compound_val) else "UNKNOWN"
        is_in_pit_val = row.get("IsPitIn")
        laps_down = int(row["laps_down"])

        # A meaningful *time* gap only exists between cars on the same lap —
        # once a car is a lap or more behind, "gap" stops being a time
        # question and becomes a laps question (laps_down, above), same as
        # a real F1 timing screen switches from "+12.4s" to "+1 LAP". The
        # sentinel here just means "not a valid time gap, don't display it
        # as one" — the frontend keys off retired/laps_down first.
        if retired or laps_down > 0:
            gap = _RETIRED_GAP_SENTINEL
        else:
            gap = round(cum_s - leader_time, 3) if cum_s > 0 else 0.0

        state = CarState(
            car_id=int(row["DriverNumber"]),
            driver_code=str(row.get("Driver", "UNK"))[:3].upper(),
            team=str(row.get("Team", "Unknown")),
            position=int(row["position"]),
            lap_number=lap_number,
            lap_time_s=float(row["LapTime_s"]) if pd.notna(row.get("LapTime_s")) else None,
            cumulative_time_s=cum_s,
            gap_to_leader_s=gap,
            tire_compound=raw_compound if raw_compound in _VALID_COMPOUNDS else "UNKNOWN",
            tire_age_laps=int(tyre_life_val) if pd.notna(tyre_life_val) else 0,
            is_in_pit=(bool(is_in_pit_val) if pd.notna(is_in_pit_val) else False) and not retired,
            pit_count=_count_pit_stops(all_laps, str(row["DriverNumber"]), lap_number),
            retired=retired,
            laps_down=laps_down,
        )
        cars.append(state)

    return sorted(cars, key=lambda c: c.position)
```

### 8.2 Step by step

**Step 1: who is in the session at all.** The set of all drivers is taken from the *whole* lap table, not from the
current lap's rows, so a driver who retired on lap 3 still exists on lap 40 (as a retirement).

**Step 2: each driver's "as of" row.** For every driver, take their most recent lap row at or before the snapshot
lap: `all_laps[LapNumber <= lap_number]`, sorted, then `groupby(...).tail(1)`. This one lookup serves both running
cars (their row *is* the current lap) and retirees (their last known state carries forward). The cumulative time
comes from `Time_s` of that row, for the reason given in section 5.4.

**Step 3: laps down.** `laps_down = lap_number - as_of_lap`, clipped at zero. A car on the current lap has 0. A car
whose latest row is from two laps ago has 2. The important design decision is what *not* to do here. The code
does **not** try to project a lapped car's time forward to make it comparable with the leader. That would require
guessing what happened in the laps for which there is no data, and if a safety car or red flag fell in the gap the
guess would be confidently wrong. The comment in the source records that this exact mistake was made once, on
the 2021 Abu Dhabi Grand Prix, which is the race the logic was being built against. Real timing screens avoid the
problem the same way: a lapped car shows "+1 LAP", not a time.

**Step 4: who has retired.** The rule is the FIA's own classification rule:

> A car that completes at least **90 % of the race distance** is *classified* as a finisher, however many laps down.

The code computes `finish_threshold = ceil(0.9 * total_laps)` and marks a driver `retired` if their last recorded lap
is both before the snapshot lap *and* short of that threshold. The first version used "no row at this lap means
retired", which wrongly flagged every lapped car as a DNF (at the 2021 Abu Dhabi Grand Prix it showed 11 finishers
when 15 had actually finished).

**Step 5: the order.** Running cars are sorted by `(laps_down, cumulative_time_s)`. Within one `laps_down` bucket,
comparing cumulative time is a fair, like-for-like comparison, so for cars on the lead lap (laps_down 0) this is
simply the running order. Retirees come after every running car, ordered by how far they got (`cumulative_time_s`
descending), which is how a real classification lists a DNF.

**Step 6: gaps.** Only cars on the same lap have a meaningful time gap. For them the gap is
`cum_s - leader_time`, rounded to milliseconds, where `leader_time` is the smallest cumulative time on the lead lap.
For lapped or retired cars the gap is a **sentinel**, `99 999.0` (`_RETIRED_GAP_SENTINEL`). A real
`float('inf')` would be nicer but serialises to the non-standard JSON token `Infinity`, which `JSON.parse`
rejects, so a big finite number is used and the frontend checks `retired` and `laps_down` first.

**Step 7: tyre and pit details.** These come from the current lap's own row. If it is missing (a retiree), the
"as of" snapshot is used. `is_in_pit` is only true for cars still running. `pit_count` counts rows with
`IsPitIn` up to the snapshot lap.

### 8.3 Worked example

Suppose lap 30 of a 78-lap race and five cars:

| Car | Last row at or before lap 30 | laps_down | Retired? | cumulative_time_s | Rank key |
|---|---|---|---|---|---|
| A | lap 30, 2 730.1 s | 0 | no | 2 730.1 | (0, 2730.1) |
| B | lap 30, 2 733.4 s | 0 | no | 2 733.4 | (0, 2733.4) |
| C | lap 29, 2 655.0 s | 1 | no | 2 655.0 | (1, 2655.0) |
| D | lap 12, 1 100.0 s | 18 | **yes** (12 < 0.9 x 78 = 71) | 1 100.0 | after all running |
| E | lap 3, 300.0 s | 27 | **yes** | 300.0 | after D (less far) |

Result: A P1 (gap 0), B P2 (+3.3 s), C P3 (**+1 LAP**, note that its time of 2 655 s is smaller than B's, but it is
ranked below because laps_down dominates), D P4 (DNF), E P5 (DNF).

### 8.4 The generator

*`backend/app/engine/replay.py`*

```python
async def replay_race(
    race_id: str,
    speed_multiplier: float = 2.0,
    start_lap: int = 1,
) -> AsyncGenerator[RaceState, None]:
    """
    Async generator that yields RaceState objects lap by lap.
    Honors speed_multiplier (2, 5, 10) to throttle emission.
    """
    laps_df, total_laps = await asyncio.to_thread(load_session_laps, race_id)
    meta = get_race_meta(race_id) or {}
    session_name = f"{meta.get('year', '')} {meta.get('event_name', race_id)}"
    interval = _BASE_LAP_INTERVAL_S / max(speed_multiplier, 0.1)

    for lap_number in range(start_lap, total_laps + 1):
        lap_group = laps_df[laps_df["LapNumber"] == lap_number].copy()
        if lap_group.empty:
            continue

        cars = _build_car_states(lap_group, laps_df, lap_number)
        state = RaceState(
            race_id=race_id,
            lap=lap_number,
            total_laps=total_laps,
            session_name=session_name,
            cars=cars,
            timestamp_ms=time.time() * 1000,
        )
        yield state
        await asyncio.sleep(interval)
```

`replay_race` is an asynchronous generator. Key points:

* The blocking `load_session_laps` runs in a worker thread (`asyncio.to_thread`).
* Laps with no rows (rare) are skipped.
* Pacing is a plain `await asyncio.sleep(interval)` where `interval = 5.0 / speed`. So at 2x a lap is emitted every
  2.5 seconds, at 5x every second, at 10x every half second. `_BASE_LAP_INTERVAL_S = 5.0` is a "demo-friendly" number, not a
  real lap duration; a real lap is 70 to 110 seconds.
* The `speed_multiplier` is read **once**, when the generator starts. The WebSocket handler keeps a separate
  `cur_speed` variable that clients can change, but as written the interval inside `replay_race` does not see
  that change. The speed buttons therefore affect the *next connection*: `useRaceSocket` lists `speed` in its
  effect dependencies, so changing speed closes the socket and opens a new one at the new speed, restarting the race.
  Section 23 lists this among the known limitations.

### 8.5 Performance

Measured on the author's laptop for the 2021 Monaco Grand Prix: building one lap's car states takes about 25 ms;
loading the pickle takes about 2 ms. Building states for a whole race would take about 2 seconds, but the replay
does it one lap at a time so the cost is spread across the sleeps.

> 🏁 **Pit-wall trivia: 2023, dominance.** Max Verstappen won 19 of the 22 races in 2023 (a record share of a season) and
> Red Bull won 21 of 22, the only exception being Carlos Sainz's victory in Singapore. Verstappen won ten races in
> a row from Miami to Monza. The season also brought back a Las Vegas Grand Prix, run on the Strip at night for the
> first time since the 1982 race in a Caesars Palace car park, and the sprint weekends gained a separate "Shootout" qualifying session.

---

## 9. The WebSocket protocol

### 9.1 Why a WebSocket

The replay is a stream of small messages at a steady rate, in one direction, with occasional commands in the other.
Polling would waste requests and add latency; server-sent events cannot carry the browser's pause and speed
commands. A WebSocket carries both directions on one connection.

### 9.2 The endpoint

*`backend/app/routers/ws.py`*

```python
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
```

### 9.3 Message reference

**Server to client** (every message is JSON `{"type": ..., "payload": ...}`):

| `type` | When | Payload |
|---|---|---|
| `race_state` | Once per lap | A `RaceState`: race id, lap, total laps, session name, all cars, timestamp |
| `prediction` | Right after each `race_state` | A `PredictionFrame`: lap, top-10 `WinProbability` list, number of simulations (500) |
| `race_end` | After the final lap | `{race_id, winner, winner_car_id}` |
| `error` | On an unknown race id or an exception | `{detail}` |
| `info` | Reserved | `{message, live}`; the client handles it, the server no longer sends it |

**Client to server:**

| `type` | Payload | Effect |
|---|---|---|
| `pause` | none | Stops emitting until `resume` |
| `resume` | none | Continues |
| `set_speed` | `{"speed": 5}` | Updates the server's `cur_speed` variable |

**Query parameters** on connect: `speed` (default 2.0) and `start` (first lap, default 1).

### 9.4 An example exchange (illustrative values)

```
client → GET /ws/race/2021-r05?speed=5
server → {"type":"race_state","payload":{
            "race_id":"2021-r05","lap":3,"total_laps":78,"session_name":"2021 Monaco Grand Prix",
            "timestamp_ms":1790451723412.0,
            "cars":[
              {"car_id":33,"driver_code":"VER","team":"Red Bull Racing","position":1,"lap_number":3,
               "lap_time_s":77.298,"cumulative_time_s":246.1,"gap_to_leader_s":0.0,
               "tire_compound":"SOFT","tire_age_laps":8,"pit_count":0,"is_in_pit":false,
               "speed_kmh":null,"drs":false,"retired":false,"laps_down":0},
              ...19 more cars...
            ]}}
server → {"type":"prediction","payload":{
            "lap":3,"n_simulations":500,
            "probabilities":[{"car_id":33,"driver_code":"VER","win_pct":20.0,"podium_pct":58.0,
                              "expected_position":3.9}, ...]}}
   ... 75 more pairs, one per lap ...
server → {"type":"race_end","payload":{"race_id":"2021-r05","winner":"VER","winner_car_id":33}}
```

### 9.5 Why the disconnect handling looks paranoid

When the browser tab closes while the server is mid-write, Starlette raises a plain `RuntimeError` whose message
contains `websocket.send` or `response already completed`, not `WebSocketDisconnect`. The handler treats those two
messages as a normal disconnect and logs anything else with a stack trace. The `finally` block cancels the
background listener task so no coroutine is left running against a closed socket.

### 9.6 The client side

*`frontend/src/hooks/useRaceSocket.js`*

```javascript
export function useRaceSocket(raceId, speed = 2) {
  const wsRef      = useRef(null);
  const [raceState,   setRaceState]   = useState(null);
  const [predictions, setPredictions] = useState(null);
  const [status,      setStatus]      = useState("idle");
  const [winner,      setWinner]      = useState(null);
  const [infoMsg,     setInfoMsg]     = useState(null);

  const send = useCallback((obj) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(obj));
    }
  }, []);

  useEffect(() => {
    if (!raceId) return;

    setStatus("connecting");
    setRaceState(null);
    setPredictions(null);
    setWinner(null);
    setInfoMsg(null);

    const ws = new WebSocket(`${WS_BASE}/race/${raceId}?speed=${speed}`);
    wsRef.current = ws;

    ws.onopen = () => setStatus("live");

    ws.onmessage = (evt) => {
      const msg = JSON.parse(evt.data);
      switch (msg.type) {
        case "race_state":
          setRaceState(msg.payload);
          break;
        case "prediction":
          setPredictions(msg.payload);
          break;
        case "race_end":
          setWinner(msg.payload.winner);
          setStatus("finished");
          break;
        case "info":
          setInfoMsg(msg.payload.message);
          if (!msg.payload.live) setStatus("idle");
          break;
        case "error":
          console.error("WS error:", msg.payload.detail);
          setStatus("error");
          break;
        default:
          break;
      }
    };

    ws.onerror  = () => setStatus("error");
    ws.onclose  = () => {};

    return () => ws.close();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [raceId, speed]);

  const pause          = useCallback(() => send({ type: "pause" }),  [send]);
  const resume         = useCallback(() => send({ type: "resume" }), [send]);
  const setSpeedRemote = useCallback(
    (s) => send({ type: "set_speed", payload: { speed: s } }), [send]
  );

  return { raceState, predictions, status, winner, infoMsg,
```

The hook is a small state machine over one `WebSocket`:

* `status` moves `idle` → `connecting` → `live` (on open) → `finished` (on `race_end`), or `error`. In the UI, `live`
  is displayed as **REPLAYING**, because it means "the stream is running", not "this is a live race".
* Opening a new socket resets `raceState`, `predictions`, `winner` and `infoMsg`, so a new race never briefly shows
  the old one's leaderboard.
* The effect's cleanup (`return () => ws.close()`) is what stops the old stream when the race, the speed or the
  component changes.
* `pause`, `resume` and `setSpeed` are `useCallback`s that send JSON if the socket is open and do nothing
  otherwise.

### 9.7 A known blocking call

`simulate_race` is an ordinary (synchronous) function and it is called directly inside the `async for` loop, so
while it runs (about 35 to 90 ms with 500 simulations) the event loop cannot serve other requests, including other
sockets. For a single-user tool that is invisible. For many simultaneous viewers, the fix is a one-liner:
`await asyncio.to_thread(simulate_race, ...)`. It is listed in the limitations chapter.

> 🏁 **Pit-wall trivia: 2019, a lost win.** At the 2019 Bahrain Grand Prix (the first race the author cached) Charles Leclerc took his
> first pole position and led almost the whole race. Late in the race a power-unit problem robbed
> Ferrari of pace, and Lewis Hamilton won instead. The same year Leclerc did win, twice, at Spa and Monza, in
> consecutive races. Max Verstappen won a chaotic wet German Grand Prix, and Lewis Hamilton clinched his sixth
> championship in the United States.

---

## 10. Monte Carlo win probability

### 10.1 The idea

A Monte Carlo simulation answers "how likely is each outcome?" by playing the future out many times with random
variation and counting. Here: take the current order and tyre state, roll the remaining laps forward 500 times with
random lap-time noise, and count how often each car finishes first (win probability) or in the top three (podium
probability). The whole thing is vectorised with NumPy, so 500 or 1 000 full races run in tens of milliseconds
instead of seconds.

**What it is not.** The model is a teaching tool, and this chapter is blunt about that. It treats every driver and
car as *equally fast* apart from their tyres. It knows nothing about the actual pace of Verstappen versus Bottas or
Ferrari versus Haas. So it can answer "what do tyre age, compound and a pit stop do to the race?" but not "who is
faster?"

### 10.2 The constants

*`backend/app/engine/monte_carlo.py`*

```python
DEGRADATION: dict[str, float] = {
    "SOFT":         0.12,
    "MEDIUM":       0.08,
    "HARD":         0.05,
    "INTERMEDIATE": 0.07,
    "WET":          0.06,
    "UNKNOWN":      0.08,
}


BASE_PACE: dict[str, float] = {
    "SOFT":         -0.5,
    "MEDIUM":        0.0,
    "HARD":          0.4,
    "INTERMEDIATE":  1.5,
    "WET":           3.0,
    "UNKNOWN":       0.0,
}


LAP_NOISE_STD: float = 0.25   # seconds
```

| Constant | Meaning |
|---|---|
| `DEGRADATION[c]` | Seconds **added per lap of tyre age**. A soft tyre loses 0.12 s each additional lap; a hard, 0.05 s. |
| `BASE_PACE[c]` | Fixed seconds relative to a "medium" reference. Soft is 0.5 s/lap faster than medium; hard is 0.4 s/lap slower. |
| `LAP_NOISE_STD` | Standard deviation of the Gaussian noise added to every lap, 0.25 s. |

These are **hand-picked**, not fitted. The source comment explains why: a regression on the five races that were
cached at the time gave physically impossible negative degradation for soft and hard tyres (there was not enough
stint data to separate real wear from noise, traffic and per-circuit differences). Shipping the fitted values would
have made the model worse, so the round numbers stayed.

*`backend/app/engine/monte_carlo.py`*

```python
STINT_LENGTH_LAPS: dict[str, float] = {
    "SOFT":         20.0,
    "MEDIUM":       30.0,
    "HARD":         40.0,
    "INTERMEDIATE": 25.0,
    "WET":          30.0,
    "UNKNOWN":      30.0,
}


STINT_LENGTH_JITTER_STD: float = 4.0   # laps


MIN_STINT_LENGTH_LAPS: float = 8.0


_ROLLOUT_PIT_COMPOUND = "HARD"
```

### 10.3 When do simulated cars pit?

Every simulated car must eventually stop, or a soft-tyre car would "win" by running 60 laps on one set. The model
schedules each car's next stop when its current stint passes a **target length**, drawn per simulation with
jitter (standard deviation 4 laps, minimum 8 laps).

The target length comes from the race itself: `_stint_targets_for_race` takes the median completed-stint length per
compound among all drivers in *this* race, ignoring each driver's last stint (still running, so its length only
shows a lower bound), and falls back to the generic table when fewer than three stints were observed.

*`backend/app/engine/monte_carlo.py`*

```python
def _stint_targets_for_race(race_id: str) -> dict[str, float]:
    """
    Median completed-stint length per compound, observed in this specific
    race. A driver's last stint in the data is excluded (it hasn't ended in
    a pit stop — it's just wherever the replay currently is — so its length
    isn't evidence of a "typical" stint, only "at least this long").
    Compounds with fewer than 3 completed-stint observations in this race
    fall back to STINT_LENGTH_LAPS.
    """
    if race_id in _stint_target_cache:
        return _stint_target_cache[race_id]

    targets = dict(STINT_LENGTH_LAPS)
    try:
        from app.engine.data_loader import load_stint_data
        lengths_by_compound: dict[str, list[float]] = {}
        for driver in load_stint_data(race_id):
            completed = driver["stints"][:-1]   # drop the still-running final stint
            for stint in completed:
                lengths_by_compound.setdefault(stint["compound"], []).append(stint["laps"])
        for compound, lengths in lengths_by_compound.items():
            if len(lengths) >= 3 and compound in targets:
                targets[compound] = float(np.median(lengths))
    except Exception:
        log.debug("Could not derive stint targets for %s — using defaults", race_id, exc_info=True)

    _stint_target_cache[race_id] = targets
    return targets
```

For the 2021 Monaco Grand Prix this yields `SOFT 33, MEDIUM 43, HARD 58` laps: real ground truth (Monaco is
notorious for very long stints) instead of a textbook figure.

After a stop, every simulated car switches to **hard** tyres (`_ROLLOUT_PIT_COMPOUND`) for the rest of the rollout.
That is a simplification: real strategies vary. It removes the need to guess a whole tree of compound choices.

### 10.3.1 The pit-loss lookup and its defect

*`backend/app/engine/monte_carlo.py`*

```python
PIT_LOSS_BY_CIRCUIT: dict[str, float] = {
    "monza":      22.0,
    "zandvoort":  24.0,
    "monaco":     28.0,
}


DEFAULT_PIT_LOSS: float = 23.0


def _pit_loss(race_id: str) -> float:
    for key, val in PIT_LOSS_BY_CIRCUIT.items():
        if key in race_id.lower():
            return val
    return DEFAULT_PIT_LOSS
```

`_pit_loss` looks for a circuit name (`monza`, `zandvoort`, `monaco`) as a **substring of the race id**. The tests use
ids like `"2023-monza"`, so the lookup works there. Real race ids are `"2021-r14"` and contain no circuit name, so
in production the lookup **never matches** and every race uses `DEFAULT_PIT_LOSS = 23.0` seconds. Measured:
`_pit_loss("2021-r14")` (Monza) returns 23.0, not 22.0. Monaco's 28 s never applies either. Fixing it means looking
up the circuit from the race metadata, which is a small change but would alter every probability, so it is recorded as
a defect in chapter 23 instead of being silently patched.

### 10.4 The simulation itself

*`backend/app/engine/monte_carlo.py`*

```python
def simulate_race(
    current_lap: int,
    total_laps: int,
    grid_state: list[CarState],
    race_id: str = "",
    n_simulations: int = 1000,
) -> list[WinProbability]:
    """
    Run vectorised Monte Carlo simulation for remaining laps.

    Parameters
    ----------
    current_lap   : lap just completed
    total_laps    : race distance
    grid_state    : list of CarState for all active cars
    race_id       : used to look up pit-loss value
    n_simulations : number of MC paths

    Returns
    -------
    list[WinProbability] sorted by win_pct descending, top-10
    """
    if not grid_state:
        return []

    # Retired cars can't win or affect anyone else's finishing order, and a
    # car a lap or more down realistically can't either (clawing back a
    # whole lap in what's left of the race essentially never happens) —
    # project win/podium chances only for cars still racing on the lead lap,
    # and give retired/lapped cars a flat 0%/0% at their already-classified
    # position instead. This also sidesteps a real problem: a lapped car's
    # cumulative_time_s is deliberately its raw, un-projected last-known
    # value (see _build_car_states for why projecting it is unreliable), so
    # feeding it into the rollout as a normal starting time would understate
    # how far behind it actually is and inflate its odds.
    active_state     = [c for c in grid_state if not c.retired and c.laps_down == 0]
    non_contending   = [c for c in grid_state if c.retired or c.laps_down > 0]

    remaining_laps = max(total_laps - current_lap, 0)
    if remaining_laps == 0 or not active_state:
        # Race finished (or nobody left running) – winner is P1 among the
        # still-classified/active field.
        ordering = sorted(grid_state, key=lambda c: c.position)
        p1 = next((c for c in ordering if not c.retired), None)
        return [
            WinProbability(
                car_id=c.car_id,
                driver_code=c.driver_code,
                win_pct=100.0 if (p1 is not None and c.car_id == p1.car_id) else 0.0,
                podium_pct=100.0 if (not c.retired and c.position <= 3) else 0.0,
                expected_position=float(c.position),
            )
            for c in ordering
        ]

    pit_loss = _pit_loss(race_id)
    n_cars = len(active_state)
    rng = np.random.default_rng()

    # ── Build per-car base state arrays ─────────────────────────────────────
    # Shape: (n_cars,)
    cum_times   = np.array([c.cumulative_time_s for c in active_state], dtype=np.float64)
    tire_ages   = np.array([c.tire_age_laps      for c in active_state], dtype=np.float64)
    compounds   = [c.tire_compound for c in active_state]
    deg_rates   = np.array([DEGRADATION.get(cp, 0.08) for cp in compounds])
    base_paces  = np.array([BASE_PACE.get(cp, 0.0)    for cp in compounds])

    # ── Broadcast to (n_simulations, n_cars) ────────────────────────────────
    cum_matrix  = np.tile(cum_times,  (n_simulations, 1))   # (S, C)
    deg_matrix  = np.tile(deg_rates,  (n_simulations, 1))   # current compound's degradation rate — changes on a pit
    pace_matrix = np.tile(base_paces, (n_simulations, 1))   # current compound's base pace — changes on a pit
    age_matrix  = np.tile(tire_ages,  (n_simulations, 1))   # current tyre age — increments each lap, resets on a pit

    # Ground the assumed stint length in what the field actually did in this
    # race so far, rather than a generic textbook figure — see
    # _stint_targets_for_race for why we use real per-race ground truth here
    # instead of trying to statistically infer it across races.
    stint_lengths = _stint_targets_for_race(race_id)

    pit_deg  = DEGRADATION[_ROLLOUT_PIT_COMPOUND]
    pit_pace = BASE_PACE[_ROLLOUT_PIT_COMPOUND]
    pit_stint_len = stint_lengths[_ROLLOUT_PIT_COMPOUND]

    # Each car's current stint has its own target length (with jitter) at
    # which it pits again during the rollout — otherwise every simulated car
    # on a given compound would pit on exactly the same lap.
    base_stint_len = np.array([stint_lengths.get(cp, 30.0) for cp in compounds])
    stint_target = np.tile(base_stint_len, (n_simulations, 1)) + rng.normal(
        0.0, STINT_LENGTH_JITTER_STD, (n_simulations, n_cars)
    )
    stint_target = np.maximum(stint_target, MIN_STINT_LENGTH_LAPS)

    # Roll forward each lap. Tyre age is tracked as real per-lap state (not
    # `starting_age + lap_offset`, which would mean the car NEVER pits again
    # for the rest of the race) so a stop actually happens once a car's
    # current stint passes its target length — without this, a compound
    # with a flatter degradation curve just keeps "winning" the fantasy of
    # an ever-lengthening single stint, however far behind it really is.
    for _ in range(remaining_laps):
        age_matrix += 1.0
        deg_penalty = deg_matrix * age_matrix

        # Gaussian noise
        noise = rng.normal(0.0, LAP_NOISE_STD, (n_simulations, n_cars))

        # Stochastic safety car / VSC event: ~8 % chance per lap adds 15-30 s to all
        sc_event = rng.random(n_simulations) < 0.08
        sc_loss  = rng.uniform(15, 30, n_simulations) * sc_event
        sc_loss  = sc_loss[:, np.newaxis]  # broadcast over cars

        # A car pits this lap if its current stint has run past its target.
        pit_mask = age_matrix >= stint_target

        # Lap time = base_pace + degradation + noise (+ pit-lane loss if pitting)
        lap_time = 90.0 + pace_matrix + deg_penalty + noise + sc_loss
        lap_time = np.where(pit_mask, lap_time + pit_loss, lap_time)
        lap_time = np.maximum(lap_time, 60.0)   # floor (safety car stints)

        cum_matrix += lap_time

        # Reset state for cars that pitted: fresh tyre, new compound, and a
        # freshly-jittered target for their next stint.
        age_matrix  = np.where(pit_mask, 0.0, age_matrix)
        deg_matrix  = np.where(pit_mask, pit_deg, deg_matrix)
        pace_matrix = np.where(pit_mask, pit_pace, pace_matrix)
        new_target = pit_stint_len + rng.normal(0.0, STINT_LENGTH_JITTER_STD, (n_simulations, n_cars))
        stint_target = np.where(pit_mask, np.maximum(new_target, MIN_STINT_LENGTH_LAPS), stint_target)

    # ── Resolve finishing positions ──────────────────────────────────────────
    # argsort each row: lower cumulative time → better position
    positions = np.argsort(np.argsort(cum_matrix, axis=1), axis=1) + 1   # (S, C)

    win_counts    = (positions == 1).sum(axis=0)           # (C,)
    podium_counts = (positions <= 3).sum(axis=0)
    avg_pos       = positions.mean(axis=0)

    results: list[WinProbability] = []
    for i, car in enumerate(active_state):
        results.append(
            WinProbability(
                car_id=car.car_id,
                driver_code=car.driver_code,
                win_pct=round(float(win_counts[i]) / n_simulations * 100, 2),
                podium_pct=round(float(podium_counts[i]) / n_simulations * 100, 2),
                expected_position=round(float(avg_pos[i]), 2),
            )
        )
    for car in non_contending:
        results.append(
            WinProbability(
                car_id=car.car_id,
                driver_code=car.driver_code,
                win_pct=0.0,
                podium_pct=0.0,
                expected_position=float(car.position),
            )
        )

    return sorted(results, key=lambda r: r.win_pct, reverse=True)
```

#### Step 1: who takes part

Only cars that are **still running on the lead lap** are simulated. A retired car cannot win, and a car a lap or
more down essentially never regains the lap. Everyone else is given a flat 0 % / 0 % at their existing position.
There is also a subtle reason for excluding lapped cars: their `cumulative_time_s` is deliberately the un-projected,
last-known value (see chapter 8), so feeding it into a rollout as if it were a normal starting time would
understate their deficit and inflate their odds.

If no laps remain (or nobody is running), the result is trivial: the P1 car wins with 100 %.

#### Step 2: state arrays

Per-car arrays are built once and broadcast to shape `(n_simulations, n_cars)`:

| Array | Shape | Meaning |
|---|---|---|
| `cum_matrix` | S x C | Current cumulative race time of each car in each simulation |
| `age_matrix` | S x C | Current tyre age |
| `deg_matrix` | S x C | Degradation rate of the current compound |
| `pace_matrix` | S x C | Base pace offset of the current compound |
| `stint_target` | S x C | Stint length at which this car in this simulation stops next |

#### Step 3: one lap of the rollout

For each remaining lap:

```
age          += 1
deg_penalty   = deg_rate × age
noise         ~ Normal(0, 0.25)                       (independent per car, per lap, per simulation)
pit_now       = (age ≥ stint_target)
lap_time      = 90.0 + base_pace + deg_penalty + noise + safety_car_loss
lap_time     += pit_loss  where pit_now
cum          += lap_time
for cars that pitted: age = 0, deg_rate = hard's, base_pace = hard's, stint_target ~ hard stint ± jitter
```

**The "90.0" is arbitrary.** Only *differences* between cars matter for the finishing order, so the base lap time
cancels out. The same is true of the safety-car term: with 8 % probability per lap, **all** cars in that simulation
lose 15 to 30 s **equally**, so it cannot change the order. It was meant to add drama, but as written it is a
no-op for win and podium probabilities. It is left in place; removing it would change nothing.

The noise is independent per car, so there is no modelling of traffic, of one car being stuck behind another, of
slipstreaming, of DRS or of overtaking difficulty. Two cars 0.5 s apart can swap freely, as if on an empty track.

#### Step 4: turning finishing times into probabilities

```python
positions      = np.argsort(np.argsort(cum_matrix, axis=1), axis=1) + 1   # rank of each car in each simulation
win_counts     = (positions == 1).sum(axis=0)
podium_counts  = (positions <= 3).sum(axis=0)
avg_pos        = positions.mean(axis=0)
```

The double `argsort` is the standard NumPy trick for "rank of each element": the first `argsort` gives the ordering,
the second converts that into ranks. Win percentage is `win_counts / n_simulations × 100`, rounded to two decimals.

### 10.5 A real example, with the model's verdict

At the end of lap 30 of the 2021 Monaco Grand Prix (78 laps; Max Verstappen won) the model, run with 4 000
simulations, gave:

| Driver | Win % | Podium % | Expected finish |
|---|---|---|---|
| BOT | 64.9 | 99.3 | 1.40 |
| VER | 35.0 | 99.1 | 1.71 |
| SAI | 0.2 | 96.6 | 2.97 |

The win probabilities sum to 100 (a built-in sanity check that the unit tests also assert), and the podium
probabilities of the running cars sum to about 300. Bottas was at that moment about to stop for a tyre change
that ended his race in the pit lane with a wheel nut that would not come off, something no lap-timing model can see coming. The
model favoured him because of his tyre state and position, exactly what it is designed to weigh, and it treated
Verstappen and Bottas as equally quick.

This is the honest shape of the tool: it is a clean way to see how tyre age and pit timing shift the odds, and a
poor way to predict a real result.

> 🏁 **Pit-wall trivia: 2024, McLaren's return to the top.** McLaren won the constructors' championship in 2024, its
> first since 1998, with a title decided at the final round in Abu Dhabi. Lando Norris scored his first Grand Prix win
> at Miami, Carlos Sainz won in Australia just weeks after an appendix operation, Oliver Bearman made a surprise
> Ferrari debut at 18 in Saudi Arabia when Sainz was ill, and Charles Leclerc finally won his home race in Monaco.
> The year ended with Max Verstappen's fourth world title, sealed in Las Vegas.

---

## 11. Strategy tools: counterfactual, undercut, optimal stop

Three POST endpoints under `/api/simulate` expose the strategy maths. Each rebuilds the car states for the *current
replay lap* the browser sends, so the answers are always about the situation on screen.

### 11.1 Counterfactual: "what if car X pits on lap N for tyre Y?"

*`backend/app/engine/monte_carlo.py`*

```python
def simulate_counterfactual(
    current_lap: int,
    total_laps: int,
    grid_state: list[CarState],
    car_id: int,
    pit_lap: int,
    target_compound: str,
    race_id: str = "",
    n_simulations: int = 1000,
) -> tuple[WinProbability, WinProbability]:
    """
    Run baseline simulation vs. counterfactual (car_id pits on pit_lap
    for target_compound).

    Returns (original_wp, counterfactual_wp) for car_id.
    """
    # Baseline
    baseline_probs = simulate_race(current_lap, total_laps, grid_state, race_id, n_simulations)
    orig = next((p for p in baseline_probs if p.car_id == car_id), None)

    # Build counterfactual grid: modify the target car's tyres
    cf_grid: list[CarState] = []
    for car in grid_state:
        if car.car_id == car_id:
            # Pit on pit_lap: subtract pit_loss from gap, reset tyre age, new compound
            pit_loss = _pit_loss(race_id)
            laps_until_pit = max(pit_lap - current_lap, 0)
            # Penalise cumulative time by pit-loss minus any future pace gain
            pace_gain_per_lap = (
                BASE_PACE.get(car.tire_compound, 0.0)
                - BASE_PACE.get(target_compound, 0.0)
            )
            net_gain = pace_gain_per_lap * (total_laps - pit_lap) - pit_loss
            cf_car = car.model_copy(update={
                "tire_compound": target_compound,
                "tire_age_laps": 0,
                "cumulative_time_s": car.cumulative_time_s + pit_loss - max(net_gain, 0),
            })
            cf_grid.append(cf_car)
        else:
            cf_grid.append(car)

    cf_probs = simulate_race(current_lap, total_laps, cf_grid, race_id, n_simulations)
    cf = next((p for p in cf_probs if p.car_id == car_id), None)

    if orig is None or cf is None:
        raise ValueError(f"car_id {car_id} not found in grid_state")

    return orig, cf
```

The endpoint (`simulate.py`) validates the request (the pit lap must be after the current lap and within the race),
builds the grid, calls this function and turns the two `WinProbability` records into a sentence such as
"Pitting SAI on lap 40 for MEDIUM tyres changes win probability from 0.2% to 0.0% (-) 0.2 pp".

**How the counterfactual is built.** A copy of the chosen car is created with the new compound, tyre age 0 and an
adjusted cumulative time, and the simulation runs again. Comparing the two runs gives the deltas.

**What to know before trusting it.** Reading the code carefully, three properties follow:

1. **The pit lap barely matters.** The car is treated as if it stops *now*: its tyre age is reset at the current
   lap and the pit loss is added to its time immediately. The `pit_lap` argument only enters through the pace-gain
   term `(total_laps - pit_lap)`. Measured on the Monaco example above (Sainz, medium tyres):

   | pit_lap | Podium % after the "pit" |
   |---|---|
   | 32 | 5.2 |
   | 40 | 5.7 |
   | 45 | 4.4 |
   | 70 | 5.6 |

   The baseline was 96.9 %. The lap number changes the result by about a point; the *fact of stopping* costs about
   ninety.
2. **Some effects are counted twice.** The adjustment is `cum + pit_loss - max(net_gain, 0)` where
   `net_gain = pace_gain × laps_left - pit_loss`. So when a stop is beneficial the cost is `2 × pit_loss - pace_gain
   × laps_left`, and the pace gain is *also* applied by the rollout as the new compound runs. The result overstates
   both the cost of the stop and the benefit of the tyre.
3. **The rollout also schedules its own later stops.** After the counterfactual stop the car may stop again inside
   the simulation, on the compound the model chooses (hard).

Bottom line: the counterfactual panel gives a fair *direction* ("stopping now is costly at this circuit") but
should not be read as an optimiser.

### 11.2 Undercut analysis

*(Full source: `backend/app/engine/monte_carlo.py`, `calculate_undercut`.)*

An **undercut** is when a driver stops before the car ahead, and the fresh-tyre pace over the next laps lets them come out in
front once that car has also stopped. The function computes, in seconds:

```
gap_before        = my_cumulative_time − target_cumulative_time
pace_gain_per_lap = BASE_PACE[my compound] − BASE_PACE[new compound]
current_deg       = DEGRADATION[my compound] × my tyre age
gap_after         = gap_before + pit_loss − (pace_gain_per_lap + current_deg) × laps_after_pit
will_undercut     = gap_after < 0
```

Interpretation: stopping costs `pit_loss` immediately, and every remaining lap gains back
`pace_gain_per_lap + current_deg`, which is the fresh tyre's pace advantage plus the degradation penalty the old tyre
would otherwise keep adding. The break-even lap is `pit_lap + pit_loss / pace_gain_per_lap`.

Three honest caveats: `current_deg` is treated as a *constant* per-lap saving although real degradation grows;
the model ignores what the target does (it might stop too, cancelling the effect); and only cars on the same lap are
offered in the UI because the maths needs a genuine time gap.

The recommendation text has three cases: "Undercut works" (`gap_after < 0`), "Undercut marginal ... around lap N"
(a break-even exists inside the race) and "Overcut recommended" (otherwise).

### 11.3 Optimal stop

*(Full source: `backend/app/engine/monte_carlo.py`, `calculate_optimal_stop`.)*

For each candidate compound (other than the current one) the function tries every pit lap from the next lap up to five
laps before the flag, computing:

```
pace_gain  = (current_pace − new_pace) × laps_remaining
deg_saving = Σ over remaining laps i of [ current_deg × (age_at_pit + i) − new_deg × i ]
net_gain   = pace_gain + deg_saving − pit_loss
```

and keeps the lap with the largest `net_gain`. The window (`earliest_lap`, `latest_lap`) is then widened up to seven
laps either side of the optimum while a simplified net gain (pace only) stays positive. Results are sorted by net
gain. Note that this considers **one stop only** and compares a stop with staying out, not with a two-stop plan.

### 11.4 The tools in the browser

| Component | Endpoint | Inputs |
|---|---|---|
| `CounterfactualPanel.jsx` | `POST /simulate/counterfactual` | driver, pit-lap slider (current lap + 1 to total − 2), compound buttons |
| `UndercutCalc.jsx` | `POST /simulate/undercut` | your car, target car (running cars on the lead lap only), pit lap, compound |
| (none) | `POST /simulate/optimal-stop` | The endpoint exists, but no panel calls it yet |

Both panels send the *current replay lap* so the server builds the grid for what you are looking at. If you have paused,
the analysis matches the paused lap.

> 🏁 **Pit-wall trivia: how fast is a pit stop?** The modern record for a stationary pit stop is **1.80 seconds**,
> set by McLaren for Lando Norris at the 2023 Qatar Grand Prix; four wheels changed by roughly twenty people. The
> *time lost* by a stop, the number this chapter's model calls `pit_loss`, is much larger, about 20 to 25 seconds
> at most circuits, because the car must slow down for the pit-lane speed limit and drive the length of the pit lane.

---

## 12. The analytics engine

### 12.1 Purpose

`analytics.py` turns the lap table of one race into (a) a JSON **summary** (cards and a driver table) and (b)
eight rendered **charts**. It also defines `RaceData`, the prepared, race-level view that `insights.py` reuses. All the computation
uses pandas and NumPy; the pictures are drawn with matplotlib on the non-interactive `Agg` backend, so no window or
display is required.

### 12.2 `RaceData`: the shared foundation

*`backend/app/engine/analytics.py`*

```python
class RaceData:
    """Everything the charts and stats need, derived once per race."""

    def __init__(self, race_id: str):
        from app.engine.data_loader import load_session_laps, get_race_meta
        from app.engine.replay import _build_car_states

        laps, total_laps = load_session_laps(race_id)
        self.race_id = race_id
        self.meta = get_race_meta(race_id) or {}
        self.total_laps = total_laps
        self.laps = laps.copy()

        last_lap = int(laps["LapNumber"].max())
        cars = _build_car_states(laps[laps["LapNumber"] == last_lap].copy(), laps, last_lap)
        self.cars = sorted(cars, key=lambda c: c.position)
        self.order = [c.driver_code for c in self.cars]                   # final classification
        self.finishers = [c.driver_code for c in self.cars if not c.retired]
        self.team = {c.driver_code: c.team for c in self.cars}
        self.position = {c.driver_code: c.position for c in self.cars}

        # Clean racing laps: has a time, not a pit in/out lap.
        clean = self.laps[
            self.laps["LapTime_s"].notna() & ~self.laps["IsPitIn"] & ~self.laps["IsPitOut"]
        ]
        lap_med = clean.groupby("LapNumber")["LapTime_s"].median()
        base = float(lap_med.quantile(0.25)) if len(lap_med) else 90.0
        self.base_pace = base
        # A lap where the whole field is slow is neutralised, not "slow driving".
        self.neutral_laps = sorted(int(l) for l in lap_med[lap_med > 1.12 * base].index)

        # Also drop the laps either side of a neutralisation: the lap it's
        # deployed on is part-slow, and the restart lap is slow for everyone
        # (cars bunched up, tyres cold) — neither is a pace signal.
        neutral = set(self.neutral_laps)
        edge_laps = ({l - 1 for l in neutral} | {l + 1 for l in neutral}) - neutral
        clean = clean[~clean["LapNumber"].isin(neutral | edge_laps)]
        clean = clean[clean["LapTime_s"] < 1.15 * base].copy()
        # Pace relative to the field on the same lap, and relative to the
        # driver's own typical offset — isolates tyre/consistency effects.
        field_med = clean.groupby("LapNumber")["LapTime_s"].transform("median")
        clean["field_delta"] = clean["LapTime_s"] - field_med
        clean["rel_delta"] = clean["field_delta"] - clean.groupby("Driver")["field_delta"].transform("median")
        self.clean = clean

        # Session-elapsed time per (lap, driver) → race position and gaps by lap.
        self.time_by_lap = self.laps.pivot_table(
            index="LapNumber", columns="Driver", values="Time_s", aggfunc="first"
        ).sort_index()
        self.rank_by_lap = self.time_by_lap.rank(axis=1, method="min")
        self.gap_by_lap = self.time_by_lap.sub(self.time_by_lap.min(axis=1), axis=0)

        self.pit_laps: dict[str, list[int]] = (
            self.laps[self.laps["IsPitIn"]].groupby("Driver")["LapNumber"].apply(list).to_dict()
        )

    def style(self, drv: str) -> dict:
        """Line colour + style; a team's second driver is dashed."""
        team = self.team.get(drv, "")
        mates = [d for d in self.order if self.team.get(d) == team]
        idx = mates.index(drv) if drv in mates else 0
        return {"color": team_color(team), "linestyle": "-" if idx == 0 else (0, (4, 2))}
```

Everything statistical in the project is built on five derived views created here. Understanding them is the key to
understanding every number in the Analytics and Insights tabs.

#### The classification

`self.cars` is the final classification: `_build_car_states` on the last lap, sorted by position.
`self.order` (driver codes), `self.finishers`, `self.team` and `self.position` are lookups derived from it.

#### Clean laps

A lap is "clean" when it has a time and is not a pit in-lap or out-lap. Pit laps are slow for reasons unrelated to pace,
so they are excluded from every pace figure.

#### Neutralised laps

Safety cars, virtual safety cars and red flags slow the whole field. They are detected from the field itself:

1. Take the **median clean lap time across all cars on each lap** (`lap_med`).
2. Take the 25th percentile of those medians as the race's normal pace, `base`.
3. Any lap whose field median exceeds `1.12 × base` is neutralised (`neutral_laps`).

The logic is that one driver being slow is a driver problem, but *the median of the entire field* being 12 %
slower is not something any driver did. The lap either side of a neutralised stretch is also dropped from the pace
data (`edge_laps`): the deployment lap is part slow, and the restart lap is slow for everyone (bunched cars, cold
tyres). Finally laps slower than `1.15 × base` are removed as anomalies.

#### Relative pace: cancelling fuel, track and traffic

Raw lap times across a race are not comparable, because cars get lighter as fuel burns (roughly 0.03 s per lap for every
kilogram of fuel carried is a common rule of thumb), the track rubbers in, and conditions change. Two derived columns cancel these
effects:

* `field_delta = lap_time − median(clean laps of all cars on that same lap)`. Every car ran that lap in the same
  conditions, so the difference is pure car-and-driver pace.
* `rel_delta = field_delta − that driver's own median field_delta`. This removes the driver's *typical* offset,
  leaving only how their pace varied around it. It is what the consistency and tyre-wear analyses use.

#### Race positions and gaps by lap

`time_by_lap` pivots `Time_s` into a lap x driver table. From it:

* `rank_by_lap = time_by_lap.rank(axis=1, method="min")`: each car's rank among those who completed that lap
  (rank 1 is the leader; a car that has retired has no entry, so those behind it move up).
* `gap_by_lap = time_by_lap − time_by_lap.min(axis=1)`: seconds behind the leader at the end of each lap.

`pit_laps` lists each driver's pit in-laps. (A red-flag detail matters here; see the insights chapter's
`_dedupe_stops`.)

#### A cache with a cap

`race_data(race_id)` is wrapped in `@lru_cache(maxsize=6)`: building a `RaceData` involves one classification and
several group-bys, so the six most recently used races are kept in memory.

### 12.3 Pit-loss estimation

*`backend/app/engine/analytics.py`*

```python
def _pit_loss_estimates(rd: RaceData) -> dict[str, list[float]]:
    """
    Rough time lost per stop: (in-lap + out-lap) minus two laps at the
    driver's own clean pace. An estimate, not a timed pit-lane figure —
    stops under a neutralisation are skipped because the field is slow then.
    """
    out: dict[str, list[float]] = {}
    neutral = set(rd.neutral_laps)
    for drv, stops in rd.pit_laps.items():
        own = rd.clean[rd.clean["Driver"] == drv]["LapTime_s"]
        if len(own) < 5:
            continue
        pace = float(own.median())
        g = rd.laps[rd.laps["Driver"] == drv].set_index("LapNumber")["LapTime_s"]
        for lap in stops:
            if lap in neutral or (lap + 1) in neutral:
                continue
            if lap in g.index and (lap + 1) in g.index and pd.notna(g[lap]) and pd.notna(g[lap + 1]):
                loss = float(g[lap] + g[lap + 1] - 2 * pace)
                if 5 <= loss <= 60:
                    out.setdefault(drv, []).append(loss)
    return out
```

The time a stop costs is estimated as **in-lap + out-lap minus two laps at the driver's own clean pace**. A driver's
clean pace is their median clean lap. The estimate is kept only when it is plausible (5 to 60 seconds) and stops made
during a neutralisation are skipped (the field is slow then, so the stop is cheap for reasons that say nothing about
the pit lane). This is an *estimate* built from lap times, not a measured pit-lane time.

### 12.4 The summary endpoint

`summary(race_id)` produces:

* **Cards**: winner, fastest lap, finishers and DNFs, lead changes, neutralised laps, pit stops, median stop loss,
  most places gained and lost, best race pace, most consistent driver, most-used tyre.
* **A driver table**: position, status, best lap, median pace, consistency, stops and places gained since lap 1.

Places gained compares finishing position with the running order after lap 1 (there is no grid data in the table,
so the start itself is not part of this figure). A defect that was fixed: the "most places lost" card used to
appear with a value of `+0` when nobody had lost a place; both cards now only appear when the value is non-zero.

### 12.5 The eight charts

| id | Title | What it shows |
|---|---|---|
| `race_trace` | Race trace | Position on every lap for every driver; hollow dots mark pit stops; amber bands mark neutralised laps. |
| `lap_times` | Lap times | Clean laps of the top ten finishers; gaps are left where laps were removed so lines are not joined across pit stops. |
| `pace_box` | Pace distribution | A box plot of each driver's clean laps, sorted by median. |
| `gap_heatmap` | Gap to leader | A drivers x laps heat map of the gap, colour capped at 90 s so the front-of-field fight stays visible. |
| `pit_stops` | Pit stops | When each driver stopped, the tyre they fitted (colour), and the estimated time lost per stop (bars). |
| `tyre_deg` | Tyre age vs pace | `rel_delta` against tyre age per compound, with 3-lap bucket means. |
| `positions_gained` | Places gained | Finishing position versus position after lap 1. |
| `consistency` | Consistency | Standard deviation of `rel_delta` per driver. |

Drawing conventions shared by all of them: a dark theme matching the app (`BG`, `FG`, `MUTED`, `GRID` constants),
team colours from a substring table (`team_color`), and a driver's *second* teammate drawn with a dashed line so a
team's two cars are distinguishable while sharing a colour.

One chart in full, as an example of the pattern:

*`backend/app/engine/analytics.py`*

```python
def chart_tyre_deg(rd: RaceData) -> bytes:
    df = rd.clean[(rd.clean["TyreLife"] > 0) & (rd.clean["TyreLife"] <= 40)]
    fig, ax = _new_fig(10.5, 5.2)
    plotted = False
    for comp in ("SOFT", "MEDIUM", "HARD", "INTERMEDIATE", "WET"):
        g = df[df["Compound"] == comp]
        if len(g) < 25:
            continue
        col = COMPOUND_COLORS[comp]
        ax.scatter(g["TyreLife"], g["rel_delta"].clip(-3, 3), s=6, color=col, alpha=0.12, linewidths=0)
        # 3-lap buckets: single-lap means are too noisy to read a trend from
        g = g.assign(bucket=(g["TyreLife"] // 3) * 3 + 1)
        m = g.groupby("bucket")["rel_delta"].agg(["mean", "count"])
        m = m[m["count"] >= 8]
        if len(m) >= 3:
            ax.plot(m.index, m["mean"], color=col, linewidth=2.2, marker="o", markersize=3.5, label=f"{comp.title()}  (n={len(g)})")
            plotted = True
    if not plotted:
        return _empty("Not enough laps on any compound for a tyre-age view")
    ax.axhline(0, color=MUTED, linewidth=0.8)
    ax.set_ylim(-1.8, 1.8)
    ax.set_xlabel("Tyre age (laps)")
    ax.set_ylabel("Pace vs. field, same lap (s)")
    ax.set_title("Pace vs. tyre age — relative to the field on the same lap, per-driver offset removed",
                 color=FG, fontsize=11, loc="left")
    leg = ax.legend(fontsize=8, frameon=False, loc="upper left")
    for t in leg.get_texts():
        t.set_color(FG)
    return _png(fig)
```

Read it for three deliberate choices: `rel_delta` is clipped to ±3 s so an outlier cannot stretch the axis; laps are
bucketed in threes because single-lap means are too noisy to show a trend; and a compound needs at least 25 laps of data
to be drawn at all (otherwise the chart would draw a line through noise).

### 12.6 Rendering and caching

*`backend/app/engine/analytics.py`*

```python
def _chart_path(race_id: str, chart_id: str) -> Path:
    return Path(settings.cache_dir) / "processed" / "charts" / f"{race_id}_{chart_id}_v{ANALYTICS_VERSION}.png"


def render_chart(race_id: str, chart_id: str) -> Optional[bytes]:
    """PNG bytes for one chart, cached on disk (rebuilt if the race data is newer)."""
    if chart_id not in CHARTS:
        return None
    path = _chart_path(race_id, chart_id)
    from app.engine import storage
    source = storage._path(race_id)
    if path.exists() and (not source.exists() or path.stat().st_mtime >= source.stat().st_mtime):
        return path.read_bytes()
    png = CHARTS[chart_id][2](race_data(race_id))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)
    return png
```

A PNG is rebuilt when it does not exist, **or** when the race's source pickle is newer than the PNG. The version
number in the filename (`ANALYTICS_VERSION`) lets a change to a chart's meaning invalidate every cached image at
once. The router adds `Cache-Control: public, max-age=3600` so the browser also reuses an image for an hour.

> 🏁 **Pit-wall trivia: 2018, the Baku lap the demo tripped over.** The 2018 Azerbaijan Grand Prix is a favourite
> of statisticians. Valtteri Bottas led when a piece of debris punctured his tyre near the end; earlier, Max
> Verstappen and Daniel Ricciardo, Red Bull team-mates, collided and both retired, bringing out the safety car around lap 40.
> Lewis Hamilton won. Baku's castle section is about 7.6 m wide at its narrowest, the tightest point on the
> calendar. The lap-40 slowdown is exactly what the neutralised-lap detector above looks for; a bug in the
> trajectory demo, described in chapter 15, was first spotted on that very lap.

---

## 13. The insights engine

### 13.1 Purpose

The Insights tab shows **45 to 48 named statistics per race**, grouped into five categories, plus structured data for
six charts and 16 season roll-ups. `insights.py` computes them from `RaceData`, stores the result as JSON on
disk, and hands the same facts to the search module.

An insight is a small dictionary: `{id, category, title, value, detail}`. A statistic that the race cannot support
(for example "undercut success rate" in a race with fewer than two comparable stops) returns `None` and is simply
absent, rather than showing a blank card.

### 13.2 The shared context

Many insights need the same intermediate results. `_Ctx` computes them once:

*(Full source: `backend/app/engine/insights.py`, `_Ctx`.)*

What each intermediate is:

| Attribute | Meaning |
|---|---|
| `timed` | All laps that have a lap time |
| `median_pace`, `n_clean`, `consistency` | Per-driver median clean lap, count of clean laps, and the standard deviation of `rel_delta` |
| `eligible` | Drivers with at least 15 clean laps and a defined spread. Pace and consistency rankings use only these, so a driver who did five laps cannot top a table |
| `pit_laps` | Pit in-laps per driver **with consecutive laps merged** (next section) |
| `stints` | One row per driver and stint: compound, first and last lap, length, whether it is the final stint |
| `swaps`, `swap_pairs` | The estimated overtake count and which pairs traded places (below) |
| `undercut_attempts`, `undercut_wins` | The undercut tally (below) |
| `pit_losses` | Per-driver stop-loss estimates from `analytics._pit_loss_estimates` |

### 13.3 A red-flag quirk and `_dedupe_stops`

*`backend/app/engine/insights.py`*

```python
def _dedupe_stops(laps: list[int]) -> list[int]:
    """
    Collapse runs of consecutive pit-in laps into one stop. Under a red flag
    (or when a car sits in the pit lane across the timing line) the feed marks
    the same visit on two laps in a row, which would otherwise double-count.
    """
    out: list[int] = []
    prev = None
    for l in sorted(laps):
        if prev is None or l != prev + 1:
            out.append(l)
        prev = l
    return out
```

During a red flag, or when a car sits in the pit lane across the timing line, the feed marks the *same* pit visit on
two consecutive laps. Counted naively, the 2021 São Paulo Grand Prix showed 81 stops for 20 cars. Merging runs of
consecutive laps into one stop brought it to 58 (still high: the feed for that race is unusual, and the module makes no
further attempt to correct it). The stint table uses the same merged list so a 1-lap "stint" is not invented.

### 13.4 The estimated overtake count

The most-quoted number in the module is "on-track position swaps". Here is exactly how it works:

*`backend/app/engine/insights.py`*

```python
    def _swaps(self) -> tuple[int, Counter]:
        rd = self.rd
        T = rd.time_by_lap
        if T.empty:
            return 0, Counter()
        cols = list(T.columns)
        arr = T.to_numpy(dtype=float)
        lap_idx = {int(l): i for i, l in enumerate(T.index)}
        pit = {(r.Driver, int(r.LapNumber)) for r in rd.laps.itertuples() if r.IsPitIn or r.IsPitOut}
        neutral = set(rd.neutral_laps)
        edges = neutral | {l - 1 for l in neutral} | {l + 1 for l in neutral}
        pairs: Counter = Counter()
        for l in sorted(lap_idx):
            p = l - 1
            if p not in lap_idx or l in edges or p in edges:
                continue
            ip, il = lap_idx[p], lap_idx[l]
            ok = [j for j, d in enumerate(cols)
                  if not np.isnan(arr[ip, j]) and not np.isnan(arr[il, j])
                  and (d, p) not in pit and (d, l) not in pit]
            for x in range(len(ok)):
                for y in range(x + 1, len(ok)):
                    a, b = ok[x], ok[y]
                    if (arr[ip, a] < arr[ip, b]) != (arr[il, a] < arr[il, b]):
                        pairs[frozenset((cols[a], cols[b]))] += 1
        return int(sum(pairs.values())), pairs
```

For every pair of consecutive laps `(p, l)`:

1. Skip the pair when either lap is neutralised (or next to a neutralisation): restarts and safety-car lapping are not
   overtaking.
2. Consider only drivers who completed both laps and who were **not** in the pits on either of them (a pit stop
   reshuffles the order without any overtake).
3. For every pair of such drivers `(a, b)`, compare whether `a` completed lap `p` before `b`, and whether `a` completed
   lap `l` before `b`. If the answer changed, that is one swap.

The total is the sum over laps; the per-pair counter also yields the "biggest fight" (`_battle`, which needs at least
two swaps by the same pair).

Why the label says *estimate*: the comparison uses **lap completion order**, which differs from true track position
for lapped cars, and a car that overtakes and is re-passed within one lap is invisible. On Monaco 2021 the figure is
1, on a fully green Styrian Grand Prix it is about 53, and both feel about right.

### 13.5 The undercut tally

*`backend/app/engine/insights.py`*

```python
    def _undercuts(self) -> tuple[int, int]:
        rd = self.rd
        rank = rd.rank_by_lap
        neutral = set(rd.neutral_laps)
        attempts = wins = 0
        for a, stops in self.pit_laps.items():
            if a not in rank.columns:
                continue
            for L in stops:
                if L in neutral or (L - 1) not in rank.index:
                    continue
                ra = rank.at[L - 1, a]
                if pd.isna(ra):
                    continue
                row = rank.loc[L - 1]
                ahead = row[row == ra - 1]
                if ahead.empty:
                    continue
                b = ahead.index[0]
                later = [s for s in self.pit_laps.get(b, []) if L < s <= L + 6]
                if not later or (later[0] + 1) not in rank.index:
                    continue
                ra2, rb2 = rank.at[later[0] + 1, a], rank.at[later[0] + 1, b]
                if pd.isna(ra2) or pd.isna(rb2):
                    continue
                attempts += 1
                wins += int(ra2 < rb2)
        return attempts, wins
```

For a car `A` that pits on lap `L` (a green-flag stop): find the car `B` directly ahead at lap `L−1`; require that
`B` also pits within the next six laps; then look at both cars' ranks on the lap after `B`'s stop. If `A` is ahead
of `B`, that is one successful undercut. The insight reports `wins/attempts`, and only when there are at least two
attempts.

### 13.6 The catalogue

All 48 per-race insights, with the exact meaning of each. The order below is the order of the `INSIGHTS` list in
`insights.py`, and the category is the group in which the Insights tab shows it.

#### Pace (10)

| id | Title | Definition |
|---|---|---|
| `fastest_lap` | Fastest lap | Smallest `LapTime_s` over all laps; shows driver, time, lap and tyre |
| `fastest_lap_timing` | Fastest lap came | The lap's position in the race as a percentage; 85 % or later is flagged as a probable end-of-race push on fresh tyres |
| `fastest_pace` | Best race pace | Lowest median clean lap among eligible drivers |
| `slowest_pace` | Slowest race pace | Highest median clean lap among eligible drivers |
| `field_spread` | Fastest-to-slowest gap | Best median minus worst median, among eligible drivers (needs 4+) |
| `winner_pace_gap` | Winner vs runner-up pace | Winner's median clean lap minus the runner-up's |
| `best_team_pace` | Fastest team on pace | Team with the lowest median `field_delta` (30+ laps, 3+ teams) |
| `worst_team_pace` | Slowest team on pace | The highest |
| `field_evolution` | Pace change, first vs last third | Median clean lap of the last third minus that of the first third; negative means the field got faster |
| `fl_vs_typical` | Fastest lap vs typical lap | Median clean lap minus the fastest lap |

#### Consistency (5)

| id | Title | Definition |
|---|---|---|
| `most_consistent` | Most consistent driver | Smallest standard deviation of `rel_delta` (eligible drivers) |
| `least_consistent` | Least consistent driver | The largest |
| `consistent_team` | Most consistent team | Lowest average spread across a team's eligible drivers |
| `peak_laps` | Most laps near own best | Count of clean laps within 0.5 s of the driver's own best clean lap |
| `tight_field` | Median lap-to-lap spread | Median of all eligible drivers' spreads: how "messy" the race was |

#### Strategy (12)

| id | Title | Definition |
|---|---|---|
| `total_stops` | Total pit stops | Sum of merged stops |
| `avg_stops` | Average stops per finisher | Mean stops among classified finishers |
| `common_strategy` | Most common strategy | The most frequent compound sequence such as `S-H` among finishers |
| `n_strategies` | Distinct strategies | Number of different sequences |
| `winner_strategy` | Winner's strategy | The winner's sequence and stop count |
| `longest_stint` | Longest stint | Maximum stint length, with driver and compound |
| `shortest_stint` | Shortest stint | Minimum length among stints that ended in a stop |
| `first_stop_early` | Earliest first stop | Smallest first pit lap |
| `first_stop_late` | Latest first stop | Largest first pit lap |
| `undercut_rate` | Undercut success rate | `wins/attempts` from section 13.5 |
| `median_pit_loss` | Median time lost per stop | Median of the loss estimates |
| `best_pit_team` | Quickest pit-cycle team | Team with the lowest median estimated loss (2+ stops each, 3+ teams) |

#### Tyres (6)

| id | Title | Definition |
|---|---|---|
| `compound_share` | Tyre mix | Share of all laps on each compound |
| `n_compounds` | Compounds used | How many different compounds appeared |
| `deg_rates` | Tyre degradation rate | The least-squares slope of `rel_delta` against tyre age (≤ 40 laps) for each compound with 40+ laps and 6+ distinct ages; the headline names the compound with the steepest slope |
| `fastest_compound` | Fastest compound on the day | Compound with the lowest median `field_delta` (25+ laps, 2+ compounds) |
| `longest_run` | Longest run per compound | Longest stint for each compound and who did it |
| `avg_stint` | Average stint length | Mean length of stints that ended in a stop, per compound |

#### Race flow (15)

| id | Title | Definition |
|---|---|---|
| `lead_changes` | Lead changes | Number of times the lap-end leader changed |
| `laps_led` | Most laps led | The driver leading at the end of the most laps |
| `neutral` | Neutralised laps | The count and the lap ranges |
| `neutral_share` | Share under neutralisation | Neutralised laps as a percentage of the race |
| `swaps` | On-track position swaps | Section 13.4 |
| `battle` | Biggest fight | The pair that swapped most (at least twice) |
| `swap_rate` | Swaps per green-flag lap | `swaps ÷ (total laps − neutralised laps)` |
| `win_margin` | Winning margin | P2's cumulative time minus the winner's at the winner's final lap |
| `closest_finish` | Closest finish gap | Smallest gap between consecutive finishers on the lead lap (3+ finishers) |
| `gainer` | Most places gained | Largest gain since lap 1 (only shown if positive) |
| `loser` | Most places lost | Largest loss (only shown if negative) |
| `dnfs` | Retirements | Count and names |
| `first_dnf` | First retirement | The earliest retirement lap |
| `lead_lap` | Finished on the lead lap | Count |
| `lapped` | Classified but lapped | Count |

The count varies (45 to 48) because conditional insights drop out; a wet race with one compound has no
"fastest compound", and a race with no retirements has no "first retirement".

### 13.7 The season roll-ups

`season_insights(year)` reads each cached race's structured **facts** (a compact dictionary saved beside its insights:
winner, team, podium, fastest-lap driver and time, stops, starters and finishers, neutralised laps, lead changes,
swaps, median pit loss, top strategy, compound laps) and computes 16 statistics across them: most wins, most wins by a
team, most podiums, fastest lap of the season, most fastest laps, most and least on-track action, most
neutralised laps, most lead changes, most retirements, retirement rate, average stops, most stops, typical pit loss,
tyre usage and the most common strategy.

For 2021 it produces, among other things: Verstappen 9 wins to Hamilton's 8 among 21 analysed races (matching the real
season once the abandoned Belgian race is excluded), Monaco as the most processional race (about one swap), the Styrian
Grand Prix as the most action-packed (about 53 swaps), and the Emilia Romagna race with 22 neutralised laps.

### 13.8 Structured chart data (`extras`)

Besides the cards, `_extras` builds JSON for the interactive charts so the browser can draw them with Recharts:

*(Full source: `backend/app/engine/insights.py`, `_extras`.)*

| Key | Drawn as |
|---|---|
| `strategy` | The strategy timeline: stints per driver in finishing order, plus pit laps |
| `pace_ranking` | The pace ranking bars |
| `field_pace` | The "field pace by lap" line (median lap time of all cars per lap, pit laps excluded) |
| `lead_timeline` | The "who led when" bar |
| `deg_curves` | The tyre wear curves: mean `rel_delta` per 3-lap age bucket per compound |
| `teams` | The team scorecard table |
| `neutral_laps`, `total_laps` | Overlays and scale for the charts |

### 13.9 Building and caching

*(Full source: `backend/app/engine/insights.py`, `race_insights`.)*

* Each insight function runs inside a `try/except`: one failing statistic is logged and skipped, so it cannot stop the rest.
* A race with **no timed laps at all** (the 2021 Belgian Grand Prix) is stored as `{"insights": [], "facts": null}`
  and the UI says there is nothing to analyse. The season roll-up filters out `facts: null` races.
* The JSON file is named with `INSIGHTS_VERSION` and is rebuilt if the race's pickle is newer, the same staleness rule as
  the chart PNGs.
* The first build of 42 races took about 16 seconds in total (roughly 0.1 to 0.7 s per race).

> 🏁 **Pit-wall trivia: 2025, new faces.** The 2025 season welcomed a wave of rookies: Kimi Antonelli replaced Lewis
> Hamilton at Mercedes at just 18, Isack Hadjar, Gabriel Bortoleto, Oliver Bearman and Jack Doohan all made
> their full-time debuts, and Franco Colapinto replaced Doohan after six races. Hamilton himself began his first
> season at Ferrari, and the opener in Melbourne, run in changeable, rain-affected conditions, was won by Lando
> Norris. The fastest-lap bonus point that the 2019 to 2024 seasons had used was discontinued for 2025, and the
> calendar reached 24 races, tied for the longest ever.

---

## 14. Ask the season: retrieval over computed facts

### 14.1 What "RAG" means here, and what it does not

"Retrieval-augmented generation" normally means: find relevant documents, then have a language model write an answer
from them. This project implements only the **retrieval** half, on purpose:

* The corpus is the set of statistics the app has already computed (chapter 13).
* Every passage is a short sentence about one race or one season.
* Retrieval ranks passages against a question.
* The "answer" is the best passages **verbatim**, with the race each came from. No language model is involved, so nothing can be invented or mis-summarised, every line is
  traceable to a computed number, and no API key, network call or cost is needed.

A language model could be layered on top to phrase a prose answer, but that needs a paid service, so it was left out.
The API response says so explicitly: `"mode": "retrieval-only (extractive, no language model)"`.

### 14.2 The corpus

`rag._build` walks every cached race and produces passages of two kinds:

* **Race passages**: one "result" passage per race (winner, team, podium, finishers, fastest lap) plus one passage per
  insight, formatted as `"<year> <event>: <title> — <value>. <detail>"`.
* **Season passages**: one per season roll-up statistic, formatted as `"<year> season: <title> — <value>. <detail>"`.

*(Full source: `backend/app/engine/rag.py`, `_race_docs,_season_docs`.)*

On the author's machine this produced **about 8 000 passages** across eight seasons. Each passage carries metadata
(`year`, `race_id`, `kind`, `category`, `source`) so the response can say where a hit came from.

### 14.3 Turning text into tokens

*`backend/app/engine/rag.py`*

```python
def _stem(w: str) -> str:
    for suf in ("ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def tokenize(text: str) -> list[str]:
    out = []
    for w in _TOKEN.findall(text.lower()):
        if w in _STOP:
            continue
        w = _SYNONYMS.get(w, w)
        out.append(_stem(w))
    return out
```

1. Lower-case the text and split it into runs of letters and digits.
2. Drop **stop words** (`the`, `who`, `was`, ...), which carry no meaning for ranking.
3. Map **synonyms**: question wording is mapped to the vocabulary the passages actually use, so "won", "win" and "victory"
   all become `winner`; "overtakes", "passes" and "action" become `swaps`; "crash", "dnf" and "retired" become
   `retirements`; "safety", "vsc" and "flag" become `neutralised`; "tires" and "rubber" become `tyre`.
4. Apply a crude **stemmer**: strip `ing`, `ed`, `es` or `s` when at least three characters remain, so `swaps` and
   `swap`, `stops` and `stop` match.

The synonym table is small and hand-made. It is the difference between a query for "who won the most races" finding
"Most wins" and finding nothing.

### 14.4 The ranking function: BM25

*`backend/app/engine/rag.py`*

```python
class _Index:
    def __init__(self, docs: list[dict]):
        self.docs = docs
        self.tf: list[Counter] = []
        self.df: Counter = Counter()
        self.postings: dict[str, list[int]] = defaultdict(list)
        for i, d in enumerate(docs):
            # Passages are searched on their own text *and* their heading, so
            # "Monaco" or "2021" in a query reaches every passage of that race.
            c = Counter(tokenize(d["text"] + " " + d["source"]))
            self.tf.append(c)
            for t in c:
                self.df[t] += 1
                self.postings[t].append(i)
        self.n = len(docs)
        self.len = [sum(c.values()) for c in self.tf]
        self.avg = (sum(self.len) / self.n) if self.n else 1.0

    def search(self, query: str, year: Optional[int], limit: int) -> list[tuple[float, dict]]:
        q = tokenize(query)
        if not q:
            return []
        scores: dict[int, float] = defaultdict(float)
        for t in set(q):
            if t not in self.postings:
                continue
            idf = math.log(1 + (self.n - self.df[t] + 0.5) / (self.df[t] + 0.5))
            for i in self.postings[t]:
                if year is not None and self.docs[i]["year"] != year:
                    continue
                f = self.tf[i][t]
                scores[i] += idf * f * (_K1 + 1) / (f + _K1 * (1 - _B + _B * self.len[i] / self.avg))
        wanted = {_INTENT_CATEGORY[t] for t in q if t in _INTENT_CATEGORY}
        for i in scores:
            if self.docs[i]["category"] in wanted:
                scores[i] *= 1.4
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])[:limit]
        return [(s, self.docs[i]) for i, s in ranked]
```

BM25 is a standard keyword relevance formula. For a query term *t* and a passage *d*:

```
score(d, t) = idf(t) × ( f(t,d) × (k1 + 1) ) / ( f(t,d) + k1 × (1 − b + b × |d| / avgdl) )

idf(t)      = ln( 1 + (N − df(t) + 0.5) / (df(t) + 0.5) )
```

* `f(t,d)`: how many times the term occurs in the passage.
* `|d|`, `avgdl`: the passage length and the average length; long passages are penalised slightly (`b = 0.75`).
* `k1 = 1.5`: how quickly repeated occurrences stop adding score.
* `idf`: rare terms count for more than common ones, `N` being the number of passages and `df(t)` the number containing the term.

A passage's score is the sum over the (distinct) query terms. The implementation is a plain **inverted index**: a
dictionary from token to the list of passages that contain it, so scoring touches only passages that share a word with
the query. There is no dependency on scikit-learn or a vector database.

A passage is indexed on its text **plus its source line**, so a query for "Monaco" or "2021" reaches every passage
of that race or season even though the race name is not repeated in each sentence.

### 14.5 Two small boosts

*(Full source: `backend/app/engine/rag.py`, `search`.)*

* **Year inference.** If the caller gives no `year` but the question contains one (`\b(20[12]\d)\b`) that exists in the
  index, it is used as the filter.
* **Intent boost.** If the question maps to `winner` or `podium`, passages of category `Result` are multiplied by 1.4.
  Without it, "who won Monaco 2021" ranked the winner's *strategy* above the *result*, because the result passage is longer
  and BM25 length-normalises.

### 14.6 Real queries

| Question (scope) | Top result |
|---|---|
| "who won the most races" (2021) | `2021 season: Most wins — VER (9). Across 21 analysed races: VER 9, HAM 8, PER 1, OCO 1, RIC 1.` |
| "which race had the most overtaking" (2021) | `2021 season: Most on-track action — Styrian Grand Prix. ~53 estimated position swaps.` |
| "safety car" (2026) | `2026 season: Most neutralised laps — Japanese Grand Prix. 6 laps under safety car / VSC / red flag.` |
| "who won the Monaco Grand Prix 2021" | `2021 Monaco Grand Prix result: race winner VER (Red Bull Racing), won the race; podium VER, SAI, NOR. ...` |

### 14.7 Lifecycle

`_ensure()` builds the index lazily, under a lock, the first time it is needed. It records a *signature*, the tuple of
cached race ids, and rebuilds when the set changes, so caching more races makes them searchable without a
restart. The build reads each race's insights JSON (cheap) rather than recomputing anything. `coverage()` reports, per season, how many races are
indexed against how many the calendar lists, which the UI shows so an empty answer can be explained ("2021: 21 of 22 races indexed").

> 🏁 **Pit-wall trivia: 2020, a first for Perez and Gasly.** Sergio Perez won the Sakhir Grand Prix from the back of the
> field after contact on lap 1, the first victory of his long career; that race featured George Russell in a Mercedes
> after Lewis Hamilton tested positive for COVID-19. Pierre Gasly took a maiden win at a chaotic Italian Grand Prix in an
> AlphaTauri, and Lewis Hamilton clinched a seventh world title in a rain-soaked Turkish Grand Prix,
> equalling Michael Schumacher's record. He had also equalled and broken Schumacher's 91 wins that season, at the
> Nürburgring and Portimão.

---

## 15. Circuits and the trajectory engine

This is the most mathematical part of the project, and the part that taught the most lessons about real data.

### 15.1 The circuit outline

`circuits.py` draws each circuit's shape once. It takes the **fastest lap of a race** and reads that lap's X/Y position
samples (FastF1 `get_telemetry()`), light-smooths and thins them to a few hundred points, and renders them with
matplotlib as a thick grey band with a thin line, a red start/finish marker and an arrow for the direction of travel.

Key behaviours (see `_trace_outline` and `_outline_for`):

* Position data is **not archived for every session**, so if the requested race has none, up to five other races at the
  same circuit are tried, newest first. Which race an outline came from is printed on the image.
* The outline array is cached in the extra cache (`circuit_outline_<slug>`), and a *failure* is cached too with a
  timestamp, so a circuit that has no data is not re-fetched for six hours (`_FAIL_RETRY_S`).
* The image is cached under `charts/circuit_<slug>_v1.png`.

The same cached outline is what the trajectory engine uses as its **reference line**.

### 15.2 The problem the trajectory engine solves

Raw position samples arrive at a handful per second and are several metres apart. On the 2019 Bahrain lap used for
testing: 709 samples in 97 seconds, an average of **7.3 Hz** (median gap 0.137 s), with steps between samples of a median 6.2 m and up to almost 30 m. Draw a car
directly from them and it jumps from point to point instead of gliding through corners.

Worse, the **timestamps are unreliable**. One sample pair showed the car moving 0.8 m in 0.12 s, the next 19 m in
0.2 s, while the speed channel read a steady 140 km/h. So the engine separates two questions:

1. **Shape**: what path did the car take? (from the positions)
2. **Timing**: where was the car along that path at each instant? (from the speed)

### 15.3 Cubic splines: Catmull–Rom

A Catmull–Rom spline is a curve that passes *through* every control point (unlike a B-spline, which only gets near them) and
has a continuous tangent, which is exactly what is needed for a car path built from measured positions. The
project uses the **non-uniform (Barry–Goldman) formulation with centripetal parametrisation**:

*`backend/app/engine/trajectory.py`*

```python
def _catmull_rom(points: np.ndarray, knots: np.ndarray, s: np.ndarray) -> np.ndarray:
    """
    Non-uniform Catmull-Rom (Barry-Goldman) through `points` (N×2) at knot
    values `knots` (strictly increasing, N), evaluated at parameter values `s`
    within [knots[0], knots[-1]]. The ends are extended by reflection.
    """
    P = np.vstack([2 * points[0] - points[1], points, 2 * points[-1] - points[-2]])
    K = np.concatenate([[2 * knots[0] - knots[1]], knots, [2 * knots[-1] - knots[-2]]])
    # segment i spans K[i+1]..K[i+2], using control points i..i+3
    i = np.clip(np.searchsorted(K, s, side="right") - 2, 0, len(K) - 4)
    t0, t1, t2, t3 = (K[i + k][:, None] for k in range(4))
    p0, p1, p2, p3 = (P[i + k] for k in range(4))
    t = s[:, None]
    a1 = ((t1 - t) * p0 + (t - t0) * p1) / (t1 - t0)
    a2 = ((t2 - t) * p1 + (t - t1) * p2) / (t2 - t1)
    a3 = ((t3 - t) * p2 + (t - t2) * p3) / (t3 - t2)
    b1 = ((t2 - t) * a1 + (t - t0) * a2) / (t2 - t0)
    b2 = ((t3 - t) * a2 + (t - t1) * a3) / (t3 - t1)
    return ((t2 - t) * b1 + (t - t1) * b2) / (t2 - t1)


def _centripetal_knots(points: np.ndarray) -> np.ndarray:
    chord = np.hypot(*np.diff(points, axis=0).T)
    return np.concatenate([[0.0], np.cumsum(np.sqrt(np.maximum(chord, 1e-6)))])
```

* The **Barry–Goldman** form builds each point by repeated linear interpolation of the neighbouring control points
  (three levels: `a1..a3`, then `b1, b2`, then the final point). It works for any spacing of the knots `t0..t3`.
* **Centripetal** parametrisation sets each knot gap to the *square root* of the chord length between points. For
  uneven sampling this provably avoids the two artefacts the plain (uniform) version can produce: overshoot loops and cusps
  inside a segment. On a circuit where consecutive samples can be 2 m or 30 m apart, that matters.
* The two ends are handled by **reflecting** the end points (`2·p0 − p1`), so the curve has a natural start and end.

*`backend/app/engine/trajectory.py`*

```python
def spline_geometry(xy: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Dense points along a centripetal Catmull-Rom through `xy`, and their cumulative arc length (m)."""
    knots = _centripetal_knots(xy)
    s = np.linspace(knots[0], knots[-1], (len(xy) - 1) * _GEOM_PER_SEGMENT + 1)
    dense = _catmull_rom(xy, knots, s)
    arc = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(dense, axis=0).T))])
    return dense, arc
```

`spline_geometry` evaluates the spline at 16 points per segment, producing a dense polyline and its **cumulative
arc length** (metres). That arc length is the currency for the timing step.

### 15.4 Timing from speed, and the 60 Hz stream

*`backend/app/engine/trajectory.py`*

```python
def smooth_path(t: np.ndarray, xy: np.ndarray, speed_t: Optional[np.ndarray] = None,
                speed_ms: Optional[np.ndarray] = None, hz: float = SAMPLE_HZ) -> dict:
    """
    Continuous 60 Hz path through coarse (t, x, y) samples.

    The spline's shape comes from `xy`. Position along it at time t is set by
    distance travelled: from the speed trace (`speed_t`, `speed_ms`) when
    given, integrated and scaled so it ends exactly at the end of the spline,
    otherwise from the samples' own times and spacing. Returns t, x, y,
    heading (radians from +x, unwrapped), distance, and the scale applied.
    """
    dense, arc = spline_geometry(xy)
    length = arc[-1]

    scale = 1.0
    time_knots, dist_at_t = t, arc[:: _GEOM_PER_SEGMENT]     # spline distance of each sample
    if speed_t is not None and speed_ms is not None and np.nanmax(speed_ms) > 0:
        v = np.nan_to_num(speed_ms, nan=0.0).clip(min=0.0)
        travelled = np.concatenate([[0.0], np.cumsum(0.5 * (v[1:] + v[:-1]) * np.diff(speed_t))])
        # only the stretch the shape samples cover (glitchy samples at either
        # end of the lap may have been dropped from the shape)
        d0, d1 = np.interp([t[0], t[-1]], speed_t, travelled)
        if d1 > d0:
            scale = length / (d1 - d0)
            time_knots, dist_at_t = speed_t, (travelled - d0) * scale

    grid = np.arange(t[0], t[-1], 1.0 / hz)
    if grid[-1] < t[-1]:
        grid = np.append(grid, t[-1])
    d = np.interp(grid, time_knots, dist_at_t)
    x = np.interp(d, arc, dense[:, 0])
    y = np.interp(d, arc, dense[:, 1])

    # tangent of the spline at that distance (±2 m chord, about a car length
    # overall), which stays smooth even when the car is barely moving
    ahead = np.clip(d + 2.0, 0, length)
    behind = np.clip(d - 2.0, 0, length)
    dx = np.interp(ahead, arc, dense[:, 0]) - np.interp(behind, arc, dense[:, 0])
    dy = np.interp(ahead, arc, dense[:, 1]) - np.interp(behind, arc, dense[:, 1])
    heading = np.unwrap(np.arctan2(dy, dx))
    # Light low-pass on the angle only (Gaussian, sigma ~0.15 s): leftover GPS
    # noise between samples would otherwise make the car's nose twitch. The
    # path itself is not altered.
    sigma = 0.15 * hz
    r = int(3 * sigma)
    kernel = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    heading = np.convolve(np.pad(heading, r, mode="edge"), kernel / kernel.sum(), mode="valid")
    return {"t": grid, "x": x, "y": y, "heading": heading, "distance": d, "distance_scale": float(scale)}
```

1. **Distance travelled by time.** Integrate the speed channel with the trapezoid rule:
   `travelled(t) = Σ ½ (v[i] + v[i+1]) Δt`.
2. **Scale to the path.** The integrated distance and the spline's arc length differ slightly (speed sensors and
   GPS disagree). A single scale factor `arc_length / integrated_distance` forces them to agree, and it is returned
   for inspection: it was 1.0065 for the Bahrain lap (a 0.65 % correction).
3. **Sample at 60 Hz.** For each 1/60 s instant, `np.interp` maps time to distance and then distance to (x, y).
   This is what makes motion steady: the car advances by `v·Δt` per frame, never by 19 m in one frame and 0.8 m in the next.
4. **Heading** is the direction of the chord from the point 2 m behind to the point 2 m ahead on the spline,
   unwrapped so angles do not jump at ±180°, then smoothed with a small Gaussian (σ = 0.15 s, applied to the angle only).
   The path itself is untouched.

The result for the 2019 Bahrain lap: 5 807 samples at 60 Hz; the largest single-frame step is 1.5 m; the largest
frame-to-frame heading change is about 3 degrees (188 °/s).

An honest measurement: converting the heading rate and speed into an implied lateral acceleration gives peak values around
10 g and a 99th percentile around 7 g, higher than a real car's roughly 5 to 6 g. The residual noise in the data is
the cause, and further smoothing would reduce it only by moving the path away from the measured samples, so the
engine stops there.

### 15.5 The reference line and the lateral offset

*`backend/app/engine/trajectory.py`*

```python
def reference_line(xy: np.ndarray, spacing_m: float = 1.0) -> dict:
    """
    Closed, smoothed reference line resampled every `spacing_m`, with unit
    tangents, left-hand normals and signed curvature (positive = turning left).
    """
    pts = xy
    if np.hypot(*(pts[0] - pts[-1])) < 1e-6:
        pts = pts[:-1]
    # centripetal knots, wrapped so the loop closes smoothly
    closed = np.vstack([pts[-2:], pts, pts[:3]])
    knots = _centripetal_knots(closed)
    s = np.linspace(knots[2], knots[2 + len(pts)], len(pts) * 40, endpoint=False)
    dense = _catmull_rom(closed, knots, s)

    loop = np.vstack([dense, dense[:1]])
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(loop, axis=0).T))])
    total = cum[-1]
    d = np.arange(0.0, total, spacing_m)
    line = np.column_stack([np.interp(d, cum, loop[:, 0]), np.interp(d, cum, loop[:, 1])])

    tan = np.roll(line, -1, axis=0) - np.roll(line, 1, axis=0)
    tan /= np.maximum(np.hypot(*tan.T), 1e-9)[:, None]
    normal = np.column_stack([-tan[:, 1], tan[:, 0]])
    ang = np.unwrap(np.arctan2(tan[:, 1], tan[:, 0]))
    curv = np.gradient(ang) / spacing_m
    k = 9                                    # a few metres of smoothing on curvature
    curv = np.convolve(np.pad(curv, (k, k), mode="wrap"), np.ones(2 * k + 1) / (2 * k + 1), mode="valid")
    return {"xy": line, "tangent": tan, "normal": normal, "curvature": curv, "length_m": float(total)}
```

The reference line is the circuit outline turned into a **closed** centripetal spline, resampled every metre. For
each of those points it stores the unit tangent, the left-pointing unit normal and the **signed curvature** (positive
means turning left). The curvature is smoothed with a moving average of 19 points so noise does not create fake
corners.

*`backend/app/engine/trajectory.py`*

```python
def lateral_offsets(path_xy: np.ndarray, ref: dict) -> tuple[np.ndarray, np.ndarray]:
    """
    Signed distance (m, positive = left of the direction of travel) from each
    path point to the reference line, and the matched reference index.

    Nearest-point matching alone can snap to a different part of the track
    where two sections run close together, so each match is kept near the
    previous one along the lap.
    """
    line = ref["xy"]
    n = len(line)
    dist, cand = cKDTree(line).query(path_xy, k=12)
    window = max(int(0.03 * n), 30)            # ~3 % of a lap either way
    idx = np.empty(len(path_xy), dtype=int)
    prev = int(cand[0, 0])
    for j in range(len(path_xy)):
        c = cand[j]
        gap = np.abs((c - prev + n // 2) % n - n // 2)
        ok = gap <= window
        pick = int(c[ok][np.argmin(dist[j][ok])]) if ok.any() else int(c[0])
        idx[j] = pick
        prev = pick
    offset = np.einsum("ij,ij->i", path_xy - line[idx], ref["normal"][idx])
    return offset, idx
```

For every path point the **signed lateral offset** is the dot product of `(point − nearest reference point)` with that
point's normal: positive means the car is left of the line, negative right. A KD-tree (`scipy.spatial.cKDTree`)
finds the nearest reference points. One subtlety: at a hairpin or where the track runs alongside itself, the
*globally* nearest point may belong to a different part of the circuit. So the twelve nearest candidates are
requested, and only those within about 3 % of a lap of the previous match are allowed, which keeps the match
following the lap.

### 15.6 Defending against bad data

Four kinds of bad data were met in real laps, each with its own defence, applied in this order in `_smooth_driver`.

*`backend/app/engine/trajectory.py`*

```python
def drop_glitches(t: np.ndarray, xy: np.ndarray, speed_ms: np.ndarray, ref: dict) -> np.ndarray:
    """
    Mask of raw samples that are physically possible. The position feed
    occasionally teleports - e.g. 2018 Baku lap 40, under a safety car, puts
    every car ~600 m off the circuit for half a minute, with single steps of
    2 km in 0.24 s. Drawn faithfully, those become huge fake excursions. A
    sample is dropped when it is more than `_MAX_TRACK_DISTANCE_M` from any
    part of the track, or further from the last good sample than the car
    could have driven by its own speed trace.
    """
    dist, _ = cKDTree(ref["xy"]).query(xy)
    near = dist <= _MAX_TRACK_DISTANCE_M
    v = np.nan_to_num(speed_ms, nan=0.0).clip(min=0.0)

    def reachable(i: int, j: int) -> bool:
        reach = 1.5 * max(v[i], v[j], 10.0) * abs(t[j] - t[i]) + _GLITCH_SLACK_M
        return bool(np.hypot(*(xy[j] - xy[i])) <= reach)

    cand = np.flatnonzero(near)
    if len(cand) == 0:
        return near
    # Split into runs of consecutive, mutually consistent samples. Start from
    # the longest run (not the first sample: a lap can open with placeholder
    # positions, e.g. near (0, 0), and anchoring on those would reject every
    # real sample after them), then take neighbouring runs outwards, each only
    # if its near end is reachable from the edge of what's already accepted.
    runs, start = [], 0
    for k in range(1, len(cand)):
        if not reachable(cand[k - 1], cand[k]):
            runs.append((start, k - 1))
            start = k
    runs.append((start, len(cand) - 1))
    best = max(range(len(runs)), key=lambda r: runs[r][1] - runs[r][0])
    ok = np.zeros(len(t), dtype=bool)
    ok[cand[runs[best][0]: runs[best][1] + 1]] = True
    left, right = runs[best][0], runs[best][1]
    for a, b in reversed(runs[:best]):
        if reachable(cand[b], cand[left]):
            ok[cand[a: b + 1]] = True
            left = a
    for a, b in runs[best + 1:]:
        if reachable(cand[right], cand[a]):
            ok[cand[a: b + 1]] = True
            right = b
    return ok
```

**1. Teleporting samples** (`drop_glitches`). On the 2018 Azerbaijan Grand Prix, lap 40 (under a safety car), every car was
reported about 600 m off the circuit for about 30 seconds, with single steps of 2.3 km in 0.24 s. Drawn faithfully these
became giant fake "excursions". A sample is discarded if it is more than 100 m from any part of the track or
farther from the last accepted sample than the car could have driven (`1.5 × max(speed) × Δt + 15 m`). Crucially the
filter does not anchor on the first sample: a lap can *open* with placeholder positions near (0, 0), and anchoring
there would reject every real sample afterwards. It instead splits the samples into runs of mutually consistent
points, starts from the longest run and accepts neighbouring runs only if reachable from it. The unit test
`test_placeholder_samples_at_lap_start_do_not_poison_the_rest` locks that in. On that lap 1 320 samples were removed; on clean laps, none.

*`backend/app/engine/trajectory.py`*

```python
def drop_backtracking(t: np.ndarray, xy: np.ndarray, ref: dict, min_advance_m: float = 2.5) -> np.ndarray:
    """
    Mask of raw samples to shape the spline with: those at least
    `min_advance_m` further along the lap than the last one kept. The merged
    position channel occasionally steps a metre or so back and forth, and in
    slow corners zigzags between samples only ~1 m apart; a spline forced
    through every one of those wiggles bends sharply and the car's heading
    flickers. At racing speed samples are 10-20 m apart, so none are lost.
    """
    _, idx = lateral_offsets(xy, ref)
    n = len(ref["xy"])
    progress = np.unwrap(idx * (2 * np.pi / n)) * (n / (2 * np.pi)) * (ref["length_m"] / n)
    keep = np.zeros(len(t), dtype=bool)
    best = -np.inf
    for i, p in enumerate(progress):
        if i == 0 or p > best + min_advance_m:
            keep[i] = True
            best = p
    keep[-1] = True
    return keep
```

**2. Backtracking and zig-zag** (`drop_backtracking`). The merged position channel occasionally steps a metre backwards, and
in slow corners zig-zags between samples about a metre apart. A spline forced through every wiggle bends sharply and the
car's heading flickers. So a sample is kept only if it is at least 2.5 m further along the lap than the last kept one.
At racing speed samples are 10 to 20 m apart, so nothing is lost.

*(Full source: `backend/app/engine/trajectory.py`, `fill_gaps`.)*

**3. Gaps** (`fill_gaps`). After filtering, a car may have no valid sample for many seconds. A straight chord across
the circuit between the samples either side would be a lie, so if a gap exceeds one second the car is assumed to follow the
reference line between them. Those stretches are returned as `gaps`, and the UI draws the car faded with "no data".

**4. Excursions next to missing data.** An excursion whose window touches a gap, or that starts within a second of a
late-starting path, cannot be trusted, and is labelled `uncertain (near missing data)` instead of being counted as a breach.

### 15.7 Detecting excursions

*`backend/app/engine/trajectory.py`*

```python
def find_excursions(t: np.ndarray, offset: np.ndarray, ref_idx: np.ndarray, ref: dict,
                    threshold_m: float, corners: list[dict]) -> list[dict]:
    """Contiguous runs where |offset| > threshold, with entry/exit times, duration and peak depth."""
    out: list[dict] = []
    over = np.abs(offset) > threshold_m
    if not over.any():
        return out

    def cross(i0: int, i1: int) -> float:
        # time |offset| crossed the threshold, interpolated between samples
        o0, o1 = abs(offset[i0]), abs(offset[i1])
        f = 0.0 if o1 == o0 else (threshold_m - o0) / (o1 - o0)
        return float(t[i0] + np.clip(f, 0, 1) * (t[i1] - t[i0]))

    edges = np.flatnonzero(np.diff(np.concatenate([[0], over.astype(int), [0]])))
    for a, b in zip(edges[::2], edges[1::2]):          # run is [a, b)
        depth = np.abs(offset[a:b]) - threshold_m
        k = a + int(np.argmax(depth))
        d_max = float(depth.max())
        t_entry = cross(a - 1, a) if a > 0 else float(t[a])
        t_exit = cross(b - 1, b) if b < len(t) else float(t[b - 1])
        dur = t_exit - t_entry
        if dur < MIN_DURATION_S or d_max < MIN_DEPTH_M:
            continue
        curv = ref["curvature"][ref_idx[k]]
        side_left = offset[k] > 0
        if a == 0 or b == len(t):
            # Runs touching the start or end of the lap are the grid, the
            # pit lane or a lap that ended in the pits, not a track-limit breach.
            kind = "lap start / pit lane"
        elif abs(curv) < 1 / 400:                        # radius > 400 m: effectively a straight
            kind = "off line"
        else:
            kind = "corner cut" if side_left == (curv > 0) else "ran wide"
        out.append({
            "t_entry": round(t_entry, 3), "t_exit": round(t_exit, 3), "t_peak": round(float(t[k]), 3),
            "duration_s": round(dur, 3), "duration_ms": int(round(dur * 1000)),
            "max_excursion_m": round(d_max, 2), "peak_offset_m": round(float(offset[k]), 2),
            "side": "left" if side_left else "right", "kind": kind,
            "i_start": int(a), "i_end": int(b - 1),
            **_corner_label(int(ref_idx[k]), ref, corners),
        })
    return out
```

An **excursion** is a maximal run of samples where `|offset| > threshold` (default 5 m; the UI offers 3, 5 and 8).
For each run:

* **Entry and exit times** are interpolated between the 60 Hz samples at the exact moment `|offset|` crosses the
  threshold (`cross`), so the duration is not quantised to 1/60 s.
* **Peak depth** is the largest `|offset| − threshold` in the run, and the depth is measured *beyond the limit*.
* A run shorter than **0.25 s** or shallower than **0.75 m** is dropped as noise.
* **Classification** by the reference line's curvature at the peak. On a straight (radius > 400 m) it is `off line`. In a corner,
  if the car is on the *inside* of the bend it is a `corner cut`, on the outside `ran wide`. A run touching the very
  start or end of the lap is `lap start / pit lane`.
* **Corner label**: the nearest numbered corner from FastF1's circuit info if within 150 m, otherwise the position
  as a percentage of the lap.

### 15.8 What the results really say

An honest summary of what was measured across real laps:

| Lap | Result |
|---|---|
| 2019 Bahrain lap 3 (20 cars) | Largest deviation from the reference line 2.15 m; **no excursions** |
| 2021 Monaco lap 5 (19 cars) | Largest 0.95 m; none |
| 2018 Azerbaijan lap 20 | Largest 1.33 m; none |
| 2018 Azerbaijan lap 40 (safety car) | 1 320 glitch samples removed; three small "uncertain" flags near missing data |
| 2025 Australia lap 5 (behind the safety car) | 17 cars about 15 m off the racing line for about 8 s at lap start: labelled `lap start / pit lane` |

On clean laps every car stays within about 1.5 m of the reference line, even in traffic. That is far tighter than real
driving. The most likely explanation is that the position feed is quantised or snapped to a track model, which would
also hide genuine corner cuts. The detector itself is exercised on synthetic laps with known answers (duration,
depth, corner-cut versus ran-wide, noise filtering), but on real data **it has not yet produced a confirmed
track-limits breach**, and the UI describes the excursions as estimates.

And a limit of the whole approach: track edges are not in the data at all, so the "limit" is a fixed distance
either side of a racing line, not a white line.

### 15.9 All drivers on one lap

*(Full source: `backend/app/engine/trajectory.py`, `lap_trajectories`.)*

`lap_trajectories` builds the multi-car replay:

1. Smooth each driver's telemetry for the chosen lap (`_smooth_driver`).
2. Work out **when each car started the lap** on a shared session clock: the previous lap's `Time_s` for that driver
   (or the lap's end minus its duration for lap 1). Subtract the earliest start so the clock begins at zero.
3. Return each car's samples (positions rounded to 0.1 m, heading, offset, excursions, gaps) together with
   the shared reference line and corner list.

The gaps between cars in the replay are therefore the **real** gaps on the road, not an artefact.

`_lap_telemetry_all` avoids downloading a race twenty times: it reads any driver-lap already in the extra cache and,
for the rest, loads the session **once** and extracts every missing driver from that single load. First load of a
race took 29 seconds for 20 drivers; the second, 7 seconds.

The same 20 x 60 Hz x 100 s of data is about 4 MB of JSON, which the browser parses in a fraction of a second.

### 15.10 The map component

The browser side is `TrajectoryMap.jsx`, a `<canvas>` renderer with its own camera and animation loop.

*`frontend/src/components/TrajectoryMap.jsx`*

```jsx
function sampleCar(car, local, hz) {
  const n = car.t.length;
  const f = Math.min(Math.max((local - car.t[0]) * hz, 0), n - 1);
  const i = Math.min(Math.floor(f), n - 2), a = f - i;
  return {
    i,
    x: car.x[i] + (car.x[i + 1] - car.x[i]) * a,
    y: car.y[i] + (car.y[i + 1] - car.y[i]) * a,
    h: car.heading[i] + (car.heading[i + 1] - car.heading[i]) * a,
    o: car.offset[i] + (car.offset[i + 1] - car.offset[i]) * a,
  };
}
```

**The clock.** A single `clockRef` holds the shared session time. Each animation frame (`requestAnimationFrame`)
computes `dt` from the timestamp the browser supplies, clamps it to 0.1 s (so a returning background tab does not
teleport the cars), and advances the clock by `dt × playbackSpeed`. Every car's local time is `clock − car.start`;
the car is drawn only while that lies within its lap. So motion is tied to real elapsed time and looks smooth at 60,
120 or 144 Hz. (Automated testing in headless Chrome measured 144 frames per second.)

**Interpolation.** `sampleCar` finds the two 60 Hz samples around the exact local time and linearly interpolates
position, heading and offset, so a 144 Hz display still shows fractional positions.

**The camera.** `camRef` holds `{zoom, cx, cy}`: the zoom factor and the world coordinate at the canvas centre. The
scale is `fit.s × zoom`, where `fit.s` fits the whole circuit. World-to-pixel is
`px = (x − cx)·s + width/2` and `py = height/2 − (y − cy)·s` (canvas y points down, world y up).

**Zooming under the cursor.** With the mouse at pixel `(sx, sy)`, the world point under it is computed *before* the zoom
and the centre is then adjusted so the same world point stays under the cursor *after* it. That is what makes
wheel zoom feel anchored instead of drifting. The wheel listener is attached natively with `{passive: false}` so the
page does not scroll at the same time. Zoom is clamped between 0.8x and 40x. **Dragging** shifts `cx, cy` by the pixel
movement divided by the scale.

**Follow mode.** When enabled, the camera centre moves towards the focused car by an exponential filter,
`k = 1 − exp(−8·dt)`, which is frame-rate independent and removes jitter.

**Drawing order** each frame: track corridor (the ±limit band around the reference line), the dashed reference line,
excursion segments in amber, corner labels, each car's fading trail (the last 2.5 s), then the cars (the focused one last,
on top and 35 % larger). A car is an arrow rotated by `−heading` with a dark label pill showing its three-letter
code in the driver's colour.

**Colours.** Twenty distinct hues (`PALETTE`) are assigned by index, one per driver on the lap, so team-mates do not
share a colour on this map.

**HUD.** React state is updated only every 100 ms (10 Hz) for the readout card, because re-rendering React 60 times a second
for a text box would waste time; the canvas itself is redrawn every frame outside React.

> 🏁 **Pit-wall trivia: circuits with a twist.** Suzuka in Japan is the only circuit on the calendar whose track crosses
> over itself in a figure of eight, and it is one of the outlines this app draws. Layouts where two stretches of track run close together,
> like a crossover or a hairpin, are exactly what the trajectory matcher's locality window guards against. Monza's high-speed layout produced the
> fastest lap ever recorded by average speed in F1: Lewis Hamilton's 2020 pole lap averaged over 264 km/h. And the
> Circuit de Spa-Francorchamps, at just over 7 km, is the longest on today's calendar; Monaco, at about 3.3 km, is the shortest.

---

## 16. Championship, qualifying, sectors, weather and stints

These smaller features share one pattern: derive from the lap table when possible, otherwise ask FastF1 for one specific
table, cache the answer, and return plain dictionaries.

### 16.1 Championship standings

*`backend/app/engine/championship.py`*

```python
def _race_points(race_id: str) -> Optional[list[dict]]:
    """Points awarded to each driver for one race, using our own classification."""
    try:
        from app.engine.data_loader import load_session_laps
        from app.engine.replay import _build_car_states

        laps_df, _ = load_session_laps(race_id)
    except Exception as exc:
        log.debug("Could not load %s for championship: %s", race_id, exc)
        return None

    last_lap = int(laps_df["LapNumber"].max())
    cars = _build_car_states(laps_df[laps_df["LapNumber"] == last_lap].copy(), laps_df, last_lap)

    fastest_driver = None
    if laps_df["LapTime_s"].notna().any():
        fastest_driver = str(laps_df.loc[laps_df["LapTime_s"].idxmin(), "Driver"])

    entries = []
    for c in sorted(cars, key=lambda c: c.position):
        # A genuine DNF (our `retired`, which already applies the FIA's
        # 90%-of-distance classification rule) scores nothing; a car that's
        # merely laps down but still classified scores for its position.
        pts = 0.0 if c.retired else float(POINTS.get(c.position, 0))
        if fastest_driver == c.driver_code and pts > 0 and c.position <= 10:
            pts += FL_POINT
        entries.append({
            "driver_code": c.driver_code,
            "team": c.team,
            "position": c.position,
            "retired": c.retired,
            "points": pts,
        })
    return entries
```

The module's opening comment explains a design decision worth repeating. FastF1's `session.results` is filled from
Ergast, which fails for nearly every session here, and when it fails `Position` is NaN for **every** driver, which
silently gave everyone zero points in every race (and made computing a season take twenty seconds per race). So the
championship scores races using **the project's own classification** (`_build_car_states` on the last lap), which
had already been checked against FastF1's official per-lap position column across every cached race.

The scoring rules implemented:

| Rule | Value |
|---|---|
| Points by position | 25, 18, 15, 12, 10, 8, 6, 4, 2, 1 for P1 to P10 |
| A retired car (below 90 % distance) | 0 points |
| A lapped but classified car | Scores for its position |
| Fastest lap | +1 point if the fastest-lap driver finished in the top ten |

Persistence is **per race** (`race_points_<race_id>` in the extra cache), so computing a season is resumable, and a slow
or failed race elsewhere does not waste the ones already scored. A cold season is computed with a thread pool of six
workers (`_LOAD_WORKERS`), because each race load is mostly disk input and pandas parsing, which parallelise well
under the interpreter lock; that took a cold season from close to a minute to a fraction of that.

Standings are `get_driver_standings(year, through_round)` and `get_constructor_standings(year, through_round)`,
with `through_round` allowing "standings after round N", which the Qualifying tab uses for "the championship after this race".

**Known simplifications** (see chapter 23): the fastest-lap point is applied in **every** season, although it existed only
from 2019 to 2024; **sprint-race points** are not included; and penalties applied after the race, or
disqualifications, are not reflected because the classification comes from lap timing.

> 🏁 **Pit-wall trivia: how points have changed.** The 25-18-15 scale used here has applied since 2010; before that,
> the winner scored 10. Points are scored down to tenth place. From 2019 to 2024 the fastest lap earned an extra point, from
> 2025 it did not, and sprint races award points to the top eight.

### 16.2 Qualifying

`load_qualifying_results` loads the *Qualifying* session with `messages=True` and returns each driver's position and
their best time in Q1, Q2 and Q3. The details that took debugging:

* Race-control messages are required so FastF1's fallback can tell which laps were deleted; without them every driver was
  `Position = NaN`, shown as P99 with blank times.
* A driver with **no timed laps at all** has no position. The API returns `null` and the UI shows **DNS**, instead of
  inventing a last place.
* `None` positions are sorted after real ones; the sort key is `(position is None, position or 0)` so the comparison never
  compares `None` to `None`.

### 16.3 Sector times

`load_sector_times(race, driver)` returns S1, S2 and S3 for each lap. The Telemetry tab's `SectorHeatmap` colours each
cell by its position within that driver's own range, green to amber to red (function `sectorColor`).

### 16.4 Weather

`load_weather_data` returns air and track temperature, humidity, wind speed and a rain flag, one frame per approximate lap.
The mapping from time to lap uses a fixed 135 s per lap (section 5.5), so treat the lap number as approximate.

### 16.5 Stints

`load_stint_data` splits each driver's laps into stints wherever the compound changes or a lap is a pit out-lap. The
Strategy tab draws them as horizontal bars, and `monte_carlo._stint_targets_for_race` reads them to learn how long
each compound really lasted in that race.

> 🏁 **Pit-wall trivia: tyres by colour.** Since Pirelli became the sole tyre supplier in 2011, every compound has had a
> colour band: **red** soft, **yellow** medium, **white** hard, **green** intermediate and **blue** full wet. The
> soft-medium-hard trio is chosen from a range of compounds numbered C0 (hardest) to C5 (softest), with C0 added in 2023, and
> the three picked for each race are labelled soft, medium and hard, so a "medium" at one circuit is not the same rubber as a "medium" at
> another.

---

## 17. The frontend

### 17.1 Structure

There are two screens: the **race selector** (no race chosen) and the **dashboard** (a race chosen). `App.jsx` owns all
shared state and passes props down; there is no router and no global store.

| State in `App.jsx` | Meaning |
|---|---|
| `selectedRace` | The chosen race metadata, or `null` for the selector |
| `speed` | Replay multiplier (2, 5 or 10) |
| `paused` | Whether the stream is paused |
| `activeTab` | Which dashboard tab is showing |
| `shared` | Whether the "Copied!" label is showing |

`useRaceSocket` supplies `raceState`, `predictions`, `status`, `winner` and `infoMsg`.

The tab layout is a plain conditional render, keyed by tab name so React remounts a tab with a fade-in animation when it changes:

*`frontend/src/App.jsx`*

```jsx
            {activeTab === "Charts" && (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
                <div className="card p-4">
                  <GapChart raceId={selectedRace.race_id} />
                </div>
                <div className="card p-4">
                  <LapDeltaChart cars={cars} />
                </div>
              </div>
            )}
```

### 17.2 Components at a glance

| Component | Data | What it draws |
|---|---|---|
| `RaceSelector` | `GET /races` | Hero, season pills, search, race cards |
| `Leaderboard` | WebSocket cars | Ordered rows with team stripe, position badge, tyre, gap, FL / DRS / PIT tags |
| `WinProbabilityChart` | WebSocket predictions | Win bars (Recharts) and podium mini-bars |
| `CounterfactualPanel` | `POST /simulate/counterfactual` | Driver, pit-lap slider, compound buttons, result |
| `UndercutCalc` | `POST /simulate/undercut` | Two drivers, pit lap, compound, verdict |
| `WeatherWidget` | `GET /weather` | Air, track, humidity, wind, rain |
| `GapChart` | `GET /gaps` | Gap-to-leader lines for the ten closest |
| `LapDeltaChart` | WebSocket cars | This lap's times as bars with an average line |
| `TelemetryPanel` | `GET /telemetry` | Speed, throttle, brake and gear against time |
| `SectorHeatmap` | `GET /sectors` | Coloured sector table |
| `TrajectoryMap` | `GET /trajectories` | Canvas circuit map (chapter 15) |
| `CircuitImage` | `GET /circuit.png` | Circuit outline with loading and missing states |
| `AnalyticsPanel` | `GET /analytics/*` | Cards, podium, table, eight PNG charts |
| `InsightsPanel` | `GET /insights`, `/seasons`, `/rag` | Highlights, timeline, charts, search, cards |
| `StintAnalysis` | `GET /stints` | Stint bars per driver |
| `QualifyingGrid` | `GET /qualifying` | Table of Q1, Q2, Q3 |
| `ChampionshipPanel` | `GET /points`, `/championship` | Standings, this-race points |
| `SpeedControl` | props | Status pill, play and pause, speed segments |
| `TireBadge` | props | Round compound badge with age |

### 17.3 Hooks

**`useKeyboardShortcuts`** listens on `window` for keys and ignores them when focus is in an input, select or textarea, so typing a lap number
never changes the replay speed:

*`frontend/src/hooks/useKeyboardShortcuts.js`*

```javascript
import { useEffect } from "react";

export function useKeyboardShortcuts({ onPause, onResume, onSpeedChange, paused, enabled = true }) {
  useEffect(() => {
    if (!enabled) return;

    function handleKey(e) {
      if (e.target.tagName === "INPUT" || e.target.tagName === "SELECT" || e.target.tagName === "TEXTAREA") return;

      switch (e.key) {
        case " ":
          e.preventDefault();
          if (paused) onResume?.();
          else onPause?.();
          break;
        case "2":
          onSpeedChange?.(2);
          break;
        case "5":
          onSpeedChange?.(5);
          break;
        case "0":
        case "1":
          onSpeedChange?.(10);
          break;
        default:
          break;
      }
    }

    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [paused, enabled, onPause, onResume, onSpeedChange]);
}
```

**`useShareableUrl`** writes `#race=<id>&lap=<n>` into the address bar and is meant to restore a race from it:

*`frontend/src/hooks/useShareableUrl.js`*

```javascript
import { useEffect } from "react";

export function useShareableUrl({ raceId, lap, onRestore }) {
  useEffect(() => {
    if (!raceId) {
      history.replaceState(null, "", window.location.pathname);
      return;
    }
    const hash = `#race=${encodeURIComponent(raceId)}${lap ? `&lap=${lap}` : ""}`;
    history.replaceState(null, "", hash);
  }, [raceId, lap]);

  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (!hash) return;
    const params = new URLSearchParams(hash);
    const savedRace = params.get("race");
    const savedLap = params.get("lap");
    if (savedRace && onRestore) {
      onRestore({ raceId: decodeURIComponent(savedRace), lap: savedLap ? parseInt(savedLap) : null });
    }
  }, []);
}

export function copyShareLink() {
  navigator.clipboard.writeText(window.location.href).catch(() => {});
}
```

**Known defect.** The first effect clears the hash whenever no race is selected, which is the case on first render, and effects run in
order, so by the time the second effect reads `window.location.hash` it is already empty. A shared link therefore never restores
the race. It is a small fix (read the hash before clearing it) and is listed in chapter 23.

### 17.4 The leaderboard

*`frontend/src/components/Leaderboard.jsx`*

```jsx
export default function Leaderboard({ cars = [], lap, totalLaps }) {
  const prevPositions = useRef({});
  const [fastestLapCarId, setFastestLapCarId] = useState(null);

  useEffect(() => {
    let bestTime = Infinity;
    let bestId = null;
    cars.forEach(c => {
      if (c.lap_time_s && c.lap_time_s < bestTime) {
        bestTime = c.lap_time_s;
        bestId = c.car_id;
      }
    });
    setFastestLapCarId(bestId);
    return () => {
      const newPrev = {};
      cars.forEach(c => { newPrev[c.car_id] = c.position; });
      prevPositions.current = newPrev;
    };
  }, [cars]);
```

Two details of note. **Position arrows** (▲ ▼) come from a `useRef` holding the previous lap's positions: the effect's *cleanup*
function stores the current positions, so on the next render the difference is available. **Fastest lap** is the car with
the smallest lap time in the current snapshot, recomputed each lap, so the "FL" tag moves between cars as the race goes on
instead of tracking the race-long fastest lap.

### 17.5 Charts and their pitfalls

Recharts drew three problems into this project, and each fix has a comment in the source.

* **Missing category labels.** Recharts silently drops category ticks it thinks would overlap, and once dropped the
  leader's own row, the one that needs a label most. The fix is `interval={0}` on the category axis in `WinProbabilityChart`
  and `LapDeltaChart`.
* **Bars animating between drivers.** The win-probability chart re-sorts every lap; with animation on, each row tweened from its previous
  occupant's width to the new one, flashing an oversized, unlabelled bar. The fix is `isAnimationActive={false}`.
* **One outlier ruining the axis.** In the gap chart, a car that lost minutes to a repair stop would stretch the axis until the real
  fight was a sliver. The fix caps the axis to 1.4 times the 90th percentile of the top ten's gaps and lets outliers run off the top:

*`frontend/src/components/GapChart.jsx`*

```jsx
  const typicalGaps = activeDrivers.flatMap(drv => chartData.map(r => r[drv]).filter(v => v != null));
  const p90 = typicalGaps.length
    ? typicalGaps.sort((a, b) => a - b)[Math.floor(typicalGaps.length * 0.9)]
    : 100;
  const yMax = Math.max(30, Math.ceil((p90 * 1.4) / 10) * 10);
```

A fourth, cosmetic one: Recharts colours tooltip text with the series colour, and several team colours are unreadable
as text on the dark tooltip. The fix is a single `itemStyle={{ color: "#e5e7eb" }}`. And a bug fixed late: the win-probability tooltip compared the
series name with the string `"win"` while the bar was named `"Win"`, so it always fell through to "Podium".

### 17.6 The Insights panel

`InsightsPanel.jsx` is the largest component and combines server data with client-side drawing.

* **Strategy timeline** is plain HTML: each stint is an absolutely positioned `div` whose `left` and `width` are percentages
  of the race (`(lap − 1) / total × 100 %`), coloured by compound, with neutralised laps as translucent amber columns behind it.
* **Pace ranking** bars scale to the largest gap.
* **Field pace** and **tyre wear curves** are Recharts line charts; `ReferenceArea` marks neutralised laps.
* **Lead timeline** is a row of coloured segments.
* **Team scorecard** draws a centre-zero bar per team: to the right of the line means slower than the field, to the left means faster.
* **Ask the season** sends the question to `/rag/search` with an optional `year` and lists passages with a category chip and source line.
  Example question chips run the search on click.

Every visual degrades to a message ("Not enough clean laps to rank pace") instead of an empty box.

### 17.7 Data-fetching conventions

* Every panel fetches with `fetch()` inside `useEffect` and stores `data`, `loading` and `error` in local state. There is
  no caching layer in the browser: the server's caches make repeat requests cheap.
* URLs come from `API_BASE` and `WS_BASE` in `constants.js` (hard-coded to `localhost:8000`).
* Errors are surfaced in the panel's own space, in words that say *why* ("no position data is archived for this circuit"),
  not a generic failure.

> 🏁 **Pit-wall trivia: a car's team colour is not just paint.** Teams choose their liveries for sponsors, broadcasters and
> fans, and the colours change: Red Bull's blue is a deep navy in the official palette, which is why the app's dark theme
> brightens it (`#3671c6`) so it stays legible, matching the colour used in the server-drawn charts. Ferrari red and McLaren papaya
> are the most stable identities on the grid, both used for decades in some form.

---

## 18. The design system

### 18.1 Principles

The interface is a **dark, data-dense dashboard** in the visual language of a motorsport timing wall: near-black carbon
surfaces, a single red accent (F1 red, `#e10600`), condensed capitals for headings, monospaced tabular figures for times.
The rules that keep it coherent:

1. **One accent colour.** Red means "the thing you can act on or should look at". Data colours (compounds, teams) are separate.
2. **Numbers use tabular figures.** Times and gaps are set in JetBrains Mono so digits align in columns.
3. **Headings are condensed caps.** Barlow Condensed at wide letter-spacing, with a red tick, gives every card the same heading treatment automatically (below).
4. **Motion is subtle and optional.** Fades and lifts under 350 ms; `prefers-reduced-motion` turns all animation off.
5. **Loading is a skeleton, not a spinner**, so the layout does not jump when data arrives.

### 18.2 Tokens

*`frontend/tailwind.config.js`*

```javascript
/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        f1red: "#e10600",
        pitwall: "#0b0d13",
        panel: "#1a1d27",
        panel2: "#212536",
        border: "#2a2f40",
        ink: { 50: "#f4f5f8", 300: "#aab1c4", 500: "#727a90", 700: "#3a4054" },
      },
      fontFamily: {
        display: ['"Barlow Condensed"', "Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ['"JetBrains Mono"', "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      boxShadow: {
        card: "0 1px 0 rgba(255,255,255,.04) inset, 0 12px 28px -16px rgba(0,0,0,.75)",
        glow: "0 0 0 1px rgba(225,6,0,.35), 0 8px 30px -8px rgba(225,6,0,.35)",
      },
      keyframes: {
        fadeUp: { from: { opacity: 0, transform: "translateY(6px)" }, to: { opacity: 1, transform: "none" } },
        shimmer: { "100%": { transform: "translateX(100%)" } },
      },
      animation: { fadeUp: "fadeUp .35s ease both", shimmer: "shimmer 1.4s infinite" },
    },
  },
  plugins: [],
};
```

| Token | Value | Use |
|---|---|---|
| `f1red` | `#e10600` | Accent, active tab, buttons |
| `pitwall` | `#0b0d13` | Page background |
| `panel` | `#1a1d27` | Card surface, and the exact colour matplotlib PNGs are drawn on, so images blend in |
| `border` | `#2a2f40` | Hairlines |
| `ink-*` | greys | Secondary text |
| `font-display` | Barlow Condensed | Headings, big numbers |
| `font-sans` | Inter | Body |
| `font-mono` | JetBrains Mono | Times, gaps, counts |

### 18.3 Global styles

*(Full source: `frontend/src/index.css`.)*

Highlights:

* **`.card`** is the surface for every panel: a subtle top-to-bottom gradient, a hairline border, 16 px radius and a soft shadow. Nearly
  every panel in `App.jsx` is a `div.card`.
* **`.card h2, .card h3`** rule gives every heading inside a card the condensed-caps-plus-red-tick style. Because these rules are
  in unlayered CSS after Tailwind's utilities, they beat a utility like `text-sm` on the same element; older components that still carry
  their own heading classes were upgraded without editing them. A `.no-tick` escape hatch removes the tick where a different icon is used.
* **`.skeleton`** is the shimmer placeholder.
* **`.tab[data-active="true"]::after`** draws the glowing red underline under the active tab.
* **`.chip`** is the small rounded pill used for metadata.
* The body background is layered radial gradients (a red glow top-left, a faint blue top-right) over the base colour, fixed to the viewport.

### 18.4 Colours for data

* **Tyres** (`TIRE_COLORS` in `constants.js`): red soft, yellow medium, light grey hard, green intermediate, blue wet, dark grey unknown.
* **Teams** (`TEAM_COLORS`, `getTeamColor`): a lookup by team name with a substring fallback (so "Red Bull Racing" and "Red Bull"
  both resolve), and a grey fallback for anything unknown. Some entries were brightened from official palette values (Red Bull,
  Aston Martin, AlphaTauri) because a dark navy is nearly invisible on a dark background.
* **Drivers on the trajectory map**: twenty distinct hues, deliberately *not* team colours, so two team-mates are told apart.

### 18.5 Accessibility notes

Contrast is generally strong (light text on near-black), interactive elements are real `<button>`s with focus outlines, and reduced motion is
respected. Known gaps: several colour-only encodings (tyre compound, driver colour) are supplemented by letters and labels but not
everywhere, canvas content is not exposed to screen readers, and the tab bar does not implement the ARIA tab pattern.

> 🏁 **Pit-wall trivia: the sound of 2026.** The 2026 rules are the biggest since 2014: power units split roughly evenly between
> the combustion engine and the electric side (the MGU-H is gone), fuels become fully sustainable, and cars use **active aerodynamics**
> with movable wings replacing the old DRS flap. Audi joins by taking over the Sauber team, Cadillac arrives as an 11th team, Honda
> partners with Aston Martin and Ford with Red Bull, and Madrid is on the calendar with a new street circuit alongside Barcelona. Those changes are
> announced facts; for the current state of any of them, check the sport's own sources.

---

## 19. API reference

Base address `http://localhost:8000`. Interactive documentation (generated from the code) is at `/docs`, and the raw
schema at `/openapi.json`. Errors use FastAPI's shape: `{"detail": "..."}` with 404 for an unknown race, 422 for an invalid
parameter, and 503 when the data behind a request could not be loaded.

### 19.1 All endpoints

| Method | Path | Returns |
|---|---|---|
| GET | `/api/health` | `{status, app, version}` |
| GET | `/api/races` | The whole calendar, each entry with a `cached` flag |
| GET | `/api/races/{race_id}` | One race's metadata plus `cached` |
| WS | `/ws/race/{race_id}?speed=&start=` | Replay stream (chapter 9) |
| GET | `/api/races/{race_id}/gaps` | `{laps, drivers, gaps_matrix, lap_times_matrix}` |
| GET | `/api/races/{race_id}/stints` | Stints per driver |
| GET | `/api/races/{race_id}/weather` | `{race_id, frames}` |
| GET | `/api/races/{race_id}/qualifying` | Q1, Q2, Q3 per driver |
| GET | `/api/races/{race_id}/sectors?driver=` | Sector times per lap |
| GET | `/api/races/{race_id}/telemetry?driver=&lap=` | Raw telemetry points |
| GET | `/api/races/{race_id}/points` | Points this race, standings after it |
| GET | `/api/championship/{year}/drivers` | Season driver standings |
| GET | `/api/championship/{year}/constructors` | Season constructor standings |
| GET | `/api/races/{race_id}/analytics/summary` | Cards and driver table |
| GET | `/api/races/{race_id}/analytics/charts` | List of chart ids, titles, captions |
| GET | `/api/races/{race_id}/analytics/charts/{chart_id}.png` | A rendered chart |
| GET | `/api/races/{race_id}/circuit.png` | Circuit outline image |
| GET | `/api/races/{race_id}/insights` | The analyses, facts and chart data |
| GET | `/api/seasons/{year}/insights` | Season roll-ups |
| GET | `/api/rag/search?q=&year=&limit=` | Best-matching facts |
| GET | `/api/rag/coverage` | Races indexed per season |
| GET | `/api/races/{race_id}/trajectory?driver=&lap=&threshold_m=` | One driver's smoothed lap |
| GET | `/api/races/{race_id}/trajectories?lap=&threshold_m=` | Every driver's smoothed lap |
| POST | `/api/simulate/counterfactual` | Pit what-if |
| POST | `/api/simulate/undercut` | Undercut verdict |
| POST | `/api/simulate/optimal-stop` | Pit windows |

Parameter limits: `q` is 2 to 200 characters; `limit` 1 to 25; `lap` 1 to 100; `threshold_m` 1 to 20; `year` on the search is 2000 to 2100.

### 19.2 Live samples

The following responses were captured from the running backend while this document was generated (arrays shortened).

*`GET /api/races/2021-r05`  ·  GET response, lists shortened to 2 items*

```json
{
  "race_id": "2021-r05",
  "year": 2021,
  "round_number": 5,
  "event_name": "Monaco Grand Prix",
  "circuit": "Monte Carlo",
  "event_date": "2021-05-23",
  "total_laps": 0,
  "f1_api": true,
  "cached": true
}
```

*`POST /api/simulate/undercut`  ·  POST response, lists shortened to 2 items*

```json
{
  "will_undercut": false,
  "gap_before_s": 35.813,
  "projected_gap_after_s": 39.013,
  "breakeven_lap": null,
  "recommendation": "Overcut recommended. Gap projected at +39.0s — insufficient pace gain from MEDIUM."
}
```

Here `car_id` 44 is Hamilton and 33 Verstappen. The 35.8 s gap and the "overcut recommended" verdict are the model's honest
reading of a big gap: no tyre advantage in the model can close that.

*`POST /api/simulate/optimal-stop`  ·  POST response, lists shortened to 2 items*

```json
{
  "windows": [
    {
      "compound": "HARD",
      "earliest_lap": 31,
      "latest_lap": 31,
      "optimal_lap": 31,
      "net_time_gain_s": 213.41
    },
    {
      "compound": "MEDIUM",
      "earliest_lap": 31,
      "latest_lap": 31,
      "optimal_lap": 31,
      "net_time_gain_s": 199.78
    }
  ]
}
```

Note the `net_time_gain_s` of 213 and 200 seconds. That is not a discovery; it is an artefact. The function
compares stopping with running the old soft tyres for the remaining 47 laps while assuming its wear keeps growing
linearly, so the "saving" is huge. Read it as "the model thinks 30-lap-old softs at Monaco are unsustainable", and that
the arithmetic is more suited to ranking compounds against each other than to reading an absolute figure.

*`GET /api/rag/search?q=safety%20car&year=2026&limit=2`  ·  GET response, lists shortened to 2 items*

```json
{
  "query": "safety car",
  "year": 2026,
  "mode": "retrieval-only (extractive, no language model)",
  "results": [
    {
      "score": 7.872,
      "text": "2026 season: Most neutralised laps — Japanese Grand Prix. 6 laps under safety car / VSC / red flag.",
      "source": "2026 season · 14 races analysed",
      "year": 2026,
      "race_id": null,
      "kind": "season",
      "category": "Season"
    },
    {
      "score": 7.761,
      "text": "2026 Hungarian Grand Prix: Neutralised laps — 1. Laps 56 (safety car / VSC / red flag).",
      "source": "2026 Hungarian Grand Prix · round 11 · Budapest",
      "year": 2026,
      "race_id": "2026-r11",
      "kind": "race",
      "category": "Race flow"
    }
  ]
}
```

---

## 20. Data structures reference

### 20.1 Replay and simulation (`schemas/race.py`)

| Model | Fields |
|---|---|
| `CarState` | `car_id`, `driver_code`, `team`, `position`, `lap_number`, `lap_time_s?`, `cumulative_time_s`, `gap_to_leader_s`, `tire_compound`, `tire_age_laps`, `pit_count`, `is_in_pit`, `speed_kmh?`, `drs`, `retired`, `laps_down` |
| `RaceState` | `race_id`, `lap`, `total_laps`, `session_name`, `cars[]`, `timestamp_ms` |
| `WinProbability` | `car_id`, `driver_code`, `win_pct` (0 to 100), `podium_pct`, `expected_position` |
| `PredictionFrame` | `lap`, `probabilities[]`, `n_simulations` |
| `CounterfactualRequest` | `race_id`, `car_id`, `pit_lap`, `target_compound`, `current_lap?` |
| `CounterfactualResponse` | original, new and delta for win and podium, plus an `explanation` sentence |
| `UndercutRequest / Response` | see the sample above |
| `OptimalStopRequest` | `race_id`, `car_id`, `current_lap`, `total_laps`, `current_compound`, `current_tire_age`, `compounds_available[]` |

`tire_compound` is the literal type `SOFT | MEDIUM | HARD | INTERMEDIATE | WET | UNKNOWN`. Two fields exist but are never filled by
the replay: `speed_kmh` stays `null` and `drs` stays `false`, so the leaderboard's DRS tag never appears.

### 20.2 Insights JSON

```
{
  "race_id", "event_name", "year", "circuit", "round",
  "insights": [ {id, category, title, value, detail} ... 45 to 48 ],
  "facts":    { winner, winner_team, fastest_lap_driver, fastest_lap_s, total_laps, stops, starters,
                finishers, dnfs, neutral_laps, lead_changes, swaps, median_pit_loss, top_strategy,
                compound_laps{}, podium[] }            (null for a race with no timed laps)
  "extras":   { strategy[], pace_ranking[], field_pace[], lead_timeline[], deg_curves{}, teams[],
                neutral_laps[], total_laps }
  "categories": ["Pace", "Consistency", "Strategy", "Tyres", "Race flow"]   (added by the router)
}
```

### 20.3 Trajectory JSON (`/trajectories`)

```
{
  "race_id", "lap", "sample_hz": 60.0, "threshold_m", "drivers_on_lap",
  "cars": [ { "driver", "team", "start" (s on the shared clock), "duration",
              "t[]", "x[]", "y[]" (metres), "heading[]" (radians), "offset[]" (signed metres from the reference),
              "max_offset_m", "glitch_samples_removed", "gaps": [[start_s, end_s]...],
              "excursions": [ { t_entry, t_exit, t_peak, duration_s, duration_ms, max_excursion_m,
                                peak_offset_m, side, kind, corner, corner_source, i_start, i_end } ] } ],
  "missing": ["drivers with no position data"],
  "reference_source", "reference_length_m", "reference": {x[], y[]}, "corners": [{label, x, y}], "method"
}
```

### 20.4 Files on disk

| Path | Content |
|---|---|
| `cache/calendar_cache.json` | `{built_at, count, races[]}` |
| `cache/processed/<race>.pkl` | `{df, total_laps, version}` |
| `cache/processed/extra/<key>.pkl` | `{value, version}` for telemetry, sectors, weather, qualifying, per-race points, circuit outlines, corners |
| `cache/processed/charts/*.png` | Analytics charts and circuit images |
| `cache/processed/insights/<race>_v2.json` | The insights JSON above |

> 🏁 **Pit-wall trivia: how much data is that?** Each car carries hundreds of sensors, and a race weekend's telemetry runs to
> gigabytes. The public archive this app reads is a tiny slice: lap times, sector times, tyre data and a position trace of a few
> samples per second per car, which is why a whole season's processed lap tables fit in tens of megabytes.

---

## 21. Testing

`python -m pytest -q` from `backend/` runs **24 tests** in about five seconds.

| File | Tests | What it checks |
|---|---|---|
| `test_monte_carlo.py` | 4 | Win probabilities sum to about 100 %; a clear leader has the highest chance; the counterfactual returns two records |
| `test_insights.py` | 7 | At least 40 insights in known categories with unique ids; consecutive pit laps merge; range formatting; season roll-ups; search respects the year filter and infers it from the question; the tokenizer's synonyms |
| `test_trajectory.py` | 11 | The spline passes through its samples; 60 Hz output with steady spacing; heading turns smoothly; lateral-offset sign and size; excursion duration and depth on a synthetic bump; corner-cut versus ran-wide; small deviations ignored; teleporting samples dropped; placeholder samples at lap start do not poison the rest; gaps follow the track; backtracking dropped |
| `test_fastf1_import.py` | 2 | FastF1 imports and a cache directory can be created |

Design choices: trajectory tests use **synthetic circles** with known answers, so they need no data and never flake.
Insight and search tests read the real local cache and are **skipped** if it is empty. `test_ws_client.py` is a manual script, not a pytest test:
it connects to a running backend, collects a few frames and asserts the message contract.

Not covered: the frontend has no automated tests (it is checked by `npm run build` and by hand), and the championship,
replay classification and analytics modules have no unit tests of their own; the replay's behaviour is protected mostly by the
long explanatory comments and by having been checked against FastF1's official per-lap positions.

---

## 22. Performance notes

Measured on the author's laptop with the 2021 Monaco Grand Prix:

| Operation | Time |
|---|---|
| Load a cached race (pickle) | about 2 ms |
| Build one lap's car states | about 25 ms |
| 500 Monte Carlo simulations | about 35 to 90 ms |
| Build insights for one race | 0.1 to 0.7 s |
| Build insights for 42 races | about 16 s |
| First download of one race | 10 to 60 s |
| First trajectory load of a race (20 drivers) | about 29 s; then about 7 s |
| Cache 122 races with the script | about 18 min |

**Where the time goes:** downloads dominate everything; after that, pandas group-bys (analytics), then the simulation. **Disk:**
the whole `cache/` folder was about 2.2 GB, of which roughly 1.1 GB is FastF1's own HTTP cache database and per-season folders;
this project's processed data (165 lap tables, 299 query results, charts, insights) is about 65 MB.

**Scaling limits:** memory holds a handful of `lru_cache`d DataFrames (16 races of laps, 6 of `RaceData`, 8 of gaps), so a
process stays small. Concurrency is the weak point: the simulation runs on the event loop, and a public deployment would need rate
limits because some endpoints trigger multi-second downloads.

---

## 23. Known limitations and defects

An honest list, ordered roughly by how much a user might notice.

1. **Changing the replay speed restarts the race.** The speed control changes a React dependency, which closes and reopens the socket; the
   server's `set_speed` handler updates a variable the running generator never re-reads.
2. **The pit-loss table never applies.** It looks for `monza`, `zandvoort`, `monaco` inside ids like `2021-r14`. All races use 23 s.
3. **The safety-car term in the simulation is a no-op**: it adds the same time to every car in a run.
4. **Counterfactual quirks**: the pit lap barely matters, and some effects are counted twice (section 11.1).
5. **Optimal-stop numbers are inflated** by the linear wear assumption (section 19.2), and no panel uses the endpoint.
6. **Win probabilities assume identical drivers and cars.** They are a tyre-and-position model, not a forecast.
7. **Championship simplifications**: the fastest-lap point is applied to every season (real: 2019 to 2024 only), sprint points are omitted, and
   post-race penalties are not reflected. Constructors are grouped by name, so a renamed team appears as two teams. The route
   also accepts 2022, which returns an empty table.
8. **`simulate_race` blocks the event loop** for a few tens of milliseconds per lap.
9. **Share links do not restore a race** (section 17.3).
10. **Weather is matched to laps with a fixed 135 s per lap.**
11. **`speed_kmh` and `drs` are never populated**, so the leaderboard's DRS tag never shows.
12. **Classification is derived, not official.** Penalties added after the race, disqualifications and stewards' decisions are not visible in lap timing.
13. **Trajectory limits**: track edges are an estimate (fixed width around a racing line), position data is snapped or coarse, and no
    genuine track-limits breach has been confirmed on real data. All 2026 sessions have no position data at all.
14. **Insights include estimates**: overtakes (lap-order comparison), undercuts, pit-stop losses and tyre wear.
15. **Front-end addresses are hard-coded** to `localhost:8000`, and `main.py` starts Uvicorn with `reload=True` on `0.0.0.0`, which
    is a development convenience, not a deployment setting.
16. **No authentication or rate limiting.** Anyone who can reach the API can trigger downloads.
17. **Pickle cache** must never be shared from an untrusted source.
18. **FastF1 3.3.7 is pinned**, still asks the retired Ergast service, and prints warnings; a newer FastF1 uses its successor but would need re-testing of every loader.
19. `httpx` remains in `requirements.txt` although the live-timing code that used it was removed.

---

## 24. Data-source problems we met and how we handled them

| Problem | Symptom | Handling |
|---|---|---|
| **Ergast retired** | "Failed to load result data from Ergast" on every load; results table all NaN | Derive classification from lap timing (chapters 8 and 16) |
| **2022 archive refuses access** | `403 AccessDenied` on every 2022 URL; FastF1 raises `KeyError: 'DriverNumber'` | Season removed from the catalogue |
| **2026 has no position data** | "Failed to load telemetry data"; trajectory and circuit maps unavailable | The trajectory endpoint returns a clear 404 message; laps and analytics still work |
| **Lap 1 has no lap time** | Gaps to the leader five to six times too large | Use FastF1's cumulative `Time` (section 5.4) |
| **Red-flag races** | One pit visit flagged on two consecutive laps; absurd stop counts | Merge consecutive pit laps |
| **Race with no timed laps** (2021 Belgium) | Empty statistics, `argmin` on an empty sequence | Store "nothing to analyse"; skip in roll-ups |
| **Position feed teleports** (2018 Baku lap 40) | Cars 600 m off the circuit; giant fake excursions | Glitch filter with run anchoring (section 15.6) |
| **Placeholder positions at lap start** | Positions near (0, 0) | Same filter; not anchored on the first sample |
| **Backtracking or zig-zag samples** | Kinked spline, flickering heading | Minimum advance of 2.5 m along the lap |
| **Unreliable timestamps** | Car appears to lurch between samples | Timing from the integrated speed channel |
| **`get_car_data` has no X, Y** | Track drawn as one dot | Use `get_telemetry()` (section 5.5) |
| **Live timing paywalled** | HTTP 401 from OpenF1 during a session | Live mode removed |
| **Compound value `"nan"` string** | Validation failure | Whitelist normalisation |

> 🏁 **Pit-wall trivia: why the safety car exists.** The first safety car in a Grand Prix was at Canada in 1973. It famously picked
> up the wrong car, so nobody could tell who was leading for several laps. The virtual safety car (VSC) was introduced in 2015 after the fatal
> Suzuka accident of Jules Bianchi in 2014, freezing the gaps between cars electronically under a set speed limit. Both are things the
> neutralised-lap detector in chapter 12 finds by looking for laps when the whole field slows down together.

---

## 25. Troubleshooting, in depth

**The backend starts but every race request hangs.** The first request for an uncached race downloads it. Watch the terminal for FastF1's
"Loading data for ..." lines. If it never progresses, F1's archive may be unreachable or refusing that season.

**`KeyError: 'DriverNumber'` inside FastF1.** The archive returned an empty or refused response for that session (403 for 2022, or a session not yet published).
Check with `curl -I https://livetiming.formula1.com/static/<year>/Index.json`.

**A chart image is wrong after I changed the code.** Bump `ANALYTICS_VERSION` (charts) or `INSIGHTS_VERSION` (insights), or delete the file under `cache/processed/`.
Both also rebuild automatically when the race's pickle is newer than the derived file.

**The insights or search results look stale.** The search index rebuilds when the *set of cached races* changes, not when their insights are recomputed. Restart the backend.

**Windows: `pip` says access denied.** You are installing into a global location; use a virtual environment.

**Windows: the terminal shows garbled arrows or dashes.** The backend writes UTF-8; set `PYTHONIOENCODING=utf-8` for the process.

**"Address already in use".** Another Uvicorn is still running. On Windows find the owner with `netstat -ano | findstr :8000` and stop it in Task Manager, on macOS/Linux with `lsof -i :8000`.

**The trajectory map is blank after "Load lap".** Either the lap has no position data (older seasons sometimes lack it; all of 2026), or the circuit
outline could not be built. The panel's error line says which.

**Everything is slow only the first time.** That is the cache warming; run `scripts/cache_all_races.py` once.

---

## 26. Extending the project

| I want to... | Where to look |
|---|---|
| Add a new insight | Write a function `_my_insight(ctx)` in `insights.py` that returns `_ins(...)` or `None`, add it to the `INSIGHTS` list, bump `INSIGHTS_VERSION`, add a test |
| Add a chart | Write `chart_x(rd)` in `analytics.py` returning PNG bytes, register it in `CHARTS`, bump `ANALYTICS_VERSION` |
| Fix the pit-loss lookup | Use `get_race_meta(race_id)["circuit"]` instead of the race id inside `_pit_loss` (and expect every probability to shift) |
| Use per-driver pace in the simulation | Replace the constant 90.0 base with each driver's measured median pace from `RaceData`; this makes the model a forecast rather than a tyre model |
| Bring 2022 back | Remove it from `UNAVAILABLE_YEARS` in `calendar.py` once F1's archive serves it, delete `calendar_cache.json`, run the caching script |
| Add a season | Extend `SUPPORTED_YEARS`, delete the calendar cache, and check the championship route's year limits |
| Add a language-model answer to search | Send the top passages from `rag.search` to a model with an instruction to answer only from them; keep the extractive list beside it |
| Make it a public site | Add rate limits and authentication, change the hard-coded API addresses, move the simulation off the event loop, review the data terms |
| Add a frontend test | Vitest with React Testing Library; the components take plain props and are easy to test in isolation |

Conventions to keep: one module per capability, one router per module, a version number on every cache, a comment when a version is
bumped, and a label on every estimate.

---

## 27. Glossary

| Term | Meaning |
|---|---|
| **Apex** | The innermost point of a corner |
| **ASGI** | The Python standard for asynchronous web servers and applications |
| **BM25** | A keyword-ranking formula (chapter 14) |
| **Catmull-Rom spline** | A curve through given points with continuous tangent (chapter 15) |
| **Classified** | Counted as a finisher (completed at least 90 % of the race distance) |
| **Compound** | The rubber mixture of a tyre: soft, medium, hard, intermediate, wet |
| **Constructor** | A team, in championship terms |
| **DNF / DNS** | Did not finish / did not start |
| **DRS** | Drag Reduction System: a flap opened on straights to boost speed (2011 to 2025) |
| **Excursion** | A run of time when a car is farther from the reference line than the limit |
| **Fastest lap** | The quickest single lap of the race |
| **FastF1** | The Python library that reads F1 timing data |
| **Field delta** | A driver's lap time minus the field's median on the same lap |
| **Halo** | The titanium cockpit-protection bar (2018 onward) |
| **In-lap / out-lap** | The lap that ends in the pits / that starts from them |
| **Laps down** | How many laps behind the leader a car is |
| **Monte Carlo** | Estimating probabilities by random repeated simulation |
| **Neutralised lap** | A lap slowed for the whole field: safety car, virtual safety car or red flag |
| **Overcut** | Staying out longer than a rival so their fresh tyres do not pay off |
| **Pit loss** | The time lost by making a stop compared with staying out |
| **Podium** | The top three finishers |
| **Pole position** | The first place on the starting grid |
| **RAG** | Retrieval-augmented generation (only the retrieval half is used here) |
| **Reference line** | The fastest-lap path used as the yardstick for track limits |
| **Safety car / VSC** | A car that leads the field slowly / a speed limit imposed electronically |
| **Sprint** | A short Saturday race (about 100 km) on some weekends |
| **Stint** | The laps between two pit stops |
| **Stop-and-go, undercut** | See section 11.2 |
| **Track limits** | The white lines that mark the edges of the track |
| **Undercut** | Stopping earlier than a rival so fresh-tyre pace gets you ahead |
| **Vectorised** | Done on whole arrays at once instead of in a Python loop |

---

## 28. Season-by-season trivia index

Every season the app covers, with the chapter where its trivia box appears and the number of races in the catalogue.

| Season | Races | Trivia | Chapter |
|---|---|---|---|
| 2018 | 21 | The Halo arrives; Leclerc debuts; Hamilton's fifth title. And the Baku safety car | 1 and 12 |
| 2019 | 21 | Fastest-lap point; Kubica's return; Leclerc's lost Bahrain win | 3 and 9 |
| 2020 | 17 | The pandemic calendar; Perez, Gasly and Hamilton's seventh title | 4 and 14 |
| 2021 | 22 (21 analysable) | The three-lap Belgian race; the Abu Dhabi finale; sprints; Saudi Arabia | 5 and 6 |
| 2022 | (excluded) | Ground-effect cars, Verstappen's 15 wins, and the archive that says no | 7 |
| 2023 | 22 | Verstappen's dominance; Las Vegas returns | 8 |
| 2024 | 24 | McLaren's title; Norris, Sainz, Bearman and Leclerc's home win | 10 |
| 2025 | 24 | The rookie wave; Hamilton at Ferrari | 13 |
| 2026 | 23 listed (14 run when cached) | The biggest rules change since 2014 | 18 |

General trivia: the first World Championship race (chapter 1), how points have changed (16), tyre colours (16), the fastest pit stop (11),
circuits with a twist (15), team colours (17), the volume of F1 data (20) and why the safety car exists (24).

---

*End of the technical guide. The code is the final authority: where this document and the source disagree, trust the source, and please
fix the document.*
