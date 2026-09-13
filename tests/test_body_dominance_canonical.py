"""Fix #6O — targeted tests for the canonical body_dominance evidence
(Fix #6M/#6N's audit conclusion): a read-only alias of the existing
avg_body_ratio/body_ratio values, raw [0,1] range, no ×10, no new formula,
no extra compute_strength() call, no change to the existing "strength"
output.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_body_dominance_canonical.py -v
"""
from core.core_models import StrengthDiagnostic


# ---------------------------------------------------------------------------
# StrengthDiagnostic.body_dominance
# ---------------------------------------------------------------------------

def test_body_dominance_equals_avg_body_ratio():
    diag = StrengthDiagnostic(strength=6.5, avg_body_ratio=0.42, momentum_slope=1.1)
    assert diag.body_dominance == diag.avg_body_ratio == 0.42


def test_body_dominance_is_read_only_alias_not_second_field():
    """Changing avg_body_ratio must be reflected in body_dominance
    immediately -- proving it's a live alias, not a snapshot copy that
    could drift."""
    diag = StrengthDiagnostic(strength=0.0, avg_body_ratio=0.1, momentum_slope=0.0)
    assert diag.body_dominance == 0.1
    diag.avg_body_ratio = 0.99
    assert diag.body_dominance == 0.99


def test_body_dominance_range_matches_avg_body_ratio_bounds():
    for v in (0.0, 0.25, 0.5, 0.75, 1.0):
        diag = StrengthDiagnostic(strength=0.0, avg_body_ratio=v, momentum_slope=0.0)
        assert 0.0 <= diag.body_dominance <= 1.0
        assert diag.body_dominance == v


def test_to_dict_includes_body_dominance_alongside_existing_keys():
    diag = StrengthDiagnostic(strength=3.0, avg_body_ratio=0.33, momentum_slope=-0.5)
    d = diag.to_dict()
    assert d["strength"] == 3.0
    assert d["avg_body_ratio"] == 0.33
    assert d["momentum_slope"] == -0.5
    assert d["body_dominance"] == 0.33


def test_old_strength_untouched_by_this_fix():
    diag = StrengthDiagnostic(strength=7.77, avg_body_ratio=0.5, momentum_slope=0.0)
    assert diag.strength == 7.77  # unchanged formula/value, not derived from body_dominance


# ---------------------------------------------------------------------------
# StructureSnapshot.body_dominance
# ---------------------------------------------------------------------------

def test_structure_snapshot_body_dominance_equals_body_ratio():
    from core.core_models import StructureSnapshot

    snapshot = StructureSnapshot(
        symbol="TEST", timeframe="M15",
        current_high=1, current_low=1, prev_high=1, prev_low=1,
        current_zone="Neutral", prev_zone="Neutral",
    )
    snapshot.body_ratio = 0.61
    assert snapshot.body_dominance == 0.61 == snapshot.body_ratio


# ---------------------------------------------------------------------------
# Live regression: reuse chain, output wiring, no extra compute.
# ---------------------------------------------------------------------------

def test_live_bias_and_structure_body_dominance_identical():
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
        assert 0.0 <= structure.body_dominance <= 1.0
        assert structure.body_dominance == structure.body_ratio
        assert bias.strength_diagnostic.body_dominance == structure.body_dominance
        # old strength output unchanged by this fix
        assert bias.strength_diagnostic.strength == structure.strength

    assert checked_any


def test_live_no_extra_compute_strength_calls():
    """Same guarantee Fix #6L already established -- this fix must not
    reintroduce a second compute_strength() call."""
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
        calls.clear()
        bias = cr.bias_engine.get_bias(symbol, tf, structure_snapshot=structure, cache=cache)
    finally:
        StrengthEngine.compute_strength = original

    assert len(calls) == 0
    assert bias.strength_diagnostic.body_dominance == structure.body_dominance


def test_live_output_bias_exposes_body_dominance_and_unchanged_strength():
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
            canonical[tf] = (structure.strength, structure.body_dominance)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=[symbol],
    )
    assert "error" not in out[symbol]
    bias_ordered = out[symbol]["bias"]

    checked_any = False
    for tf, (expected_strength, expected_body_dominance) in canonical.items():
        if tf not in bias_ordered:
            continue
        checked_any = True
        assert bias_ordered[tf]["strength"] == expected_strength
        assert bias_ordered[tf]["body_dominance"] == expected_body_dominance
        assert 0.0 <= bias_ordered[tf]["body_dominance"] <= 1.0

    assert checked_any


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
