"""Fix #7O — Momentum Expansion v1 baseline: a momentum-only strategy
consuming canonical atr_normalized_momentum directly.

This is a v1 BASELINE only -- it measures strong CURRENT momentum at the
moment of evaluation, NOT a proven weak-to-strong expansion over time.
There is no historical/prior-snapshot state anywhere in this strategy.
Stateful weak->strong/threshold-crossing semantics are explicitly
deferred to a later rule audit/version. These tests lock in v1's exact
behavior, not a claim that the rules are final.

Threshold/confidence audit (reported in the strategy source too): a live
empirical sample across all 36 canonical SYMBOLS x all 9 canonical
TIMEFRAMES (324 pairs, zero missing) found |atr_normalized_momentum|
p90=2.26 -- MOMENTUM_THRESHOLD=2.0 sits at roughly that percentile and
doubles as strategy_momentum_confidence()'s own existing saturation cap
(Fix #6AT/#6AU), not an independently invented number.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7o_momentum_expansion_strategy_v1.py -v
"""
import pathlib
from datetime import datetime, timezone

import pytest

from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot


_RECENT_CANDLES = [
    {"direction": "bull", "index": 10, "timestamp": "2026-01-01T00:00:00Z"},
    {"direction": "bear", "index": 11, "timestamp": "2026-01-01T01:00:00Z"},
    {"direction": "bull", "index": 12, "timestamp": "2026-01-01T02:00:00Z"},
]


def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        atr_normalized_momentum=None,
        recent_candles=list(_RECENT_CANDLES),
    )
    base.update(overrides)
    return StrategySnapshot(**base)


# ---------------------------------------------------------------------------
# Eligibility: bullish/bearish.
# ---------------------------------------------------------------------------

def test_bullish_eligible_fires_long():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=2.5), {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Bullish Momentum Expansion"
    assert result["trigger"] == "MOMENTUM_EXPANSION"


def test_bearish_eligible_fires_short():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=-2.5), {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Bearish Momentum Expansion"


# ---------------------------------------------------------------------------
# Rejections.
# ---------------------------------------------------------------------------

def test_below_threshold_rejected():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    assert MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=1.5), {}) is None
    assert MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=-1.5), {}) is None


def test_zero_rejected():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    assert MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=0.0), {}) is None


def test_missing_momentum_rejected():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    assert MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=None), {}) is None


def test_wrong_raw_legacy_momentum_ignored():
    """A huge raw legacy `momentum` value must never substitute for a
    missing/insufficient canonical atr_normalized_momentum."""
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    snap = _base_snapshot(momentum=9999.0, atr_normalized_momentum=None)
    assert MomentumExpansionStrategy().react(snap, {}) is None

    snap2 = _base_snapshot(momentum=9999.0, atr_normalized_momentum=1.0)  # below threshold
    assert MomentumExpansionStrategy().react(snap2, {}) is None


def test_source_file_never_reads_raw_momentum_field():
    text = pathlib.Path("core/strategy/MomentumExpansionStrategy.py").read_text(encoding="utf-8")
    assert "snapshot.momentum" not in text


# ---------------------------------------------------------------------------
# Exact threshold boundary behavior.
# ---------------------------------------------------------------------------

def test_exact_boundary_value_is_eligible_bullish():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=2.0), {})
    assert result is not None
    assert result["direction"] == "long"


def test_exact_boundary_value_is_eligible_bearish():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=-2.0), {})
    assert result is not None
    assert result["direction"] == "short"


def test_just_below_boundary_rejected():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    assert MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=1.999999), {}) is None
    assert MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=-1.999999), {}) is None


# ---------------------------------------------------------------------------
# Confidence: monotonic with magnitude, bounded, exact formula.
# ---------------------------------------------------------------------------

def test_confidence_at_threshold_is_the_documented_floor():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=2.0), {})
    assert result["confidence"] == 0.5


def test_confidence_saturates_at_4x_atr():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=4.0), {})
    assert result["confidence"] == 1.0


def test_confidence_stays_capped_beyond_saturation():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=10.0), {})
    assert result["confidence"] == 1.0


def test_confidence_monotonic_with_magnitude():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    s = MomentumExpansionStrategy()
    magnitudes = [2.0, 2.5, 3.0, 3.5, 4.0]
    confidences = [s.react(_base_snapshot(atr_normalized_momentum=m), {})["confidence"] for m in magnitudes]
    assert confidences == sorted(confidences)
    assert len(set(confidences)) == len(confidences)  # strictly increasing, not flat


def test_confidence_bounded_zero_to_one():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    s = MomentumExpansionStrategy()
    for m in (2.0, 2.5, 3.3, 5.0, 6.83, -2.0, -6.83):
        result = s.react(_base_snapshot(atr_normalized_momentum=m), {})
        assert 0.0 <= result["confidence"] <= 1.0


def test_exact_confidence_formula_value():
    """Locks the exact v1 formula:
    round(min(abs(momentum) / (2.0 * 2.0), 1.0), 2)."""
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=3.0), {})
    assert result["confidence"] == 0.75  # 3.0 / 4.0 = 0.75


