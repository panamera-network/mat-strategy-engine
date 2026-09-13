"""Fix #6C — targeted tests for pre_break_trend evidence (additive on top
of detect_structure_event()'s existing BOS/CHoCH detection; no formula
change). pre_break_trend exposes the two-swing `trend` value the function
already computed before deciding BOS vs CHoCH (see structure_utils.py and
Fix #6B's audit).

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_pre_break_trend.py -v
"""
from core.core_models import CandleSnapshot
from core.structure_utils import (
    SWING_WINDOW,
    detect_structure_event,
    find_swings,
)


def c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100, timestamp=ts)


def _flat(candles, ts, price=97.0, n=SWING_WINDOW):
    for _ in range(n):
        candles.append(c(price, price + 0.2, price - 0.2, price, str(ts)))
        ts += 1
    return ts


def build_two_swing_candles(low1, high1, low2, high2, final_open, final_high, final_low, final_close):
    """Two confirmed swing lows and two confirmed swing highs (enough for
    detect_trend() to return a real Bullish/Bearish verdict, not Neutral),
    followed by one final candle whose close decides the break. Varying
    only the final candle against the SAME swing setup lets one setup
    produce both the BOS (continuation) and CHoCH (reversal) case for a
    given trend direction."""
    candles = []
    ts = 0
    ts = _flat(candles, ts)
    candles.append(c(low1 - 0.5, low1 + 0.5, low1, low1 + 0.3, str(ts))); ts += 1
    ts = _flat(candles, ts)
    candles.append(c(high1 - 0.3, high1, high1 - 1.0, high1 - 0.5, str(ts))); ts += 1
    ts = _flat(candles, ts)
    candles.append(c(low2 - 0.5, low2 + 0.5, low2, low2 + 0.3, str(ts))); ts += 1
    ts = _flat(candles, ts)
    candles.append(c(high2 - 0.3, high2, high2 - 1.0, high2 - 0.5, str(ts))); ts += 1
    ts = _flat(candles, ts)
    candles.append(c(final_open, final_high, final_low, final_close, str(ts))); ts += 1
    return candles


def build_single_swing_pair_candles(low1, high1, final_open, final_high, final_low, final_close):
    """Exactly one confirmed swing low and one confirmed swing high — too
    few for detect_trend() (which requires 2 of each) to return anything
    but "Neutral", regardless of the final break direction."""
    candles = []
    ts = 0
    ts = _flat(candles, ts)
    candles.append(c(low1 - 0.5, low1 + 0.5, low1, low1 + 0.3, str(ts))); ts += 1
    ts = _flat(candles, ts)
    candles.append(c(high1 - 0.3, high1, high1 - 1.0, high1 - 0.5, str(ts))); ts += 1
    ts = _flat(candles, ts)
    candles.append(c(final_open, final_high, final_low, final_close, str(ts))); ts += 1
    return candles


# ---------------------------------------------------------------------------
# Bullish-trend swing setup (higher-high, higher-low): low1=90, high1=100,
# low2=95 (>low1), high2=110 (>high1) -> detect_trend() == "Bullish".
# ---------------------------------------------------------------------------

def test_bullish_bos_with_prior_bullish_trend_exposes_bullish():
    candles = build_two_swing_candles(
        low1=90, high1=100, low2=95, high2=110,
        final_open=108, final_high=112, final_low=107, final_close=111,  # closes above 110
    )
    swing_highs, swing_lows = find_swings(candles)
    assert len(swing_highs) == 2 and len(swing_lows) == 2

    event = detect_structure_event(candles, swing_highs, swing_lows)
    assert event["direction"] == "Bullish"
    assert event["type"] == "BOS"
    assert event["pre_break_trend"] == "Bullish"


def test_bearish_choch_with_prior_bullish_trend_exposes_bullish():
    """Same Bullish-trend swing setup, but the final candle breaks the
    OTHER way (below the last swing low) -> bearish direction against a
    Bullish trend -> CHoCH, pre_break_trend must still read "Bullish"."""
    candles = build_two_swing_candles(
        low1=90, high1=100, low2=95, high2=110,
        final_open=94, final_high=96, final_low=90, final_close=91,  # closes below 95
    )
    swing_highs, swing_lows = find_swings(candles)
    assert len(swing_highs) == 2 and len(swing_lows) == 2

    event = detect_structure_event(candles, swing_highs, swing_lows)
    assert event["direction"] == "Bearish"
    assert event["type"] == "CHOCH"
    assert event["pre_break_trend"] == "Bullish"


# ---------------------------------------------------------------------------
# Bearish-trend swing setup (lower-high, lower-low): low1=95, high1=105,
# low2=90 (<low1), high2=100 (<high1) -> detect_trend() == "Bearish".
# ---------------------------------------------------------------------------

def test_bearish_bos_with_prior_bearish_trend_exposes_bearish():
    candles = build_two_swing_candles(
        low1=95, high1=105, low2=90, high2=100,
        final_open=92, final_high=93, final_low=85, final_close=87,  # closes below 90
    )
    swing_highs, swing_lows = find_swings(candles)
    assert len(swing_highs) == 2 and len(swing_lows) == 2

    event = detect_structure_event(candles, swing_highs, swing_lows)
    assert event["direction"] == "Bearish"
    assert event["type"] == "BOS"
    assert event["pre_break_trend"] == "Bearish"


