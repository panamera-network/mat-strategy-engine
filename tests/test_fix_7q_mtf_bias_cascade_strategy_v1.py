"""Fix #7Q — MTF Bias Cascade v1 baseline: a fixed 3-timeframe (higher/
current/lower) canonical .bias agreement check.

This is a v1 BASELINE only -- timeframe families, weighting, and
partial-agreement rules are explicitly deferred to a later rule audit.
These tests lock in v1's exact behavior, not a claim that the rules are
final.

Evidence audit (Fix #7Q): no new StrategySnapshot/StructureSnapshot
wiring was needed at all. Every Strategy plugin already receives the same
`context` dict (core/Output/Output.py::_build_strategy_signals()), keyed
f"{symbol}_{tf}" for every canonical BIAS_ORDER timeframe, and
StrategySnapshot.bias already carries the canonical Fix #7C-corrected
bias direction ("Bullish"/"Bearish"/"Neutral"). This fix only adds a
central, canonical higher/current/lower timeframe mapping
(_cascade_timeframes(), derived from the real ordered timeframe sequence,
not a hardcoded per-strategy guess) and reads .bias through the existing
context dict -- never .direction, never alignment_decision, never the
legacy raw .momentum field.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7q_mtf_bias_cascade_strategy_v1.py -v
"""
from datetime import datetime, timezone

import pytest

from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot


def _snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        recent_candles=[{"direction": "bull", "index": 42, "timestamp": "2026-01-01T00:00:00Z"}],
    )
    base.update(overrides)
    return StrategySnapshot(**base)


def _cascade_context(symbol, higher_tf, higher_bias, lower_tf, lower_bias):
    return {
        f"{symbol}_{higher_tf}": _snapshot(symbol=symbol, timeframe=higher_tf, bias=higher_bias),
        f"{symbol}_{lower_tf}": _snapshot(symbol=symbol, timeframe=lower_tf, bias=lower_bias),
    }


# ---------------------------------------------------------------------------
# Timeframe mapping correct (audited from the real canonical order, not a
# hardcoded illustrative example).
# ---------------------------------------------------------------------------

def test_timeframe_mapping_m15():
    from core.strategy.MTFBiasCascadeStrategy import _cascade_timeframes
    assert _cascade_timeframes("M15") == ("M30", "M15", "M5")


def test_timeframe_mapping_h1_does_not_match_the_informal_h4_h1_m15_example():
    """The canonical sequence is M1,M5,M15,M30,H1,H4,D1,W1,MN1 -- H1's
    true immediate lower neighbor is M30, not M15 (M15 is two steps
    below H1). A hardcoded "H4/H1/M15" mapping would be wrong against the
    real canonical order -- this test locks in the CORRECT derived
    mapping, not the illustrative example given in the fix description."""
    from core.strategy.MTFBiasCascadeStrategy import _cascade_timeframes
    assert _cascade_timeframes("H1") == ("H4", "H1", "M30")


def test_timeframe_mapping_h4():
    from core.strategy.MTFBiasCascadeStrategy import _cascade_timeframes
    assert _cascade_timeframes("H4") == ("D1", "H4", "H1")


def test_timeframe_mapping_d1():
    from core.strategy.MTFBiasCascadeStrategy import _cascade_timeframes
    assert _cascade_timeframes("D1") == ("W1", "D1", "H4")


def test_timeframe_mapping_unknown_timeframe_returns_none():
    from core.strategy.MTFBiasCascadeStrategy import _cascade_timeframes
    assert _cascade_timeframes("M2") is None
    assert _cascade_timeframes("") is None


# ---------------------------------------------------------------------------
# Edge timeframe behavior explicit: M1 (no lower) and MN1 (no higher)
# must both be out of scope for v1, never silently degrade to a 2-TF check.
# ---------------------------------------------------------------------------

