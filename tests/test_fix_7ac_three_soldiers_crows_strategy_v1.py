"""Fix #7AC — MAT Three White Soldiers / Three Black Crows v1: a fixed,
exactly-3-candle pattern (three same-color candles with progressively-
extending closes, each opening inside the prior candle's real body), per
MAT's own locked rules (confirmed via Fix #7AC's own rule-audit report
before implementation).

EVIDENCE AUDIT (performed before writing any detector -- see
core/structure_utils.py's detect_three_soldiers_crows_sequence() own
docstring for the full detail): same conclusion Fix #7AA/#7AB's own
audits already reached -- StrategySnapshot.recent_candles (Fix #7K) only
exposes direction/index/timestamp/volume, no OHLC at all -- insufficient
for the body/open/close comparisons this pattern needs. Closed with a
new structure_utils detector reusing the SAME already-fetched `candles`
window StructureEngine already has -- no new MT5 fetch. Same fixed
exactly-3-candle window as Fix #7AB's Three Inside (C1=candles[-3],
C2=candles[-2], C3=candles[-1]) -- no widening search, so the
stale-identity bug class cannot arise here either.

LOCKED MAT RULES:
  Three White Soldiers: C1/C2/C3 all bullish, C2.close > C1.close,
                         C3.close > C2.close, C2.open inside C1's body
                         (inclusive), C3.open inside C2's body
                         (inclusive).
  Three Black Crows:    C1/C2/C3 all bearish, C2.close < C1.close,
                         C3.close < C2.close, C2.open inside C1's body
                         (inclusive), C3.open inside C2's body
                         (inclusive).
  Wicks are entirely unrestricted on all three candles -- only OPENS are
  constrained to the prior body, and only CLOSES are compared for
  progression (never highs/lows).

DOJI REJECTION: a doji (close == open) at ANY of C1/C2/C3 rejects the
whole sequence outright, before any other check runs.

NO CONTEXT GATES (LOCKED): no prior high/low break requirement, no
small-wick threshold, no long-body/ATR-relative-size threshold, no
body-size similar/increasing requirement, no prior-trend eligibility
gate, no gap requirement, no zone/S&R/S&D/bias/structure eligibility
gate of any kind. Momentum only ever supports confidence.

CONFIDENCE v1: confirmed sequence gets a flat BASE_CONFIDENCE (0.5) plus
canonical momentum support only (MOMENTUM_WEIGHT 0.5) -- the same
pattern already established by Fix #7P/.../#7AA/#7AB.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7ac_three_soldiers_crows_strategy_v1.py -v
"""
import inspect
from datetime import datetime, timezone

from core.core_models import CandleSnapshot
from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot
from core.structure_utils import detect_three_soldiers_crows_sequence


def _c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=10.0, timestamp=ts)


def _valid_soldiers():
    """C1/C2/C3 all bullish, progressive closes, each open inside prior
    body. C2's high/low both exceed C1's own high/low (wick excursion),
    and C3 closes further along without breaking C1's or C2's high --
    proving wicks/highs are never checked, only opens and closes."""
    return [
        _c(100, 108, 96, 105, 0),   # C1: bullish, body [100,105]
        _c(102, 118, 90, 110, 1),   # C2: bullish, open 102 inside C1 body [100,105]; wick escapes both sides
        _c(107, 112, 106, 112, 2),  # C3: bullish, open 107 inside C2 body [102,110]; close 112 > 110, < C2.high(118)
    ]


def _valid_crows():
    """Bearish mirror."""
    return [
        _c(105, 109, 97, 100, 0),   # C1: bearish, body [100,105]
        _c(103, 115, 85, 95, 1),    # C2: bearish, open 103 inside C1 body [100,105]; wick escapes both sides
        _c(98, 99, 88, 88, 2),      # C3: bearish, open 98 inside C2 body [95,103]; close 88 < 95, > C2.low(85)
    ]


# ---------------------------------------------------------------------------
# Core valid sequences.
# ---------------------------------------------------------------------------

