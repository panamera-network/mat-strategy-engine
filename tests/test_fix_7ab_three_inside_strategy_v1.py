"""Fix #7AB — MAT Three Inside Up / Three Inside Down v1: a fixed,
exactly-3-candle pattern (Candle1 -> Candle2 body-in-body "Harami"
containment -> Candle3 confirmation), per MAT's own locked rules
(confirmed via Fix #7AB's own rule-audit report before implementation).

EVIDENCE AUDIT (performed before writing any detector -- see
core/structure_utils.py's detect_three_inside_sequence() own docstring
for the full detail): StrategySnapshot.recent_candles (Fix #7K) only
exposes direction/index/timestamp/volume, no OHLC at all -- insufficient
for the body/close comparisons this pattern needs. Closed with a new
structure_utils detector reusing the SAME already-fetched `candles`
window StructureEngine already has -- no new MT5 fetch, no OHLC ever
reconstructed inside the Strategy layer. Unlike Fix #7AA's Inside Bar
(variable-length search), this pattern is ALWAYS exactly 3 candles ending
at candles[-1] -- there is no widening search and no stale-identity
concern can arise structurally.

LOCKED MAT RULES:
  Three Inside Up:   C1 bearish, C2 bullish, C3 bullish, C3.close
                      STRICTLY > C1.open.
  Three Inside Down: C1 bullish, C2 bearish, C3 bearish, C3.close
                      STRICTLY < C1.open.
  C2's body must be fully within C1's body, INCLUSIVE boundaries; C2's
  WICK is unrestricted (may extend beyond C1's high/low). C3's boundary
  is C1's OPEN specifically (not C1's body high/low pair, not C1's
  wick), compared STRICTLY (equality does NOT confirm -- the opposite
  convention from C2's inclusive containment check).

DOJI REJECTION: a doji (close == open) at ANY of C1/C2/C3 rejects the
whole sequence outright, before any other check.

NO CONTEXT GATES (LOCKED): no prior-trend eligibility gate, no gap
requirement, no Candle-1 ATR/significance threshold, no zone/S&R/S&D/
bias/structure/momentum eligibility gate of any kind. Momentum only
ever supports confidence.

CONFIDENCE v1: confirmed sequence gets a flat BASE_CONFIDENCE (0.5) plus
canonical momentum support only (MOMENTUM_WEIGHT 0.5) -- the same
pattern already established by Fix #7P/#7S/#7T/#7W/#7X/#7Y/#7AA.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7ab_three_inside_strategy_v1.py -v
"""
import inspect
from datetime import datetime, timezone

import pytest

from core.core_models import CandleSnapshot
from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot
from core.structure_utils import detect_three_inside_sequence


def _c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=10.0, timestamp=ts)


def _three_inside_up_with_wick_excursion():
    """C1 bearish body [100,110], C2 bullish body [102,108] contained
    (inclusive) within C1's body, but C2's WICK extends beyond C1's own
    high (112) AND low (98) on BOTH sides -- must not invalidate the
    child. C3 closes 111 (> C1.open=110, confirming) while staying BELOW
    C1's own high (112) -- proving confirmation uses C1's OPEN, not its
    wick."""
    return [
        _c(110, 112, 98, 100, 0),   # C1: bearish, body [100,110]
        _c(102, 115, 95, 108, 1),   # C2: bullish, body [102,108] contained; wick escapes BOTH sides
        _c(108, 116, 107, 111, 2),  # C3: bullish, closes 111 > 110 (C1.open), still < 112 (C1.high)
    ]


def _three_inside_down_with_wick_excursion():
    """Bearish mirror."""
    return [
        _c(100, 112, 98, 110, 0),   # C1: bullish, body [100,110]
        _c(108, 115, 95, 102, 1),   # C2: bearish, body [102,108] contained; wick escapes both sides
        _c(102, 103, 99, 99, 2),    # C3: bearish, closes 99 < 100 (C1.open), still > 98 (C1.low)
    ]


# ---------------------------------------------------------------------------
# Core valid sequences, both directions, with wick excursion + body-break-
# without-H/L-break proven in the same fixture.
# ---------------------------------------------------------------------------

def test_three_inside_up_valid_with_c2_wick_excursion_and_body_only_break():
    candles = _three_inside_up_with_wick_excursion()
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is True
    assert result["direction"] == "Bullish"
    assert result["c1_index"] == 0
    assert result["c2_index"] == 1
    assert result["c3_index"] == 2
    # C2's wick genuinely escaped C1's high/low -- proving wick is ignored.
    assert candles[1].high > result["c1_high"]
    assert candles[1].low < result["c1_low"]
    # C3 confirmed by breaking C1's BODY (open) without breaking C1's HIGH.
    assert result["c3_close"] > result["c1_open"]
    assert result["c3_close"] < result["c1_high"]


