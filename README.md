# mat-strategy-engine

The calculation engine behind **MAT.ai**. Connects to MetaTrader 5, runs
multi-timeframe bias/momentum/structure analysis per symbol, evaluates a
plugin-based strategy layer on top, and serves the result as structured JSON
for the dashboard to consume.

This repo is one of three apps in the MAT.ai ecosystem:

| App | Role |
|---|---|
| **engine** *(this repo)* | MT5 calculation + strategy evaluation → JSON |
| **dashboard** | Viewer/UI — consumes this engine's JSON, draws charts |
| **agent** | Reasons directly off the JSON this engine produces |

## How it fits together

```
MT5 terminal
   │
   ▼
core/ engines (Bias, Momentum, Structure, Strength, Shift, Demand, Suppression)
   │
   ├──► core/Output/  → per-symbol JSON: bias + scalping + swing + health
   │
   └──► core/strategy/ → plugin strategies evaluate every timeframe,
                          signals attached to the same JSON block
   │
   ▼
api/core_router.py  (mounted at /core)
   │
   ▼
dashboard
```

## Strategy plugins

Strategies are auto-discovered — drop a `.py` file in `core/strategy/`
defining a class that inherits `Strategy` (from `strategy_models.py`) and
it loads automatically. No registration, no editing `StrategyEngine.py`.

- Each strategy's signal includes a `price` (for placing a marker on a
  chart) and a `timestamp` — both needed by the dashboard to draw it.
- Strategies can be toggled on/off at runtime via:
  - `GET /core/strategies` — list every loaded strategy + its on/off state
  - `PATCH /core/strategies/{name}` — `{"enabled": true|false}`
  - State is in-memory (resets on restart) and shared across the whole app.
- One strategy throwing an error is isolated — it's logged and skipped, the
  rest of the evaluation still runs.

## Key API routes

| Route | Purpose |
|---|---|
| `GET /core/output` | Main feed — bias/scalping/swing/health + strategy signals, per symbol |
| `GET /core/strategies` | List strategy plugins + enabled state |
| `PATCH /core/strategies/{name}` | Toggle a strategy on/off |
| `POST /core/evaluate` | Run strategies against a manually supplied snapshot/context |
| `GET /api/mt5/*` | MT5 connection diagnostics, symbol resolution, candle status |
| `GET /api/system-status` | CPU/RAM/MT5 health check |

## Project structure

```
main.py              → FastAPI entrypoint, mounts all routers
api/core_router.py   → /core routes — the live route layer over core/
core/                → engine logic (Bias, Momentum, Structure, Strength, ...)
  Output/            → assembles the final per-symbol JSON
  strategy/          → plugin strategies + StrategyEngine
mt5/                 → MT5 connection, symbol resolution, candle fetching
routes/              → /api routes (system status, MT5 status/diagnostics)
scripts/             → manual debug scripts (not automated tests)
archive/             → retired code, kept for reference
```

See [CLAUDE.md](CLAUDE.md) for the full repo map, known issues, and
architecture notes.

## Getting started

1. Clone and enter the repo:
   ```bash
   git clone https://github.com/panamera-network/mat-strategy-engine.git
   cd mat-strategy-engine
   ```

2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate      # Windows
   source .venv/bin/activate   # Mac/Linux
   ```

3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

4. Make sure the MT5 terminal is running and logged into an account, then
   start the server:
   ```bash
   uvicorn main:app --reload
   ```

5. Check it's alive:
   ```bash
   curl http://127.0.0.1:8000/core/output
   ```

## Notes

- No automated test suite exists yet — changes are sanity-checked by running
  the app against a live MT5 terminal and hitting `/core/output` directly.
  See `scripts/` for manual debug scripts.
- `requirements.txt` is currently unpinned by design (revisit before
  production deploy).
