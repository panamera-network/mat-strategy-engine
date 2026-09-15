"""Fix #7K — IPC v1 baseline: Ignite -> Pullback -> Confirmation, a new
3-candle-sequence strategy.

This is a v1 BASELINE only -- the color-sequence rule and the confidence
formula are both explicitly provisional (parameter tuning deferred to a
future IPC rule audit). These tests lock in v1's exact behavior, not a
claim that the rules are final.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7k_ipc_strategy_v1.py -v
"""
from datetime import datetime, timezone

import pytest

from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot


def _candle(direction: str, index: int, timestamp: str = None):
    return {"direction": direction, "index": index, "timestamp": timestamp or f"t{index}"}


def _base_snapshot(recent_candles, **overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="M5", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        recent_candles=recent_candles,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_BULLISH_SEQUENCE = [_candle("bull", 10), _candle("bear", 11), _candle("bull", 12)]
_BEARISH_SEQUENCE = [_candle("bear", 10), _candle("bull", 11), _candle("bear", 12)]


# ---------------------------------------------------------------------------
# Eligibility: bullish/bearish candidates.
# ---------------------------------------------------------------------------

def test_bullish_ipc_candidate_fires_long():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BULLISH_SEQUENCE)
    result = IPCStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["trigger"] == "IPC"
    assert result["reason"] == "Bullish IPC"


def test_bearish_ipc_candidate_fires_short():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BEARISH_SEQUENCE)
    result = IPCStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["trigger"] == "IPC"
    assert result["reason"] == "Bearish IPC"


# ---------------------------------------------------------------------------
# Rejections.
# ---------------------------------------------------------------------------

def test_wrong_candle_order_rejected():
    """Color sequence matches an IPC pattern set, but not aligned to the
    I/P/C position order this fix requires (bull, bull, bear is not any
    valid IPC shape at all -- covers "right colors, wrong slot")."""
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot([_candle("bull", 10), _candle("bull", 11), _candle("bear", 12)])
    assert IPCStrategy().react(snap, {}) is None


def test_wrong_color_sequence_rejected():
    """All three candles the same color -- no ignite/pullback contrast at
    all, must not be mistaken for either IPC shape."""
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot([_candle("bull", 10), _candle("bull", 11), _candle("bull", 12)])
    assert IPCStrategy().react(snap, {}) is None


def test_missing_one_leg_rejected_only_two_candles():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BULLISH_SEQUENCE[:2])
    assert IPCStrategy().react(snap, {}) is None


def test_missing_all_candles_rejected():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(None)
    assert IPCStrategy().react(snap, {}) is None


def test_neutral_candle_in_sequence_rejected():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot([_candle("bull", 10), _candle("neutral", 11), _candle("bull", 12)])
    assert IPCStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Chart markings: exactly 3, correct labels/geometry.
# ---------------------------------------------------------------------------

def test_exactly_three_markings_emitted():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BULLISH_SEQUENCE)
    result = IPCStrategy().react(snap, {})
    assert len(result["chart_markings"]) == 3


def test_marking_labels_are_ipc_i_p_c_in_order():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BULLISH_SEQUENCE)
    result = IPCStrategy().react(snap, {})
    labels = [m["label"] for m in result["chart_markings"]]
    assert labels == ["IPC I", "IPC P", "IPC C"]


def test_marking_geometry_matches_the_actual_three_candles_used():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BULLISH_SEQUENCE)
    result = IPCStrategy().react(snap, {})
    m_i, m_p, m_c = result["chart_markings"]
    assert m_i["candle_index"] == 10 and m_i["timestamp"] == "t10"
    assert m_p["candle_index"] == 11 and m_p["timestamp"] == "t11"
    assert m_c["candle_index"] == 12 and m_c["timestamp"] == "t12"


def test_markings_carry_timeframe_and_direction():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BEARISH_SEQUENCE, timeframe="H1")
    result = IPCStrategy().react(snap, {})
    for m in result["chart_markings"]:
        assert m["timeframe"] == "H1"
        assert m["direction"] == "short"
        assert m["type"] == "candle"