def test_three_inside_down_valid_with_c2_wick_excursion_and_body_only_break():
    candles = _three_inside_down_with_wick_excursion()
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is True
    assert result["direction"] == "Bearish"
    assert candles[1].high > result["c1_high"]
    assert candles[1].low < result["c1_low"]
    assert result["c3_close"] < result["c1_open"]
    assert result["c3_close"] > result["c1_low"]


# ---------------------------------------------------------------------------
# Inclusive C2 body-containment equality.
# ---------------------------------------------------------------------------

def test_c2_body_touching_c1_body_low_exactly_still_contained():
    candles = [
        _c(110, 112, 98, 100, 0),   # C1: body [100,110]
        _c(100, 113, 96, 105, 1),   # C2: open EXACTLY == c1 body low (100) -- inclusive boundary
        _c(105, 116, 104, 111, 2),  # C3: confirms
    ]
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is True


def test_c2_body_touching_c1_body_high_exactly_still_contained():
    candles = [
        _c(110, 112, 98, 100, 0),   # C1: body [100,110]
        _c(103, 113, 96, 110, 1),   # C2: close EXACTLY == c1 body high (110) -- inclusive boundary
        _c(110, 116, 109, 111, 2),  # C3: confirms
    ]
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is True


# ---------------------------------------------------------------------------
# Strict C3 boundary — equality must reject, not confirm.
# ---------------------------------------------------------------------------

def test_c3_close_exactly_equal_to_c1_open_rejected_bullish():
    candles = [
        _c(110, 112, 98, 100, 0),   # C1: body [100,110], open=110
        _c(102, 111, 99, 108, 1),   # C2: contained
        _c(108, 112, 107, 110, 2),  # C3: closes EXACTLY 110 == C1.open -- must NOT confirm
    ]
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is False


def test_c3_close_exactly_equal_to_c1_open_rejected_bearish():
    candles = [
        _c(100, 112, 98, 110, 0),   # C1: body [100,110], open=100
        _c(108, 111, 99, 102, 1),   # C2: contained
        _c(102, 103, 99, 100, 2),   # C3: closes EXACTLY 100 == C1.open -- must NOT confirm
    ]
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is False


# ---------------------------------------------------------------------------
# Doji rejection -- any of C1/C2/C3.
# ---------------------------------------------------------------------------

def test_doji_c1_rejected():
    candles = [
        _c(105, 112, 98, 105, 0),   # C1: doji (open == close)
        _c(102, 111, 99, 108, 1),
        _c(108, 116, 107, 111, 2),
    ]
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is False


def test_doji_c2_rejected():
    candles = [
        _c(110, 112, 98, 100, 0),
        _c(105, 111, 99, 105, 1),   # C2: doji
        _c(108, 116, 107, 111, 2),
    ]
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is False


def test_doji_c3_rejected():
    candles = [
        _c(110, 112, 98, 100, 0),
        _c(102, 111, 99, 108, 1),
        _c(111, 116, 107, 111, 2),  # C3: doji
    ]
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is False


# ---------------------------------------------------------------------------
# Other rejections.
# ---------------------------------------------------------------------------

def test_c2_same_color_as_c1_rejected():
    """C2 must be the OPPOSITE color of C1 -- a same-color C2 is not a
    Harami at all, regardless of containment."""
    candles = [
        _c(110, 112, 98, 100, 0),   # C1 bearish
        _c(102, 111, 99, 100.5, 1),  # C2 also bearish-ish? make it clearly bearish: close < open
    ]
    candles = [
        _c(110, 112, 98, 100, 0),
        _c(108, 111, 99, 103, 1),   # C2 bearish (103 < 108) -- SAME color as C1
        _c(102, 106, 101, 105, 2),
    ]
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is False


def test_c2_not_contained_in_c1_body_rejected():
    candles = [
        _c(110, 112, 98, 100, 0),   # C1 body [100,110]
        _c(95, 113, 90, 111, 1),    # C2 body [95,111] -- exceeds C1 body on both sides
        _c(111, 116, 110, 112, 2),
    ]
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is False


def test_c3_wrong_color_rejected():
    """C3 must be the SAME color as the reversal direction -- a C3 that
    closes beyond C1.open but is itself the wrong color (shouldn't
    geometrically happen alongside a real close-beyond-open in the
    confirming direction, but verify the color flags are checked, not
    assumed)."""
    candles = [
        _c(110, 112, 98, 100, 0),   # C1 bearish
        _c(102, 111, 99, 108, 1),   # C2 bullish, contained
        _c(112, 113, 109, 111, 2),  # C3 closes 111 > 110 but is itself bearish (open=112 > close=111)
    ]
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is False


