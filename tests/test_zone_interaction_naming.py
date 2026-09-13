"""Fix #6D — targeted tests for the canonical zone-interaction naming
(core.ShiftEngine.detect_zone_interaction()), additive/rename-only on top
of the pre-existing detect_shift() wick-touch formula (Fix #6A/#6B's
audit). detect_shift() is kept as a thin alias; StyleSnapshot gains
zone_interaction/zone_interaction_direction/zone_interaction_color
alongside the legacy shift_confirmed/shift_direction/shift_color fields,
mirrored to the exact same values.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_zone_interaction_naming.py -v
"""
from core.ShiftEngine import ShiftEngine
from core.core_models import CandleSnapshot


def make_candle(o, h, l, cl, ts="1"):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100, timestamp=ts)


class FakeCandleEngine:
    def __init__(self, candle):
        self._candle = candle

    def get_snapshots(self, symbol, tf, count=1, cache=None):
        return [self._candle] if self._candle is not None else []


class FakeStructureSnapshot:
    def __init__(self, symbol="TEST", context_zone="demand", context_level=100.0):
        self.symbol = symbol
        self.context_zone = context_zone
        self.context_level = context_level


# ---------------------------------------------------------------------------
# Same candle + same zone -> old and new fields equivalent.
# ---------------------------------------------------------------------------

def test_new_and_legacy_fields_equivalent_on_demand_touch():
    candle = make_candle(100.5, 100.6, 100.0, 100.4)  # low touches level exactly
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(candle))

    result = engine.detect_zone_interaction(structure, "M15", conviction=0.5)

    assert result["zone_interaction"] is True
    assert result["zone_interaction_direction"] == "Bullish"
    assert result["shifted"] == result["zone_interaction"]
    assert result["shift_direction"] == result["zone_interaction_direction"]
    assert result["shift_color"] == result["zone_interaction_color"]


def test_new_and_legacy_fields_equivalent_on_supply_touch():
    candle = make_candle(99.5, 100.0, 99.4, 99.8)  # high touches level exactly
    structure = FakeStructureSnapshot(context_zone="supply", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(candle))

    result = engine.detect_zone_interaction(structure, "M15", conviction=0.8)

    assert result["zone_interaction"] is True
    assert result["zone_interaction_direction"] == "Bearish"
    assert result["shifted"] == result["zone_interaction"]
    assert result["shift_direction"] == result["zone_interaction_direction"]
    assert result["shift_color"] == result["zone_interaction_color"]


def test_detect_shift_alias_produces_identical_dict_to_canonical_method():
    """detect_shift() must be a pure alias — same inputs, same complete
    dict (both canonical and legacy keys), not a divergent implementation."""
    candle = make_candle(100.5, 100.6, 100.0, 100.4)
    engine = ShiftEngine(FakeCandleEngine(candle))

    structure_a = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    result_canonical = engine.detect_zone_interaction(structure_a, "M15", conviction=0.5)

    structure_b = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    result_legacy = engine.detect_shift(structure_b, "M15", conviction=0.5)

    assert result_canonical == result_legacy


# ---------------------------------------------------------------------------
# No interaction -> both canonical and legacy read false/Neutral.
# ---------------------------------------------------------------------------

def test_no_interaction_when_price_far_from_zone():
    candle = make_candle(150.0, 151.0, 149.0, 150.5)  # nowhere near level=100.0
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(candle))

    result = engine.detect_zone_interaction(structure, "M15", conviction=0.5)

    assert result["zone_interaction"] is False
    assert result["zone_interaction_direction"] == "Neutral"
    assert result["shifted"] is False
    assert result["shift_direction"] == "Neutral"


def test_no_interaction_when_no_zone_or_level():
    structure = FakeStructureSnapshot(context_zone=None, context_level=None)
    engine = ShiftEngine(FakeCandleEngine(make_candle(100, 101, 99, 100)))

    result = engine.detect_zone_interaction(structure, "M15")

    assert result["zone_interaction"] is False
    assert result["shifted"] is False
    assert result["zone_interaction_direction"] == "Neutral"


