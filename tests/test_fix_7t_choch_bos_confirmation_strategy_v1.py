"""Fix #7T — CHoCH -> BOS Confirmation v1 baseline: a SEQUENCE
confirmation strategy (a genuine, earlier, same-direction CHoCH followed
by a LATER BOS), not "current BOS + current trend" collapsed into one
check.

Evidence audit: detect_structure_event() (structure_utils.py) evaluates
ONLY candles[-1] against the swing levels known from the FULL window it
is given -- a single StrategySnapshot can only ever prove "this exact
candle satisfies a break condition right now", never "a CHoCH happened
several candles ago and this BOS happened later". No existing event-
history mechanism covered this before this fix; Fix #7P's
detect_breakout_retest() answers a different question (breakout-then-
retest of the SAME level). Fix #7T closes the gap with
structure_utils.detect_choch_then_bos(): a pure function that replays the
canonical find_swings()/detect_structure_event() on shorter PREFIXES of
the SAME already-fetched lookback window (no new fetch, no duplicate
classification, no persistent state) to recover genuine prior-CHoCH-
before-this-BOS sequence evidence.

This is a v1 BASELINE only -- sequence expiry, max bars between events,
zone confluence, retest requirement, and confidence tuning are explicitly
deferred to a later rule audit. These tests lock in v1's exact behavior,
not a claim that the rules are final.

BOS origin identity audit (this fix's own follow-up audit, before its
first commit): current_event["index"] (StrategySnapshot.event_index)
ALWAYS describes "now" -- a BOS leg can stay beyond its broken level for
several more candles after the real break, so the LATER "BOS" marking
must not simply be "now". Explicit testing against 5 named timelines
(single-candle BOS, BOS with trailing closes beyond the level, a failed-
then-renewed breakout, a full opposite reversal before a same-direction
re-confirmation, and a wick-only touch before the real close-break)
confirmed detect_choch_then_bos() must additionally report the TRUE
origin of the current BOS leg (bos_origin_index/bos_origin_timestamp),
reusing the exact same current-leg backward-origin principle Fix #7P
already proved for detect_breakout_retest() (one shared implementation,
_find_current_leg_origin(), not a second independent one). The CHoCH
search itself, its own two-phase origin refinement, the BOS/CHoCH
classification, the sequence direction rule, the confidence formula, and
the marking count were all left unchanged -- only which candle the
"later BOS" marking points at was corrected.

Ordering-invariant audit (this fix's second follow-up audit, still before
its first commit): the live 36x9-universe scan surfaced a real degenerate
case (NZDJPY_i, W1, exact values reproduced in
test_util_live_discovered_same_break_reclassification_rejected below)
where bos_origin_index came out EQUAL to choch_index -- the same physical
break candle is a genuine CHoCH against the swings known at its own point
in time, then gets relabeled a "BOS" once one more swing shifts the
current/full-window trend read to Neutral (Fix #6C's own Neutral-pre-
break-trend default-to-continuation fallback). That is one break wearing
two labels, not a real CHoCH-then-later-BOS sequence. detect_choch_then_
bos() now requires bos_origin_index STRICTLY GREATER than choch_index --
enforced in the canonical sequence evidence itself (so it can never claim
confirmation incorrectly), with a matching defensive re-check in the
Strategy too (the same defense-in-depth pattern BreakoutRetestStrategy,
Fix #7P, already uses for its own origin/retest ordering). CHoCH/BOS
classification, the Neutral fallback behavior itself, the origin helper,
confidence, marking count, and the lookback size are all unchanged.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7t_choch_bos_confirmation_strategy_v1.py -v
"""
from datetime import datetime, timezone

import pytest

from core.core_models import CandleSnapshot
from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot
from core.structure_utils import SWING_WINDOW, detect_choch_then_bos, detect_structure_event, find_swings


# ---------------------------------------------------------------------------
# Synthetic candle builders (explicit, engineered pivots -- not random data)
# so find_swings()/detect_structure_event() produce known, verifiable swing
# structure. Each timeline was run against the ACTUAL implementation before
# being locked in here, per this repo's established audit practice.
# ---------------------------------------------------------------------------

def _c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100.0, timestamp=str(ts))


def _ramp(start_val, end_val, n, base_idx, candles):
    step = (end_val - start_val) / n
    for i in range(n):
        v = start_val + step * (i + 1)
        o = v - abs(step) * 0.1
        cl = v
        h = v + abs(step) * 0.05
        l = v - abs(step) * 0.15
        candles.append(_c(o, h, l, cl, base_idx + i))


def _pivot_low(value, base_idx, candles, margin=5):
    candles.append(_c(value + margin * 0.5, value + margin, value, value + margin * 0.3, base_idx))


def _pivot_high(value, base_idx, candles, margin=5):
    candles.append(_c(value - margin * 0.5, value, value - margin, value - margin * 0.3, base_idx))


