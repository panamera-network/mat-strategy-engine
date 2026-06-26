# strategy-issues.md — core/strategy/ findings (parked, not in CLAUDE.md)

Reviewed 2026-06-21, all known issues fixed 2026-06-23. Kept separate from
CLAUDE.md because Farez is considering a different architecture — engine
running basic modules first, with MAT.ai calling "strategy" logic on top.
The base engine (`core/Output/`) is confirmed solid (live-verified
2026-06-23) and `core/strategy/` is now a clean, bug-free plugin system —
both are ready whichever way that architecture decision lands.

## Plugin architecture (2026-06-23)
`StrategyEngine.py` auto-discovers strategies instead of a hardcoded dict —
drop a `.py` file in `core/strategy/` defining a class that inherits
`Strategy` (from `strategy_models.py`) and it loads automatically, no edits
to `StrategyEngine.py` needed. `evaluate()` now wraps each strategy's
`.react()` call in try/except — one strategy throwing logs and is skipped,
the rest still run. A `/core/strategies` (GET) + `/core/strategies/{name}`
(PATCH) API pair lets a frontend list and toggle strategies on/off
(in-memory only — resets on restart).

`test_payload.py` moved to `scripts/test_strategy_payload.py` — it `POST`s
to a local server at module import time, which would have fired
automatically every time the auto-discovery loader scanned the package.

## Connected to `/core/output` + chart-ready price (2026-06-23)
`core/Output/Output.py` now calls `StrategyEngine.evaluate()` for every
timeframe of every symbol and attaches the results as
`display_block["strategy_signals"]` — so `/core/output` (the main dashboard
feed) carries strategy signals alongside bias/scalping/swing in one response,
not just the separate `/core/evaluate` endpoint. It builds its own
`StrategySnapshot` context directly from `structure_engine.get_snapshot()`
per timeframe (independent of the already-transformed scalping/swing display
snapshots, which no longer carry raw structure fields) — this means an extra
`structure_engine.get_snapshot()` call per timeframe per symbol on top of
what `get_style_snapshot()` already does internally. Live-verified working,
no crash, but **not yet measured for perf impact** at full 36-symbol scale —
worth profiling if `/core/output` response time becomes a problem.

Every strategy's signal dict now includes a `"price"` field
(`price_from_snapshot()` in `strategy_models.py`) — prefers `context_level`
(zone/level price), falls back to the midpoint of `current_high`/
`current_low`. This is what a frontend needs to place a marker/zone on the
correct y-axis price when drawing signals on a chart; `timestamp` alone only
gave the x-axis position.

**Found and fixed a split-brain singleton bug while wiring this in** — same
class of bug as the old `SnapshotCache` issue. `api/core_router.py` and
`core/Output/Output.py` were each instantiating their own `StrategyEngine()`,
so a strategy toggled off via `/core/strategies` (which mutated
`core_router.py`'s instance) would have had zero effect on `/core/output`'s
separate instance. Fixed: `core/strategy/StrategyEngine.py` now exports a
shared `strategy_engine` singleton; both callers import it instead of
instantiating their own. Verified live — toggling a strategy off is now
visible from both entry points using the same instance.

## Bug fixes (2026-06-23)
- **`StrategySnapshot` (`strategy_models.py`) was missing `current_high` /
  `current_low`** — added as `Optional[float] = None`, and
  `to_strategy_snapshot()` in `StrategyEngine.py` now carries them over from
  `StructureSnapshot`. This was the confirmed crash bug in
  `GroupedLastCandleBiasStrategy.py` (`AttributeError` on the range-check
  branch). Verified fixed — full crash path (range > 50, valid filter) now
  runs clean.
- **`GroupedLastCandleBiasStrategy.py` rewritten**: added the missing `"H4"`
  entry to `shift_tf_map`/`filter_tf_map`, made `group_b` actually compute
  its own bull/bear counts on `["W1","D1","H4"]` instead of silently reusing
  group A's counts, added a bearish mirror (`bearish_count >= 3` → short,
  Group B bearish variant), and switched `"M"` → `"MN1"` to match
  `mt5/constants.py`. Range-check guard now skips cleanly when
  `current_high`/`current_low` are `None` instead of crashing.
- **`LastCandleBiasStrategy.py`**: `"M"` → `"MN1"`, added the missing
  `"timestamp"` key to the returned signal dict (was already symmetric
  long/short, no mirror needed).
- **`ScalpingBiasCascade.py` rewritten**: added the bullish mirror (bearish
  alignment across M15/M30/H1 + M1 bullish CHOCH flip → long), removed the
  dead `swing_tfs` var, replaced all `print()` debug statements with
  `logger.debug(...)`.
- **`DoubleEngulfingStrategy.py` rewritten**: confidence now `min(..., 1.0)`
  capped, added the bearish mirror for every bullish scenario (double-bear
  engulf, two delayed-bear-confirm variants, bullish reversal mirroring the
  existing bearish reversal).
- **`ZoneContinuationStrategy.py`** — confirmed still clean, untouched.

All fixes verified by direct `StrategyEngine.evaluate()` calls (bullish +
bearish paths per strategy, the original crash path, and a deliberately
exploding fake strategy to confirm isolation) — no automated test suite
exists yet, see CLAUDE.md's `/tests` plan item.