def test_bullish_choch_with_prior_bearish_trend_exposes_bearish():
    """Same Bearish-trend swing setup, but the final candle closes above
    the last swing high instead -> bullish direction against a Bearish
    trend -> CHoCH, pre_break_trend must still read "Bearish"."""
    candles = build_two_swing_candles(
        low1=95, high1=105, low2=90, high2=100,
        final_open=101, final_high=103, final_low=99, final_close=102,  # closes above 100
    )
    swing_highs, swing_lows = find_swings(candles)
    assert len(swing_highs) == 2 and len(swing_lows) == 2

    event = detect_structure_event(candles, swing_highs, swing_lows)
    assert event["direction"] == "Bullish"
    assert event["type"] == "CHOCH"
    assert event["pre_break_trend"] == "Bearish"


# ---------------------------------------------------------------------------
# Neutral-trend break, still labeled BOS today (Fix #6B Q2's edge case) —
# pre_break_trend must expose "Neutral" clearly rather than hiding it.
# ---------------------------------------------------------------------------

def test_neutral_trend_break_labeled_bos_exposes_neutral():
    candles = build_single_swing_pair_candles(
        low1=90, high1=100,
        final_open=103, final_high=106, final_low=102, final_close=105,  # closes above 100
    )
    swing_highs, swing_lows = find_swings(candles)
    assert len(swing_highs) == 1 and len(swing_lows) == 1  # too few for a real trend verdict

    event = detect_structure_event(candles, swing_highs, swing_lows)
    assert event["type"] == "BOS"  # today's default/fallback labeling (Fix #6B)
    assert event["pre_break_trend"] == "Neutral"


# ---------------------------------------------------------------------------
# No event -> pre_break_trend is None (scoped to an actual break; same
# convention as leg_origin_*/broken_level's "None when no confirmed event").
# ---------------------------------------------------------------------------

def test_no_break_but_swings_exist_pre_break_trend_is_none():
    """Swing evidence exists (so `trend` gets computed internally) but the
    final candle doesn't break either level -> still no event, and
    pre_break_trend must be None, not a leaked/unused trend value."""
    candles = build_two_swing_candles(
        low1=90, high1=100, low2=95, high2=110,
        final_open=105, final_high=106, final_low=104, final_close=105,  # stays inside [95, 110]
    )
    swing_highs, swing_lows = find_swings(candles)
    assert len(swing_highs) == 2 and len(swing_lows) == 2

    event = detect_structure_event(candles, swing_highs, swing_lows)
    assert event["type"] == "None"
    assert event["valid"] is False
    assert event["pre_break_trend"] is None


def test_no_swings_at_all_pre_break_trend_is_none():
    """Empty swing_highs/swing_lows (the pre-existing early-return guard,
    trend never even computed) must also produce pre_break_trend=None."""
    candles = [c(100, 100.2, 99.8, 100.0, str(i)) for i in range(3)]
    event = detect_structure_event(candles, [], [])
    assert event["type"] == "None"
    assert event["pre_break_trend"] is None


def test_existing_fields_unchanged_by_this_additive_fix():
    """Sanity: adding pre_break_trend doesn't alter any pre-existing field."""
    candles = build_two_swing_candles(
        low1=90, high1=100, low2=95, high2=110,
        final_open=108, final_high=112, final_low=107, final_close=111,
    )
    swing_highs, swing_lows = find_swings(candles)
    event = detect_structure_event(candles, swing_highs, swing_lows)
    assert set(event.keys()) >= {
        "type", "direction", "valid", "index", "broken_level",
        "leg_origin_index", "leg_origin_timestamp", "leg_origin_price", "leg_origin_swing_label",
        "pre_break_trend",
    }
    assert event["index"] == len(candles) - 1
    assert event["broken_level"] == 110


# ── StructureSnapshot / StructureEngine / Output wiring ──────────────────

def test_structure_snapshot_carries_pre_break_trend_live():
    """Live regression: a real StructureSnapshot must expose pre_break_trend
    consistently with structure_valid — populated (Bullish/Bearish/Neutral)
    when there's a confirmed event, None otherwise."""
    import api.core_router as cr
    from core.candle_cache import CandleCache

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    found_valid_event = False
    for tf in timeframes:
        snap = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
        if snap is None:
            continue
        assert hasattr(snap, "pre_break_trend")
        if snap.structure_valid:
            found_valid_event = True
            assert snap.pre_break_trend in ("Bullish", "Bearish", "Neutral")
        else:
            assert snap.pre_break_trend is None

    _ = found_valid_event  # market-dependent; per-snapshot assertions above already cover both branches


def test_structure_events_output_shape_includes_pre_break_trend():
    """Live /core/output structure_events must include pre_break_trend
    alongside the existing keys, populated for every structure_valid=True
    entry (per _build_structure_extras()'s existing filter)."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine,
        candle_engine=cr.candle_engine,
        momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine,
        shift_engine=cr.shift_engine,
        structure_engine=cr.structure_engine,
        cache=cache,
        symbols=[symbol],
    )
    assert "error" not in out[symbol]
    structure_events = out[symbol].get("structure_events", {})
    for tf, event in structure_events.items():
        assert "pre_break_trend" in event
        assert event["pre_break_trend"] in ("Bullish", "Bearish", "Neutral")


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