def _bullish_choch_then_bos_candles():
    """Downtrend (2 lower highs, 2 lower lows) -> bullish CHoCH (breaks
    the last swing high) -> new higher swing low + higher swing high
    (bullish trend established) -> bullish BOS (breaks the new swing
    high). Returns (candles_up_to_bos, choch_origin_index, bos_index)."""
    candles = []
    idx = 0
    _ramp(150, 105, 3, idx, candles); idx = len(candles)
    _pivot_low(100, idx, candles); idx = len(candles)
    _ramp(100, 125, 4, idx, candles); idx = len(candles)
    _pivot_high(130, idx, candles); idx = len(candles)
    _ramp(130, 85, 4, idx, candles); idx = len(candles)
    _pivot_low(80, idx, candles); idx = len(candles)
    _ramp(80, 105, 4, idx, candles); idx = len(candles)
    _pivot_high(110, idx, candles); idx = len(candles)
    _ramp(110, 108, 3, idx, candles); idx = len(candles)
    candles.append(_c(108, 141, 107, 140, idx)); idx = len(candles)
    choch_origin_idx = idx - 1
    _ramp(140, 135, 3, idx, candles); idx = len(candles)
    _pivot_low(120, idx, candles); idx = len(candles)
    _ramp(120, 150, 4, idx, candles); idx = len(candles)
    _pivot_high(160, idx, candles); idx = len(candles)
    _ramp(160, 155, 3, idx, candles); idx = len(candles)
    candles.append(_c(155, 181, 154, 180, idx)); idx = len(candles)
    bos_idx = idx - 1
    return candles[:bos_idx + 1], choch_origin_idx, bos_idx


def _bearish_choch_then_bos_candles():
    """Mirror of the above: uptrend -> bearish CHoCH -> new lower swings
    -> bearish BOS."""
    candles = []
    idx = 0
    _ramp(50, 95, 3, idx, candles); idx = len(candles)
    _pivot_high(100, idx, candles); idx = len(candles)
    _ramp(100, 75, 4, idx, candles); idx = len(candles)
    _pivot_low(70, idx, candles); idx = len(candles)
    _ramp(70, 115, 4, idx, candles); idx = len(candles)
    _pivot_high(120, idx, candles); idx = len(candles)
    _ramp(120, 92, 3, idx, candles); idx = len(candles)
    _pivot_low(90, idx, candles); idx = len(candles)
    _ramp(90, 92, 3, idx, candles); idx = len(candles)
    candles.append(_c(92, 93, 59, 60, idx)); idx = len(candles)
    choch_origin_idx = idx - 1
    _ramp(60, 65, 3, idx, candles); idx = len(candles)
    _pivot_high(80, idx, candles); idx = len(candles)
    _ramp(80, 50, 4, idx, candles); idx = len(candles)
    _pivot_low(40, idx, candles); idx = len(candles)
    _ramp(40, 45, 3, idx, candles); idx = len(candles)
    candles.append(_c(45, 46, 19, 20, idx)); idx = len(candles)
    bos_idx = idx - 1
    return candles[:bos_idx + 1], choch_origin_idx, bos_idx


def _pure_uptrend_no_choch_candles():
    """Bullish from the very first confirmable comparison -- never flips
    via a CHoCH, so the final continuation break must find NO prior
    CHoCH anywhere in the window."""
    candles = []
    idx = 0
    _ramp(100, 105, 3, idx, candles); idx = len(candles)
    _pivot_low(103, idx, candles); idx = len(candles)
    _ramp(103, 120, 4, idx, candles); idx = len(candles)
    _pivot_high(125, idx, candles); idx = len(candles)
    _ramp(125, 115, 4, idx, candles); idx = len(candles)
    _pivot_low(112, idx, candles); idx = len(candles)
    _ramp(112, 130, 4, idx, candles); idx = len(candles)
    _pivot_high(135, idx, candles); idx = len(candles)
    _ramp(135, 132, 3, idx, candles); idx = len(candles)
    candles.append(_c(132, 145, 131, 144, idx)); idx = len(candles)
    bos_idx = idx - 1
    return candles[:bos_idx + 1], bos_idx


def _bullish_choch_bos_with_trailing_closes():
    """Case 2: CHoCH -> true BOS -> 3 MORE closes remain beyond the same
    broken level before "now". Returns (candles, choch_idx,
    true_bos_origin_idx, now_idx) -- true_bos_origin_idx != now_idx."""
    candles, choch_idx = _bullish_choch_then_bos_candles_prefix()
    idx = len(candles)
    _ramp(140, 135, 3, idx, candles); idx = len(candles)
    _pivot_low(120, idx, candles); idx = len(candles)
    _ramp(120, 150, 4, idx, candles); idx = len(candles)
    _pivot_high(160, idx, candles); idx = len(candles)
    _ramp(160, 155, 3, idx, candles); idx = len(candles)
    candles.append(_c(155, 181, 154, 180, idx)); idx = len(candles)
    true_bos_origin_idx = idx - 1
    candles.append(_c(180, 185, 178, 183, idx)); idx = len(candles)
    candles.append(_c(183, 190, 180, 188, idx)); idx = len(candles)
    candles.append(_c(188, 195, 185, 192, idx)); idx = len(candles)
    now_idx = idx - 1
    return candles, choch_idx, true_bos_origin_idx, now_idx


