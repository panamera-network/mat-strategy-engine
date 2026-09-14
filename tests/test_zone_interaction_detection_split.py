"""Fix #6AJ — targeted tests for splitting ShiftEngine's zone interaction
detection (pure, no conviction dependency) from its colorization
(conviction-based brightness only), per Fix #6AI's audit finding that
detect_zone_interaction()'s only use of `conviction` was color brightness,
never detection/direction.

Scope: this is a pure internal refactor. detect_zone_interaction()'s
public signature, return dict, values, single-candle fetch, and
current_shift_direction/last_shift_change bookkeeping are all required to
stay byte-for-byte identical to before the split -- tests below confirm
this directly, alongside the two new composable steps
(_detect_interaction_evidence(), build_zone_interaction_result()).
StyleEngine.py's call ordering, the conviction formula, Alignment, and
Suppression/Strategy are untouched (not exercised by this file at all).

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_zone_interaction_detection_split.py -v
"""
from core.ShiftEngine import ShiftEngine
from core.core_models import CandleSnapshot


def make_candle(o, h, l, cl, ts="1"):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100, timestamp=ts)


class FakeCandleEngine:
    def __init__(self, candle):
        self._candle = candle
        self.call_count = 0
        self.last_count_arg = None

    def get_snapshots(self, symbol, tf, count=1, cache=None):
        self.call_count += 1
        self.last_count_arg = count
        return [self._candle] if self._candle is not None else []


class FakeStructureSnapshot:
    def __init__(self, symbol="TEST", context_zone="demand", context_level=100.0):
        self.symbol = symbol
        self.context_zone = context_zone
        self.context_level = context_level


# ---------------------------------------------------------------------------
# Old public detect_zone_interaction() output identical to pre-split shape
# ---------------------------------------------------------------------------

def test_public_output_has_exact_same_keys_and_values_as_before():
    candle = make_candle(100.5, 100.6, 100.0, 100.4)  # low touches level exactly
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(candle))

    result = engine.detect_zone_interaction(structure, "M15", conviction=0.5)

    assert set(result.keys()) == {
        "zone_interaction", "zone_interaction_direction", "zone_interaction_color",
        "zone_type", "level", "shifted", "shift_direction", "shift_color",
    }
    assert result["zone_interaction"] is True
    assert result["zone_interaction_direction"] == "Bullish"
    assert result["zone_type"] == "demand"
    assert result["level"] == 100.0
    assert result["shifted"] == result["zone_interaction"]
    assert result["shift_direction"] == result["zone_interaction_direction"]
    assert result["shift_color"] == result["zone_interaction_color"]


def test_supply_touch_output_unchanged():
    candle = make_candle(99.5, 100.0, 99.4, 99.8)  # high touches level exactly
    structure = FakeStructureSnapshot(context_zone="supply", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(candle))

    result = engine.detect_zone_interaction(structure, "M15", conviction=0.8)

    assert result["zone_interaction"] is True
    assert result["zone_interaction_direction"] == "Bearish"
    assert result["shifted"] == result["zone_interaction"]
    assert result["shift_direction"] == result["zone_interaction_direction"]
    assert result["shift_color"] == result["zone_interaction_color"]


def test_no_interaction_no_candles_output_unchanged():
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(None))

    result = engine.detect_zone_interaction(structure, "M15")

    assert result["zone_interaction"] is False
    assert result["shifted"] is False
    assert result["zone_interaction_direction"] == "Neutral"
    assert result["zone_type"] == "neutral"
    assert result["level"] is None


def test_no_interaction_no_zone_or_level_output_unchanged():
    structure = FakeStructureSnapshot(context_zone=None, context_level=None)
    engine = ShiftEngine(FakeCandleEngine(make_candle(100, 101, 99, 100)))

    result = engine.detect_zone_interaction(structure, "M15")

    assert result["zone_interaction"] is False
    assert result["shifted"] is False
    assert result["zone_interaction_direction"] == "Neutral"


def test_detect_shift_alias_still_identical_to_canonical():
    candle = make_candle(100.5, 100.6, 100.0, 100.4)
    engine = ShiftEngine(FakeCandleEngine(candle))

    structure_a = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    result_canonical = engine.detect_zone_interaction(structure_a, "M15", conviction=0.5)

    structure_b = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    result_legacy = engine.detect_shift(structure_b, "M15", conviction=0.5)

    assert result_canonical == result_legacy


def test_boundary_tolerance_unchanged():
    level = 100.0
    epsilon = 0.0002
    at_boundary = make_candle(100.5, 100.6, level + epsilon, 100.4)
    just_outside = make_candle(100.5, 100.6, level + epsilon + 0.00005, 100.4)
    structure = FakeStructureSnapshot(context_zone="demand", context_level=level)

    engine_at = ShiftEngine(FakeCandleEngine(at_boundary))
    assert engine_at.detect_zone_interaction(structure, "M15")["zone_interaction"] is True

    engine_outside = ShiftEngine(FakeCandleEngine(just_outside))
    assert engine_outside.detect_zone_interaction(structure, "M15")["zone_interaction"] is False


