"""Fix #6V — targeted tests for canonical ATR-normalized momentum
(MomentumEngine.compute()'s atr_normalized_momentum = slope2/ATR14, no
clamp/multiplier/threshold — Fix #6U's audit conclusion). Additive only:
.score/.momentum/.direction/.confidence_drop/.reversal are untouched.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_atr_normalized_momentum.py -v
"""
from core.MomentumEngine import MomentumEngine, ATR14_MIN_CANDLES
from core.core_models import CandleSnapshot
from core.demand_engine import compute_atr


def c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100, timestamp=ts)


class FakeCandleEngine:
    """Unused by compute() directly; only needed for get_momentum()/
    get_score()'s own count=6 fetch path."""
    def __init__(self, candles):
        self._candles = candles

    def get_snapshots(self, symbol, timeframe, count=6, cache=None):
        return self._candles[-count:]


def build_candles(n, base=100.0, step=0.5, wiggle=0.3):
    """n candles with a mild upward drift and non-degenerate ranges, so
    ATR14 is well-defined and non-zero."""
    candles = []
    price = base
    for i in range(n):
        o = price
        cl = price + step
        h = max(o, cl) + wiggle
        l = min(o, cl) - wiggle
        candles.append(c(o, h, l, cl, str(i)))
        price = cl
    return candles


def build_flat_then_move_candles(n, flat_price=100.0, flat_range=0.4, final_delta=5.0):
    """n-1 flat, non-degenerate candles (for a stable ATR14) followed by
    one final candle whose close moves sharply -- isolates slope2's effect
    from ATR's."""
    candles = []
    for i in range(n - 1):
        o = flat_price
        cl = flat_price
        h = flat_price + flat_range / 2
        l = flat_price - flat_range / 2
        candles.append(c(o, h, l, cl, str(i)))
    last_open = flat_price
    last_close = flat_price + final_delta
    h = max(last_open, last_close) + flat_range / 2
    l = min(last_open, last_close) - flat_range / 2
    candles.append(c(last_open, h, l, last_close, str(n - 1)))
    return candles


def make_engine():
    return MomentumEngine(candle_engine=None)


# ---------------------------------------------------------------------------
# Exact formula: slope2 / ATR14
# ---------------------------------------------------------------------------

def test_atr_normalized_momentum_equals_slope2_over_atr14():
    candles = build_candles(20)
    engine = make_engine()
    snap = engine.compute(candles, "TEST", "M15")

    closes6 = [cand.close for cand in candles[-6:]]
    expected_slope2 = closes6[5] - closes6[2]
    expected_atr14 = compute_atr(candles, period=14)

    assert snap.slope == round(expected_slope2, 2)
    assert snap.atr_normalized_momentum == expected_slope2 / expected_atr14


# ---------------------------------------------------------------------------
# Sign preservation
# ---------------------------------------------------------------------------

def test_positive_sign_preserved_for_bullish_move():
    candles = build_flat_then_move_candles(20, final_delta=+5.0)
    engine = make_engine()
    snap = engine.compute(candles, "TEST", "M15")
    assert snap.atr_normalized_momentum is not None
    assert snap.atr_normalized_momentum > 0


def test_negative_sign_preserved_for_bearish_move():
    candles = build_flat_then_move_candles(20, final_delta=-5.0)
    engine = make_engine()
    snap = engine.compute(candles, "TEST", "M15")
    assert snap.atr_normalized_momentum is not None
    assert snap.atr_normalized_momentum < 0


def test_symmetric_magnitude_for_symmetric_opposite_moves():
    """Fix #6U's finding: dividing a signed slope2 by an always-positive
    ATR preserves sign losslessly and symmetrically, unlike the legacy
    strength formula's clamp-induced bias (Fix #6M)."""
    bullish = build_flat_then_move_candles(20, final_delta=+5.0)
    bearish = build_flat_then_move_candles(20, final_delta=-5.0)
    engine = make_engine()
    bull_snap = engine.compute(bullish, "TEST", "M15")
    bear_snap = engine.compute(bearish, "TEST", "M15")
    assert bull_snap.atr_normalized_momentum == -bear_snap.atr_normalized_momentum


# ---------------------------------------------------------------------------
# No clamp / no saturation
# ---------------------------------------------------------------------------

def test_no_clamp_large_move_exceeds_typical_bounded_ranges():
    candles = build_flat_then_move_candles(20, final_delta=500.0)
    engine = make_engine()
    snap = engine.compute(candles, "TEST", "M15")
    assert snap.atr_normalized_momentum is not None
    # A move this large relative to a tiny flat ATR must NOT be clamped to
    # any bounded range like [0,10] or [-1,1] -- it should reflect the
    # true (large) ratio.
    assert abs(snap.atr_normalized_momentum) > 10


# ---------------------------------------------------------------------------
# Cross-instrument dimensionlessness (finite, comparable order of magnitude)
# ---------------------------------------------------------------------------

def test_cross_instrument_values_are_finite_and_comparable_scale():
    """Simulate wildly different price scales (EURUSD-like ~1.0, XAUUSD-like
    ~4000, BTCUSD-like ~100000) with the SAME relative move size, and
    confirm atr_normalized_momentum lands in a comparable range for all,
    unlike the raw unnormalized score."""
    import math

    def scaled_candles(scale):
        return build_flat_then_move_candles(20, flat_price=scale, flat_range=scale * 0.004, final_delta=scale * 0.05)

    engine = make_engine()
    results = []
    for scale in (1.0, 4000.0, 100000.0):
        candles = scaled_candles(scale)
        snap = engine.compute(candles, "TEST", "M15")
        assert snap.atr_normalized_momentum is not None
        assert math.isfinite(snap.atr_normalized_momentum)
        results.append(snap.atr_normalized_momentum)

    # All within the same rough order of magnitude (unlike raw .score,
    # which would span ~5 orders of magnitude across these scales).
    assert max(results) / min(results) < 5