def test_confidence_symmetric_for_bearish():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    s = MomentumExpansionStrategy()
    bull = s.react(_base_snapshot(atr_normalized_momentum=3.0), {})
    bear = s.react(_base_snapshot(atr_normalized_momentum=-3.0), {})
    assert bull["confidence"] == bear["confidence"] == 0.75


# ---------------------------------------------------------------------------
# No zone/structure/bias/candle-pattern dependency.
# ---------------------------------------------------------------------------

def test_eligibility_ignores_zone_structure_bias():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    snap = _base_snapshot(
        atr_normalized_momentum=2.5,
        bias="Bearish", context_zone="supply",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
    )
    result = MomentumExpansionStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"  # momentum sign alone decides direction


def test_eligibility_ignores_candle_pattern_shape():
    """The specific candle-direction sequence must not matter -- only
    used for identifying the current candle's own timestamp/index."""
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    all_bear_candles = [
        {"direction": "bear", "index": 1, "timestamp": "t1"},
        {"direction": "bear", "index": 2, "timestamp": "t2"},
        {"direction": "bear", "index": 3, "timestamp": "t3"},
    ]
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=2.5, recent_candles=all_bear_candles), {})
    assert result is not None
    assert result["direction"] == "long"


def test_source_file_does_not_read_zone_structure_bias_candle_pattern():
    text = pathlib.Path("core/strategy/MomentumExpansionStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("snapshot.context_zone", "snapshot.bias", "snapshot.structure_type",
                      "snapshot.structure_direction", "snapshot.structure_valid",
                      "snapshot.snr_context"):
        assert forbidden not in text, f"MomentumExpansionStrategy.py unexpectedly reads {forbidden}"


# ---------------------------------------------------------------------------
# No historical/prior-snapshot state.
# ---------------------------------------------------------------------------

def test_source_file_has_no_state_between_calls():
    """Static check: the strategy must not store anything on self between
    calls (no prior-snapshot memory) -- calling react() twice with
    different snapshots must be fully independent."""
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    s = MomentumExpansionStrategy()
    r1 = s.react(_base_snapshot(atr_normalized_momentum=2.0), {})
    r2 = s.react(_base_snapshot(atr_normalized_momentum=1.0), {})  # would-be "weaker" second call
    r3 = s.react(_base_snapshot(atr_normalized_momentum=2.0), {})
    assert r1 == r3  # identical inputs -> identical output, no memory of r2 in between
    assert r2 is None
    assert not vars(s)  # no instance state accumulated


# ---------------------------------------------------------------------------
# Chart marking: exactly one, real geometry, no fabrication.
# ---------------------------------------------------------------------------

def test_exactly_one_candle_marking_emitted():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=2.5), {})
    assert len(result["chart_markings"]) == 1
    assert result["chart_markings"][0]["type"] == "candle"


def test_marking_uses_real_current_candle_geometry():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=2.5), {})
    m = result["chart_markings"][0]
    # The LAST entry of recent_candles is the current/most-recent candle.
    assert m["timestamp"] == "2026-01-01T02:00:00Z"
    assert m["candle_index"] == 12
    assert m["timeframe"] == "H1"
    assert m["direction"] == "long"


def test_marking_label_matches_direction():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    s = MomentumExpansionStrategy()
    bull = s.react(_base_snapshot(atr_normalized_momentum=2.5), {})
    bear = s.react(_base_snapshot(atr_normalized_momentum=-2.5), {})
    assert bull["chart_markings"][0]["label"] == "Bullish Momentum Expansion"
    assert bear["chart_markings"][0]["label"] == "Bearish Momentum Expansion"


def test_marking_self_validates():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=2.5), {})
    validate_chart_marking(result["chart_markings"][0])


def test_no_marking_when_no_recent_candles_available():
    """Defensive: if recent_candles is genuinely empty (should not happen
    live once eligible, per the strategy's own documented reasoning), the
    strategy must reject rather than fabricate a timestamp/index."""
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    snap = _base_snapshot(atr_normalized_momentum=2.5, recent_candles=[])
    assert MomentumExpansionStrategy().react(snap, {}) is None

    snap2 = _base_snapshot(atr_normalized_momentum=2.5, recent_candles=None)
    assert MomentumExpansionStrategy().react(snap2, {}) is None


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    result = MomentumExpansionStrategy().react(_base_snapshot(atr_normalized_momentum=2.5), {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_strategy_engine_discovers_thirteen_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.strategies) == 13
    assert "MomentumExpansionStrategy" in engine.enabled


def test_existing_twelve_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_twelve = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy",
    }
    assert existing_twelve <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_to_none():
    base = dict(
        symbol="T", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
    )
    snap = StrategySnapshot(**base)
    assert snap.atr_normalized_momentum is None
    assert snap.recent_candles is None
    from core.strategy.MomentumExpansionStrategy import MomentumExpansionStrategy
    assert MomentumExpansionStrategy().react(snap, {}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
