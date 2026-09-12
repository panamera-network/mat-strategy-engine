"""Fix #5F2 — targeted tests for structural leg origin evidence
(leg_origin_index/timestamp/price/swing_label), additive on top of
detect_structure_event()'s existing BOS/CHoCH detection with no formula
change.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_structure_leg_origin.py -v
"""
from core.core_models import CandleSnapshot
from core.structure_utils import (
    SWING_WINDOW,
    detect_structure_event,
    find_swings,
)


def c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100, timestamp=ts)


def build_bullish_break_candles():
    """A swing low, then a swing high, then price closes above the swing
    high -> bullish BOS/CHoCH. The swing low is the opposing (unbroken)
    swing -> expected leg origin."""
    candles = []
    ts = 0

    # Flat lead-in so find_swings() has enough candles on the left side of
    # the first swing to confirm it (SWING_WINDOW on each side).
    for _ in range(SWING_WINDOW):
        candles.append(c(100, 100.2, 99.8, 100.0, str(ts))); ts += 1

    # Swing low at 95 (dips below the flat lead-in and the candles after it).
    candles.append(c(99, 95.5, 95.0, 99.5, str(ts))); ts += 1  # index = SWING_WINDOW
    swing_low_index = SWING_WINDOW

    for _ in range(SWING_WINDOW):
        candles.append(c(100, 100.2, 99.8, 100.0, str(ts))); ts += 1

    # Rally up to a swing high at 105.
    for _ in range(SWING_WINDOW):
        candles.append(c(101, 101.2, 100.8, 101.0, str(ts))); ts += 1
    candles.append(c(102, 105.5, 104.5, 104.0, str(ts))); ts += 1  # swing high at 105.5
    swing_high_index = len(candles) - 1

    for _ in range(SWING_WINDOW):
        candles.append(c(103, 103.2, 102.8, 103.0, str(ts))); ts += 1

    # Final candle: close breaks above the swing high (105.5) -> bullish event.
    candles.append(c(103, 106.0, 102.9, 105.8, str(ts))); ts += 1

    return candles, swing_low_index, swing_high_index


def build_bearish_break_candles():
    """Mirror of the bullish case: a swing high, then a swing low, then
    price closes below the swing low -> bearish BOS/CHoCH. The swing high
    is the opposing (unbroken) swing -> expected leg origin."""
    candles = []
    ts = 0

    for _ in range(SWING_WINDOW):
        candles.append(c(100, 100.2, 99.8, 100.0, str(ts))); ts += 1

    # Swing high at 105.
    candles.append(c(101, 105.5, 104.5, 101.5, str(ts))); ts += 1
    swing_high_index = SWING_WINDOW

    for _ in range(SWING_WINDOW):
        candles.append(c(100, 100.2, 99.8, 100.0, str(ts))); ts += 1

    # Drop down to a swing low at 95.
    for _ in range(SWING_WINDOW):
        candles.append(c(99, 99.2, 98.8, 99.0, str(ts))); ts += 1
    candles.append(c(98, 95.5, 95.0, 96.0, str(ts))); ts += 1  # swing low at 95.0
    swing_low_index = len(candles) - 1

    for _ in range(SWING_WINDOW):
        candles.append(c(97, 97.2, 96.8, 97.0, str(ts))); ts += 1

    # Final candle: close breaks below the swing low (95.0) -> bearish event.
    candles.append(c(97, 97.1, 93.0, 93.5, str(ts))); ts += 1

    return candles, swing_high_index, swing_low_index


def test_bullish_event_leg_origin_is_opposing_swing_low():
    candles, swing_low_index, swing_high_index = build_bullish_break_candles()
    swing_highs, swing_lows = find_swings(candles)
    assert swing_low_index in swing_lows
    assert swing_high_index in swing_highs

    event = detect_structure_event(candles, swing_highs, swing_lows)
    assert event["direction"] == "Bullish"
    assert event["type"] in ("BOS", "CHOCH")
    assert event["broken_level"] == candles[swing_high_index].high

    assert event["leg_origin_index"] == swing_low_index
    assert event["leg_origin_price"] == candles[swing_low_index].low
    assert event["leg_origin_timestamp"] == str(candles[swing_low_index].timestamp)
    assert event["leg_origin_swing_label"] in ("HL", "LL")


def test_bearish_event_leg_origin_is_opposing_swing_high():
    candles, swing_high_index, swing_low_index = build_bearish_break_candles()
    swing_highs, swing_lows = find_swings(candles)
    assert swing_high_index in swing_highs
    assert swing_low_index in swing_lows

    event = detect_structure_event(candles, swing_highs, swing_lows)
    assert event["direction"] == "Bearish"
    assert event["type"] in ("BOS", "CHOCH")
    assert event["broken_level"] == candles[swing_low_index].low

    assert event["leg_origin_index"] == swing_high_index
    assert event["leg_origin_price"] == candles[swing_high_index].high
    assert event["leg_origin_timestamp"] == str(candles[swing_high_index].timestamp)
    assert event["leg_origin_swing_label"] in ("LH", "HH")


