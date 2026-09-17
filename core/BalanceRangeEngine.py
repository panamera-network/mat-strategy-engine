"""Fix #7Y — Balance Range detection (canonical range/naming alignment).

This module was originally written as "AccumulationRangeEngine" (its own
evidence audit already concluded nothing here can distinguish genuine
accumulation from distribution from generic sideways chop — see below).
It is renamed here to neutral, canonical terminology: a "Balance Range" is
just a bounded consolidation where price has stayed contained between two
levels — no claim about WHY price is contained, or what (if anything) is
happening inside it. This is the SAME calculation, SAME thresholds, SAME
behavior as before — naming only.

Downstream interpretation is a SEPARATE, later concern: Fix #7Y's own
Volume Profile strategy consumes this evidence and calls it a "Balance
Range Volume Profile" (still no accumulation/distribution claim — just a
profile built over a balance range). A future PO3 strategy may consume
this EXACT SAME range evidence and re-label it "PO3 Accumulation" — but
only once Manipulation and Distribution are independently proven; this
module itself will never make that call, and nothing about the detector
changes to support it. One canonical range detector, multiple honest
downstream interpretations.

BALANCE-RANGE EVIDENCE AUDIT (performed before writing anything below;
committed HEAD vs ambient WIP were checked separately for every term this
fix's own instruction asked about):

  - `core/TrendEngine.py` (committed) has a "Sideways" label inside
    `detect_trend(avg_bias, avg_strength)` — but this function, and both
    of its only callers (`core/bias_mode.py`, `core/strategy_snapshot.py`),
    are entirely ORPHANED: `grep`-confirmed, nothing else anywhere in this
    repo imports either of those two caller modules. This is dead code,
    the same class of leftover CLAUDE.md already documents for
    `core/StrategyBuilder.py` — not live evidence.
  - `core/structure_utils.py`'s OWN `detect_trend(candles, swing_highs,
    swing_lows)` (the one `StructureEngine` actually calls) only ever
    returns "Bullish"/"Bearish"/"Neutral" from a 2-swing HH/HL vs LH/LL
    comparison. "Neutral" means "no established 2-swing trend either
    way" — it is not a bounded range with a high/low, a duration, or any
    touch/containment history, and it says nothing about whether price
    has stayed inside a band.
  - No committed, LIVE code anywhere in this repo identifies consolidation
    / balance range / compression / repeated containment / session-phase
    evidence. `find_swings()`/`label_swing_points()` (committed, live)
    give confirmed swing highs/lows but never bundle them into a bounded,
    contained range object.
  - Nothing in this codebase — committed or ambient — carries any
    volume-based or order-flow evidence that could distinguish
    ACCUMULATION from DISTRIBUTION from generic sideways chop. All three
    look identical to every engine here: price staying inside a band.
    This module therefore exposes only a neutral "Balance Range" — a
    bounded consolidation suitable for Volume Profile analysis — and
    never claims accumulation, distribution, or any other directional
    intent. That naming discipline is the entire reason this module
    exists under this name.

TIMEFRAME CHOICE (reported before implementation, per this fix's own
instruction): detection runs on the CURRENT STRATEGY TIMEFRAME (the same
per-(symbol, tf) `candles` window StructureEngine.get_snapshot() already
fetches), NOT a fixed analysis timeframe like Fix #7X's previous-week M30.
Reason: "compression" is inherently scale-relative — what counts as a
tight range on M1 is meaningless noise on D1 — so a scalping strategy
evaluating M5 should see M5-scale consolidation, not a D1-scale one
imposed on it. This also means NO NEW MT5 FETCH is needed at all: the
already-fetched `candles` window (StructureEngine's own FETCH_COUNT) is
reused directly.

RANGE IDENTITY / STALE-RANGE DECISION (made explicitly, not silently):
detection always anchors at the CURRENT (most recent) candle and expands
BACKWARD — the same current-leg-identity principle this codebase already
established for breakout origins (structure_utils._find_current_leg_
origin(), Fix #7P/#7T/#7W). This means a range price has since cleanly
broken and left is NOT carried forward as stale "historical" evidence and
is NOT re-exposed separately — once price moves away, the backward
expansion from "now" simply finds whatever short recent window exists
today (almost always failing MIN_RANGE_DURATION for a genuine breakout,
since consecutive displacing candles blow the ATR-relative width bound
almost immediately). v1 deliberately does not keep a second "last known
range" state once the current one is no longer active — that is an
explicit scope decision, not an oversight.

TEMPORAL-INTEGRITY FOLLOW-UP AUDIT (before this fix's first commit): the
"CURRENT (most recent) candle" this function anchors at is never the
candle a Strategy will react to. StructureEngine.get_snapshot() passes
`candles[:-1]` (everything through N-1) into this function, holding back
the true current candle (N) entirely — so "the current candle" from this
function's own point of view is always N-1, one candle earlier than what
`current_high`/`current_low`/`current_close` on the same snapshot
describe. See detect_balance_range()'s own docstring for the full audit
that motivated this (a live check found including the reaction candle
itself could shift VAH by a real amount, and could even make detection
fail entirely for the exact rejection geometry a Strategy consuming this
evidence is meant to catch).

THRESHOLD AUDIT (live, before choosing values — not intuition): a probe
script ran this exact backward-expansion algorithm across all 36 symbols
x 9 timeframes (324 (symbol, tf) pairs with a valid ATR) using the same
already-fetched FETCH_COUNT-candle window StructureEngine uses. At a
generous 2.5x-ATR probe multiplier, resulting duration was consistent
across every timeframe (median ~6-8 candles from M1 through MN1 alike —
confirming ATR-relative width really does normalize duration across
scale) with width/ATR median 2.21. A grid of (multiplier, min_duration,
touch_tolerance_fraction) combinations was then evaluated for how
selective each was:
    multiplier=1.5 min_dur=5  tol=0.15 -> 8.6% of pairs qualify
    multiplier=1.5 min_dur=6  tol=0.20 -> 5.2% of pairs qualify  <- chosen
    multiplier=2.0 min_dur=5  tol=0.20 -> 24.1% of pairs qualify
    multiplier=2.0 min_dur=8  tol=0.25 -> 12.3% of pairs qualify
    multiplier=2.5 min_dur=6  tol=0.20 -> 25.9% of pairs qualify
The chosen combination (5.2% live qualification rate) matches this whole
strategy series' established "selective eligibility, not blanket firing"
convention — 20-26% (the looser multipliers) would call roughly a
quarter of ALL symbol/timeframe pairs at any instant a "range", too loose
to mean anything as compression; 1.5x ATR / 6-candle minimum / 2 touches
per side is the v1 selection. These values are UNCHANGED by this naming
rename.
"""
from typing import Dict, List