def test_markings_each_self_validate():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BULLISH_SEQUENCE)
    result = IPCStrategy().react(snap, {})
    for m in result["chart_markings"]:
        validate_chart_marking(m)  # raises ChartMarkingError if invalid


def test_no_fabricated_geometry_when_candle_lacks_timestamp():
    """If a candle's evidence carries only an index (no timestamp), the
    marking must be built from that real index alone -- never invent a
    timestamp to fill the gap."""
    from core.strategy.IPCStrategy import IPCStrategy
    sequence = [
        {"direction": "bull", "index": 20, "timestamp": None},
        {"direction": "bear", "index": 21, "timestamp": None},
        {"direction": "bull", "index": 22, "timestamp": None},
    ]
    snap = _base_snapshot(sequence)
    result = IPCStrategy().react(snap, {})
    for m in result["chart_markings"]:
        assert "timestamp" not in m
        assert m["candle_index"] in (20, 21, 22)


# ---------------------------------------------------------------------------
# Confidence: bounded [0, 1], momentum as support only (never a gate).
# ---------------------------------------------------------------------------

def test_confidence_bounded_zero_to_one_no_momentum():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BULLISH_SEQUENCE, atr_normalized_momentum=None)
    result = IPCStrategy().react(snap, {})
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["confidence"] == 0.5  # base only, no momentum term


def test_confidence_rises_with_agreeing_momentum_but_stays_bounded():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BULLISH_SEQUENCE, atr_normalized_momentum=5.0)
    result = IPCStrategy().react(snap, {})
    assert result["confidence"] == 1.0  # saturates at cap, never exceeds 1.0


def test_confidence_floors_at_base_on_disagreeing_momentum():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BULLISH_SEQUENCE, atr_normalized_momentum=-2.0)
    result = IPCStrategy().react(snap, {})
    assert result["confidence"] == 0.5  # wrong-direction momentum contributes 0


def test_exact_confidence_formula_value():
    """Locks the exact v1 formula: 0.5 + 0.5 * strategy_momentum_confidence
    (capped at [0,1]) -- 1.0 ATR agreeing momentum -> momentum term 0.5."""
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BULLISH_SEQUENCE, atr_normalized_momentum=1.0)
    result = IPCStrategy().react(snap, {})
    assert result["confidence"] == 0.75


# ---------------------------------------------------------------------------
# No zone/bias/structure dependency.
# ---------------------------------------------------------------------------

def test_eligibility_ignores_zone_bias_structure():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(
        _BULLISH_SEQUENCE,
        bias="Bearish", context_zone="supply",
        structure_type="CHOCH", structure_direction="Bearish", structure_valid=True,
    )
    result = IPCStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"  # candle sequence alone decides direction


def test_source_file_does_not_read_zone_bias_or_structure_fields():
    """Static check reinforcing the eligibility-ignores test above: the
    plugin source itself never references context_zone/bias/structure_type/
    structure_direction/structure_valid for eligibility."""
    import pathlib
    text = pathlib.Path("core/strategy/IPCStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("snapshot.context_zone", "snapshot.bias", "snapshot.structure_type",
                      "snapshot.structure_direction", "snapshot.structure_valid"):
        assert forbidden not in text, f"IPCStrategy.py unexpectedly reads {forbidden}"


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.IPCStrategy import IPCStrategy
    snap = _base_snapshot(_BULLISH_SEQUENCE)
    result = IPCStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_strategy_engine_discovers_nine_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.strategies) == 9
    assert "IPCStrategy" in engine.enabled


def test_existing_eight_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_eight = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy",
    }
    assert existing_eight <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_to_none():
    """A raw-JSON-body StrategySnapshot(**data) that omits recent_candles
    (e.g. an older /core/evaluate caller) falls through to None, same
    convention as every other Fix #7K-era additive field -- never guessed."""
    base = dict(
        symbol="T", timeframe="M5", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
    )
    snap = StrategySnapshot(**base)
    assert snap.recent_candles is None
    from core.strategy.IPCStrategy import IPCStrategy
    assert IPCStrategy().react(snap, {}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