def test_too_few_candles_rejected():
    candles = [_c(100, 110, 90, 105, 0), _c(102, 108, 98, 104, 1)]
    result = detect_three_inside_sequence(candles)
    assert result["confirmed"] is False


def test_empty_candles_rejected():
    assert detect_three_inside_sequence([])["confirmed"] is False


# ---------------------------------------------------------------------------
# Strategy react() — evidence-only.
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
        three_inside_confirmed=False, three_inside_direction=None,
        three_inside_c1_index=None, three_inside_c1_timestamp=None,
        three_inside_c1_open=None, three_inside_c1_high=None, three_inside_c1_low=None, three_inside_c1_close=None,
        three_inside_c2_index=None, three_inside_c2_timestamp=None,
        three_inside_c2_open=None, three_inside_c2_high=None, three_inside_c2_low=None, three_inside_c2_close=None,
        three_inside_c3_index=None, three_inside_c3_timestamp=None,
        three_inside_c3_open=None, three_inside_c3_high=None, three_inside_c3_low=None, three_inside_c3_close=None,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_UP_SEQUENCE = dict(
    three_inside_confirmed=True, three_inside_direction="Bullish",
    three_inside_c1_index=0, three_inside_c1_timestamp="0",
    three_inside_c1_open=110.0, three_inside_c1_high=112.0, three_inside_c1_low=98.0, three_inside_c1_close=100.0,
    three_inside_c2_index=1, three_inside_c2_timestamp="1",
    three_inside_c2_open=102.0, three_inside_c2_high=115.0, three_inside_c2_low=95.0, three_inside_c2_close=108.0,
    three_inside_c3_index=2, three_inside_c3_timestamp="2",
    three_inside_c3_open=108.0, three_inside_c3_high=116.0, three_inside_c3_low=107.0, three_inside_c3_close=111.0,
)
_DOWN_SEQUENCE = dict(
    three_inside_confirmed=True, three_inside_direction="Bearish",
    three_inside_c1_index=0, three_inside_c1_timestamp="0",
    three_inside_c1_open=100.0, three_inside_c1_high=112.0, three_inside_c1_low=98.0, three_inside_c1_close=110.0,
    three_inside_c2_index=1, three_inside_c2_timestamp="1",
    three_inside_c2_open=108.0, three_inside_c2_high=115.0, three_inside_c2_low=95.0, three_inside_c2_close=102.0,
    three_inside_c3_index=2, three_inside_c3_timestamp="2",
    three_inside_c3_open=102.0, three_inside_c3_high=103.0, three_inside_c3_low=99.0, three_inside_c3_close=99.0,
)


def test_strategy_up_sequence_fires_long():
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    snap = _base_snapshot(**_UP_SEQUENCE)
    result = ThreeInsideStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Bullish Three Inside"
    assert result["price"] == 111.0


def test_strategy_down_sequence_fires_short():
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    snap = _base_snapshot(**_DOWN_SEQUENCE)
    result = ThreeInsideStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Bearish Three Inside"
    assert result["price"] == 99.0


def test_strategy_not_confirmed_rejected():
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    snap = _base_snapshot()
    assert ThreeInsideStrategy().react(snap, {}) is None


def test_strategy_missing_geometry_rejected():
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    overrides = dict(_UP_SEQUENCE)
    overrides["three_inside_c1_open"] = None
    snap = _base_snapshot(**overrides)
    assert ThreeInsideStrategy().react(snap, {}) is None


def test_exactly_three_markings_all_real():
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    snap = _base_snapshot(**_UP_SEQUENCE)
    result = ThreeInsideStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 3
    types = [m["type"] for m in markings]
    assert types == ["candle", "candle", "candle"]
    for m in markings:
        validate_chart_marking(m)

    c1_marking, c2_marking, c3_marking = markings
    assert c1_marking["timestamp"] == "0"
    assert c1_marking["candle_index"] == 0
    assert c2_marking["timestamp"] == "1"
    assert c2_marking["candle_index"] == 1
    assert c3_marking["timestamp"] == "2"
    assert c3_marking["candle_index"] == 2
    assert c1_marking["label"] == "Three Inside C1"
    assert c2_marking["label"] == "Three Inside C2"
    assert c3_marking["label"] == "Three Inside Confirmation"


# ---------------------------------------------------------------------------
# Fix #7AB — Chart Marking Acceptance Audit.
# ---------------------------------------------------------------------------

