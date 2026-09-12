"""Fix #4C — targeted regression: StructureEngine.context_zone/context_level
must come from the injected DemandEngine.get_context(), not detect_snd().

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_structure_engine_context.py -v
"""
import core.StructureEngine as structure_engine_module
from core.CandleEngine import CandleEngine
from core.demand_engine import DemandEngine
from core.StructureEngine import StructureEngine


class FakeDemandEngine:
    """Returns a fixed (zone_type, level) regardless of symbol/tf/cache —
    lets the test assert StructureEngine used exactly this value."""

    def __init__(self, zone_type, level):
        self.zone_type = zone_type
        self.level = level
        self.calls = []

    def get_context(self, symbol, tf, count=50, cache=None, zones=None):
        self.calls.append((symbol, tf, cache))
        return self.zone_type, self.level


def test_detect_snd_no_longer_imported_into_structure_engine():
    """StructureEngine.py must not import/reference detect_snd at all — it
    should not be able to detect SND independently even by accident."""
    assert not hasattr(structure_engine_module, "detect_snd"), (
        "detect_snd is still imported into StructureEngine.py — Fix #4C requires it gone from here "
        "(the function itself must stay in structure_utils.py, just not referenced here)"
    )


def test_structure_engine_uses_injected_demand_engine_context():
    """With a demand_engine injected, get_snapshot()'s context_zone/context_level
    must equal exactly what that engine's get_context() returns — proving
    delegation, not independent detection."""
    fake_demand = FakeDemandEngine(zone_type="supply", level=4321.5)
    engine = StructureEngine(candle_engine=CandleEngine(), demand_engine=fake_demand)

    # Isolate this test from real MT5 by feeding synthetic candles via cache.
    from core.core_models import CandleSnapshot

    candles = [
        CandleSnapshot(open=100 + i * 0.1, high=100.2 + i * 0.1, low=99.8 + i * 0.1, close=100.1 + i * 0.1, volume=10, timestamp=str(i))
        for i in range(30)
    ]

    class FakeCache:
        def get(self, symbol, tf, count=100):
            return candles[-count:] if count and count < len(candles) else candles

    snapshot = engine.get_snapshot("TEST", "M15", cache=FakeCache())
    assert snapshot is not None
    assert snapshot.context_zone == "supply"
    assert snapshot.context_level == 4321.5
    assert len(fake_demand.calls) == 1, "demand_engine.get_context() must be called exactly once, not zero or duplicated"
    assert fake_demand.calls[0][0:2] == ("TEST", "M15")


def test_structure_engine_without_demand_engine_degrades_to_neutral():
    """No demand_engine injected -> ("neutral", None), never a crash and
    never a fallback to independent SND detection."""
    from core.core_models import CandleSnapshot

    candles = [
        CandleSnapshot(open=100 + i * 0.1, high=100.2 + i * 0.1, low=99.8 + i * 0.1, close=100.1 + i * 0.1, volume=10, timestamp=str(i))
        for i in range(30)
    ]

    class FakeCache:
        def get(self, symbol, tf, count=100):
            return candles[-count:] if count and count < len(candles) else candles

    engine = StructureEngine(candle_engine=CandleEngine())  # no demand_engine
    snapshot = engine.get_snapshot("TEST", "M15", cache=FakeCache())
    assert snapshot is not None
    assert snapshot.context_zone == "neutral"
    assert snapshot.context_level is None


def test_live_structure_context_matches_demand_engine_get_context():
    """The actual required regression: for the same symbol/TF, live,
    StructureEngine's context must equal DemandEngine.get_context()
    exactly — not merely similar."""
    import api.core_router as cr
    from core.candle_cache import CandleCache

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4"]

    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    for tf in timeframes:
        snapshot = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
        assert snapshot is not None, f"{symbol}/{tf}: get_snapshot returned None"

        expected_zone, expected_level = cr.demand_engine.get_context(symbol, tf, cache=cache)

        assert snapshot.context_zone == expected_zone, (
            f"{symbol}/{tf}: StructureEngine.context_zone={snapshot.context_zone!r} != "
            f"DemandEngine.get_context()={expected_zone!r}"
        )
        assert snapshot.context_level == expected_level, (
            f"{symbol}/{tf}: StructureEngine.context_level={snapshot.context_level!r} != "
            f"DemandEngine.get_context()={expected_level!r}"
        )


if __name__ == "__main__":
    test_detect_snd_no_longer_imported_into_structure_engine()
    print("[PASS] detect_snd not imported into StructureEngine.py")

    test_structure_engine_uses_injected_demand_engine_context()
    print("[PASS] get_snapshot() uses injected demand_engine's get_context() verbatim")

    test_structure_engine_without_demand_engine_degrades_to_neutral()
    print("[PASS] no demand_engine injected -> neutral/None, no crash")

    test_live_structure_context_matches_demand_engine_get_context()
    print("[PASS] live: StructureEngine.context_zone/level == DemandEngine.get_context() on every timeframe")

    print("\nALL FIX #4C REGRESSION CHECKS PASSED")
