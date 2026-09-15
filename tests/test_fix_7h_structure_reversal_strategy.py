"""Fix #7H — StructureReversalStrategy: the first genuinely new V12
strategy (Fix #7A/#7F's "Structure Reversal" family), built purely on
canonical structure evidence already on StrategySnapshot, with a
chart_markings "structure" marking from day one (Fix #7F/#7G's contract).

Eligibility is structure-first and structure-only:
  - structure_valid must be True
  - structure_type must be exactly "CHOCH" (BOS never qualifies)
  - structure_direction "Bullish"/"Bearish" -> "long"/"short"; anything
    else (Neutral, unrecognized) -> no candidate
No zone requirement, no bias requirement, no momentum gate -- momentum
may only scale confidence once already eligible.

Confidence formula (exact, reported before commit):
    confidence = round(min(0.5 + 0.5 * strategy_momentum_confidence(
        atr_normalized_momentum, direction), 1.0), 2)
0.5 base (CHoCH's own unconditional structural confirmation) + up to 0.5
more from the canonical, direction-agreement-gated momentum ingredient
(Fix #6AU, reused unmodified -- wrong-direction/None/zero ATR momentum
contributes exactly 0 to that term). Range: [0.5, 1.0] whenever eligible.

Also confirms (Fix #7H's own additive wiring): StrategySnapshot gained
event_timestamp/event_index/event_broken_level (straight copies from
StructureSnapshot, same pattern as Fix #6AS/#7C), needed to build the
marking's geometry -- none of the existing 7 plugins read these new
fields, and their own outputs are unaffected.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7h_structure_reversal_strategy.py -v
"""
from datetime import datetime, timezone

import pytest

from core.strategy.StructureReversalStrategy import StructureReversalStrategy, BASE_CONFIDENCE, MOMENTUM_WEIGHT
from core.strategy.strategy_models import StrategySnapshot, strategy_momentum_confidence


def _snap(**overrides):
    base = dict(
        symbol="T", timeframe="H1", bias="Neutral", momentum=5.0, strength=5.0,
        suppression=False, suppression_reason="",
        structure_type="CHOCH", structure_direction="Bullish", structure_valid=True,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        current_high=1.11, current_low=1.09,
        atr_normalized_momentum=None,
        event_timestamp="2026-01-01T00:00:00Z", event_index=17, event_broken_level=1.1050,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


# ---------------------------------------------------------------------------
# Bullish / Bearish CHoCH.
# ---------------------------------------------------------------------------

def test_bullish_choch_produces_long_candidate():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_direction="Bullish"), {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Bullish CHoCH"
    assert result["trigger"] == "CHOCH"


def test_bearish_choch_produces_short_candidate():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_direction="Bearish"), {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Bearish CHoCH"


# ---------------------------------------------------------------------------
# BOS rejection, invalid structure rejection, neutral rejection.
# ---------------------------------------------------------------------------

def test_bos_produces_no_candidate():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_type="BOS", structure_direction="Bullish"), {})
    assert result is None


def test_invalid_structure_produces_no_candidate():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_valid=False), {})
    assert result is None


def test_neutral_structure_direction_produces_no_candidate():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_type="CHOCH", structure_direction="Neutral"), {})
    assert result is None


def test_none_structure_type_produces_no_candidate():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_type="None", structure_direction="Bullish"), {})
    assert result is None


# ---------------------------------------------------------------------------
# No zone / bias / momentum gate on eligibility.
# ---------------------------------------------------------------------------

def test_eligibility_ignores_zone_context():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_direction="Bullish", context_zone="supply"), {})
    assert result is not None  # zone context irrelevant to eligibility


def test_eligibility_ignores_bias_field():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_direction="Bullish", bias="Bearish"), {})
    assert result is not None  # bias field (unrelated to structure_direction) irrelevant to eligibility


def test_eligibility_fires_even_with_no_momentum_at_all():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_direction="Bullish", atr_normalized_momentum=None), {})
    assert result is not None
    assert result["confidence"] == BASE_CONFIDENCE  # floor, momentum contributes 0