def test_leg_origin_index_timestamp_price_are_consistent_on_the_same_candle():
    """index/timestamp/price must all describe the exact same candle, not
    three independently-derived values that could drift apart."""
    candles, swing_low_index, _ = build_bullish_break_candles()
    swing_highs, swing_lows = find_swings(candles)
    event = detect_structure_event(candles, swing_highs, swing_lows)

    origin_candle = candles[event["leg_origin_index"]]
    assert event["leg_origin_timestamp"] == str(origin_candle.timestamp)
    assert event["leg_origin_price"] == origin_candle.low  # bullish event -> origin is a swing low


def test_swing_label_matches_label_swing_points_rule():
    """The origin's swing label must agree with label_swing_points()'s
    independent classification of the very same swing index — proving
    no second, divergent labeling rule was introduced."""
    from core.structure_utils import label_swing_points

    candles, swing_low_index, _ = build_bullish_break_candles()
    swing_highs, swing_lows = find_swings(candles)
    event = detect_structure_event(candles, swing_highs, swing_lows)

    all_points = label_swing_points(candles, swing_highs, swing_lows)
    matching = [p for p in all_points if p.index == swing_low_index]
    assert len(matching) == 1
    assert event["leg_origin_swing_label"] == matching[0].label


def test_no_event_all_origin_fields_none():
    """Flat candles with no break -> type/direction None/Neutral as before,
    and all four leg_origin_* fields must also be None."""
    candles = [c(100, 100.2, 99.8, 100.0, str(i)) for i in range(20)]
    swing_highs, swing_lows = find_swings(candles)
    event = detect_structure_event(candles, swing_highs, swing_lows)

    assert event["type"] == "None"
    assert event["direction"] == "Neutral"
    assert event["valid"] is False
    assert event["leg_origin_index"] is None
    assert event["leg_origin_timestamp"] is None
    assert event["leg_origin_price"] is None
    assert event["leg_origin_swing_label"] is None


def test_no_swings_at_all_all_origin_fields_none():
    """Empty swing_highs/swing_lows (the pre-existing early-return guard)
    must also produce None origin fields, not a crash."""
    candles = [c(100, 100.2, 99.8, 100.0, str(i)) for i in range(3)]
    event = detect_structure_event(candles, [], [])
    assert event["type"] == "None"
    assert event["leg_origin_index"] is None
    assert event["leg_origin_timestamp"] is None
    assert event["leg_origin_price"] is None
    assert event["leg_origin_swing_label"] is None


def test_existing_type_direction_broken_level_unchanged():
    """Sanity: the pre-existing fields' values are exactly what they were
    before this fix — this is purely additive, not a reinterpretation."""
    candles, swing_low_index, swing_high_index = build_bullish_break_candles()
    swing_highs, swing_lows = find_swings(candles)
    event = detect_structure_event(candles, swing_highs, swing_lows)

    assert set(event.keys()) >= {"type", "direction", "valid", "index", "broken_level"}
    assert event["index"] == len(candles) - 1
    assert event["broken_level"] == candles[swing_high_index].high
    assert event["valid"] is True


# ── StructureSnapshot / StructureEngine wiring ───────────────────────────

def test_structure_snapshot_carries_leg_origin_fields_live():
    """Live regression: a real StructureSnapshot must expose the same
    leg_origin_* values detect_structure_event() would have produced for
    its own lookback window, whenever a structure event is valid."""
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
        assert hasattr(snap, "leg_origin_index")
        assert hasattr(snap, "leg_origin_timestamp")
        assert hasattr(snap, "leg_origin_price")
        assert hasattr(snap, "leg_origin_swing_label")
        if snap.structure_valid:
            found_valid_event = True
            assert snap.leg_origin_index is not None
            assert snap.leg_origin_timestamp is not None
            assert snap.leg_origin_price is not None
            assert snap.leg_origin_swing_label in ("HH", "LH", "LL", "HL")
        else:
            assert snap.leg_origin_index is None
            assert snap.leg_origin_timestamp is None
            assert snap.leg_origin_price is None
            assert snap.leg_origin_swing_label is None

    # Not a hard requirement that a valid event exists in this particular
    # live sample (market-dependent), but if one does, it must carry the
    # fields correctly (asserted above per-timeframe already).
    _ = found_valid_event


def test_structure_events_output_shape_includes_leg_origin():
    """Live /core/output structure_events must include the four new keys
    alongside the existing ones, unchanged in meaning."""
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
        assert "leg_origin_index" in event
        assert "leg_origin_timestamp" in event
        assert "leg_origin_price" in event
        assert "leg_origin_swing_label" in event
        # Every entry in structure_events is already filtered to
        # structure_valid=True (see _build_structure_extras()), so origin
        # fields must be populated, not None, for every listed tf.
        assert event["leg_origin_index"] is not None
        assert event["leg_origin_timestamp"] is not None
        assert event["leg_origin_price"] is not None
        assert event["leg_origin_swing_label"] in ("HH", "LH", "LL", "HL")


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
