"""Fix #6BD — confidence_drop retired: compatibility/deprecated field,
intentionally frozen to False. Fix #6BC's audit found the old raw-price-unit
formula (slope2 < slope1 and abs(acceleration) > 0.5) severely instrument-
scale-broken (0% activation for FX, ~50% for crypto, purely from price
scale) with zero live behavioral consumer since Fix #6AO retired legacy
suppression. The field itself stays in MomentumSnapshot/StructureSnapshot/
BiasShiftEvent for /core/bias/shift* backward compatibility -- no new
formula, threshold, or ATR-based replacement is introduced.

Fix #6BK later retired /core/bias/shift*'s own calculation entirely
(detect_bias_shift() never actually detected a shift -- see Fix #6BJ's
audit); the live-event test below was updated accordingly to prove that
retirement instead of a real fired event.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_confidence_drop_frozen.py -v
"""
import dataclasses
from datetime import datetime, timezone

from core.MomentumEngine import MomentumEngine
from core.core_models import CandleSnapshot, MomentumSnapshot, StructureSnapshot, BiasShiftEvent


def c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100, timestamp=ts)


def make_engine():
    return MomentumEngine(candle_engine=None)


# ---------------------------------------------------------------------------
# Schema unchanged: field still present on all three types.
# ---------------------------------------------------------------------------

def test_momentum_snapshot_schema_still_has_confidence_drop():
    field_names = {f.name for f in dataclasses.fields(MomentumSnapshot)}
    assert "confidence_drop" in field_names


def test_structure_snapshot_schema_still_has_confidence_drop():
    field_names = {f.name for f in dataclasses.fields(StructureSnapshot)}
    assert "confidence_drop" in field_names


def test_bias_shift_event_schema_still_has_confidence_drop():
    event = BiasShiftEvent(
        symbol="T", timeframe="M15", previous_bias="Neutral", new_bias="Bullish",
        trigger="BOS", confirmed=True, momentum=5.0, confidence_drop=False,
        suppression=[], zone="demand", structure="breakout", direction="Bullish",
    )
    assert hasattr(event, "confidence_drop")
    assert event.confidence_drop is False


# ---------------------------------------------------------------------------
# Frozen to False, regardless of input that used to trigger the old formula.
# ---------------------------------------------------------------------------

def _sharp_deceleration_candles():
    """Candles engineered so the OLD formula (slope2 < slope1 and
    abs(acceleration) > 0.5) would have fired: a strong up-move (slope1
    large positive) followed by a sharp reversal (slope2 large negative)."""
    return [
        c(100, 101, 99, 100, "0"),
        c(100, 106, 100, 106, "1"),   # slope1 window start
        c(106, 112, 106, 112, "2"),
        c(112, 118, 112, 118, "3"),   # slope1 window end: slope1 = 118-100 = 18
        c(118, 118, 100, 102, "4"),
        c(102, 102, 90, 92, "5"),     # slope2 = 92-112 = -20 -> old formula: -20 < 18 and
                                      # abs(-20-18)=38 > 0.5 -> True under the retired formula
    ]


def test_confidence_drop_false_even_for_input_that_used_to_trigger_old_formula():
    engine = make_engine()
    snap = engine.compute(_sharp_deceleration_candles(), "TEST", "M15")
    assert snap.confidence_drop is False


def test_confidence_drop_false_for_flat_candles_too():
    flat = [c(100, 100.1, 99.9, 100, str(i)) for i in range(6)]
    engine = make_engine()
    snap = engine.compute(flat, "TEST", "M15")
    assert snap.confidence_drop is False


def test_confidence_drop_false_on_early_return_path():
    engine = make_engine()
    snap = engine.compute([c(100, 101, 99, 100, "0")], "TEST", "M15")
    assert snap.confidence_drop is False


# ---------------------------------------------------------------------------
# StructureSnapshot propagates False.
# ---------------------------------------------------------------------------

def test_structure_snapshot_propagates_false():
    import api.core_router as cr
    from core.candle_cache import CandleCache

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    checked_any = False
    for tf in timeframes:
        structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
        if structure is None:
            continue
        checked_any = True
        assert structure.confidence_drop is False
    assert checked_any


# ---------------------------------------------------------------------------
# Fix #6BK later retired detect_bias_shift() entirely (Fix #6BJ's audit:
# it never actually detected a shift -- prev_bias was accepted but never
# compared against anything). At the time this fix (#6BD) landed, it still
# fired real BiasShiftEvents and this test proved confidence_drop froze to
# False on one; now it proves the retirement itself instead -- see
# tests/test_bias_shift_route_retired.py for #6BK's own dedicated coverage.
# ---------------------------------------------------------------------------

