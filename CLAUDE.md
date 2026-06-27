# CLAUDE.md — mat-strategy-engine

This file gives Claude (and future-you) context on this repo before making changes.

## Project Overview

`mat-strategy-engine` is the Python/FastAPI backend that powers MAT.ai's trading
analysis. It connects to MT5, runs multi-timeframe bias/momentum/structure
calculations per symbol, and outputs structured JSON consumed by the dashboard
and by MAT.ai's reasoning layer.

This repo is one of three separate apps in the MAT.ai ecosystem:
- **engine** (this repo) — calculation + JSON output
- **dashboard** — pure viewer, no logic
- **agent** — reasons directly off the JSON this repo produces

## Repo Structure

```
main.py                → FastAPI entrypoint. Mounts 3 routers:
                          - routes/system_status.py  → prefix /api
                          - routes/mt5_status.py      → prefix /api
                          - api/core_router.py        → prefix /core
api/core_router.py     → LIVE route layer. All endpoints call into core/.
core/                  → LIVE engine logic (active, in development)
  BiasEngine.py, CandleEngine.py, MomentumEngine.py, ShiftEngine.py,
  StrengthEngine.py, StructureEngine.py, StyleEngine.py,
  SuppressionEngine.py, TrendEngine.py, demand_engine.py,
  OrderBlockEngine.py, FVGEngine.py, structure_utils.py,
  core_models.py, strategy_snapshot.py, SnapshotCache.py
  strategy/             → StrategyEngine.py + individual strategy modules
  Output/                → output assembly layer (current focus, see below)
mt5/                    → MT5 connector + symbol/constants layer
routes/                 → system_status, mt5_status
data/, tests/
```


## core/Output/ — Current Focus

This is the assembly layer that turns raw engine output into the final
per-symbol JSON block (bias + scalping + swing + health + signal_health).

```
Output.py            (230 lines) → orchestrator: build_multi_symbol_output()
alignment_signal.py  (172 lines) → compute_alignment_signal, compute_signal_health
build_scalping.py    (203 lines) → build_scalping_diagnostic()
swing_diag.py        (147 lines) → enrich_swing_with_diagnostic()
diagnostic_models.py (186 lines) → ScalpCfg and related models
health_log.py         (65 lines) → build_symbol_health()
helper.py            (152 lines) → display % formatting, color mapping, strip_nulls
test.py               (45 lines) → manual debug script (not automated), run directly with live MT5
```

### Data flow
1. `build_multi_symbol_output()` loops every symbol in `SYMBOLS`.
2. Pulls `bias_map` from `bias_engine`, builds scalping + swing snapshot maps
   via `get_style_snapshot()`.
3. Computes alignment signal + confidence history per style.
4. Runs diagnostics (`build_scalping_diagnostic`, `enrich_swing_with_diagnostic`).
5. Assembles `symbol_block` (bias/scalping/swing), strips nulls, adds display
   percentages, attaches health + signal_health.
6. Caches the snapshot in `SnapshotCache` for next-run comparisons.

## Known Bugs / Issues

These were found during a code review on 2026-06-21. All items below have
been resolved — see "Plan for Fixing" for remaining outstanding work.

## Live Verification (2026-06-23)

No automated test suite exists for this repo (see `/tests` below) — instead,
changes are sanity-checked by actually running `uvicorn main:app` against a
live MT5 terminal and hitting `/core/output`. This caught three real bugs that
static review missed:

1. `fastapi_cache`, `GPUtil`, `psutil` were imported in `main.py` /
   `routes/system_status.py` but never pinned in `requirements.txt` — app
   wouldn't boot on a fresh install. Fixed: installed + pinned.
2. Windows console (`cp1252`) can't encode the unicode arrows/emoji
   (`→ ✅ ❌ ⚠️`) used throughout `core/log.py` and elsewhere — every
   `print()`/logging call with those characters crashed the request. Fixed:
   `sys.stdout`/`sys.stderr` reconfigured to UTF-8 at the top of `main.py`.
3. **Real logic bug, exposed by the `SnapshotCache` singleton fix above.**
   `build_scalping.py` and `swing_diag.py` read `prev_bias_map[tf]["label"]`
   / `["strength"]`, but `bias_map[tf]` actually stores `"bias_label"` and a
   `"strength_diagnostic"` object — wrong keys entirely. Before the singleton
   fix, `prev` was always `None` so this code path never ran; once `prev` is
   real, every symbol crashed on the second request. Fixed both files to read
   the correct keys.