def test_bullish_signal_exactly_three_markings_with_locked_labels():
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    result = ThreeInsideStrategy().react(_base_snapshot(**_UP_SEQUENCE), {})
    markings = result["chart_markings"]
    assert len(markings) == 3
    assert [m["type"] for m in markings] == ["candle", "candle", "candle"]
    assert [m["label"] for m in markings] == [
        "Three Inside C1", "Three Inside C2", "Three Inside Confirmation",
    ]
    for m in markings:
        assert m["direction"] == "long"
        validate_chart_marking(m)


def test_bearish_signal_exactly_three_markings_with_locked_labels():
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    result = ThreeInsideStrategy().react(_base_snapshot(**_DOWN_SEQUENCE), {})
    markings = result["chart_markings"]
    assert len(markings) == 3
    assert [m["type"] for m in markings] == ["candle", "candle", "candle"]
    assert [m["label"] for m in markings] == [
        "Three Inside C1", "Three Inside C2", "Three Inside Confirmation",
    ]
    for m in markings:
        assert m["direction"] == "short"
        validate_chart_marking(m)


def test_marking_indices_strictly_increasing_c1_lt_c2_lt_c3():
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    for sequence in (_UP_SEQUENCE, _DOWN_SEQUENCE):
        result = ThreeInsideStrategy().react(_base_snapshot(**sequence), {})
        c1_marking, c2_marking, c3_marking = result["chart_markings"]
        assert c1_marking["candle_index"] < c2_marking["candle_index"] < c3_marking["candle_index"]


def test_marking_timestamps_match_upstream_evidence_exactly():
    """The marking's timestamp must be the SAME object/value the detector
    produced -- not reformatted, not re-derived from the candle_index, not
    recomputed by the Strategy layer in any way."""
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    snap = _base_snapshot(**_UP_SEQUENCE)
    result = ThreeInsideStrategy().react(snap, {})
    c1_marking, c2_marking, c3_marking = result["chart_markings"]
    assert c1_marking["timestamp"] == snap.three_inside_c1_timestamp
    assert c2_marking["timestamp"] == snap.three_inside_c2_timestamp
    assert c3_marking["timestamp"] == snap.three_inside_c3_timestamp
    assert c1_marking["candle_index"] == snap.three_inside_c1_index
    assert c2_marking["candle_index"] == snap.three_inside_c2_index
    assert c3_marking["candle_index"] == snap.three_inside_c3_index


def test_rejected_setup_emits_no_markings_and_no_signal():
    """A snapshot where the sequence never confirmed must not emit any
    Three-Inside markings at all -- react() returns None outright, so
    there is no `chart_markings` list to mislead a dashboard with."""
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    snap = _base_snapshot()  # three_inside_confirmed=False
    assert ThreeInsideStrategy().react(snap, {}) is None


def test_detector_output_is_the_single_source_of_marking_identity():
    """The Strategy must not recompute or independently derive C1/C2/C3
    identity -- it only reads whatever detect_three_inside_sequence()
    already placed on the (Structure -> Strategy) snapshot. Verified two
    ways: (1) source-level -- react() never calls the detector or touches
    raw candles; (2) behaviorally -- feeding the REAL detector's own
    output straight through produces markings whose index/timestamp are
    byte-identical to that output, with no transformation."""
    import inspect

    from core.strategy import ThreeInsideStrategy as mod
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    from core.structure_utils import detect_three_inside_sequence

    react_source = inspect.getsource(mod.ThreeInsideStrategy.react)
    assert "detect_three_inside_sequence" not in react_source
    assert "candles[" not in react_source

    candles = _three_inside_up_with_wick_excursion()
    detector_result = detect_three_inside_sequence(candles)
    assert detector_result["confirmed"] is True

    snap = _base_snapshot(
        three_inside_confirmed=detector_result["confirmed"],
        three_inside_direction=detector_result["direction"],
        three_inside_c1_index=detector_result["c1_index"],
        three_inside_c1_timestamp=detector_result["c1_timestamp"],
        three_inside_c1_open=detector_result["c1_open"], three_inside_c1_high=detector_result["c1_high"],
        three_inside_c1_low=detector_result["c1_low"], three_inside_c1_close=detector_result["c1_close"],
        three_inside_c2_index=detector_result["c2_index"],
        three_inside_c2_timestamp=detector_result["c2_timestamp"],
        three_inside_c2_open=detector_result["c2_open"], three_inside_c2_high=detector_result["c2_high"],
        three_inside_c2_low=detector_result["c2_low"], three_inside_c2_close=detector_result["c2_close"],
        three_inside_c3_index=detector_result["c3_index"],
        three_inside_c3_timestamp=detector_result["c3_timestamp"],
        three_inside_c3_open=detector_result["c3_open"], three_inside_c3_high=detector_result["c3_high"],
        three_inside_c3_low=detector_result["c3_low"], three_inside_c3_close=detector_result["c3_close"],
    )
    result = ThreeInsideStrategy().react(snap, {})
    c1_marking, c2_marking, c3_marking = result["chart_markings"]
    assert c1_marking["candle_index"] == detector_result["c1_index"]
    assert c1_marking["timestamp"] == detector_result["c1_timestamp"]
    assert c2_marking["candle_index"] == detector_result["c2_index"]
    assert c2_marking["timestamp"] == detector_result["c2_timestamp"]
    assert c3_marking["candle_index"] == detector_result["c3_index"]
    assert c3_marking["timestamp"] == detector_result["c3_timestamp"]


