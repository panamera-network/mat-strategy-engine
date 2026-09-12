"""Fix #4D1 — targeted regression: StyleEngine.get_style_snapshot() must
reuse StructureSnapshot.context_zone for StyleSnapshot.demand instead of
calling DemandEngine.get_label() a second time (Fix #4C already made
context_zone the canonical DemandEngine.get_context() result).

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_style_engine_zone_label.py -v
"""
from core.StyleEngine import get_style_snapshot


class FakeStructureSnapshot:
    def __init__(self, context_zone):
        self.context_zone = context_zone
        self.structure_type = "BOS"


class FakeStructureEngine:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def get_snapshot(self, symbol, tf, cache=None):
        return self.snapshot


class FakeBias:
    bias_label = "bullish"
    bias_score = 3.0


class FakeBiasEngine:
    def get_bias(self, symbol, tf, structure_snapshot=None, cache=None):
        return FakeBias()


class FakeMomentum:
    score = 0.1


class FakeMomentumEngine:
    def get_momentum(self, symbol, tf, cache=None):
        return FakeMomentum()


class ExplodingDemandEngine:
    """If get_style_snapshot() still calls get_label()/get_context(), this
    blows up the test loudly instead of silently returning a plausible value."""

    def get_label(self, symbol, tf, cache=None):
        raise AssertionError("DemandEngine.get_label() must not be called from get_style_snapshot() anymore (Fix #4D1)")

    def get_context(self, symbol, tf, count=50, cache=None):
        raise AssertionError("DemandEngine.get_context() must not be called from get_style_snapshot() anymore (Fix #4D1)")

    def get_zones(self, symbol, tf, count=50, cache=None):
        raise AssertionError("DemandEngine.get_zones() must not be called from get_style_snapshot() (never was)")


class FakeShiftResult(dict):
    pass


class FakeShiftEngine:
    def detect_shift(self, structure, tf, conviction=None, cache=None):
        return {"shifted": False, "shift_direction": "none", "shift_color": "gray"}

    def get_last_shift_change_time(self, symbol, tf):
        return None


def test_style_snapshot_demand_equals_structure_context_zone():
    """StyleSnapshot.demand must equal exactly StructureSnapshot.context_zone
    — proving get_style_snapshot() reused the field instead of recomputing
    its own label."""
    structure = FakeStructureSnapshot(context_zone="supply")
    snapshot = get_style_snapshot(
        symbol="TEST", tf="M15", mode="scalping",
        bias_engine=FakeBiasEngine(),
        momentum_engine=FakeMomentumEngine(),
        demand_engine=ExplodingDemandEngine(),
        structure_engine=FakeStructureEngine(structure),
        shift_engine=FakeShiftEngine(),
    )
    assert snapshot.demand == "supply"
    assert snapshot.demand == structure.context_zone


def test_get_label_not_called_in_live_style_path():
    """A demand_engine whose get_label()/get_context() raise must not blow
    up get_style_snapshot() — proves neither is reached anymore."""
    structure = FakeStructureSnapshot(context_zone="demand")
    snapshot = get_style_snapshot(
        symbol="TEST", tf="H1", mode="swing",
        bias_engine=FakeBiasEngine(),
        momentum_engine=FakeMomentumEngine(),
        demand_engine=ExplodingDemandEngine(),
        structure_engine=FakeStructureEngine(structure),
        shift_engine=FakeShiftEngine(),
    )
    assert snapshot.demand == "demand"


def test_live_style_snapshot_matches_structure_context_zone():
    """Live regression: for real XAUUSD_i data, get_style_snapshot()'s
    StyleSnapshot.demand must equal the StructureSnapshot.context_zone
    fetched independently for the same symbol/tf."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.StyleEngine import get_style_snapshot as live_get_style_snapshot

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M15", "H1", "H4"]

    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    for tf in timeframes:
        structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
        assert structure is not None, f"{symbol}/{tf}: get_snapshot returned None"

        snapshot = live_get_style_snapshot(
            symbol, tf, "scalping",
            cr.bias_engine, cr.momentum_engine,
            cr.demand_engine, cr.structure_engine, cr.shift_engine,
            cache=cache,
        )
        assert snapshot.demand == structure.context_zone, (
            f"{symbol}/{tf}: StyleSnapshot.demand={snapshot.demand!r} != "
            f"StructureSnapshot.context_zone={structure.context_zone!r}"
        )


if __name__ == "__main__":
    test_style_snapshot_demand_equals_structure_context_zone()
    print("[PASS] StyleSnapshot.demand == structure.context_zone")

    test_get_label_not_called_in_live_style_path()
    print("[PASS] get_style_snapshot() never touches an exploding DemandEngine")

    test_live_style_snapshot_matches_structure_context_zone()
    print("[PASS] live: StyleSnapshot.demand == StructureSnapshot.context_zone across timeframes")

    print("\nALL FIX #4D1 REGRESSION CHECKS PASSED")