def _bullish_choch_then_bos_candles_prefix():
    """Just the downtrend + bullish-CHoCH portion shared by several
    timelines below (factored out of _bullish_choch_then_bos_candles())."""
    candles = []
    idx = 0
    _ramp(150, 105, 3, idx, candles); idx = len(candles)
    _pivot_low(100, idx, candles); idx = len(candles)
    _ramp(100, 125, 4, idx, candles); idx = len(candles)
    _pivot_high(130, idx, candles); idx = len(candles)
    _ramp(130, 85, 4, idx, candles); idx = len(candles)
    _pivot_low(80, idx, candles); idx = len(candles)
    _ramp(80, 105, 4, idx, candles); idx = len(candles)
    _pivot_high(110, idx, candles); idx = len(candles)
    _ramp(110, 108, 3, idx, candles); idx = len(candles)
    candles.append(_c(108, 141, 107, 140, idx)); idx = len(candles)
    choch_origin_idx = idx - 1
    return candles, choch_origin_idx


def _bullish_choch_bos_failed_then_renewed():
    """Case 3: CHoCH -> BOS -> price fails back through the level ->
    later a NEW BOS, same direction. Returns (candles, choch_idx,
    old_stale_bos_idx, new_bos_idx)."""
    candles, choch_idx = _bullish_choch_then_bos_candles_prefix()
    idx = len(candles)
    _ramp(140, 135, 3, idx, candles); idx = len(candles)
    _pivot_low(120, idx, candles); idx = len(candles)
    _ramp(120, 150, 4, idx, candles); idx = len(candles)
    _pivot_high(160, idx, candles); idx = len(candles)
    _ramp(160, 155, 3, idx, candles); idx = len(candles)
    candles.append(_c(155, 181, 154, 180, idx)); idx = len(candles)  # stale/old BOS
    old_bos_idx = idx - 1
    candles.append(_c(180, 180, 150, 152, idx)); idx = len(candles)  # fails back below 160
    candles.append(_c(152, 155, 148, 150, idx)); idx = len(candles)
    candles.append(_c(150, 205, 149, 200, idx)); idx = len(candles)  # new BOS, breaks above old swing high
    new_bos_idx = idx - 1
    return candles[:new_bos_idx + 1], choch_idx, old_bos_idx, new_bos_idx


def _bullish_choch_bos_after_full_opposite_reversal():
    """Case 4: CHoCH -> old BOS -> a full OPPOSITE (bearish) CHoCH
    reversal -> a NEW bullish CHoCH -> a NEW bullish BOS. Returns
    (candles, old_choch_idx, old_bos_idx, new_choch_idx, new_bos_idx).
    Swing confirmation needs `window` candles after each pivot before it
    is "known" to a later prefix -- every phase below leaves that gap
    deliberately, verified against the real implementation before being
    locked in here (see this fix's own audit)."""
    candles, old_choch_idx = _bullish_choch_then_bos_candles_prefix()
    idx = len(candles)
    _ramp(140, 135, 3, idx, candles); idx = len(candles)
    _pivot_low(120, idx, candles); idx = len(candles)
    _ramp(120, 150, 4, idx, candles); idx = len(candles)
    _pivot_high(160, idx, candles); idx = len(candles)
    _ramp(160, 155, 3, idx, candles); idx = len(candles)
    candles.append(_c(155, 181, 154, 180, idx)); idx = len(candles)
    old_bos_idx = idx - 1
    # Full reversal: bearish CHoCH breaking below the last swing low.
    _ramp(180, 145, 3, idx, candles); idx = len(candles)
    _pivot_high(150, idx, candles); idx = len(candles)
    _ramp(150, 122, 3, idx, candles); idx = len(candles)
    candles.append(_c(122, 123, 90, 92, idx)); idx = len(candles)
    # New lower swing high, confirmed (>= window candles after) before the
    # new bullish CHoCH candle.
    _ramp(92, 95, 2, idx, candles); idx = len(candles)
    _pivot_low(85, idx, candles); idx = len(candles)
    _ramp(85, 100, 2, idx, candles); idx = len(candles)
    _pivot_high(105, idx, candles); idx = len(candles)
    _ramp(105, 100, 4, idx, candles); idx = len(candles)
    new_choch_idx = len(candles)
    candles.append(_c(100, 135, 99, 133, idx)); idx = len(candles)
    assert new_choch_idx == idx - 1
    # New bullish leg: higher low + higher high, each confirmed before
    # the final new BOS.
    _ramp(133, 128, 3, idx, candles); idx = len(candles)
    _pivot_low(122, idx, candles); idx = len(candles)
    _ramp(122, 145, 4, idx, candles); idx = len(candles)
    _pivot_high(150, idx, candles); idx = len(candles)
    _ramp(150, 145, 4, idx, candles); idx = len(candles)
    candles.append(_c(145, 175, 144, 173, idx)); idx = len(candles)
    new_bos_idx = idx - 1
    return candles[:new_bos_idx + 1], old_choch_idx, old_bos_idx, new_choch_idx, new_bos_idx


def _bullish_choch_bos_with_wick_only_touch_first():
    """Case 5: CHoCH -> a wick-only touch of the prospective BOS level
    (never closes beyond it) -> later a real close-break. Returns
    (candles, choch_idx, wick_touch_idx, real_break_idx)."""
    candles, choch_idx = _bullish_choch_then_bos_candles_prefix()
    idx = len(candles)
    _ramp(140, 135, 3, idx, candles); idx = len(candles)
    _pivot_low(120, idx, candles); idx = len(candles)
    _ramp(120, 148, 4, idx, candles); idx = len(candles)
    candles.append(_c(148, 165, 147, 150, idx)); idx = len(candles)  # wick to 165, closes 150 -- not a break
    wick_touch_idx = idx - 1
    _ramp(150, 148, 2, idx, candles); idx = len(candles)
    _pivot_high(160, idx, candles); idx = len(candles)
    _ramp(160, 155, 3, idx, candles); idx = len(candles)
    candles.append(_c(155, 181, 154, 180, idx)); idx = len(candles)  # real close-break
    real_break_idx = idx - 1
    return candles[:real_break_idx + 1], choch_idx, wick_touch_idx, real_break_idx


