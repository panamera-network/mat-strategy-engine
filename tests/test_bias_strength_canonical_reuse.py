"""Fix #6L — targeted tests proving BiasEngine reuses StructureEngine's
already-computed StrengthDiagnostic (26-candle FETCH_COUNT window) instead
of calling StrengthEngine.compute_strength() a second time, whenever a
structure_snapshot is available (Fix #6K's audit: the two independently-
computed values disagreed because they used differently-sized candle
windows for the same symbol/tf).

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_bias_strength_canonical_reuse.py -v
"""
from core.BiasEngine import BiasEngine
from core.core_models import CandleSnapshot, StrengthDiagnostic


def c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100, timestamp=ts)


FALLBACK_CANDLES = [
    c(100, 101, 99, 101, "1"),
    c(101, 102, 100, 102, "2"),
    c(102, 103, 101, 100, "3"),
    c(100, 101, 99, 101, "4"),
    c(101, 102, 100, 99, "5"),
]


class SpyStrengthEngine:
    def __init__(self):
        self.calls = 0

    def compute_strength(self, candles):
        self.calls += 1
        return StrengthDiagnostic(1.23, 0.45, 0.67)


class FakeCandleEngine:
    def get_snapshots(self, symbol, tf, cache=None, count=100):
        return FALLBACK_CANDLES


class FakeStructure:
    def __init__(self, strength, body_ratio, momentum_slope,
                 structure_valid=False, structure_type="None", structure_direction="Neutral", pre_break_trend=None):
        self.strength = strength
        self.body_ratio = body_ratio
        self.momentum_slope = momentum_slope
        self.structure_valid = structure_valid
        self.structure_type = structure_type
        self.structure_direction = structure_direction
        self.pre_break_trend = pre_break_trend


def make_engine():
    spy = SpyStrengthEngine()
    engine = BiasEngine(candle_engine=FakeCandleEngine(), strength_engine=spy)
    return engine, spy


# ---------------------------------------------------------------------------
# get_bias(): structure_snapshot available -> reuse, no second compute call.
# ---------------------------------------------------------------------------

def test_get_bias_reuses_structure_strength_no_second_compute():
    engine, spy = make_engine()
    structure = FakeStructure(strength=7.5, body_ratio=0.62, momentum_slope=1.4)

    snapshot = engine.get_bias("XAUUSD_i", "M15", structure_snapshot=structure)

    assert spy.calls == 0
    assert snapshot.strength_diagnostic.strength == 7.5
    assert snapshot.strength_diagnostic.avg_body_ratio == 0.62
    assert snapshot.strength_diagnostic.momentum_slope == 1.4


def test_get_bias_strength_equals_structure_strength_exactly():
    engine, spy = make_engine()
    structure = FakeStructure(strength=3.14, body_ratio=0.5, momentum_slope=-2.0)

    snapshot = engine.get_bias("EURUSD_i", "H1", structure_snapshot=structure)

    assert snapshot.strength_diagnostic.strength == structure.strength


# ---------------------------------------------------------------------------
# get_bias_map(): same reuse, per timeframe.
# ---------------------------------------------------------------------------

def test_get_bias_map_reuses_structure_strength_per_tf_no_second_compute():
    engine, spy = make_engine()
    structure_map = {
        "M1": FakeStructure(strength=2.0, body_ratio=0.2, momentum_slope=0.1),
        "M5": FakeStructure(strength=9.9, body_ratio=0.9, momentum_slope=-3.3),
    }

    bias_map = engine.get_bias_map("XAUUSD_i", ["M1", "M5"], structure_map=structure_map)

    assert spy.calls == 0
    assert bias_map["M1"]["strength_diagnostic"].strength == 2.0
    assert bias_map["M1"]["strength_diagnostic"].avg_body_ratio == 0.2
    assert bias_map["M1"]["strength_diagnostic"].momentum_slope == 0.1
    assert bias_map["M5"]["strength_diagnostic"].strength == 9.9
    assert bias_map["M5"]["strength_diagnostic"].avg_body_ratio == 0.9
    assert bias_map["M5"]["strength_diagnostic"].momentum_slope == -3.3


# ---------------------------------------------------------------------------
# Existing fallback behavior unchanged: no structure_snapshot available at
# all (and no structure_engine injected) -> still computes independently.
# ---------------------------------------------------------------------------

def test_get_bias_without_structure_snapshot_still_computes_independently():
    engine, spy = make_engine()

    snapshot = engine.get_bias("XAUUSD_i", "M15", structure_snapshot=None)

    assert spy.calls == 1
    assert snapshot.strength_diagnostic.strength == 1.23
    assert snapshot.strength_diagnostic.avg_body_ratio == 0.45
    assert snapshot.strength_diagnostic.momentum_slope == 0.67


