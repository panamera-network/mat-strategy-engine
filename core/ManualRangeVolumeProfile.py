"""Fix #7Z — Manual Range Volume Profile: the third Volume Profile range
source, built entirely on Fix #7X's committed foundation
(build_volume_profile(): candle_approximation, 24 instrument-aware bins,
70% value area, POC/VAH/VAL) and Fix #7Y's build_profile_marking() -- no
second Volume Profile calculation anywhere in this module.

ARCHITECTURE AUDIT (performed before writing anything below):
  - The live per-cycle pipeline (StructureEngine.get_snapshot() ->
    StrategyEngine.evaluate(), driven by Output.py once per (symbol, tf)
    every request/websocket tick) has no concept of a user-selected
    range anywhere, and must not gain one: Fix #7X's previous-week range
    and Fix #7Y's Balance Range are both auto-detected EVERY cycle by
    design, but a Manual Range is, by definition, not derivable from
    "now" -- it only exists once a person picks two points on a chart.
  - `api/core_router.py` already exposes `GET /core/history/{symbol}/
    {timeframe}` (returns OHLCV with each candle's own epoch `time`) --
    this is the SAME endpoint a dashboard/TradingView-style UI would
    already use to render a chart before letting a user drag a range, so
    a request built on this module can validly reuse those exact epoch
    values as start/end without inventing a new timestamp format.
  - CONCLUSION: Manual Range Volume Profile is exposed as its own,
    explicitly-triggered function (this module) and its own dedicated API
    route (POST /core/volume-profile/manual, api/core_router.py) --
    NEVER as a `Strategy` subclass (StrategyEngine._discover_strategies()
    auto-loads every Strategy subclass file under core/strategy/ and
    evaluates it every cycle; a Manual Range function deliberately lives
    OUTSIDE that package and is never a Strategy, so it can never be
    auto-discovered or auto-evaluated). No wiring into StructureSnapshot/
    StrategySnapshot/Output.py at all -- "user range -> engine -> profile
    result" is a standalone call, not a per-cycle evidence field.

DATA RETRIEVAL AUDIT / EXACT BEHAVIOR (reported before commit):
  - Timestamp-addressed request: fetched via the NEW `mt5.copy_rates_
    range()` path (mt5/fetcher.py:fetch_candles_range(), core/
    CandleEngine.py:get_snapshots_by_range()) -- MT5 itself bounds the
    fetch to exactly [start_timestamp, end_timestamp], never a count-based
    over-fetch, never routed through the shared per-request CandleCache
    (that cache doesn't have a date-range concept). This is a genuinely
    NEW kind of MT5 call this codebase didn't have before -- justified
    because "fetch only requested symbol/timeframe/range" cannot be done
    with the existing count-based fetch at all.
  - Index-addressed request — STABLE MANUAL RANGE IDENTITY FOLLOW-UP
    AUDIT (before this fix's first commit): the original v1 design fetched
    index-addressed ranges via `CandleEngine.get_snapshots(symbol, tf,
    count=N)`, which always returns the LAST N candles ending at "now"
    (MT5's own `copy_rates_from_pos(pos=0, count=N)` semantics) -- this
    made `end_index` silently mean "whatever candle is most recent at the
    exact instant of this call", drifting to DIFFERENT real candles on
    every repeated request as time passes and new candles close. That
    violates "manual means user-selected, preserve exactly" for the index
    path specifically, and is exactly the failure mode this follow-up
    fixes: a naked (start_index, end_index) request is NO LONGER accepted
    at all (rejected explicitly, see below). Index-addressing now
    REQUIRES a `reference_end_timestamp` -- the stable anchor "this
    index window ends at/before this exact moment", live-verified via
    `mt5.copy_rates_from(symbol, tf, anchor, count)`
    (mt5/fetcher.py:fetch_candles_from_anchor(), core/CandleEngine.py:
    get_snapshots_from_anchor()): unlike `copy_rates_from_pos`, this
    fetches `count` candles ending at/before the FIXED `anchor` datetime,
    never "now" -- confirmed live that the same (anchor, count) always
    returns the same candles regardless of when the call is made or how
    many newer candles have since closed. N is
    `max(end_index + 1, DEFAULT_INDEX_REFERENCE_COUNT)` --
    DEFAULT_INDEX_REFERENCE_COUNT matches `GET /core/history`'s own
    default `count` (200) purely so a caller reusing indices from that
    endpoint's response (with that SAME response's own latest candle
    timestamp as `reference_end_timestamp`) gets an identical window.
    This is now a genuinely STABLE, provable guarantee, not a weaker one
    -- see this module's own test suite for the before/after-a-new-candle
    proof.
  - CACHING: a manual range's own candles never change once every candle
    in it has closed -- both the timestamp path and the (now
    anchor-stabilized) index path are cached identically: a simple,
    indefinite, in-PROCESS memo dict keyed by the exact request
    parameters (symbol, timeframe, and either the timestamp pair or the
    (reference_end_timestamp, start_index, end_index) triple). Repeat
    requests for the exact same range never re-fetch or re-hit MT5. This
    is NOT a persistent/cross-restart cache and NOT shared with the
    per-request CandleCache -- a deliberately minimal implementation, not
    a new caching subsystem. A caller must never cache a NAKED index
    request indefinitely (there is no such thing here any more -- the
    function itself rejects one outright).

RANGE SEMANTICS: the fetched candle set is used exactly as returned/
sliced -- no expansion, no snapping to a swing/S&R/session boundary, no
Balance-Range or previous-week adjustment of any kind. Inclusivity is
explicit and tested: BOTH the candle at start and the candle at end are
included (`candles[start_index:end_index + 1]` for the index path;
MT5's own `copy_rates_range()` semantics — inclusive of both endpoints —
for the timestamp path); the very next candle beyond either boundary is
excluded.

DESCRIPTIVE EVIDENCE (v1 interpretation only, never a trade signal): this
module optionally reports where the range's OWN LAST candle closed
relative to the built value area (`price_vs_value_area`: "above"/
"below"/"inside") and which of POC/VAH/VAL that close is nearest to
(`nearest_level`). This deliberately uses the RANGE'S OWN closing price,
not a separate "live now" price lookup -- computing this from a fresh,
separate current-price fetch would make the result non-deterministic and
harder to cache, and would blur "what happened in the range I selected"
with "what is the market doing right now" (a materially different
question, out of scope for v1). No buy/sell signal is generated here or
implied by these fields -- a separate, explicit consumer (Manual Range
VAH/VAL Reaction, Manual POC Reclaim, Manual Profile Breakout, or a
reasoning/MAT-interpretation layer) would have to consume this result
deliberately to produce one; none of those are part of this fix."""
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from core.CandleEngine import CandleEngine
from core.core_models import CandleSnapshot
from core.VolumeProfileEngine import build_profile_marking, build_volume_profile

