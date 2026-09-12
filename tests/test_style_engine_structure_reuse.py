"""Fix #4D2 — targeted regression: StyleEngine.get_style_snapshot() must
reuse a caller-supplied structure_snapshot instead of calling
StructureEngine.get_snapshot() a second time, while staying backward
compatible for callers that don't pass one.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_style_engine_structure_reuse.py -v
"""
from core.StyleEngine import get_style_snapshot


class FakeStructureSnapshot:
    def __init__(self, context_zone):
        self.context_zone = context_zone
        self.structure_type = "BOS"


class ExplodingStructureEngine:
    """If get_style_snapshot() still calls get_snapshot() when a
    structure_snapshot was already supplied, this blows up loudly."""

    def get_snapshot(self, symbol, tf, cache=None):
        raise AssertionError(
            "StructureEngine.get_snapshot() must not be called from "
            "get_style_snapshot() when structure_snapshot is already supplied (Fix #4D2)"
        )


class FakeStructureEngine:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.calls = 0

    def get_snapshot(self, symbol, tf, cache=None):
        self.calls += 1
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


class FakeDemandEngine:
    def get_label(self, symbol, tf, cache=None):
        raise AssertionError("get_label() should not be reached (Fix #4D1) — unrelated to this test but guards regressions")


class FakeShiftEngine:
    def detect_shift(self, structure, tf, conviction=None, cache=None):
        return {"shifted": False, "shift_direction": "none", "shift_color": "gray"}

    def get_last_shift_change_time(self, symbol, tf):
        return None


def test_structure_engine_not_called_when_snapshot_supplied():
    """A StructureEngine whose get_snapshot() raises must not blow up
    get_style_snapshot() when structure_snapshot is passed in — proves the
    second fetch is skipped entirely."""
    structure = FakeStructureSnapshot(context_zone="demand")
    snapshot = get_style_snapshot(
        symbol="TEST", tf="M15", mode="scalping",
        bias_engine=FakeBiasEngine(),
        momentum_engine=FakeMomentumEngine(),
        demand_engine=FakeDemandEngine(),
        structure_engine=ExplodingStructureEngine(),
        shift_engine=FakeShiftEngine(),
        structure_snapshot=structure,
    )
    assert snapshot.demand == "demand"
    assert snapshot.structure_label == "BOS"


def test_fallback_path_without_structure_snapshot_still_works():
    """Omitting structure_snapshot (existing callers, e.g.
    build_multi_symbol_snapshot()) must still fetch via
    structure_engine.get_snapshot() exactly once, unchanged behavior."""
    structure = FakeStructureSnapshot(context_zone="supply")
    fake_structure_engine = FakeStructureEngine(structure)
    snapshot = get_style_snapshot(
        symbol="TEST", tf="H1", mode="swing",
        bias_engine=FakeBiasEngine(),
        momentum_engine=FakeMomentumEngine(),
        demand_engine=FakeDemandEngine(),
        structure_engine=fake_structure_engine,
        shift_engine=FakeShiftEngine(),
    )
    assert snapshot.demand == "supply"
    assert fake_structure_engine.calls == 1, "fallback path must still call get_snapshot() exactly once"


def test_live_output_unchanged_with_structure_reuse():
    """Live regression: /core/output for XAUUSD_i must be byte-identical
    (excluding last_updated) whether or not Output.py's structure_map[tf]
    reuse path is exercised — this IS the live path post-Fix #4D2, so this
    test simply asserts it runs clean and produces the expected shape."""
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
    assert symbol in out
    assert "error" not in out[symbol], f"unexpected error: {out[symbol].get('error')}"
    assert "bias" in out[symbol] and "scalping" in out[symbol] and "swing" in out[symbol]


def test_live_structure_engine_call_count_reduced_per_tf():
    """The actual point of Fix #4D2: wrap StructureEngine.get_snapshot with
    a counter and confirm build_multi_symbol_output() calls it exactly once
    per (symbol, tf) instead of twice (once via _build_structure_context,
    once via get_style_snapshot)."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]

    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    call_counts = {}
    original_get_snapshot = cr.structure_engine.get_snapshot

    def counting_get_snapshot(sym, tf, cache=None):
        call_counts[(sym, tf)] = call_counts.get((sym, tf), 0) + 1
        return original_get_snapshot(sym, tf, cache=cache)

    cr.structure_engine.get_snapshot = counting_get_snapshot
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
        cr.structure_engine.get_snapshot = original_get_snapshot

    for tf in timeframes:
        count = call_counts.get((symbol, tf), 0)
        assert count == 1, (
            f"{symbol}/{tf}: structure_engine.get_snapshot() called {count} times, "
            f"expected exactly 1 (was 2 before Fix #4D2 — once in _build_structure_context, "
            f"once again in get_style_snapshot)"
        )


if __name__ == "__main__":
    test_structure_engine_not_called_when_snapshot_supplied()
    print("[PASS] get_style_snapshot() skips get_snapshot() when structure_snapshot is supplied")

    test_fallback_path_without_structure_snapshot_still_works()
    print("[PASS] fallback path (no structure_snapshot) still works, calls get_snapshot() once")

    test_live_output_unchanged_with_structure_reuse()
    print("[PASS] live /core/output runs clean with structure reuse wired in")

    test_live_structure_engine_call_count_reduced_per_tf()
    print("[PASS] live: structure_engine.get_snapshot() called exactly once per (symbol, tf)")

    print("\nALL FIX #4D2 REGRESSION CHECKS PASSED")