def test_detect_bias_shift_always_returns_none_even_for_a_real_confirmed_event():
    import api.core_router as cr
    from core.ShiftEngine import detect_bias_shift

    symbols = ["XAUUSD_i", "BTCUSD_i", "EURUSD_i", "USDJPY_i", "GBPUSD_i"]
    timeframes = ["M15", "H1", "H4", "D1"]
    checked_a_confirmed_event = False
    for symbol in symbols:
        for tf in timeframes:
            structure = cr.structure_engine.get_snapshot(symbol, tf)
            if not structure or not structure.structure_valid:
                continue
            checked_a_confirmed_event = True
            event = detect_bias_shift(prev_bias="Neutral", snapshot=structure, symbol=symbol)
            assert event is None

    # confirms this test actually exercised a real, live, confirmed-valid
    # structural event -- not vacuously true because none existed to fire.
    assert checked_a_confirmed_event


# ---------------------------------------------------------------------------
# Old raw-price scale no longer affects it -- FX/crypto give the same
# (False) compatibility result regardless of instrument price scale.
# ---------------------------------------------------------------------------

def test_fx_and_crypto_same_compatibility_result_live():
    import api.core_router as cr
    from core.candle_cache import CandleCache

    fx_symbol = "EURUSD_i"
    crypto_symbol = "BTCUSD_i"
    timeframes = ["M5", "M15", "H1", "H4"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([fx_symbol, crypto_symbol], timeframes, count=100)

    checked_any = False
    for tf in timeframes:
        fx_structure = cr.structure_engine.get_snapshot(fx_symbol, tf, cache=cache)
        crypto_structure = cr.structure_engine.get_snapshot(crypto_symbol, tf, cache=cache)
        if fx_structure is None or crypto_structure is None:
            continue
        checked_any = True
        assert fx_structure.confidence_drop is False
        assert crypto_structure.confidence_drop is False
        assert fx_structure.confidence_drop == crypto_structure.confidence_drop

    assert checked_any


def test_rolling_sample_confidence_drop_never_true_regardless_of_scale():
    """Rolling replay across a large historical sample, several instrument
    classes -- confirms the freeze holds structurally (not just on the
    handful of live snapshots above), matching Fix #6BC's audit
    methodology in reverse (activation rate must now be exactly 0%)."""
    import api.core_router as cr
    from core.candle_cache import CandleCache

    symbols = ["EURUSD_i", "USDJPY_i", "XAUUSD_i", "BTCUSD_i", "XTIUSD_i"]
    tf = "M15"
    count = 300
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, [tf], count=count)

    engine = MomentumEngine(cr.candle_engine)
    checked = 0
    for symbol in symbols:
        candles = cr.candle_engine.get_snapshots(symbol, tf, count=count, cache=cache)
        for i in range(6, len(candles)):
            window = candles[i - 6:i]
            snap = engine.compute(window, symbol, tf)
            assert snap.confidence_drop is False
            checked += 1

    assert checked > 100


# ---------------------------------------------------------------------------
# No other preserved momentum field changes: momentum/slope/score/
# atr_normalized_momentum stay byte-identical to their pre-#6BD formulas.
# ---------------------------------------------------------------------------

def test_other_fields_unaffected_synthetic():
    engine = make_engine()
    candles = _sharp_deceleration_candles()
    snap = engine.compute(candles, "TEST", "M15")

    closes6 = [cand.close for cand in candles[-6:]]
    expected_slope2 = closes6[5] - closes6[2]
    expected_scaled = max(0.0, min(10.0, abs(expected_slope2) * 2.5))

    assert snap.score == expected_slope2
    assert snap.momentum == expected_scaled
    assert snap.slope == round(expected_slope2, 2)
    # atr_normalized_momentum is None here (only 6 candles, < ATR14_MIN_CANDLES)
    assert snap.atr_normalized_momentum is None


def test_other_fields_unaffected_live():
    import api.core_router as cr
    from core.candle_cache import CandleCache

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    checked_any = False
    for tf in timeframes:
        structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
        if structure is None:
            continue
        checked_any = True
        # These fields are untouched by Fix #6BD -- sanity bounds only,
        # not re-deriving the formulas (already covered by other test files).
        assert isinstance(structure.momentum, float)
        assert structure.atr_normalized_momentum is None or isinstance(structure.atr_normalized_momentum, float)

    assert checked_any


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