# ---------------------------------------------------------------------------
# Confidence formula: exact value, bounded, wrong-direction contributes 0.
# ---------------------------------------------------------------------------

def test_confidence_formula_exact_value_agreeing_momentum():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_direction="Bullish", atr_normalized_momentum=1.0), {})
    expected_momentum_term = strategy_momentum_confidence(1.0, "long")
    expected = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * expected_momentum_term, 1.0), 2)
    assert expected_momentum_term == 0.5
    assert expected == 0.75
    assert result["confidence"] == 0.75


def test_confidence_wrong_direction_momentum_contributes_zero():
    strat = StructureReversalStrategy()
    # Bullish CHoCH (direction="long") but momentum strongly bearish.
    result = strat.react(_snap(structure_direction="Bullish", atr_normalized_momentum=-5.0), {})
    assert result is not None
    assert strategy_momentum_confidence(-5.0, "long") == 0.0
    assert result["confidence"] == BASE_CONFIDENCE  # floor, wrong-direction contributes 0


def test_confidence_bounded_across_a_range_of_momentum_values():
    strat = StructureReversalStrategy()
    for atr in (-50.0, -1.0, -0.001, 0.0, 0.001, 0.5, 1.0, 2.0, 50.0, None):
        result = strat.react(_snap(structure_direction="Bullish", atr_normalized_momentum=atr), {})
        assert result is not None
        assert BASE_CONFIDENCE <= result["confidence"] <= 1.0


def test_confidence_saturates_at_full_weight():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_direction="Bullish", atr_normalized_momentum=100.0), {})
    assert result["confidence"] == 1.0


# ---------------------------------------------------------------------------
# Chart marking: exact geometry, label, direction.
# ---------------------------------------------------------------------------

def test_chart_marking_exact_geometry_bullish():
    strat = StructureReversalStrategy()
    result = strat.react(
        _snap(
            timeframe="H4", structure_direction="Bullish",
            event_timestamp="2026-03-01T12:00:00Z", event_index=41, event_broken_level=1.2345,
        ),
        {},
    )
    assert "chart_markings" in result
    assert len(result["chart_markings"]) == 1
    marking = result["chart_markings"][0]
    assert marking["type"] == "structure"
    assert marking["strategy"] == "StructureReversalStrategy"
    assert marking["timeframe"] == "H4"
    assert marking["label"] == "Bullish CHoCH"
    assert marking["direction"] == "long"
    assert marking["timestamp"] == "2026-03-01T12:00:00Z"
    assert marking["candle_index"] == 41
    assert marking["price"] == 1.2345
    assert marking["evidence_ref"] == {"source": "structure_events", "timeframe": "H4", "index": 41}


def test_chart_marking_exact_geometry_bearish():
    strat = StructureReversalStrategy()
    result = strat.react(
        _snap(
            timeframe="M15", structure_direction="Bearish",
            event_timestamp="2026-03-01T13:00:00Z", event_index=7, event_broken_level=0.9876,
        ),
        {},
    )
    marking = result["chart_markings"][0]
    assert marking["label"] == "Bearish CHoCH"
    assert marking["direction"] == "short"
    assert marking["timeframe"] == "M15"
    assert marking["timestamp"] == "2026-03-01T13:00:00Z"
    assert marking["candle_index"] == 7
    assert marking["price"] == 0.9876


def test_signal_top_level_price_matches_broken_level():
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_direction="Bullish", event_broken_level=1.5), {})
    assert result["price"] == 1.5


def test_chart_marking_is_internally_valid():
    """The marking StructureReversalStrategy builds must itself pass
    Fix #7G's own validator (it already does, since make_chart_marking()
    validates before returning -- this test proves that construction path
    never silently produces something invalid)."""
    from core.strategy.chart_markings import validate_chart_marking
    strat = StructureReversalStrategy()
    result = strat.react(_snap(structure_direction="Bearish"), {})
    validate_chart_marking(result["chart_markings"][0])  # raises if invalid


# ---------------------------------------------------------------------------
# StrategyEngine discovers the new strategy: 7 -> 8.
# ---------------------------------------------------------------------------

def test_strategy_engine_discovers_eight_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.enabled) == 8
    assert "StructureReversalStrategy" in engine.enabled