# ---------------------------------------------------------------------------
# detect_choch_then_bos() — unit-level audit checks on the utility itself,
# run against the actual implementation with explicit synthetic timelines.
# ---------------------------------------------------------------------------

def test_util_bullish_choch_then_later_bullish_bos_confirmed():
    """Case 1: CHoCH -> one true BOS candle -> current candle IS that BOS.
    bos_origin_index must equal the current candle itself here (a single-
    candle leg -- origin and "now" are the same point)."""
    candles, choch_origin_idx, bos_idx = _bullish_choch_then_bos_candles()
    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    assert event["valid"] and event["type"] == "BOS" and event["direction"] == "Bullish"
    result = detect_choch_then_bos(candles, event)
    assert result["choch_confirmed"] is True
    assert result["choch_index"] == choch_origin_idx
    assert result["bos_origin_index"] == bos_idx
    assert result["choch_index"] < result["bos_origin_index"]


def test_util_bearish_choch_then_later_bearish_bos_confirmed():
    candles, choch_origin_idx, bos_idx = _bearish_choch_then_bos_candles()
    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    assert event["valid"] and event["type"] == "BOS" and event["direction"] == "Bearish"
    result = detect_choch_then_bos(candles, event)
    assert result["choch_confirmed"] is True
    assert result["choch_index"] == choch_origin_idx
    assert result["bos_origin_index"] == bos_idx
    assert result["choch_index"] < result["bos_origin_index"]


def test_util_case2_bos_origin_is_not_now_when_closes_continue_beyond_level():
    """Case 2: CHoCH -> true BOS -> 2-3 more closes remain beyond the same
    broken level. bos_origin_index must be the TRUE origin candle, never
    "now" (event["index"]) -- the exact bug this fix's follow-up audit
    found and corrected."""
    candles, choch_idx, true_origin_idx, now_idx = _bullish_choch_bos_with_trailing_closes()
    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    assert event["valid"] and event["type"] == "BOS" and event["index"] == now_idx
    assert now_idx != true_origin_idx  # the whole point of this case
    result = detect_choch_then_bos(candles, event)
    assert result["bos_origin_index"] == true_origin_idx
    assert result["bos_origin_index"] != now_idx
    assert result["choch_index"] == choch_idx
    assert result["choch_index"] < result["bos_origin_index"]


def test_util_case3_bos_origin_is_new_leg_not_stale_old_bos():
    """Case 3: CHoCH -> BOS -> price fails back through the level -> a
    LATER, NEW BOS, same direction. bos_origin_index must be the NEW
    leg's origin, never the stale/old, already-invalidated BOS."""
    candles, choch_idx, old_bos_idx, new_bos_idx = _bullish_choch_bos_failed_then_renewed()
    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    assert event["valid"] and event["type"] == "BOS"
    result = detect_choch_then_bos(candles, event)
    assert result["bos_origin_index"] == new_bos_idx
    assert result["bos_origin_index"] != old_bos_idx
    assert result["choch_index"] == choch_idx
    assert result["choch_index"] < result["bos_origin_index"]


def test_util_case4_choch_and_bos_both_from_new_leg_after_full_reversal():
    """Case 4: CHoCH -> old BOS -> a full OPPOSITE (bearish) reversal ->
    later a NEW same-direction CHoCH and a NEW same-direction BOS. Both
    choch_index and bos_origin_index must reflect the NEW leg, never the
    stale pre-reversal CHoCH/BOS."""
    candles, old_choch_idx, old_bos_idx, new_choch_idx, new_bos_idx = _bullish_choch_bos_after_full_opposite_reversal()
    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    assert event["valid"] and event["type"] == "BOS" and event["direction"] == "Bullish"
    result = detect_choch_then_bos(candles, event)
    assert result["choch_confirmed"] is True
    assert result["choch_index"] == new_choch_idx
    assert result["choch_index"] != old_choch_idx
    assert result["bos_origin_index"] == new_bos_idx
    assert result["bos_origin_index"] != old_bos_idx
    assert result["choch_index"] < result["bos_origin_index"]


def test_util_case5_wick_only_touch_never_picked_as_bos_origin():
    """Case 5: CHoCH -> a wick-only touch of the prospective BOS level
    (never closes beyond it) -> later a real close-break. The wick-only
    touch must never be picked as the origin -- origin identification is
    close-based, exactly like detect_breakout_retest()'s own beyond()."""
    candles, choch_idx, wick_touch_idx, real_break_idx = _bullish_choch_bos_with_wick_only_touch_first()
    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    assert event["valid"] and event["type"] == "BOS"
    result = detect_choch_then_bos(candles, event)
    assert result["bos_origin_index"] == real_break_idx
    assert result["bos_origin_index"] != wick_touch_idx
    assert result["choch_index"] == choch_idx