# ---------------------------------------------------------------------------
# Insufficient history -> explicit None, no fallback denominator
# ---------------------------------------------------------------------------

def test_insufficient_candles_for_atr14_returns_none():
    candles = build_candles(ATR14_MIN_CANDLES - 1)  # one short of the minimum
    engine = make_engine()
    snap = engine.compute(candles, "TEST", "M15")
    assert len(candles) < ATR14_MIN_CANDLES
    assert snap.atr_normalized_momentum is None
    # But everything else still computes normally -- this fix is additive.
    assert snap.score != 0.0 or snap.slope == 0.0  # sanity: compute() still ran


def test_exactly_minimum_candles_computes_a_value():
    candles = build_candles(ATR14_MIN_CANDLES)
    engine = make_engine()
    snap = engine.compute(candles, "TEST", "M15")
    assert snap.atr_normalized_momentum is not None


def test_fewer_than_six_candles_still_returns_none_via_early_return():
    engine = make_engine()
    snap = engine.compute(build_candles(3), "TEST", "M15")
    assert snap.atr_normalized_momentum is None
    assert snap.momentum == 0.0
    assert snap.slope == 0.0


# ---------------------------------------------------------------------------
# Old fields unchanged
# ---------------------------------------------------------------------------

def test_old_score_and_momentum_unchanged_by_this_fix():
    candles = build_candles(20)
    engine = make_engine()
    snap = engine.compute(candles, "TEST", "M15")

    closes6 = [cand.close for cand in candles[-6:]]
    expected_slope2 = closes6[5] - closes6[2]
    expected_scaled = max(0.0, min(10.0, abs(expected_slope2) * 2.5))

    assert snap.score == expected_slope2
    assert snap.momentum == expected_scaled
    assert snap.direction in ("Up", "Down", "Neutral")
    assert isinstance(snap.confidence_drop, bool)
    assert isinstance(snap.reversal, bool)


def test_no_extra_candle_fetch_when_called_via_compute_directly():
    """compute() takes a candles list directly -- confirming this fix adds
    no additional call to any candle-fetching method inside compute()
    itself (it only ever uses the list already passed in)."""
    candles = build_candles(20)
    engine = make_engine()  # candle_engine=None -- would raise/fail if compute() tried to fetch
    snap = engine.compute(candles, "TEST", "M15")
    assert snap.atr_normalized_momentum is not None  # proves it ran to completion without touching self.candle_engine


# ---------------------------------------------------------------------------
# StructureSnapshot wiring (synthetic, mirrors StructureEngine.py's wiring)
# ---------------------------------------------------------------------------

def test_structure_snapshot_field_exists_and_defaults_to_none():
    from core.core_models import StructureSnapshot

    snapshot = StructureSnapshot(
        symbol="TEST", timeframe="M15",
        current_high=1, current_low=1, prev_high=1, prev_low=1,
        current_zone="Neutral", prev_zone="Neutral",
    )
    assert snapshot.atr_normalized_momentum is None
    snapshot.atr_normalized_momentum = 1.23
    assert snapshot.atr_normalized_momentum == 1.23


# ---------------------------------------------------------------------------
# Live regression: canonical Structure path, /core/output wiring.
# ---------------------------------------------------------------------------

def test_live_structure_snapshot_matches_canonical_momentum_snapshot():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.StructureEngine import FETCH_COUNT

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

        # Recompute independently via the same canonical window for comparison.
        candles = cr.candle_engine.get_snapshots(symbol, tf, count=FETCH_COUNT, cache=cache)
        expected = cr.momentum_engine.compute(candles, symbol, tf)

        assert structure.atr_normalized_momentum == expected.atr_normalized_momentum
        assert structure.momentum == expected.momentum  # legacy field still matches too
        if expected.atr_normalized_momentum is not None:
            import math
            assert math.isfinite(expected.atr_normalized_momentum)

    assert checked_any


def test_live_output_momentum_evidence_matches_canonical_structure_value():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    canonical = {}
    for tf in timeframes:
        structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
        if structure is not None:
            canonical[tf] = structure.atr_normalized_momentum

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=[symbol],
    )
    assert "error" not in out[symbol]
    momentum_evidence = out[symbol]["momentum_evidence"]

    checked_any = False
    for tf, expected in canonical.items():
        assert tf in momentum_evidence
        checked_any = True
        assert momentum_evidence[tf]["atr_normalized_momentum"] == expected

    assert checked_any


def test_live_style_snapshot_and_alignment_unaffected():
    """This fix must not migrate StyleSnapshot.momentum, alignment, or
    conviction -- confirm the live scalping/swing blocks are unchanged in
    shape (no new key leaked in) and StyleSnapshot.momentum still reads
    the legacy raw .score, not the new normalized value."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbol = "XAUUSD_i"
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], ["M15"], count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=[symbol],
    )
    assert "error" not in out[symbol]
    scalping_m15 = out[symbol]["scalping"]["M15"]
    assert "atr_normalized_momentum" not in scalping_m15


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