# ---------------------------------------------------------------------------
# Existing 7 strategies' outputs unchanged.
# ---------------------------------------------------------------------------

def _legacy_base_snapshot(**overrides):
    base = dict(
        symbol="T", timeframe="M5", bias="Bullish", momentum=5.0, strength=5.0,
        suppression=False, suppression_reason="",
        structure_type="BOS", structure_direction="Bullish", structure_valid=True,
        context_zone="demand", context_level=1.0, timestamp=datetime.now(timezone.utc),
        current_high=1.1, current_low=0.9, snr_strength=0.0, atr_normalized_momentum=1.0,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


def test_double_engulfing_output_unaffected_by_new_snapshot_fields():
    from core.strategy.DoubleEngulfingStrategy import DoubleEngulfingStrategy
    snap = _legacy_base_snapshot(timeframe="M15", engulfing_sequence=["bull", "bull"], engulfing_strength="Weak")
    result = DoubleEngulfingStrategy().react(snap, {})
    assert result is not None
    assert "chart_markings" not in result
    assert set(result.keys()) == {"symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price"}


def test_zone_continuation_output_unaffected_by_new_snapshot_fields():
    from core.strategy.ZoneContinuationStrategy import ZoneContinuationStrategy
    htf = _legacy_base_snapshot(timeframe="H1", context_zone="demand")
    ctx = {"T_H1": htf, "T_H4": htf}
    snap = _legacy_base_snapshot(timeframe="M5", structure_type="breakout", structure_direction="Bullish")
    result = ZoneContinuationStrategy().react(snap, ctx)
    assert result is not None
    assert "chart_markings" not in result


def test_new_snapshot_fields_default_to_none_when_omitted():
    """POST /core/evaluate's raw-JSON construction (StrategySnapshot(**data))
    omitting these keys must simply fall through to None, same pattern as
    Fix #6AS's atr_normalized_momentum."""
    snap = StrategySnapshot(
        symbol="T", timeframe="H1", bias="Neutral", momentum=1.0, strength=1.0,
        suppression=False, suppression_reason="", structure_type="CHOCH",
        structure_direction="Bullish", structure_valid=True, context_zone="neutral",
        context_level=None, timestamp=datetime.now(timezone.utc),
    )
    assert snap.event_timestamp is None
    assert snap.event_index is None
    assert snap.event_broken_level is None


def test_all_other_six_strategy_files_do_not_reference_new_fields():
    import pathlib
    plugin_dir = pathlib.Path("core/strategy")
    for name in [
        "BiasContinuationScalpingStrategy.py", "BiasContinuationSwingStrategy.py",
        "DoubleEngulfingStrategy.py", "ZoneContinuationStrategy.py",
        "ScalpingBiasCascade.py", "GroupedLastCandleBiasStrategy.py", "LastCandleBiasStrategy.py",
    ]:
        text = (plugin_dir / name).read_text(encoding="utf-8")
        assert "event_timestamp" not in text
        assert "event_broken_level" not in text


# ---------------------------------------------------------------------------
# Live end-to-end: to_strategy_snapshot() actually threads the new fields
# through from a real StructureSnapshot.
# ---------------------------------------------------------------------------

def test_live_to_strategy_snapshot_threads_event_evidence():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.strategy.StrategyEngine import to_strategy_snapshot
    from mt5.constants import TIMEFRAMES

    symbols = ["XAUUSD_i", "BTCUSD_i", "EURUSD_i", "USDJPY_i", "GBPUSD_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, TIMEFRAMES, count=100)

    checked_a_confirmed_event = False
    for symbol in symbols:
        for tf in TIMEFRAMES:
            structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
            if not structure or not structure.structure_valid:
                continue
            checked_a_confirmed_event = True
            strategy_snap = to_strategy_snapshot(structure)
            assert strategy_snap.event_timestamp == structure.event_timestamp
            assert strategy_snap.event_index == structure.event_index
            assert strategy_snap.event_broken_level == structure.event_broken_level
            assert strategy_snap.event_timestamp is not None
            assert strategy_snap.event_index is not None

    assert checked_a_confirmed_event


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
