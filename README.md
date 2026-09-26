# SAK RACING SIM

A full-stack, real-time Formula 1 Race & Strategy Simulator.

## Features

- **Historical Replay** — 196 races from 2018–2026 streamed lap-by-lap at 2x/5x/10x speed
- **Win Probability** — Monte Carlo simulation (1000 runs) updating each lap
- **Strategy Simulator** — counterfactual "what-if" pit stop analysis mid-race
- **Leaderboard** — all 20 drivers, positions, tyre compounds, pit counts, gaps
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

Open http://localhost:5173

## API

- `GET /api/races` — list all available races
- `WS /ws/race/{race_id}?speed=2` — replay stream
- `POST /api/simulate/counterfactual` — strategy simulation

## License

Licensed under the [Apache License, Version 2.0](LICENSE). See [NOTICE](NOTICE) for attribution.