def test_confidence_formula_reported_exactly():
    from core.strategy.ThreeInsideStrategy import BASE_CONFIDENCE, MOMENTUM_WEIGHT, ThreeInsideStrategy
    assert BASE_CONFIDENCE == 0.5
    assert MOMENTUM_WEIGHT == 0.5
    overrides = dict(_UP_SEQUENCE)
    overrides["atr_normalized_momentum"] = 1.0  # agrees with "long"
    snap = _base_snapshot(**overrides)
    result = ThreeInsideStrategy().react(snap, {})
    assert result["confidence"] == round(0.5 + 0.5 * 0.5, 2)


def test_confidence_floor_with_no_momentum_support():
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    snap = _base_snapshot(**_UP_SEQUENCE)
    result = ThreeInsideStrategy().react(snap, {})
    assert result["confidence"] == 0.5


def test_standard_output_fields_present():
    from core.strategy.ThreeInsideStrategy import ThreeInsideStrategy
    snap = _base_snapshot(**_UP_SEQUENCE)
    result = ThreeInsideStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


# ---------------------------------------------------------------------------
# Absence of context gates.
# ---------------------------------------------------------------------------

def test_no_eligibility_gate_dependency():
    import core.strategy.ThreeInsideStrategy as mod
    source = inspect.getsource(mod.ThreeInsideStrategy.react)
    forbidden = (
        "context_zone", "context_level", "snr_context", "nearest_support", "nearest_resistance",
        "balance_range_confirmed", "volume_profile_", "structure_valid", "structure_type",
        "bias ==", "snapshot.bias", "inside_bar_",
    )
    for term in forbidden:
        assert term not in source, term


def test_detector_never_calls_structure_or_trend_detection():
    import core.structure_utils as su_mod
    source = inspect.getsource(su_mod.detect_three_inside_sequence)
    assert "detect_structure_event(" not in source
    assert "find_swings(" not in source
    assert "detect_trend(" not in source


def test_no_prior_trend_gap_or_atr_significance_check():
    """No prior-trend eligibility gate, no gap requirement, no Candle-1
    ATR/significance threshold -- confirmed by CODE BODY absence (the
    docstring itself legitimately discusses these ruled-out concepts in
    prose, e.g. "no gap requirement" -- checking the full source would
    trip on the docstring's own words, the same self-referential trap
    that hit Fix #7W/#7Y/#7AA; scope to statements after the docstring)."""
    import ast

    import core.structure_utils as su_mod

    source = inspect.getsource(su_mod.detect_three_inside_sequence)
    tree = ast.parse(source)
    func_node = tree.body[0]
    body_without_docstring = func_node.body[1:]  # drop the docstring Expr node
    code_only = ast.unparse(ast.Module(body=body_without_docstring, type_ignores=[]))

    forbidden = ("compute_atr", "gap", "prior_trend", "SWING_LOOKBACK", "MAX_INSIDE_BAR_CHILDREN")
    for term in forbidden:
        assert term not in code_only, term


# ---------------------------------------------------------------------------
# Discovery.
# ---------------------------------------------------------------------------

def test_strategy_engine_discovers_twentyfive_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.strategies) == 25
    assert "ThreeInsideStrategy" in engine.enabled


def test_existing_twentyfour_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_twentyfour = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy", "CHOCHBOSConfirmationStrategy", "MomentumPullbackRecoveryStrategy",
        "SupportResistanceReactionStrategy", "SupportResistanceBreakoutRetestStrategy",
        "VolumeProfileWeeklyReactionStrategy", "BalanceRangeVAHVALReactionStrategy",
        "InsideBarBreakoutStrategy",
    }
    assert existing_twentyfour <= set(engine.enabled.keys())