# Fix #7Z — see this module's own docstring for the full caching-behavior
# audit. Keyed by (mode, symbol, timeframe, start, end); never expires
# within a process lifetime (a manual range's own historical candles
# never change once closed).
_manual_range_cache: Dict[tuple, Dict] = {}

# Fix #7Z — matches GET /core/history/{symbol}/{timeframe}'s own default
# `count` (api/core_router.py), so an index-addressed request's indices
# align with that same endpoint's response when `reference_end_timestamp`
# is that same response's own latest candle timestamp -- see this
# module's own docstring (DATA RETRIEVAL AUDIT) for the full rationale.
DEFAULT_INDEX_REFERENCE_COUNT = 200


def _no_result(error: str) -> Dict:
    return {
        "confirmed": False, "error": error,
        "range_type": "manual_range", "symbol": None, "timeframe": None,
        "start_timestamp": None, "end_timestamp": None,
        "start_index": None, "end_index": None,
        "range_high": None, "range_low": None,
        "poc": None, "vah": None, "val": None,
        "total_volume": None, "value_area_pct": None, "num_bins": None,
        "source_type": None, "price_vs_value_area": None, "nearest_level": None,
    }


def _resolve_candles_by_timestamp(candle_engine: CandleEngine, symbol: str, timeframe: str, start_timestamp: int, end_timestamp: int) -> List[CandleSnapshot]:
    date_from = datetime.utcfromtimestamp(int(start_timestamp))
    date_to = datetime.utcfromtimestamp(int(end_timestamp))
    return candle_engine.get_snapshots_by_range(symbol, timeframe, date_from, date_to)