def test_util_bos_without_prior_choch_rejected():
    candles, bos_idx = _pure_uptrend_no_choch_candles()
    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    assert event["valid"] and event["type"] == "BOS"
    result = detect_choch_then_bos(candles, event)
    assert result["choch_confirmed"] is False
    assert result["choch_index"] is None


def test_util_choch_only_current_event_rejected():
    """current_event itself classified as CHOCH (not BOS) -- there is by
    definition no "later BOS" for the sequence to end at."""
    candles, _, bos_idx = _bullish_choch_then_bos_candles()
    fake_choch_event = {"valid": True, "type": "CHOCH", "direction": "Bullish", "index": bos_idx, "broken_level": 100.0}
    result = detect_choch_then_bos(candles, fake_choch_event)
    assert result["choch_confirmed"] is False


def test_util_invalid_event_rejected():
    candles, _, bos_idx = _bullish_choch_then_bos_candles()
    invalid_event = {"valid": False, "type": "None", "direction": "Neutral", "index": bos_idx, "broken_level": None}
    result = detect_choch_then_bos(candles, invalid_event)
    assert result["choch_confirmed"] is False


def test_util_opposite_direction_choch_rejected():
    """The window contains a real, confirmed bearish CHoCH -- but the
    (artificially supplied) current event claims Bullish. No bullish
    CHoCH exists anywhere in this window, so it must still reject."""
    candles, _, bos_idx = _bearish_choch_then_bos_candles()
    wrong_direction_event = {"valid": True, "type": "BOS", "direction": "Bullish", "index": bos_idx, "broken_level": 40.0}
    result = detect_choch_then_bos(candles, wrong_direction_event)
    assert result["choch_confirmed"] is False


def test_util_same_candle_choch_bos_structurally_impossible():
    """The scan starts at bos_index - 1, strictly before the BOS's own
    candle -- a same-candle CHoCH/BOS collision cannot occur by
    construction, not merely by a runtime check."""
    candles, choch_origin_idx, bos_idx = _bullish_choch_then_bos_candles()
    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    result = detect_choch_then_bos(candles, event)
    assert result["choch_confirmed"] is True
    assert result["choch_index"] != bos_idx
    assert result["choch_index"] < bos_idx


def test_util_bos_before_choch_impossible_by_scan_direction():
    """The scan only ever looks at indices strictly less than bos_index --
    a returned choch_index greater than or equal to bos_index is
    structurally impossible, confirmed here rather than merely asserted
    in prose."""
    candles, choch_origin_idx, bos_idx = _bearish_choch_then_bos_candles()
    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    result = detect_choch_then_bos(candles, event)
    assert result["choch_confirmed"] is True
    assert result["choch_index"] < event["index"]


def test_util_too_short_window_returns_no_evidence_not_a_crash():
    candles, _, bos_idx = _bullish_choch_then_bos_candles()
    short_event = {"valid": True, "type": "BOS", "direction": "Bullish", "index": SWING_WINDOW, "broken_level": 100.0}
    result = detect_choch_then_bos(candles, short_event)
    assert result["choch_confirmed"] is False


def test_util_deterministic_repeated_evaluation():
    """Pure function over its arguments only -- calling it twice with the
    identical candles/event must always return an identical result."""
    candles, _, bos_idx = _bullish_choch_then_bos_candles()
    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    result1 = detect_choch_then_bos(candles, event)
    result2 = detect_choch_then_bos(candles, event)
    result3 = detect_choch_then_bos(candles, event)
    assert result1 == result2 == result3


def test_util_no_cross_contamination_between_independent_calls():
    """No persistent/shared state exists (confirmed by source scan below
    too) -- interleaving calls with two completely different candle sets
    (standing in for two different symbol/timeframe pairs) must not affect
    each other's results."""
    bull_candles, _, _ = _bullish_choch_then_bos_candles()
    bear_candles, _, _ = _bearish_choch_then_bos_candles()
    sh_b, sl_b = find_swings(bull_candles, window=SWING_WINDOW)
    bull_event = detect_structure_event(bull_candles, sh_b, sl_b)
    sh_r, sl_r = find_swings(bear_candles, window=SWING_WINDOW)
    bear_event = detect_structure_event(bear_candles, sh_r, sl_r)

    result_bull_1 = detect_choch_then_bos(bull_candles, bull_event)
    result_bear_1 = detect_choch_then_bos(bear_candles, bear_event)
    result_bull_2 = detect_choch_then_bos(bull_candles, bull_event)
    result_bear_2 = detect_choch_then_bos(bear_candles, bear_event)

    assert result_bull_1 == result_bull_2
    assert result_bear_1 == result_bear_2
    assert result_bull_1["choch_confirmed"] is True
    assert result_bear_1["choch_confirmed"] is True


def test_util_no_persistent_state_in_structure_utils_module():
    """Source-scan confirmation that detect_choch_then_bos() introduces no
    module-level mutable cache/dict that could leak state across calls."""
    import pathlib
    text = pathlib.Path("core/structure_utils.py").read_text(encoding="utf-8")
    start = text.index("def detect_choch_then_bos")
    end = text.index("\ndef ", start + 1)
    body = text[start:end]
    for forbidden in ("global ", "_cache", "_CACHE", "functools.lru_cache"):
        assert forbidden not in body


