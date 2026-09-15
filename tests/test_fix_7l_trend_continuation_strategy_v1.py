"""Fix #7L — Trend Continuation v1 baseline: a valid BOS whose direction
agrees with the canonical pre-break trend (Fix #6C), i.e. a genuine
continuation of an already-established trend.

This is a v1 BASELINE only -- the eligibility rule and the confidence
formula are both explicitly provisional (final rules/tuning deferred to a
later rule audit). These tests lock in v1's exact behavior, not a claim
that the rules are final.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7l_trend_continuation_strategy_v1.py -v
"""
from datetime import datetime, timezone

import pytest

from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot


def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        event_timestamp="2026-01-01T00:00:00Z", event_index=42, event_broken_level=1.2345,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


# ---------------------------------------------------------------------------
# Eligibility: bullish/bearish valid continuation.
# ---------------------------------------------------------------------------

def test_bullish_valid_continuation_fires_long():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish")
    result = TrendContinuationStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["trigger"] == "BOS"
    assert result["reason"] == "Bullish BOS Continuation"


def test_bearish_valid_continuation_fires_short():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bearish", structure_valid=True, pre_break_trend="Bearish")
    result = TrendContinuationStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["trigger"] == "BOS"
    assert result["reason"] == "Bearish BOS Continuation"


# ---------------------------------------------------------------------------
# Rejections.
# ---------------------------------------------------------------------------

def test_choch_rejected():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="CHOCH", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bearish")
    assert TrendContinuationStrategy().react(snap, {}) is None


def test_bullish_bos_from_neutral_rejected():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Neutral")
    assert TrendContinuationStrategy().react(snap, {}) is None


def test_bearish_bos_from_neutral_rejected():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bearish", structure_valid=True, pre_break_trend="Neutral")
    assert TrendContinuationStrategy().react(snap, {}) is None


def test_bos_against_pre_break_trend_rejected():
    """A bullish BOS whose pre_break_trend was actually Bearish (an
    inconsistent combination detect_structure_event() would never itself
    label BOS in real data -- it would be CHOCH -- but the strategy's own
    eligibility must independently enforce agreement, never trust the
    structure_type label alone)."""
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bearish")
    assert TrendContinuationStrategy().react(snap, {}) is None


def test_bearish_bos_against_pre_break_trend_rejected():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bearish", structure_valid=True, pre_break_trend="Bullish")
    assert TrendContinuationStrategy().react(snap, {}) is None


def test_invalid_structure_rejected():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=False, pre_break_trend="Bullish")
    assert TrendContinuationStrategy().react(snap, {}) is None


def test_no_confirmed_event_rejected():
    """Default snapshot: structure_type='None', structure_valid=False,
    pre_break_trend=None -- the everyday no-event case."""
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot()
    assert TrendContinuationStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Chart marking: exactly one, correct label/geometry.
# ---------------------------------------------------------------------------

def test_exactly_one_structure_marking_emitted():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish")
    result = TrendContinuationStrategy().react(snap, {})
    assert len(result["chart_markings"]) == 1


def test_marking_label_matches_direction():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    bullish = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish")
    bearish = _base_snapshot(structure_type="BOS", structure_direction="Bearish", structure_valid=True, pre_break_trend="Bearish")
    r_bull = TrendContinuationStrategy().react(bullish, {})
    r_bear = TrendContinuationStrategy().react(bearish, {})
    assert r_bull["chart_markings"][0]["label"] == "Bullish BOS Continuation"
    assert r_bear["chart_markings"][0]["label"] == "Bearish BOS Continuation"


def test_marking_geometry_uses_real_evaluated_event_evidence():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(
        structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish",
        event_timestamp="2026-03-01T04:00:00Z", event_index=17, event_broken_level=1.09876,
    )
    result = TrendContinuationStrategy().react(snap, {})
    m = result["chart_markings"][0]
    assert m["timestamp"] == "2026-03-01T04:00:00Z"
    assert m["candle_index"] == 17
    assert m["price"] == 1.09876
    assert m["timeframe"] == "H1"
    assert m["direction"] == "long"
    assert m["type"] == "structure"
    assert m["evidence_ref"] == {"source": "structure_events", "timeframe": "H1", "index": 17}