def test_valid_three_white_soldiers():
    candles = _valid_soldiers()
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is True
    assert result["direction"] == "Bullish"
    assert result["c1_index"] == 0
    assert result["c2_index"] == 1
    assert result["c3_index"] == 2


def test_valid_three_black_crows():
    candles = _valid_crows()
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is True
    assert result["direction"] == "Bearish"


# ---------------------------------------------------------------------------
# Doji rejection -- any of C1/C2/C3.
# ---------------------------------------------------------------------------

def test_doji_c1_rejected():
    candles = [
        _c(102, 108, 96, 102, 0),   # C1: doji
        _c(102, 118, 90, 110, 1),
        _c(107, 112, 106, 112, 2),
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


def test_doji_c2_rejected():
    candles = [
        _c(100, 108, 96, 105, 0),
        _c(102, 118, 90, 102, 1),   # C2: doji
        _c(107, 112, 106, 112, 2),
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


def test_doji_c3_rejected():
    candles = [
        _c(100, 108, 96, 105, 0),
        _c(102, 118, 90, 110, 1),
        _c(107, 112, 106, 107, 2),  # C3: doji
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


# ---------------------------------------------------------------------------
# Opposite-color interruption.
# ---------------------------------------------------------------------------

def test_opposite_color_interruption_rejected_soldiers():
    """C1/C3 bullish but C2 bearish -- breaks the same-color-all-3 rule."""
    candles = [
        _c(100, 108, 96, 105, 0),   # C1 bullish
        _c(104, 106, 98, 101, 1),   # C2 bearish (interruption)
        _c(102, 112, 100, 110, 2),  # C3 bullish
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


def test_opposite_color_interruption_rejected_crows():
    candles = [
        _c(105, 109, 97, 100, 0),   # C1 bearish
        _c(101, 108, 99, 106, 1),   # C2 bullish (interruption)
        _c(104, 105, 90, 95, 2),    # C3 bearish
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


# ---------------------------------------------------------------------------
# Progressive-close failure.
# ---------------------------------------------------------------------------

def test_c2_close_not_progressive_rejected_soldiers():
    """C2 bullish and open-contained, but C2.close <= C1.close -- no
    progression, must reject."""
    candles = [
        _c(100, 108, 96, 105, 0),   # C1: close 105
        _c(101, 106, 99, 103, 1),   # C2: bullish (103>101) but close 103 < C1.close 105
        _c(102, 112, 100, 110, 2),
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


def test_c3_close_not_progressive_rejected_soldiers():
    candles = [
        _c(100, 108, 96, 105, 0),   # C1: close 105
        _c(102, 118, 90, 110, 1),   # C2: close 110 > 105, OK
        _c(107, 111, 106, 108, 2),  # C3: bullish (108>107) but close 108 < C2.close 110
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


def test_c2_close_not_progressive_rejected_crows():
    candles = [
        _c(105, 109, 97, 100, 0),   # C1: close 100
        _c(103, 107, 99, 101, 1),   # C2: bearish (101<103) but close 101 > C1.close 100
        _c(98, 99, 88, 88, 2),
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


def test_c3_close_not_progressive_rejected_crows():
    candles = [
        _c(105, 109, 97, 100, 0),   # C1: close 100
        _c(103, 115, 85, 95, 1),    # C2: close 95 < 100, OK
        _c(98, 99, 90, 96, 2),      # C3: bearish (96<98) but close 96 > C2.close 95
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


# ---------------------------------------------------------------------------
# Inclusive open-containment boundary equality.
# ---------------------------------------------------------------------------

def test_c2_open_exactly_at_c1_body_boundary_valid():
    """C2.open == C1's body high exactly -- inclusive boundary, still
    valid."""
    candles = [
        _c(100, 108, 96, 105, 0),   # C1: body [100,105]
        _c(105, 118, 90, 111, 1),   # C2: open EXACTLY == c1 body high (105)
        _c(107, 115, 106, 113, 2),
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is True


def test_c3_open_exactly_at_c2_body_boundary_valid():
    """C3.open == C2's body low exactly -- inclusive boundary, still
    valid."""
    candles = [
        _c(100, 108, 96, 105, 0),    # C1: body [100,105]
        _c(102, 118, 90, 110, 1),    # C2: body [102,110]
        _c(102, 112, 100, 112, 2),   # C3: open EXACTLY == c2 body low (102)
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is True


# ---------------------------------------------------------------------------
# Open outside prior body rejection.
# ---------------------------------------------------------------------------

def test_c2_open_outside_c1_body_rejected():
    candles = [
        _c(100, 108, 96, 105, 0),   # C1: body [100,105]
        _c(106, 118, 90, 112, 1),   # C2: open 106 -- ABOVE c1 body high (105)
        _c(108, 116, 107, 114, 2),
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


def test_c3_open_outside_c2_body_rejected():
    candles = [
        _c(100, 108, 96, 105, 0),
        _c(102, 118, 90, 110, 1),   # C2: body [102,110]
        _c(111, 116, 109, 114, 2),  # C3: open 111 -- ABOVE c2 body high (110)
    ]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


# ---------------------------------------------------------------------------
# Wick can exceed prior H/L without invalidating; close progression
# without breaking prior high/low is still valid.
# ---------------------------------------------------------------------------

def test_wick_exceeds_prior_high_low_still_valid():
    candles = _valid_soldiers()
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is True
    # C2's wick genuinely escaped C1's high/low on both sides.
    assert candles[1].high > result["c1_high"]
    assert candles[1].low < result["c1_low"]


def test_close_progression_without_breaking_prior_high_still_valid():
    """C3 closes higher than C2's close but stays BELOW C2's own high --
    proving only closes are compared, never highs/lows."""
    candles = _valid_soldiers()
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is True
    assert result["c3_close"] > result["c2_close"]
    assert result["c3_close"] < result["c2_high"]


def test_close_progression_without_breaking_prior_low_still_valid_crows():
    candles = _valid_crows()
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is True
    assert result["c3_close"] < result["c2_close"]
    assert result["c3_close"] > result["c2_low"]


# ---------------------------------------------------------------------------
# Other basic rejections.
# ---------------------------------------------------------------------------

def test_too_few_candles_rejected():
    candles = [_c(100, 110, 90, 105, 0), _c(102, 108, 98, 104, 1)]
    result = detect_three_soldiers_crows_sequence(candles)
    assert result["confirmed"] is False


def test_empty_candles_rejected():
    assert detect_three_soldiers_crows_sequence([])["confirmed"] is False


# ---------------------------------------------------------------------------
# Strategy react().
# ---------------------------------------------------------------------------

def _candle(direction, index, timestamp, volume=100.0):
    return {"direction": direction, "index": index, "timestamp": timestamp, "volume": volume}


def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="M15", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        recent_candles=[_candle("bull", 2, "2026-01-01T00:00:00Z")],
        three_soldiers_crows_confirmed=False, three_soldiers_crows_direction=None,
        three_soldiers_crows_c1_index=None, three_soldiers_crows_c1_timestamp=None,
        three_soldiers_crows_c1_open=None, three_soldiers_crows_c1_high=None,
        three_soldiers_crows_c1_low=None, three_soldiers_crows_c1_close=None,
        three_soldiers_crows_c2_index=None, three_soldiers_crows_c2_timestamp=None,
        three_soldiers_crows_c2_open=None, three_soldiers_crows_c2_high=None,
        three_soldiers_crows_c2_low=None, three_soldiers_crows_c2_close=None,
        three_soldiers_crows_c3_index=None, three_soldiers_crows_c3_timestamp=None,
        three_soldiers_crows_c3_open=None, three_soldiers_crows_c3_high=None,
        three_soldiers_crows_c3_low=None, three_soldiers_crows_c3_close=None,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_SOLDIERS_SEQUENCE = dict(
    three_soldiers_crows_confirmed=True, three_soldiers_crows_direction="Bullish",
    three_soldiers_crows_c1_index=0, three_soldiers_crows_c1_timestamp="0",
    three_soldiers_crows_c1_open=100.0, three_soldiers_crows_c1_high=108.0,
    three_soldiers_crows_c1_low=96.0, three_soldiers_crows_c1_close=105.0,
    three_soldiers_crows_c2_index=1, three_soldiers_crows_c2_timestamp="1",
    three_soldiers_crows_c2_open=102.0, three_soldiers_crows_c2_high=118.0,
    three_soldiers_crows_c2_low=90.0, three_soldiers_crows_c2_close=110.0,
    three_soldiers_crows_c3_index=2, three_soldiers_crows_c3_timestamp="2",
    three_soldiers_crows_c3_open=107.0, three_soldiers_crows_c3_high=112.0,
    three_soldiers_crows_c3_low=106.0, three_soldiers_crows_c3_close=112.0,
)
_CROWS_SEQUENCE = dict(
    three_soldiers_crows_confirmed=True, three_soldiers_crows_direction="Bearish",
    three_soldiers_crows_c1_index=0, three_soldiers_crows_c1_timestamp="0",
    three_soldiers_crows_c1_open=105.0, three_soldiers_crows_c1_high=109.0,
    three_soldiers_crows_c1_low=97.0, three_soldiers_crows_c1_close=100.0,
    three_soldiers_crows_c2_index=1, three_soldiers_crows_c2_timestamp="1",
    three_soldiers_crows_c2_open=103.0, three_soldiers_crows_c2_high=115.0,
    three_soldiers_crows_c2_low=85.0, three_soldiers_crows_c2_close=95.0,
    three_soldiers_crows_c3_index=2, three_soldiers_crows_c3_timestamp="2",
    three_soldiers_crows_c3_open=98.0, three_soldiers_crows_c3_high=99.0,
    three_soldiers_crows_c3_low=88.0, three_soldiers_crows_c3_close=88.0,
)


def test_strategy_soldiers_fires_long():
    from core.strategy.ThreeSoldiersCrowsStrategy import ThreeSoldiersCrowsStrategy
    snap = _base_snapshot(**_SOLDIERS_SEQUENCE)
    result = ThreeSoldiersCrowsStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Three White Soldiers"
    assert result["price"] == 112.0


def test_strategy_crows_fires_short():
    from core.strategy.ThreeSoldiersCrowsStrategy import ThreeSoldiersCrowsStrategy
    snap = _base_snapshot(**_CROWS_SEQUENCE)
    result = ThreeSoldiersCrowsStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Three Black Crows"
    assert result["price"] == 88.0


def test_strategy_not_confirmed_rejected():
    from core.strategy.ThreeSoldiersCrowsStrategy import ThreeSoldiersCrowsStrategy
    snap = _base_snapshot()
    assert ThreeSoldiersCrowsStrategy().react(snap, {}) is None


def test_strategy_missing_geometry_rejected():
    from core.strategy.ThreeSoldiersCrowsStrategy import ThreeSoldiersCrowsStrategy
    overrides = dict(_SOLDIERS_SEQUENCE)
    overrides["three_soldiers_crows_c1_index"] = None
    snap = _base_snapshot(**overrides)
    assert ThreeSoldiersCrowsStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Chart markings -- exactly 3 real markings.
# ---------------------------------------------------------------------------

def test_exactly_three_markings_all_real():
    from core.strategy.ThreeSoldiersCrowsStrategy import ThreeSoldiersCrowsStrategy
    snap = _base_snapshot(**_SOLDIERS_SEQUENCE)
    result = ThreeSoldiersCrowsStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 3
    assert [m["type"] for m in markings] == ["candle", "candle", "candle"]
    assert [m["label"] for m in markings] == [
        "Three Soldiers/Crows C1", "Three Soldiers/Crows C2", "Three Soldiers/Crows C3",
    ]
    for m in markings:
        assert m["direction"] == "long"
        validate_chart_marking(m)

    c1_marking, c2_marking, c3_marking = markings
    assert c1_marking["timestamp"] == "0"
    assert c1_marking["candle_index"] == 0
    assert c2_marking["timestamp"] == "1"
    assert c2_marking["candle_index"] == 1
    assert c3_marking["timestamp"] == "2"
    assert c3_marking["candle_index"] == 2


def test_exactly_three_markings_crows_direction():
    from core.strategy.ThreeSoldiersCrowsStrategy import ThreeSoldiersCrowsStrategy
    snap = _base_snapshot(**_CROWS_SEQUENCE)
    result = ThreeSoldiersCrowsStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 3
    for m in markings:
        assert m["direction"] == "short"


def test_rejected_setup_emits_no_markings_and_no_signal():
    from core.strategy.ThreeSoldiersCrowsStrategy import ThreeSoldiersCrowsStrategy
    snap = _base_snapshot()
    assert ThreeSoldiersCrowsStrategy().react(snap, {}) is None


def test_marking_identity_sourced_from_detector_not_recomputed():
    """Feed the REAL detector's own output through -- markings' index/
    timestamp must be byte-identical, proving no recalculation in the
    Strategy layer."""
    from core.strategy.ThreeSoldiersCrowsStrategy import ThreeSoldiersCrowsStrategy

    candles = _valid_soldiers()
    detector_result = detect_three_soldiers_crows_sequence(candles)
    assert detector_result["confirmed"] is True

    snap = _base_snapshot(
        three_soldiers_crows_confirmed=detector_result["confirmed"],
        three_soldiers_crows_direction=detector_result["direction"],
        three_soldiers_crows_c1_index=detector_result["c1_index"],
        three_soldiers_crows_c1_timestamp=detector_result["c1_timestamp"],
        three_soldiers_crows_c1_open=detector_result["c1_open"], three_soldiers_crows_c1_high=detector_result["c1_high"],
        three_soldiers_crows_c1_low=detector_result["c1_low"], three_soldiers_crows_c1_close=detector_result["c1_close"],
        three_soldiers_crows_c2_index=detector_result["c2_index"],
        three_soldiers_crows_c2_timestamp=detector_result["c2_timestamp"],
        three_soldiers_crows_c2_open=detector_result["c2_open"], three_soldiers_crows_c2_high=detector_result["c2_high"],
        three_soldiers_crows_c2_low=detector_result["c2_low"], three_soldiers_crows_c2_close=detector_result["c2_close"],
        three_soldiers_crows_c3_index=detector_result["c3_index"],
        three_soldiers_crows_c3_timestamp=detector_result["c3_timestamp"],
        three_soldiers_crows_c3_open=detector_result["c3_open"], three_soldiers_crows_c3_high=detector_result["c3_high"],
        three_soldiers_crows_c3_low=detector_result["c3_low"], three_soldiers_crows_c3_close=detector_result["c3_close"],
    )
    result = ThreeSoldiersCrowsStrategy().react(snap, {})
    c1_marking, c2_marking, c3_marking = result["chart_markings"]
    assert c1_marking["candle_index"] == detector_result["c1_index"]
    assert c1_marking["timestamp"] == detector_result["c1_timestamp"]
    assert c2_marking["candle_index"] == detector_result["c2_index"]
    assert c2_marking["timestamp"] == detector_result["c2_timestamp"]
    assert c3_marking["candle_index"] == detector_result["c3_index"]
    assert c3_marking["timestamp"] == detector_result["c3_timestamp"]


# ---------------------------------------------------------------------------
# Confidence formula.
# ---------------------------------------------------------------------------

def test_confidence_formula_reported_exactly():
    from core.strategy.ThreeSoldiersCrowsStrategy import BASE_CONFIDENCE, MOMENTUM_WEIGHT, ThreeSoldiersCrowsStrategy
    assert BASE_CONFIDENCE == 0.5
    assert MOMENTUM_WEIGHT == 0.5
    overrides = dict(_SOLDIERS_SEQUENCE)
    overrides["atr_normalized_momentum"] = 1.0  # agrees with "long"
    snap = _base_snapshot(**overrides)
    result = ThreeSoldiersCrowsStrategy().react(snap, {})
    assert result["confidence"] == round(0.5 + 0.5 * 0.5, 2)


def test_confidence_floor_with_no_momentum_support():
    from core.strategy.ThreeSoldiersCrowsStrategy import ThreeSoldiersCrowsStrategy
    snap = _base_snapshot(**_SOLDIERS_SEQUENCE)
    result = ThreeSoldiersCrowsStrategy().react(snap, {})
    assert result["confidence"] == 0.5


def test_standard_output_fields_present():
    from core.strategy.ThreeSoldiersCrowsStrategy import ThreeSoldiersCrowsStrategy
    snap = _base_snapshot(**_SOLDIERS_SEQUENCE)
    result = ThreeSoldiersCrowsStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


# ---------------------------------------------------------------------------
# Absence of context gates.
# ---------------------------------------------------------------------------

def test_no_eligibility_gate_dependency():
    import core.strategy.ThreeSoldiersCrowsStrategy as mod
    source = inspect.getsource(mod.ThreeSoldiersCrowsStrategy.react)
    forbidden = (
        "context_zone", "context_level", "snr_context", "nearest_support", "nearest_resistance",
        "balance_range_confirmed", "volume_profile_", "structure_valid", "structure_type",
        "bias ==", "snapshot.bias", "inside_bar_", "three_inside_",
    )
    for term in forbidden:
        assert term not in source, term


def test_detector_never_calls_structure_or_trend_detection():
    import core.structure_utils as su_mod
    source = inspect.getsource(su_mod.detect_three_soldiers_crows_sequence)
    assert "detect_structure_event(" not in source
    assert "find_swings(" not in source
    assert "detect_trend(" not in source


def test_no_prior_trend_gap_wick_or_atr_size_check():
    """No prior-trend eligibility gate, no gap requirement, no small-wick
    threshold, no long-body/ATR-relative-size threshold, no body-size
    similar/increasing requirement -- confirmed by CODE BODY absence
    (the docstring itself legitimately discusses these ruled-out concepts
    in prose, e.g. "no gap requirement" -- checking the full source would
    trip on the docstring's own words, the same self-referential trap
    that hit Fix #7W/#7Y/#7AA/#7AB; scope to statements after the
    docstring)."""
    import ast

    import core.structure_utils as su_mod

    source = inspect.getsource(su_mod.detect_three_soldiers_crows_sequence)
    tree = ast.parse(source)
    func_node = tree.body[0]
    body_without_docstring = func_node.body[1:]
    code_only = ast.unparse(ast.Module(body=body_without_docstring, type_ignores=[]))

    forbidden = (
        "compute_atr", "gap", "prior_trend", "SWING_LOOKBACK", "MAX_INSIDE_BAR_CHILDREN",
        ".high >", ".high <", ".low >", ".low <",  # no wick/high/low comparisons anywhere
    )
    for term in forbidden:
        assert term not in code_only, term


# ---------------------------------------------------------------------------
# Discovery.
# ---------------------------------------------------------------------------

def test_three_soldiers_crows_strategy_present_in_engine():
    """This fix's own discovery-count test goes stale the moment a later
    fix adds another strategy (Fix #7AD bumps 26 -> 27) -- this checks
    only that THIS fix's own strategy is present, not the total count.
    See test_fix_7ad_po3_strategy_v1.py for the current total-count/
    full-roster tests."""
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert "ThreeSoldiersCrowsStrategy" in engine.enabled


def test_existing_twentyfive_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_twentyfive = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy", "CHOCHBOSConfirmationStrategy", "MomentumPullbackRecoveryStrategy",
        "SupportResistanceReactionStrategy", "SupportResistanceBreakoutRetestStrategy",
        "VolumeProfileWeeklyReactionStrategy", "BalanceRangeVAHVALReactionStrategy",
        "InsideBarBreakoutStrategy", "ThreeInsideStrategy",
    }
    assert existing_twentyfive <= set(engine.enabled.keys())