# ---------------------------------------------------------------------------
# Ordering invariant (this fix's own follow-up audit, before its first
# commit): a confirmed sequence requires bos_origin_index STRICTLY
# GREATER than choch_index. bos_origin_index == choch_index is a real,
# live-discovered edge case (not hypothetical) -- reproduced verbatim
# below with the exact real candle values captured from the live scan.
# ---------------------------------------------------------------------------

def test_util_live_discovered_same_break_reclassification_rejected():
    """Regression for the exact live-discovered case: the SAME physical
    break candle is a genuine CHoCH when evaluated against the swings
    known at its own point in time (a real, confirmed Bullish two-swing
    trend existed then), but the current/full-window evaluation relabels
    it a "BOS" once one more swing (a new, lower swing high) shifts the
    trend read to Neutral (Fix #6C's own Neutral-pre-break-trend default-
    to-continuation fallback) -- one break wearing two labels, not a real
    CHoCH-then-later-BOS sequence. Exact real candle values from the live
    36x9-universe scan (NZDJPY_i, W1) that first surfaced this case.
    Expected: choch_confirmed=False, no valid sequence evidence, and the
    strategy does not fire."""
    raw = [
        (92.38, 93.73, 91.969, 93.44), (92.831, 94.036, 92.56, 92.653),
        (92.533, 93.525, 92.47, 93.073), (93.222, 95.413, 92.856, 95.343),
        (95.23, 95.344, 92.757, 92.888), (92.527, 93.622, 92.502, 93.393),
        (93.179, 93.81, 92.382, 92.498), (92.26, 92.761, 91.037, 91.163),
        (91.178, 92.472, 91.096, 92.014), (91.961, 93.571, 91.827, 93.178),
        (93.041, 95.076, 92.985, 94.838), (94.576, 95.428, 94.304, 94.837),
        (94.804, 95.305, 92.522, 92.684), (92.657, 93.097, 91.661, 92.939),
        (92.66, 93.918, 92.659, 93.827), (93.672, 95.161, 93.312, 95.039),
        (94.822, 95.193, 94.525, 94.633), (94.58, 94.782, 91.192, 91.845),
        (91.649, 91.929, 89.198, 89.231), (88.955, 89.437, 88.911, 89.176),
    ]
    candles = [_c(o, h, l, cl, i) for i, (o, h, l, cl) in enumerate(raw)]

    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    assert event["valid"] and event["type"] == "BOS" and event["direction"] == "Bearish"

    # Confirm this really is the degenerate case: without the ordering
    # invariant, the origin helper alone would report the same index the
    # CHoCH search finds -- both equal 18.
    bos_origin_before_invariant = _find_current_leg_origin_for_test(candles, event["index"], event["broken_level"], event["direction"])
    assert bos_origin_before_invariant == 18

    result = detect_choch_then_bos(candles, event)
    assert result["choch_confirmed"] is False
    assert result["choch_index"] is None
    assert result["bos_origin_index"] is None
    assert result["bos_origin_timestamp"] is None

    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    from core.strategy.strategy_models import StrategySnapshot
    snap = StrategySnapshot(
        symbol="NZDJPY_i", timeframe="W1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type=event["type"], structure_direction=event["direction"], structure_valid=event["valid"],
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        event_broken_level=event["broken_level"], event_index=event["index"], event_timestamp=str(candles[event["index"]].timestamp),
        choch_confirmed=result["choch_confirmed"], choch_index=result["choch_index"],
        choch_timestamp=result["choch_timestamp"], choch_broken_level=result["choch_broken_level"],
        bos_origin_index=result["bos_origin_index"], bos_origin_timestamp=result["bos_origin_timestamp"],
    )
    assert CHOCHBOSConfirmationStrategy().react(snap, {}) is None


def _find_current_leg_origin_for_test(candles, current_index, level, direction):
    """Local re-derivation (not importing the private helper) purely to
    document, in this test, what the origin WOULD be without the ordering
    invariant -- confirms the degenerate case is real, not a typo."""
    def beyond(cand):
        return cand.close > level if direction == "Bullish" else cand.close < level
    origin_index = 0
    for i in range(current_index - 1, -1, -1):
        if not beyond(candles[i]):
            origin_index = i + 1
            break
    return origin_index


def test_util_genuine_three_way_distinct_ordering_still_fires():
    """Proves a genuine case with CHoCH origin < BOS origin < current
    evaluation candle (all three distinct) still fires and both markings
    still represent the two distinct true origins -- the ordering
    invariant must reject only the degenerate equal/reversed case, never
    a real, properly-ordered sequence."""
    candles, choch_idx, true_bos_origin_idx, now_idx = _bullish_choch_bos_with_trailing_closes()
    assert choch_idx < true_bos_origin_idx < now_idx  # genuinely 3 distinct points
    sh, sl = find_swings(candles, window=SWING_WINDOW)
    event = detect_structure_event(candles, sh, sl)
    assert event["valid"] and event["type"] == "BOS" and event["index"] == now_idx
    result = detect_choch_then_bos(candles, event)
    assert result["choch_confirmed"] is True
    assert result["choch_index"] == choch_idx
    assert result["bos_origin_index"] == true_bos_origin_idx
    assert result["bos_origin_index"] > result["choch_index"]


# ---------------------------------------------------------------------------
# Strategy-level tests.
# ---------------------------------------------------------------------------

def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        event_broken_level=None, event_index=None, event_timestamp=None,
        choch_confirmed=False, choch_index=None, choch_timestamp=None, choch_broken_level=None,
        bos_origin_index=None, bos_origin_timestamp=None,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