def test_get_bias_map_without_structure_map_still_computes_independently():
    engine, spy = make_engine()

    bias_map = engine.get_bias_map("XAUUSD_i", ["M1", "M5"], structure_map=None)

    assert spy.calls == 2  # once per tf, unchanged from before this fix
    assert bias_map["M1"]["strength_diagnostic"].strength == 1.23
    assert bias_map["M5"]["strength_diagnostic"].strength == 1.23


def test_candle_ratio_bias_fallback_still_uses_candles_unchanged():
    """This fix must not touch evaluate_bias()'s own candle-fetch/fallback
    logic — bias_label/bias_score must still come from the candle ratio
    when structure is invalid, independent of the strength reuse change."""
    engine, spy = make_engine()
    invalid_structure = FakeStructure(strength=5.0, body_ratio=0.5, momentum_slope=0.0, structure_valid=False)

    snapshot = engine.get_bias("XAUUSD_i", "M15", structure_snapshot=invalid_structure)

    # 3 up-closes, 2 down-closes among FALLBACK_CANDLES -> (3-2)/5*10 = 2.0 -> uptrend
    assert snapshot.bias_label == "uptrend"
    assert snapshot.bias_score == 2.0
    # Strength still reuses the (invalid-structure) snapshot's values, per
    # this fix's rule — reuse doesn't gate on structure_valid, only on
    # structure_snapshot being present at all.
    assert snapshot.strength_diagnostic.strength == 5.0
    assert spy.calls == 0


# ---------------------------------------------------------------------------
# Live regression: real pipeline, real MT5 data.
# ---------------------------------------------------------------------------

def test_live_compute_strength_called_exactly_once_per_symbol_tf():
    """StrengthEngine.compute_strength() is a plain instance method — both
    StructureEngine.py's module-level strength_engine and api/core_router's
    injected one are separate StrengthEngine() instances (stateless, so
    functionally interchangeable), so patch the class method to count every
    call regardless of which instance makes it."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.StrengthEngine import StrengthEngine

    symbol = "XAUUSD_i"
    tf = "M15"
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], [tf], count=100)

    calls = []
    original = StrengthEngine.compute_strength

    def counting_compute_strength(self, candles):
        calls.append(1)
        return original(self, candles)

    StrengthEngine.compute_strength = counting_compute_strength
    try:
        structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
        assert structure is not None
        calls.clear()  # only count calls from here on (get_bias's own resolution)
        bias = cr.bias_engine.get_bias(symbol, tf, structure_snapshot=structure, cache=cache)
    finally:
        StrengthEngine.compute_strength = original

    assert len(calls) == 0  # get_bias() reused the already-computed structure strength
    assert bias.strength_diagnostic.strength == structure.strength


def test_live_bias_strength_equals_structure_strength():
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
        bias = cr.bias_engine.get_bias(symbol, tf, structure_snapshot=structure, cache=cache)
        checked_any = True
        assert bias.strength_diagnostic.strength == structure.strength
        assert bias.strength_diagnostic.avg_body_ratio == structure.body_ratio
        assert bias.strength_diagnostic.momentum_slope == structure.momentum_slope

    assert checked_any


def test_live_suppression_reads_same_canonical_value_as_bias():
    """At the time this fix landed, SuppressionEngine.detect_suppression()
    read structure.strength directly inside get_snapshot(), and bias reused
    that exact same value — so the two could never disagree about whether
    strength is low. Fix #6AO later retired detect_suppression() from the
    live get_snapshot() path entirely (structure.suppression/
    suppression_reason are now always False/"" -- Fix #6AN's audit found
    ~83-94% suppression driven almost entirely by this one strength<4
    condition, with no evidence the blocked candidates were worse). This
    test's own assertion is about bias/structure strength agreement, not
    about detect_suppression() being invoked, so it still holds -- updated
    docstring/import only, no behavior change."""
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
        bias = cr.bias_engine.get_bias(symbol, tf, structure_snapshot=structure, cache=cache)
        checked_any = True
        suppression_would_trigger_on_strength = structure.strength < 4
        bias_strength_would_trigger_same = bias.strength_diagnostic.strength < 4
        assert suppression_would_trigger_on_strength == bias_strength_would_trigger_same
        # Fix #6AO — the legacy gate no longer runs live; confirm the
        # always-inactive canonical state directly.
        assert structure.suppression is False
        assert structure.suppression_reason == ""

    assert checked_any


def test_live_output_bias_strength_follows_canonical_structure_strength():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    # Canonical values, fetched independently via the same cache.
    canonical = {}
    for tf in timeframes:
        structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
        if structure is not None:
            canonical[tf] = structure.strength

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=[symbol],
    )
    assert "error" not in out[symbol]
    bias_ordered = out[symbol]["bias"]

    checked_any = False
    for tf, expected_strength in canonical.items():
        if tf not in bias_ordered:
            continue
        checked_any = True
        assert bias_ordered[tf]["strength"] == expected_strength

    assert checked_any


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
