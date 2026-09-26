# SAK RACING SIM

A full-stack, real-time Formula 1 Race & Strategy Simulator.

## Features

- **Historical Replay** — 174 races from 2018–2026 streamed lap-by-lap at 2x/5x/10x speed (2022 is excluded: F1's timing archive refuses it)
- **Win Probability** — Monte Carlo simulation (1000 runs) updating each lap
- **Strategy Simulator** — counterfactual "what-if" pit stop analysis mid-race
- **Leaderboard** — all 20 drivers, positions, tyre compounds, pit counts, gaps
- **Insights** — ~45 named analyses per race (pace, consistency, strategy, tyres, race flow) plus season roll-ups, computed from lap timing
- **Ask the season** — local keyword retrieval (BM25) over those statistics, per season or across all; extractive, no LLM or API key
- **Trajectory & track limits** — every driver's lap as a smooth 60 Hz path on a zoomable circuit map, with estimated off-track excursions
- **Persistent Cache** — race data saved after first load for instant repeat access

## Stack

- **Backend**: Python 3.11, FastAPI, Uvicorn, WebSockets, FastF1, NumPy, Pandas
- **Frontend**: React 18, Vite, Tailwind CSS, Recharts, Lucide icons
- **Data**: FastF1 (historical)

## Setup

### Backend

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

### Optional: cache every race

```bash
cd backend
python scripts/cache_all_races.py
```

Downloads and caches every past race (about 20 minutes, ~2 GB) so replay and analytics load instantly offline.

Open http://localhost:5173

## API

- `GET /api/races` — list all available races
- `WS /ws/race/{race_id}?speed=2` — replay stream
- `POST /api/simulate/counterfactual` — strategy simulation
- `GET /api/races/{race_id}/insights` — the per-race analyses
- `GET /api/seasons/{year}/insights` — season roll-ups over cached races
- `GET /api/rag/search?q=...&year=` — search the insight passages
- `GET /api/rag/coverage` — how many races per season are searchable

## License

Licensed under the [Apache License, Version 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.