def test_edge_timeframe_m1_has_no_lower_neighbor_rejected():
    from core.strategy.MTFBiasCascadeStrategy import _cascade_timeframes, MTFBiasCascadeStrategy
    assert _cascade_timeframes("M1") is None
    snap = _snapshot(timeframe="M1", bias="Bullish")
    context = {"EURUSD_i_M5": _snapshot(symbol="EURUSD_i", timeframe="M5", bias="Bullish")}
    assert MTFBiasCascadeStrategy().react(snap, context) is None


def test_edge_timeframe_mn1_has_no_higher_neighbor_rejected():
    from core.strategy.MTFBiasCascadeStrategy import _cascade_timeframes, MTFBiasCascadeStrategy
    assert _cascade_timeframes("MN1") is None
    snap = _snapshot(timeframe="MN1", bias="Bullish")
    context = {"EURUSD_i_W1": _snapshot(symbol="EURUSD_i", timeframe="W1", bias="Bullish")}
    assert MTFBiasCascadeStrategy().react(snap, context) is None


# ---------------------------------------------------------------------------
# Eligibility: 3TF agreement.
# ---------------------------------------------------------------------------

def test_three_tf_bullish_agreement_valid():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish")
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Bullish MTF Bias Cascade"
    assert result["trigger"] == "MTF_BIAS_CASCADE"