Known remaining gap (deprioritized, not fixed): `XBRUSD_i` (Brent) fails with
`'NoneType' object has no attribute 'structure_type'` — `StructureEngine.get_snapshot()`
returns `None` when there are under 3 candle snapshots for a symbol/TF, and
nothing downstream guards against that `None`. Symbol-specific data
availability issue, not a logic bug. Confirmed not worth fixing right now.

## Swing-based SMC engine (2026-06-27)

`core/StructureEngine.py` was rewritten from single-candle HH/HL/LH/LL
comparison to proper swing-based BOS/CHoCH detection:

- **`core/structure_utils.py`** (new) — pure swing/structure functions with
  no dependency on other engines: `find_swings()` (20-candle lookback,
  3-candle-each-side confirmation), `detect_trend()`, `detect_structure_event()`
  (BOS = break with the trend, CHoCH = break against it — trend flip),
  `derive_snr_levels()` (HH → Resistance, LL → Support, CHoCH flips the
  nearest level's role), `detect_snd()`. Split out from `StructureEngine.py`
  specifically to avoid a circular import — `StructureEngine` pulls in
  `SuppressionEngine`, which pulls in `BiasEngine`, which now also needs the
  swing functions.
- **`core/BiasEngine.py`** — `evaluate_bias()` now checks for a confirmed
  BOS/CHoCH first (score ±8/±10, stronger signal for CHoCH since it's a
  trend flip) and only falls back to the old up-close/down-close ratio when
  there's no confirmed structure event.
- **`core/demand_engine.py`** rewritten — supply/demand zones are now ATR(14)
  based (`compute_atr()`, `detect_zones()`) instead of a fixed body-ratio
  comparison; a zone is `mitigated` once price closes back inside it.
  `DemandEngine.get_label()` (the live interface used by `StyleEngine.py`)
  is preserved; the previously-dead module-level `demand_engine` instance and
  `fetch_demand_label`/`get_demand` wrapper functions (confirmed unused
  anywhere in the repo) were dropped in the rewrite.
- **`core/OrderBlockEngine.py`** (new) — `detect_order_blocks()`: bullish OB
  = last bearish candle before a BOS Bullish, bearish OB = last bullish
  candle before a BOS Bearish; mitigated once price closes back inside it.
- **`core/FVGEngine.py`** (new) — `detect_fvg()`: 3-candle fair value gap
  detection, returns unmitigated gaps only.
- **`core/core_models.py`** — added `SNRLevel`, `OrderBlock`, `FVG`
  dataclasses; `StructureSnapshot` gained `snr_levels`, `order_blocks`, `fvg`
  fields.
- **`core/Output/Output.py`** — `_build_structure_context()` fetches one
  `StructureSnapshot` per timeframe (shared by strategy evaluation, SNR,
  order blocks, and FVGs — no duplicate fetches across those four). Added
  `snr_levels`, `order_blocks`, `fvg`, `supply_demand_zones` to every
  symbol's output block, all keyed by timeframe.

**Real bug fixed along the way**: `StructureEngine.get_snapshot()` called
`self.candle_engine.get_snapshots(self, symbol=symbol, ...)` — an extra,
wrong `self` positional argument. This *should* have crashed every call with
`TypeError: got multiple values for argument 'symbol'` (confirmed by testing
it directly) — but it silently "worked" because `api/core_router.py:30` was
separately instantiating `StructureEngine(CandleEngine)` with the **class**
instead of an instance, so `self.candle_engine` was the class itself; calling
its unbound method with the wrong `self` happened to not collide because
`get_snapshots()`'s body never reads `self`. Two independent bugs were
canceling each other out. Fixed both: removed the extra `self` arg, and
`core_router.py` now passes the actual `candle_engine` instance.

## Candle cache layer (2026-06-27)

The SMC engine work above made `/core/output` measurably slow (~56s for 36
symbols) because every feature — `BiasEngine`, `StructureEngine`,
`MomentumEngine`, `ShiftEngine`, `demand_engine` — independently called
`CandleEngine.get_snapshots()` per (symbol, timeframe), each one a real MT5
round-trip. Fixed with a request-scoped cache:

- **`core/candle_cache.py`** (new) — `CandleCache`: `fetch_all(symbols,
  timeframes, count)` batch-fetches every (symbol, tf) combo once;
  `get(symbol, tf, count)` reads from the store (slicing the trailing
  `count` candles) and never touches MT5 again for that pair within the
  same request. Falls back to a direct fetch (and caches it) if asked for a
  pair that wasn't pre-fetched. Thread-safe (a lock around the store dict).
- **`core/CandleEngine.py`** — `get_snapshots()` gained an optional `cache`
  param; if given, reads through the cache instead of calling `fetch_candles()`
  directly. Backward compatible — omitting `cache` behaves exactly as before.
- **Threaded `cache` through every engine that fetches candles**:
  `BiasEngine.get_bias()`/`get_bias_map()`, `StructureEngine.get_snapshot()`/
  `batch_snapshots()`, `MomentumEngine.get_momentum()`/`get_score()`,
  `ShiftEngine.detect_shift()`, `demand_engine.get_zones()`/`get_label()`,
  `StyleEngine.get_style_snapshot()`, and all of `Output.py`'s internal
  helpers — all the way up to `build_multi_symbol_output(..., cache=...)`.
- **`api/core_router.py`**: `/core/output` (both the GET route and the
  websocket loop) builds one `CandleCache`, calls `fetch_all(SYMBOLS,
  TIMEFRAMES, count=100)` once, then passes it through. Fresh cache per
  request/loop-iteration — not persistent.

**Result**: ~56s → ~15-16s for a full 36-symbol `/core/output` (verified
live, repeatedly, on a clean port — the original ~56-64s figures included
contamination from an unrelated process that's constantly polling
`localhost:8000` with `/ws`, `/queue`, `/health` requests having nothing to
do with this app; re-test on a different port to get a clean number if
profiling again).

**Did not reach the `<5s` target — investigated and explained, not just
guessed at**: with the cache, `_build_symbol_snapshot()`'s own compute time
across all 36 symbols is ~0.3s total. The remaining ~15s is irreducible MT5
round-trip cost for the 324 distinct (symbol, timeframe) pairs (36 × 9), at
roughly 45ms/call — this is now a *single* round-trip per pair per request
(down from many before caching), not redundant calls. Two follow-up attempts
to push further both made things worse or did nothing:
- Parallelizing the batch fetch with a thread pool made it ~3.5x *slower*
  (55s) — the MT5 Python API does not handle concurrent calls well, likely
  serializing internally.
- Reducing the fetched candle `count` (100 → 50 → 30) barely moved the
  total — the per-call cost is dominated by fixed IPC/symbol-switch
  overhead, not by how much data is requested.

Getting under 5s would need a different architecture: a background job
refreshing a longer-lived cache every N seconds, with `/core/output`
requests reading from that warm cache instead of triggering a fresh fetch
per request. Not implemented — bigger architectural change, deferred until
actually needed.

## Symbol-filtered `/core/output` (2026-06-27)

Added `POST /core/output` (alongside the existing `GET /core/output`, which
still always processes the full `SYMBOLS` list — unchanged, used by the
websocket and any caller that wants everything). The POST route accepts an
optional JSON body `{"symbols": ["XAUUSD_i", "EURUSD_i", ...]}`; if given, only
those symbols are processed — empty/omitted body falls back to all symbols,
same as GET.

`build_multi_symbol_output()` gained an optional `symbols` param (defaults to
the global `SYMBOLS` list when not given) — this is the only core change;
everything downstream (the `CandleCache` batch-fetch, per-symbol loop) already
worked off whatever list it's given.

This exists for `mat-engine-dashboard`'s symbol selector — fetching a
handful of symbols instead of all 36 is dramatically faster, since
`CandleCache.fetch_all()` only has to round-trip MT5 for the requested
symbols. **Verified live**: first request after server startup pays a ~30s
one-time MT5/symbol-resolution cold-start cost (not specific to this
feature — same cold start happens on any first request); subsequent
requests for 5 symbols took ~5s, vs ~15s for all 36.

## Other Folders — Status Check (reviewed 2026-06-21)

### `/tests` — broken, doesn't run
- `test_core.py` — imports `from candle import Candle` and `from strategy import
  compute_bias`. Neither module exists in this repo (real equivalents are
  `mt5/fetcher.py:Candle` and `core/strategy/...`). Fails on import.
- `test_patterns.py`, `test_plugins.py` — 0 bytes, empty placeholders.
  `test_plugins.py` is now stale-named since `/plugins` was deleted entirely
  (was just empty stubs, never wired into `core/`).
- There is effectively **no working test coverage** right now. Worth rebuilding
  from scratch against current module paths once core bugs above are fixed,
  rather than patching these.

### `/mt5` — mostly live and working, but has cruft
Live and confirmed in use: `fetcher.py`, `init.py`, `symbol_resolver.py`,
`mt5_diagnostics.py`, `constants.py`, `timeframes.py`.

`mt5/init.py` exports the canonical `ensure_mt5_ready()` — raises `RuntimeError`
if `mt5.initialize()` fails or if `mt5.account_info()` is `None` (terminal up
but no account connected). `fetcher.py`, `symbol_resolver.py`,
`mt5_diagnostics.py`, and `routes/mt5_status.py` all call through this one
function instead of each rolling their own `mt5.initialize()` check. The old
root-level `mt5_connector.py` (dead code) and the module-level
`mt5.initialize()` side effect that used to fire at import time in
`routes/mt5_status.py` are both gone.

`resolve_symbol()` and `resolve_symbols_batch()` in `symbol_resolver.py` now
both go through one shared `_best_match()` (`SequenceMatcher`-based) so single
and batch lookups can't disagree on the same symbol. Non-strict batch
resolution now also respects the same 0.6 cutoff as `resolve_symbol()`
(previously non-strict batch mode had no cutoff at all and would "resolve" to
the closest name regardless of how bad the match was).

`mt5/payload.py` was deleted — it imported `from bias.bias_map import
BiasRequest, refine_bias_map`, a package that never existed anywhere in this
repo, and had no live caller.

### `core/StrategyBuilder.py` — orphaned
Not imported anywhere. The live strategy logic that `api/core_router.py`
actually calls is `core/strategy/StrategyEngine.py`. Possibly an earlier
version of the same thing. Worth confirming with Farez whether this can be
archived/removed.

### Tooling
- **`requirements.txt` has zero version pins** — every dependency (`pandas`,
  `numpy`, `MetaTrader5`, `fastapi`, etc.) is unpinned. A fresh `pip install`
  could pull a breaking newer version of any of these with no warning.
  Worth pinning at least the ones most likely to break things (`MetaTrader5`,
  `fastapi`, `pandas`).

### Minor naming/navigation notes (not bugs)
- `core/strategy/test_payload.py` is a manual debug script (POSTs to a
  running local server via `requests`), not an automated test — lives in
  source code rather than `tests/`, worth moving if `/tests` gets rebuilt.
- `core/helper.py` (used by `SuppressionEngine.py`) and
  `core/Output/helper.py` are two unrelated files with the same name —
  easy to grab the wrong one when navigating/importing.

**Note on workflow:** once any of these issues are fixed, remove the
corresponding entry from this doc rather than marking it "done" — keep this
file reflecting only current/outstanding state.

## Plan for Fixing (proposed order)

1. Rebuild `/tests` from scratch against current module paths — current
   tests don't run at all.

## Conventions / Notes for Claude

- When fixing bugs above, fix one at a time with a focused diff — don't bundle
  unrelated cleanup into the same change.
- Farez prefers keeping legacy code for reference rather than deleting outright
  — default to moving retired code to the `/archive` folder rather than `rm`,
  unless explicitly told to delete. Deleted outright on 2026-06-23 (confirmed
  dead-with-no-salvageable-logic, by explicit request): `engine/`, `/plugins`,
  `/utils`, `mt5_connector.py`, `mt5/payload.py`, and the extensionless
  `api/noti`, `api/notifications_router`, `api/slack`, `core/webpush` (the
  latter four were unparseable scratch/draft code — multiple competing
  half-written implementations pasted into one file, calling helper functions
  that were never defined anywhere in the repo).
- This doc should stay current: once an item in "Known Bugs / Issues" or
  "Other Folders" is fixed, remove that entry rather than leaving it marked
  done — keep the doc reflecting only outstanding state, not a changelog.