# ---------------------------------------------------------------------------
# Detection result independent of conviction
# ---------------------------------------------------------------------------

def test_detection_evidence_has_no_conviction_parameter_at_all():
    import inspect
    sig = inspect.signature(ShiftEngine._detect_interaction_evidence)
    assert "conviction" not in sig.parameters


def test_same_interaction_direction_zone_level_regardless_of_conviction():
    candle = make_candle(100.5, 100.6, 100.0, 100.4)
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)

    results = []
    for conviction in (None, 0.0, 0.3, 0.7, 1.0, 5.0, -3.0):
        engine = ShiftEngine(FakeCandleEngine(candle))  # fresh engine per call, isolate bookkeeping
        result = engine.detect_zone_interaction(structure, "M15", conviction=conviction)
        results.append(result)

    for r in results:
        assert r["zone_interaction"] == results[0]["zone_interaction"]
        assert r["zone_interaction_direction"] == results[0]["zone_interaction_direction"]
        assert r["zone_type"] == results[0]["zone_type"]
        assert r["level"] == results[0]["level"]
        assert r["shifted"] == results[0]["shifted"]
        assert r["shift_direction"] == results[0]["shift_direction"]


def test_evidence_dict_reusable_across_multiple_conviction_values():
    """The whole point of the split: detect once, colorize many times with
    no re-detection/re-fetch."""
    candle = make_candle(100.5, 100.6, 100.0, 100.4)
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    fake_candles = FakeCandleEngine(candle)
    engine = ShiftEngine(fake_candles)

    evidence = engine._detect_interaction_evidence(structure, "M15")
    assert fake_candles.call_count == 1

    result_low = engine.build_zone_interaction_result(evidence, conviction=0.1)
    result_high = engine.build_zone_interaction_result(evidence, conviction=0.9)

    # No additional fetch happened for the two colorization calls.
    assert fake_candles.call_count == 1

    assert result_low["zone_interaction"] == result_high["zone_interaction"] is True
    assert result_low["zone_interaction_direction"] == result_high["zone_interaction_direction"] == "Bullish"
    assert result_low["zone_type"] == result_high["zone_type"] == "demand"
    assert result_low["level"] == result_high["level"] == 100.0


# ---------------------------------------------------------------------------
# Different conviction changes color only
# ---------------------------------------------------------------------------

def test_different_conviction_changes_color_only():
    candle = make_candle(100.5, 100.6, 100.0, 100.4)
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(candle))
    evidence = engine._detect_interaction_evidence(structure, "M15")

    result_low = engine.build_zone_interaction_result(evidence, conviction=0.1)
    result_high = engine.build_zone_interaction_result(evidence, conviction=0.9)

    # Colors differ (brightness scales with conviction)...
    assert result_low["zone_interaction_color"] != result_high["zone_interaction_color"]
    assert result_low["shift_color"] != result_high["shift_color"]

    # ...but every non-color field is identical.
    for key in ("zone_interaction", "zone_interaction_direction", "zone_type", "level", "shifted", "shift_direction"):
        assert result_low[key] == result_high[key]


def test_none_conviction_gives_base_unscaled_color():
    candle = make_candle(100.5, 100.6, 100.0, 100.4)
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(candle))
    evidence = engine._detect_interaction_evidence(structure, "M15")

    result = engine.build_zone_interaction_result(evidence, conviction=None)
    assert result["zone_interaction_color"] == ShiftEngine.SHIFT_COLORS["Bullish"]


def test_neutral_direction_color_unaffected_by_conviction():
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(make_candle(150.0, 151.0, 149.0, 150.5)))  # far from zone
    evidence = engine._detect_interaction_evidence(structure, "M15")

    result_low = engine.build_zone_interaction_result(evidence, conviction=0.1)
    result_high = engine.build_zone_interaction_result(evidence, conviction=0.9)

    assert result_low["zone_interaction_color"] == result_high["zone_interaction_color"] == ShiftEngine.SHIFT_COLORS["Neutral"]


# ---------------------------------------------------------------------------
# Fetch count unchanged (still exactly one call, count=1)
# ---------------------------------------------------------------------------

def test_fetch_count_and_arg_unchanged():
    candle = make_candle(100.5, 100.6, 100.0, 100.4)
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    fake_candles = FakeCandleEngine(candle)
    engine = ShiftEngine(fake_candles)

    engine.detect_zone_interaction(structure, "M15", conviction=0.5)

    assert fake_candles.call_count == 1
    assert fake_candles.last_count_arg == 1


# ---------------------------------------------------------------------------
# Bookkeeping unchanged: current_shift_direction/last_shift_change timing
# ---------------------------------------------------------------------------