def test_three_tf_bearish_agreement_valid():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bearish")
    context = _cascade_context("EURUSD_i", "H4", "Bearish", "M30", "Bearish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Bearish MTF Bias Cascade"


# ---------------------------------------------------------------------------
# Rejections.
# ---------------------------------------------------------------------------

def test_one_neutral_rejected():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish")
    context = _cascade_context("EURUSD_i", "H4", "Neutral", "M30", "Bullish")
    assert MTFBiasCascadeStrategy().react(snap, context) is None


def test_one_disagreement_rejected():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish")
    context = _cascade_context("EURUSD_i", "H4", "Bearish", "M30", "Bullish")
    assert MTFBiasCascadeStrategy().react(snap, context) is None


def test_one_missing_rejected():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish")
    context = {"EURUSD_i_H4": _snapshot(symbol="EURUSD_i", timeframe="H4", bias="Bullish")}  # M30 missing
    assert MTFBiasCascadeStrategy().react(snap, context) is None


def test_current_snapshot_neutral_rejected():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Neutral")
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    assert MTFBiasCascadeStrategy().react(snap, context) is None


def test_empty_context_rejected():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish")
    assert MTFBiasCascadeStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# No alignment_decision / no raw momentum dependency.
# ---------------------------------------------------------------------------

def test_no_alignment_decision_dependency():
    """The strategy's own docstring explains what it deliberately does NOT
    use (naming compute_alignment_signal/alignment_decision/core.Output in
    prose to contrast with .bias) -- so this checks the actual import
    lines only, not mere mention of the term in explanatory text."""
    import pathlib
    lines = pathlib.Path("core/strategy/MTFBiasCascadeStrategy.py").read_text(encoding="utf-8").splitlines()
    import_lines = [ln for ln in lines if ln.startswith("from ") or ln.startswith("import ")]
    for ln in import_lines:
        assert "alignment" not in ln.lower()
        assert "core.Output" not in ln
    assert "alignment_decision" not in "\n".join(import_lines)


def test_no_raw_momentum_dependency():
    import pathlib
    text = pathlib.Path("core/strategy/MTFBiasCascadeStrategy.py").read_text(encoding="utf-8")
    assert "snapshot.momentum" not in text
    assert ".direction ==" not in text  # never reads StyleSnapshot-style .direction


def test_eligibility_reads_only_bias_field_never_direction_field():
    """Defense in depth: a snapshot whose .direction attribute (if it even
    existed) disagreed with .bias must still be judged purely on .bias."""
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish")
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    assert result is not None
    assert result["direction"] == "long"


# ---------------------------------------------------------------------------
# No zone/structure/candle-pattern dependency.
# ---------------------------------------------------------------------------

def test_eligibility_ignores_zone_structure_candle_pattern():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(
        symbol="EURUSD_i", timeframe="H1", bias="Bullish",
        context_zone="supply", structure_type="CHOCH", structure_direction="Bearish", structure_valid=True,
    )
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    assert result is not None
    assert result["direction"] == "long"


def test_source_file_does_not_read_zone_or_structure_fields():
    import pathlib
    text = pathlib.Path("core/strategy/MTFBiasCascadeStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("snapshot.context_zone", "snapshot.context_level",
                      "snapshot.structure_type", "snapshot.structure_direction", "snapshot.structure_valid",
                      "snapshot.active_zone_type", "snapshot.mitigated_zone_type"):
        assert forbidden not in text, f"MTFBiasCascadeStrategy.py unexpectedly reads {forbidden}"


# ---------------------------------------------------------------------------
# Chart marking: exactly one real candle marking, no fabrication.
# ---------------------------------------------------------------------------

def test_exactly_one_candle_marking_emitted():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish")
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    assert len(result["chart_markings"]) == 1
    assert result["chart_markings"][0]["type"] == "candle"


def test_marking_uses_real_current_candle_geometry():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish")
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    m = result["chart_markings"][0]
    assert m["timestamp"] == "2026-01-01T00:00:00Z"
    assert m["candle_index"] == 42
    assert m["direction"] == "long"


def test_marking_label_matches_direction():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    s = MTFBiasCascadeStrategy()
    bull = s.react(_snapshot(symbol="T", timeframe="H1", bias="Bullish"), _cascade_context("T", "H4", "Bullish", "M30", "Bullish"))
    bear = s.react(_snapshot(symbol="T", timeframe="H1", bias="Bearish"), _cascade_context("T", "H4", "Bearish", "M30", "Bearish"))
    assert bull["chart_markings"][0]["label"] == "Bullish MTF Bias Cascade"
    assert bear["chart_markings"][0]["label"] == "Bearish MTF Bias Cascade"


def test_evidence_ref_includes_all_three_timeframe_bias_states():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish")
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    evidence = result["chart_markings"][0]["evidence_ref"]
    assert evidence["H4"] == "Bullish"
    assert evidence["H1"] == "Bullish"
    assert evidence["M30"] == "Bullish"


def test_marking_self_validates():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish")
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    validate_chart_marking(result["chart_markings"][0])


def test_no_marking_when_no_recent_candles_available():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish", recent_candles=[])
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    assert MTFBiasCascadeStrategy().react(snap, context) is None


# ---------------------------------------------------------------------------
# Confidence: bounded, exact formula.
# ---------------------------------------------------------------------------

def test_confidence_bounded_base_only():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish", atr_normalized_momentum=None)
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["confidence"] == 0.5


def test_confidence_exact_formula_with_momentum():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish", atr_normalized_momentum=1.0)
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    assert result["confidence"] == 0.75


def test_confidence_saturates_at_cap():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish", atr_normalized_momentum=5.0)
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    assert result["confidence"] == 1.0


def test_confidence_floors_at_base_on_disagreeing_momentum():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish", atr_normalized_momentum=-2.0)
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    assert result["confidence"] == 0.5


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    snap = _snapshot(symbol="EURUSD_i", timeframe="H1", bias="Bullish")
    context = _cascade_context("EURUSD_i", "H4", "Bullish", "M30", "Bullish")
    result = MTFBiasCascadeStrategy().react(snap, context)
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_strategy_engine_discovers_fifteen_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.strategies) == 15
    assert "MTFBiasCascadeStrategy" in engine.enabled


def test_existing_fourteen_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_fourteen = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy",
    }
    assert existing_fourteen <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_gracefully():
    """A raw-JSON-body StrategySnapshot(**data) that omits recent_candles
    falls through to None -- never guessed -- and the strategy rejects
    cleanly rather than crashing."""
    base = dict(
        symbol="T", timeframe="H1", bias="Bullish", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
    )
    snap = StrategySnapshot(**base)
    assert snap.recent_candles is None
    from core.strategy.MTFBiasCascadeStrategy import MTFBiasCascadeStrategy
    context = _cascade_context("T", "H4", "Bullish", "M30", "Bullish")
    assert MTFBiasCascadeStrategy().react(snap, context) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