from core.core_models import CandleSnapshot
from core.demand_engine import compute_atr

# See this module's own docstring for the full live threshold audit (324
# (symbol, tf) pairs) that produced these exact values. Unchanged by this
# fix's naming rename.
COMPRESSION_ATR_MULTIPLIER = 1.5
MIN_RANGE_DURATION = 6
TOUCH_TOLERANCE_ATR_FRACTION = 0.20
MIN_TOUCHES_PER_SIDE = 2


def detect_balance_range(candles: List[CandleSnapshot], atr: float) -> Dict:
    """Pure, deterministic Balance Range detector (formerly named
    "detect_accumulation_candidate_range" — same calculation, same
    thresholds, renamed only; see this module's own docstring for why).

    Anchors at the CURRENT (most recent) candle and expands backward,
    growing [range_low, range_high] to include each earlier candle's own
    high/low, stopping the instant the cumulative width would exceed
    COMPRESSION_ATR_MULTIPLIER * atr (the SAME backward-scan-from-now
    shape this codebase already uses for current-leg identity — see this
    module's own docstring for why that also solves stale-range
    identity for free, with no separate check needed).

    Requires the resulting window to be at least MIN_RANGE_DURATION
    candles long (a genuine, meaningful consolidation, not 2-3 candles of
    noise), and requires at least MIN_TOUCHES_PER_SIDE candles whose own
    high/low come within TOUCH_TOLERANCE_ATR_FRACTION * atr of each
    boundary (repeated interaction with BOTH sides, not merely resting
    near one edge).

    `atr` must be the caller's own already-computed compute_atr() value
    over the SAME `candles` (never recomputed differently here) — reuses
    the one canonical ATR helper (core.demand_engine.compute_atr(), Fix
    #4's own ATR(14)), not a second formula.

    Temporal-integrity contract (Fix #7Y's own follow-up audit, before
    this fix's first commit): this function always treats `candles[-1]`
    as "the current candle" and anchors there — it has no special
    knowledge of any LATER, still-to-be-evaluated reaction candle. A
    caller that wants a Strategy to react to candle N against a level
    that already existed BEFORE N must pass `candles[:-1]` here (see
    StructureEngine.get_snapshot()'s own wiring) — a live audit found
    that passing the reaction candle itself could shift VAH by a real
    amount (an unusually large tick_volume candle measurably moved the
    value-area boundary) and, more seriously, could make detection fail
    entirely for the exact geometry a VAH/VAL reaction is meant to catch
    (a genuine rejection candle whose wick briefly exceeds the old range
    before closing back inside — using it to SEED this function's own
    backward expansion could blow the compression bound and report no
    range at all instead of a valid, pre-existing one).

    Returns confirmed/start_index/start_timestamp/end_index/
    end_timestamp/range_high/range_low — all None/False together when
    `candles`/`atr` are missing, the compression bound is exceeded before
    MIN_RANGE_DURATION candles are included (e.g. a trending market: each
    displacing candle blows the width bound almost immediately), or the
    resulting window doesn't touch both sides at least twice each."""
    no_range = {
        "confirmed": False,
        "start_index": None, "start_timestamp": None,
        "end_index": None, "end_timestamp": None,
        "range_high": None, "range_low": None,
    }
    if not candles or atr is None or atr <= 0:
        return no_range

    current_index = len(candles) - 1
    range_high = candles[current_index].high
    range_low = candles[current_index].low
    start_index = current_index

    for i in range(current_index - 1, -1, -1):
        candidate_high = max(range_high, candles[i].high)
        candidate_low = min(range_low, candles[i].low)
        if (candidate_high - candidate_low) > COMPRESSION_ATR_MULTIPLIER * atr:
            break
        range_high, range_low = candidate_high, candidate_low
        start_index = i

    duration = current_index - start_index + 1
    if duration < MIN_RANGE_DURATION:
        return no_range

    tolerance = TOUCH_TOLERANCE_ATR_FRACTION * atr
    window = candles[start_index:current_index + 1]
    top_touches = sum(1 for c in window if c.high >= range_high - tolerance)
    bottom_touches = sum(1 for c in window if c.low <= range_low + tolerance)
    if top_touches < MIN_TOUCHES_PER_SIDE or bottom_touches < MIN_TOUCHES_PER_SIDE:
        return no_range

    return {
        "confirmed": True,
        "start_index": start_index,
        "start_timestamp": str(candles[start_index].timestamp),
        "end_index": current_index,
        "end_timestamp": str(candles[current_index].timestamp),
        "range_high": range_high,
        "range_low": range_low,
    }