def test_no_interaction_when_no_candles():
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(None))

    result = engine.detect_zone_interaction(structure, "M15")

    assert result["zone_interaction"] is False
    assert result["shifted"] is False
    assert result["zone_interaction_direction"] == "Neutral"


# ---------------------------------------------------------------------------
# Formula/tolerance unchanged: epsilon=0.0002, inclusive boundary.
# ---------------------------------------------------------------------------

def test_formula_tolerance_unchanged_demand_boundary():
    level = 100.0
    epsilon = 0.0002

    at_boundary = make_candle(100.5, 100.6, level + epsilon, 100.4)  # low == level+epsilon -> touches
    just_outside = make_candle(100.5, 100.6, level + epsilon + 0.00005, 100.4)  # just beyond -> no touch

    structure = FakeStructureSnapshot(context_zone="demand", context_level=level)

    engine_at = ShiftEngine(FakeCandleEngine(at_boundary))
    assert engine_at.detect_zone_interaction(structure, "M15")["zone_interaction"] is True

    engine_outside = ShiftEngine(FakeCandleEngine(just_outside))
    assert engine_outside.detect_zone_interaction(structure, "M15")["zone_interaction"] is False


def test_formula_tolerance_unchanged_supply_boundary():
    level = 100.0
    epsilon = 0.0002

    at_boundary = make_candle(99.5, level - epsilon, 99.4, 99.8)  # high == level-epsilon -> touches
    just_outside = make_candle(99.5, level - epsilon - 0.00005, 99.4, 99.8)  # just short -> no touch

    structure = FakeStructureSnapshot(context_zone="supply", context_level=level)

    engine_at = ShiftEngine(FakeCandleEngine(at_boundary))
    assert engine_at.detect_zone_interaction(structure, "M15")["zone_interaction"] is True

    engine_outside = ShiftEngine(FakeCandleEngine(just_outside))
    assert engine_outside.detect_zone_interaction(structure, "M15")["zone_interaction"] is False


def test_choch_or_structure_fields_never_consulted():
    """Fix #6D's own constraint: this mechanism must not read CHoCH/BOS or
    any other structure evidence — only context_zone/context_level. A
    FakeStructureSnapshot with no structure_valid/structure_type attributes
    at all must still work fine, proving nothing else is accessed."""
    candle = make_candle(100.5, 100.6, 100.0, 100.4)
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    assert not hasattr(structure, "structure_valid")
    assert not hasattr(structure, "structure_type")

    engine = ShiftEngine(FakeCandleEngine(candle))
    result = engine.detect_zone_interaction(structure, "M15")
    assert result["zone_interaction"] is True


# ---------------------------------------------------------------------------
# Live regression: current /core/output-facing behavior unchanged, both
# canonical and legacy StyleSnapshot fields present and consistent.
# ---------------------------------------------------------------------------

def test_live_style_snapshot_exposes_canonical_and_legacy_zone_fields_consistently():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.StyleEngine import get_style_snapshot

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    checked_any = False
    for tf in timeframes:
        mode = "scalping" if tf in ("M1", "M5", "M15", "M30") else "swing"
        snapshot = get_style_snapshot(
            symbol, tf, mode,
            cr.bias_engine, cr.momentum_engine, cr.demand_engine, cr.structure_engine, cr.shift_engine,
            cache=cache,
        )
        checked_any = True
        assert hasattr(snapshot, "zone_interaction")
        assert hasattr(snapshot, "zone_interaction_direction")
        assert hasattr(snapshot, "zone_interaction_color")
        assert snapshot.zone_interaction == snapshot.shift_confirmed
        assert snapshot.zone_interaction_direction == snapshot.shift_direction
        assert snapshot.zone_interaction_color == snapshot.shift_color

    assert checked_any


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