# event_index/event_timestamp ("now") are deliberately set to a LATER,
# DIFFERENT candle than bos_origin_index/bos_origin_timestamp (the true
# origin) in both fixtures below -- this is exactly Case 2's shape (a BOS
# leg with trailing closes beyond the level) and proves the marking uses
# the origin fields, not "now", rather than passing by coincidence.
_BULLISH_SEQUENCE = dict(
    structure_type="BOS", structure_direction="Bullish", structure_valid=True,
    event_broken_level=160.0, event_index=38, event_timestamp="2026-01-01T08:00:00Z",
    choch_confirmed=True, choch_index=22, choch_timestamp="2026-01-01T02:00:00Z", choch_broken_level=110.0,
    bos_origin_index=35, bos_origin_timestamp="2026-01-01T05:00:00Z",
)
_BEARISH_SEQUENCE = dict(
    structure_type="BOS", structure_direction="Bearish", structure_valid=True,
    event_broken_level=40.0, event_index=37, event_timestamp="2026-01-02T08:00:00Z",
    choch_confirmed=True, choch_index=21, choch_timestamp="2026-01-02T02:00:00Z", choch_broken_level=90.0,
    bos_origin_index=34, bos_origin_timestamp="2026-01-02T05:00:00Z",
)


def test_bullish_choch_then_bos_valid_long():
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    result = CHOCHBOSConfirmationStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["trigger"] == "CHOCH_BOS_CONFIRMATION"
    assert result["reason"] == "Bullish BOS Confirmation"


def test_bearish_choch_then_bos_valid_short():
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    snap = _base_snapshot(**_BEARISH_SEQUENCE)
    result = CHOCHBOSConfirmationStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["trigger"] == "CHOCH_BOS_CONFIRMATION"
    assert result["reason"] == "Bearish BOS Confirmation"


def test_bos_without_choch_confirmed_rejected():
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["choch_confirmed"] = False
    overrides["choch_index"] = None
    overrides["choch_timestamp"] = None
    overrides["choch_broken_level"] = None
    snap = _base_snapshot(**overrides)
    assert CHOCHBOSConfirmationStrategy().react(snap, {}) is None


def test_missing_bos_origin_geometry_rejected():
    """Defensive: choch_confirmed=True should never appear without
    bos_origin_index/bos_origin_timestamp (detect_choch_then_bos() only
    ever sets them together), but never fabricate a marking if it
    somehow does."""
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["bos_origin_index"] = None
    overrides["bos_origin_timestamp"] = None
    snap = _base_snapshot(**overrides)
    assert CHOCHBOSConfirmationStrategy().react(snap, {}) is None


def test_defensive_bos_origin_equal_choch_index_rejected():
    """Strategy-level defense in depth (matching BreakoutRetestStrategy's
    own ordering check, Fix #7P): a hand-built/inconsistent snapshot that
    somehow claims choch_confirmed=True with bos_origin_index equal to
    choch_index must still reject, never trusting choch_confirmed alone
    without re-checking the ordering it implies. The upstream sequence
    evidence (detect_choch_then_bos()) already enforces this and would
    never produce such a snapshot itself -- this proves the strategy
    doesn't ALSO depend on that upstream guarantee alone."""
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["bos_origin_index"] = overrides["choch_index"]
    overrides["bos_origin_timestamp"] = overrides["choch_timestamp"]
    snap = _base_snapshot(**overrides)
    assert CHOCHBOSConfirmationStrategy().react(snap, {}) is None


def test_defensive_bos_origin_before_choch_index_rejected():
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["bos_origin_index"] = overrides["choch_index"] - 1
    snap = _base_snapshot(**overrides)
    assert CHOCHBOSConfirmationStrategy().react(snap, {}) is None


def test_current_event_choch_not_bos_rejected():
    """A defensive/inconsistent snapshot claiming choch_confirmed=True
    while structure_type is CHOCH (not BOS) must still reject -- the
    strategy's own gate checks structure_type == "BOS" independently."""
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["structure_type"] = "CHOCH"
    snap = _base_snapshot(**overrides)
    assert CHOCHBOSConfirmationStrategy().react(snap, {}) is None


def test_invalid_structure_rejected():
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["structure_valid"] = False
    snap = _base_snapshot(**overrides)
    assert CHOCHBOSConfirmationStrategy().react(snap, {}) is None


def test_neutral_direction_rejected():
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    overrides = dict(_BULLISH_SEQUENCE)
    overrides["structure_direction"] = "Neutral"
    snap = _base_snapshot(**overrides)
    assert CHOCHBOSConfirmationStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Chart markings: exactly 2 real structure markings, no fabricated geometry.
# ---------------------------------------------------------------------------

def test_exactly_two_real_markings_bullish():
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    result = CHOCHBOSConfirmationStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 2
    for m in markings:
        validate_chart_marking(m)
        assert m["type"] == "structure"
        assert m["direction"] == "long"

    choch_marking, bos_marking = markings
    assert choch_marking["label"] == "Bullish CHoCH"
    assert choch_marking["timestamp"] == "2026-01-01T02:00:00Z"
    assert choch_marking["candle_index"] == 22
    assert choch_marking["price"] == 110.0

    assert bos_marking["label"] == "Bullish BOS Confirmation"
    assert bos_marking["timestamp"] == "2026-01-01T05:00:00Z"
    assert bos_marking["candle_index"] == 35
    assert bos_marking["price"] == 160.0