def test_marking_self_validates():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish")
    result = TrendContinuationStrategy().react(snap, {})
    validate_chart_marking(result["chart_markings"][0])


def test_no_reconstructed_geometry_when_broken_level_unavailable():
    """When event_broken_level is None (shouldn't happen with a genuine
    confirmed event, per Fix #2/#6C's guarantee, but the marking must
    never invent a price if it somehow is), the marking is still valid
    from timestamp+index alone -- never a fabricated price."""
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(
        structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish",
        event_broken_level=None,
    )
    result = TrendContinuationStrategy().react(snap, {})
    assert "price" not in result["chart_markings"][0]
    validate_chart_marking(result["chart_markings"][0])


# ---------------------------------------------------------------------------
# Confidence: bounded [0, 1], exact v1 formula, momentum as support only.
# ---------------------------------------------------------------------------

def test_confidence_bounded_zero_to_one_no_momentum():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish", atr_normalized_momentum=None)
    result = TrendContinuationStrategy().react(snap, {})
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["confidence"] == 0.5  # base only, no momentum term


def test_confidence_saturates_at_cap_with_strong_agreeing_momentum():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish", atr_normalized_momentum=5.0)
    result = TrendContinuationStrategy().react(snap, {})
    assert result["confidence"] == 1.0


def test_confidence_floors_at_base_on_disagreeing_momentum():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish", atr_normalized_momentum=-2.0)
    result = TrendContinuationStrategy().react(snap, {})
    assert result["confidence"] == 0.5


def test_exact_confidence_formula_value():
    """Locks the exact v1 formula: 0.5 + 0.5 * strategy_momentum_confidence
    -- 1.0 ATR agreeing momentum -> momentum term 0.5 -> confidence 0.75."""
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish", atr_normalized_momentum=1.0)
    result = TrendContinuationStrategy().react(snap, {})
    assert result["confidence"] == 0.75


# ---------------------------------------------------------------------------
# No zone/candle dependency.
# ---------------------------------------------------------------------------

def test_eligibility_ignores_zone_and_candle_evidence():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(
        structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish",
        context_zone="supply",  # opposing zone -- must not block eligibility
        recent_candles=[
            {"direction": "bear", "index": 1, "timestamp": "t1"},
            {"direction": "bear", "index": 2, "timestamp": "t2"},
            {"direction": "bear", "index": 3, "timestamp": "t3"},
        ],  # no IPC-style bullish candle sequence at all -- must not matter
    )
    result = TrendContinuationStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"


def test_source_file_does_not_read_zone_or_candle_fields():
    """Static check reinforcing the eligibility-ignores test above: the
    plugin source itself never references context_zone/context_level or
    recent_candles for eligibility."""
    import pathlib
    text = pathlib.Path("core/strategy/TrendContinuationStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("snapshot.context_zone", "snapshot.context_level", "snapshot.recent_candles",
                      "snapshot.bias", "snapshot.snr_context"):
        assert forbidden not in text, f"TrendContinuationStrategy.py unexpectedly reads {forbidden}"


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    snap = _base_snapshot(structure_type="BOS", structure_direction="Bullish", structure_valid=True, pre_break_trend="Bullish")
    result = TrendContinuationStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_strategy_engine_discovers_ten_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.strategies) == 10
    assert "TrendContinuationStrategy" in engine.enabled


def test_existing_nine_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_nine = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy",
    }
    assert existing_nine <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_to_none():
    """A raw-JSON-body StrategySnapshot(**data) that omits pre_break_trend
    (e.g. an older /core/evaluate caller) falls through to None, same
    convention as every other Fix #7-era additive field -- never guessed."""
    base = dict(
        symbol="T", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="BOS", structure_direction="Bullish", structure_valid=True,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
    )
    snap = StrategySnapshot(**base)
    assert snap.pre_break_trend is None
    from core.strategy.TrendContinuationStrategy import TrendContinuationStrategy
    assert TrendContinuationStrategy().react(snap, {}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
