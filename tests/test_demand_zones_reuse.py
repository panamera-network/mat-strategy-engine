"""Fix #4D3 — targeted regression: DemandEngine.detect_zones() must run
exactly once per (symbol, tf) within one /core/output build. Before this
fix it ran twice — once via StructureEngine.get_snapshot() ->
DemandEngine.get_context(), once via Output._build_supply_demand_zones() ->
DemandEngine.get_zones().

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_demand_zones_reuse.py -v
"""
from core.demand_engine import DemandEngine, SupplyDemandZone


def make_zone(zone_type, top, bottom, valid=True):
    return SupplyDemandZone(type=zone_type, top=top, bottom=bottom, valid=valid)


def make_candle(o, h, l, c):
    from core.core_models import CandleSnapshot
    return CandleSnapshot(open=o, high=h, low=l, close=c, volume=100, timestamp="0")


class FakeCandleEngine:
    def __init__(self, candles):
        self.candles = candles

    def get_snapshots(self, symbol, tf, count=50, cache=None):
        return self.candles


# ── DemandEngine.get_context() accepts a precomputed zones list ─────────

def test_get_context_with_zones_skips_detect_zones():
    """Passing `zones=` must bypass detect_zones() entirely — proven by
    monkeypatching detect_zones to explode if called."""
    import core.demand_engine as demand_engine_module

    def exploding_detect_zones(candles):
        raise AssertionError("detect_zones() must not be called when zones= is supplied")

    original = demand_engine_module.detect_zones
    demand_engine_module.detect_zones = exploding_detect_zones
    try:
        engine = DemandEngine(candle_engine=FakeCandleEngine([make_candle(99, 101, 99, 100.0)]))
        precomputed = [make_zone("demand", top=101, bottom=100.5)]
        zone_type, level = engine.get_context("X", "M15", zones=precomputed)
        assert zone_type == "demand"
        assert level == 101
    finally:
        demand_engine_module.detect_zones = original


def test_get_context_without_zones_still_computes_it():
    """Backward compatibility: omitting zones= (every pre-4D3 caller) must
    still compute detect_zones() itself, unchanged."""
    engine = DemandEngine(candle_engine=FakeCandleEngine([make_candle(99, 101, 99, 100.0)]))
    # No zones passed -> real detect_zones() runs on the fake single-candle
    # list (ATR needs >= 2 candles, so this legitimately returns neutral).
    zone_type, level = engine.get_context("X", "M15")
    assert zone_type == "neutral"
    assert level is None


def test_get_context_zones_result_matches_non_reused_path():
    """The reused-zones path and the recompute-it-yourself path must agree
    on the same input — proving reuse doesn't change selector behavior."""
    import core.demand_engine as demand_engine_module

    candles = [make_candle(100 + i * 0.1, 100.2 + i * 0.1, 99.8 + i * 0.1, 100.1 + i * 0.1) for i in range(30)]
    engine = DemandEngine(candle_engine=FakeCandleEngine(candles))

    zones = demand_engine_module.detect_zones(candles)
    zone_type_direct, level_direct = engine.get_context("X", "M15", count=50)
    zone_type_reused, level_reused = engine.get_context("X", "M15", count=50, zones=zones)

    assert zone_type_direct == zone_type_reused
    assert level_direct == level_reused


# ── Live: exactly 1 detect_zones() call per (symbol, tf) in /core/output ──

def test_live_detect_zones_called_once_per_symbol_tf():
    """The actual required regression: wrap detect_zones() with a counter
    and run a real /core/output build for one symbol — every timeframe
    must show exactly 1 call, not 2."""
    import core.demand_engine as demand_engine_module
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]

    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    call_counts = {}
    original_detect_zones = demand_engine_module.detect_zones

    def counting_detect_zones(candles):
        # Identify the (symbol, tf) this call belongs to by candle identity
        # isn't possible directly, so instead count total calls and compare
        # against the number of (symbol, tf) pairs processed.
        counting_detect_zones.total += 1
        return original_detect_zones(candles)

    counting_detect_zones.total = 0
    demand_engine_module.detect_zones = counting_detect_zones
    try:
        build_multi_symbol_output(
            bias_engine=cr.bias_engine,
            candle_engine=cr.candle_engine,
            momentum_engine=cr.momentum_engine,
            demand_engine=cr.demand_engine,
            shift_engine=cr.shift_engine,
            structure_engine=cr.structure_engine,
            cache=cache,
            symbols=[symbol],
        )
    finally:
        demand_engine_module.detect_zones = original_detect_zones

    assert counting_detect_zones.total == len(timeframes), (
        f"detect_zones() called {counting_detect_zones.total} times for {len(timeframes)} "
        f"timeframes — expected exactly 1 per (symbol, tf), was 2 before Fix #4D3"
    )


if __name__ == "__main__":
    test_get_context_with_zones_skips_detect_zones()
    print("[PASS] get_context(zones=...) skips detect_zones() entirely")

    test_get_context_without_zones_still_computes_it()
    print("[PASS] get_context() without zones= still computes detect_zones() (backward compat)")

    test_get_context_zones_result_matches_non_reused_path()
    print("[PASS] reused-zones path agrees with recompute-it-yourself path")

    test_live_detect_zones_called_once_per_symbol_tf()
    print("[PASS] live: detect_zones() called exactly once per (symbol, tf) across a full /core/output build")

    print("\nALL FIX #4D3 REGRESSION CHECKS PASSED")