def test_exactly_two_real_markings_bearish():
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    snap = _base_snapshot(**_BEARISH_SEQUENCE)
    result = CHOCHBOSConfirmationStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 2
    for m in markings:
        validate_chart_marking(m)
        assert m["type"] == "structure"
        assert m["direction"] == "short"
    assert markings[0]["label"] == "Bearish CHoCH"
    assert markings[1]["label"] == "Bearish BOS Confirmation"


def test_no_fabricated_geometry():
    """Every geometry value on both markings must be a straight, real
    field already present on the snapshot -- never invented/derived. The
    BOS marking must use bos_origin_index/bos_origin_timestamp (the true
    leg origin, Fix #7T's own follow-up audit correction) -- NOT
    event_index/event_timestamp, which the fixture deliberately sets to a
    different, later value ("now") to prove this isn't passing by
    coincidence."""
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    assert snap.event_index != snap.bos_origin_index
    assert snap.event_timestamp != snap.bos_origin_timestamp
    result = CHOCHBOSConfirmationStrategy().react(snap, {})
    choch_marking, bos_marking = result["chart_markings"]
    assert choch_marking["price"] == snap.choch_broken_level
    assert choch_marking["timestamp"] == snap.choch_timestamp
    assert choch_marking["candle_index"] == snap.choch_index
    assert bos_marking["price"] == snap.event_broken_level
    assert bos_marking["timestamp"] == snap.bos_origin_timestamp
    assert bos_marking["candle_index"] == snap.bos_origin_index
    assert bos_marking["timestamp"] != snap.event_timestamp
    assert bos_marking["candle_index"] != snap.event_index


# ---------------------------------------------------------------------------
# Confidence: exact formula, bounded.
# ---------------------------------------------------------------------------

def test_confidence_bounded_and_exact_formula():
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    snap_no_momentum = _base_snapshot(atr_normalized_momentum=None, **_BULLISH_SEQUENCE)
    result = CHOCHBOSConfirmationStrategy().react(snap_no_momentum, {})
    assert result["confidence"] == 0.5

    snap_partial = _base_snapshot(atr_normalized_momentum=1.0, **_BULLISH_SEQUENCE)
    result2 = CHOCHBOSConfirmationStrategy().react(snap_partial, {})
    assert result2["confidence"] == 0.75

    snap_saturated = _base_snapshot(atr_normalized_momentum=5.0, **_BULLISH_SEQUENCE)
    result3 = CHOCHBOSConfirmationStrategy().react(snap_saturated, {})
    assert result3["confidence"] == 1.0

    for r in (result, result2, result3):
        assert 0.0 <= r["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# No duplicate BOS/CHoCH classification; no zone/bias scoring.
# ---------------------------------------------------------------------------

def test_no_duplicate_classification_in_strategy():
    import pathlib
    text = pathlib.Path("core/strategy/CHOCHBOSConfirmationStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("find_swings", "detect_structure_event", "detect_trend", "detect_choch_then_bos"):
        assert forbidden not in text, f"CHOCHBOSConfirmationStrategy.py unexpectedly references {forbidden!r}"


def test_no_zone_or_bias_scoring():
    import pathlib
    text = pathlib.Path("core/strategy/CHOCHBOSConfirmationStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("snapshot.active_zone", "snapshot.mitigated_zone", "snapshot.bias", "snapshot.conviction"):
        assert forbidden not in text, f"CHOCHBOSConfirmationStrategy.py unexpectedly reads {forbidden}"


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    snap = _base_snapshot(**_BULLISH_SEQUENCE)
    result = CHOCHBOSConfirmationStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_strategy_engine_discovers_choch_bos_confirmation_strategy():
    """Originally asserted the discovered count equals exactly 18 -- Fix
    #7U later added a genuinely new 19th strategy
    (MomentumPullbackRecoveryStrategy), which made that exact-count
    snapshot stale (a real, intended addition, not a regression -- see
    tests/test_fix_7u_momentum_pullback_recovery_strategy_v1.py::test_strategy_engine_discovers_nineteen_strategies_now
    for that fix's own count assertion). Rewritten to check the actual
    invariant this test exists for -- CHOCHBOSConfirmationStrategy is
    discovered alongside the original 17 -- rather than a total count that
    any future new strategy would otherwise make stale again."""
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert "CHOCHBOSConfirmationStrategy" in engine.enabled
    existing_seventeen = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy",
    }
    assert existing_seventeen <= set(engine.enabled.keys())


def test_existing_seventeen_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_seventeen = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy",
    }
    assert existing_seventeen <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_gracefully():
    """A raw-JSON-body StrategySnapshot(**data) that omits choch_confirmed
    falls through to False -- never guessed -- and the strategy rejects
    cleanly rather than crashing."""
    base = dict(
        symbol="T", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="BOS", structure_direction="Bullish", structure_valid=True,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
    )
    snap = StrategySnapshot(**base)
    assert snap.choch_confirmed is False
    from core.strategy.CHOCHBOSConfirmationStrategy import CHOCHBOSConfirmationStrategy
    assert CHOCHBOSConfirmationStrategy().react(snap, {}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