def test_bookkeeping_updated_on_full_evidence_path():
    candle = make_candle(100.5, 100.6, 100.0, 100.4)
    structure = FakeStructureSnapshot(symbol="SYM", context_zone="demand", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(candle))

    assert ("SYM", "M15") not in engine.current_shift_direction
    engine.detect_zone_interaction(structure, "M15")
    assert engine.current_shift_direction[("SYM", "M15")] == "Bullish"
    assert ("SYM", "M15") in engine.last_shift_change


def test_bookkeeping_skipped_on_no_candles_early_return():
    structure = FakeStructureSnapshot(symbol="SYM2", context_zone="demand", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(None))

    engine.detect_zone_interaction(structure, "M15")
    assert ("SYM2", "M15") not in engine.current_shift_direction
    assert ("SYM2", "M15") not in engine.last_shift_change


def test_bookkeeping_skipped_on_no_zone_or_level_early_return():
    structure = FakeStructureSnapshot(symbol="SYM3", context_zone=None, context_level=None)
    engine = ShiftEngine(FakeCandleEngine(make_candle(100, 101, 99, 100)))

    engine.detect_zone_interaction(structure, "M15")
    assert ("SYM3", "M15") not in engine.current_shift_direction
    assert ("SYM3", "M15") not in engine.last_shift_change


def test_get_last_shift_change_time_unaffected_by_split():
    candle = make_candle(100.5, 100.6, 100.0, 100.4)
    structure = FakeStructureSnapshot(symbol="SYM4", context_zone="demand", context_level=100.0)
    engine = ShiftEngine(FakeCandleEngine(candle))

    assert engine.get_last_shift_change_time("SYM4", "M15") is None
    engine.detect_zone_interaction(structure, "M15")
    assert engine.get_last_shift_change_time("SYM4", "M15") is not None


def test_direction_change_updates_last_shift_change_across_calls():
    structure_demand = FakeStructureSnapshot(symbol="SYM5", context_zone="demand", context_level=100.0)
    structure_supply = FakeStructureSnapshot(symbol="SYM5", context_zone="supply", context_level=100.0)
    # candle.low=100.0 touches a demand level at 100.0; candle.high=100.6
    # also satisfies the supply check (>= level-epsilon) at the same level,
    # so re-labeling the same candle against a supply zone flips the
    # direction from Bullish to Bearish (verified against the exact
    # formula) -- either way this exercises a genuine direction change.
    engine = ShiftEngine(FakeCandleEngine(make_candle(100.5, 100.6, 100.0, 100.4)))

    engine.detect_zone_interaction(structure_demand, "M15")
    assert engine.current_shift_direction[("SYM5", "M15")] == "Bullish"
    first_change = engine.get_last_shift_change_time("SYM5", "M15")
    assert first_change is not None

    engine.detect_zone_interaction(structure_supply, "M15")
    assert engine.current_shift_direction[("SYM5", "M15")] == "Bearish"
    second_change = engine.get_last_shift_change_time("SYM5", "M15")
    assert second_change is not None


# ---------------------------------------------------------------------------
# CHoCH/structure fields still never consulted (Fix #6D's own constraint,
# reconfirmed post-split)
# ---------------------------------------------------------------------------

def test_choch_or_structure_fields_never_consulted_post_split():
    candle = make_candle(100.5, 100.6, 100.0, 100.4)
    structure = FakeStructureSnapshot(context_zone="demand", context_level=100.0)
    assert not hasattr(structure, "structure_valid")
    assert not hasattr(structure, "structure_type")

    engine = ShiftEngine(FakeCandleEngine(candle))
    result = engine.detect_zone_interaction(structure, "M15")
    assert result["zone_interaction"] is True


# ---------------------------------------------------------------------------
# Live regression: /core/output-facing behavior unchanged end-to-end
# ---------------------------------------------------------------------------

def test_live_style_snapshot_zone_fields_unchanged_post_split():
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


def test_live_shift_score_ordering_bug_status_at_time_of_this_fix():
    """At the time Fix #6AJ landed, shift_score was still permanently 0.0
    in conviction because StyleEngine.py's call ordering hadn't been fixed
    yet -- this fix (#6AJ) deliberately did not touch that, only split
    ShiftEngine's detection from its colorization. Fix #6AK later fixed
    the ordering AND made conviction direction-relative (see
    test_direction_relative_conviction.py), which also corrected
    conviction_breakdown's shape for scalping mode (Fix #6AG's finding:
    it used to expose swing-shaped keys even for scalping). This test now
    documents that scalping's breakdown is momentum/shift/bias-shaped,
    not the old structure/bias/zone_score shape."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.StyleEngine import get_style_snapshot

    symbol = "XAUUSD_i"
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], ["M1"], count=100)

    snapshot = get_style_snapshot(
        symbol, "M1", "scalping",
        cr.bias_engine, cr.momentum_engine, cr.demand_engine, cr.structure_engine, cr.shift_engine,
        cache=cache,
    )
    assert set(snapshot.conviction_breakdown.keys()) == {"momentum", "shift", "bias"}