def _resolve_candles_by_index(candle_engine: CandleEngine, symbol: str, timeframe: str, reference_end_timestamp: int, start_index: int, end_index: int) -> Optional[List[CandleSnapshot]]:
    fetch_count = max(end_index + 1, DEFAULT_INDEX_REFERENCE_COUNT)
    anchor = datetime.utcfromtimestamp(int(reference_end_timestamp))
    all_candles = candle_engine.get_snapshots_from_anchor(symbol, timeframe, anchor, fetch_count)
    if len(all_candles) <= end_index:
        return None
    return all_candles[start_index:end_index + 1]


def build_manual_range_profile(
    candle_engine: CandleEngine,
    symbol: str,
    timeframe: str,
    start_timestamp: Optional[int] = None,
    end_timestamp: Optional[int] = None,
    start_index: Optional[int] = None,
    end_index: Optional[int] = None,
    reference_end_timestamp: Optional[int] = None,
) -> Dict:
    """Fix #7Z — the single entry point for a Manual Range Volume Profile
    request. Timestamps are the CANONICAL identity for a manual range --
    prefer (start_timestamp, end_timestamp) whenever possible. An index-
    addressed request, (start_index, end_index), is also accepted but
    ONLY together with `reference_end_timestamp` -- the stable anchor
    that makes the indices provably resolve to the same candles on every
    call (see this module's own docstring, STABLE MANUAL RANGE IDENTITY
    FOLLOW-UP AUDIT). A NAKED index request (no reference_end_timestamp)
    is rejected outright -- its meaning would silently drift as new
    candles close, which this fix's own audit found and fixed.

    Preserves the user's selection exactly: no automatic Balance-Range
    expansion, previous-week adjustment, S&R/swing/session snapping. The
    resulting candle set is fed directly into Fix #7X's own unchanged
    build_volume_profile() -- no second Volume Profile implementation.

    Returns a dict with confirmed=False and a human-readable `error` for:
    start > end, an empty/unreachable range, a naked index request, or a
    symbol/timeframe MT5 can't resolve any candles for at all. On
    success, confirmed=True and every field of the PROFILE OUTPUT
    CONTRACT (range_type="manual_range", symbol, timeframe, start/end
    timestamp+index, range high/low, POC, VAH, VAL, total_volume ["total
    activity" -- never real traded volume, same source_type=
    "candle_approximation" audit as Fix #7X/#7Y], value_area_pct,
    num_bins, source_type) plus the v1 descriptive evidence
    (price_vs_value_area, nearest_level) -- never a trade signal."""
    by_timestamp = start_timestamp is not None and end_timestamp is not None
    by_index = start_index is not None and end_index is not None

    if by_timestamp and by_index:
        return _no_result("supply exactly one of (start_timestamp, end_timestamp) or (start_index, end_index), not both")
    if not by_timestamp and not by_index:
        return _no_result("must supply either (start_timestamp, end_timestamp) or (start_index, end_index)")
    if by_index and reference_end_timestamp is None:
        return _no_result(
            "index-addressed requests require reference_end_timestamp (a stable anchor) -- "
            "a naked (start_index, end_index) request is not accepted because its meaning "
            "would drift as new candles close; prefer (start_timestamp, end_timestamp) instead"
        )

    if by_timestamp:
        if start_timestamp > end_timestamp:
            return _no_result("start_timestamp > end_timestamp")
        cache_key = ("ts", symbol, timeframe, int(start_timestamp), int(end_timestamp))
        if cache_key in _manual_range_cache:
            return _manual_range_cache[cache_key]
        candles = _resolve_candles_by_timestamp(candle_engine, symbol, timeframe, start_timestamp, end_timestamp)
    else:
        if start_index > end_index:
            return _no_result("start_index > end_index")
        if start_index < 0 or end_index < 0:
            return _no_result("indices must be non-negative")
        cache_key = ("idx", symbol, timeframe, int(reference_end_timestamp), int(start_index), int(end_index))
        if cache_key in _manual_range_cache:
            return _manual_range_cache[cache_key]
        candles = _resolve_candles_by_index(candle_engine, symbol, timeframe, reference_end_timestamp, start_index, end_index)
        if candles is None:
            return _no_result("requested index range exceeds available history for this symbol/timeframe")

    if not candles:
        return _no_result("no candles found for the requested range (empty range, or an unresolvable symbol/timeframe)")

    profile = build_volume_profile(candles, symbol=symbol, timeframe=timeframe)
    if profile is None:
        return _no_result("profile could not be built from an empty candle set")

    last_close = candles[-1].close
    if last_close > profile.value_area_high:
        price_vs_value_area = "above"
    elif last_close < profile.value_area_low:
        price_vs_value_area = "below"
    else:
        price_vs_value_area = "inside"

    distances = {
        "POC": abs(last_close - profile.poc_price),
        "VAH": abs(last_close - profile.value_area_high),
        "VAL": abs(last_close - profile.value_area_low),
    }
    nearest_level = min(distances, key=distances.get)

    result = {
        "confirmed": True, "error": None,
        "range_type": "manual_range",
        "symbol": symbol,
        "timeframe": timeframe,
        "start_timestamp": str(candles[0].timestamp),
        "end_timestamp": str(candles[-1].timestamp),
        "start_index": start_index if by_index else None,
        "end_index": end_index if by_index else None,
        "range_high": max(c.high for c in candles),
        "range_low": min(c.low for c in candles),
        "poc": profile.poc_price,
        "vah": profile.value_area_high,
        "val": profile.value_area_low,
        "total_volume": profile.total_volume,
        "value_area_pct": profile.value_area_pct,
        "num_bins": profile.num_bins,
        "source_type": profile.source_type,
        "price_vs_value_area": price_vs_value_area,
        "nearest_level": nearest_level,
    }
    _manual_range_cache[cache_key] = result
    return result


def build_manual_range_marking(result: Dict) -> Optional[Dict]:
    """Fix #7Z — builds the shared `profile` chart marking (Fix #7Y's
    build_profile_marking(), reused unchanged -- no second marking
    builder) for an already-built manual range result. Contains exactly
    the user-selected geometry (start/end, range high/low, POC, VAH,
    VAL) -- no reconstructed or auto-expanded geometry. This is the
    marking a later UI/TradingView integration renders when a user drags
    a range. Returns None if `result` is not a confirmed profile."""
    if not result.get("confirmed"):
        return None
    return build_profile_marking(
        strategy="ManualRangeVolumeProfile",
        timeframe=result["timeframe"],
        label="Manual Range Volume Profile",
        poc=result["poc"], vah=result["vah"], val=result["val"],
        source_type=result["source_type"],
        total_volume=result["total_volume"],
        value_area_pct=result["value_area_pct"],
        range_type="manual_range",
        range_high=result["range_high"], range_low=result["range_low"],
        range_start_timestamp=result["start_timestamp"], range_end_timestamp=result["end_timestamp"],
        start_index=result["start_index"], end_index=result["end_index"],
    )
