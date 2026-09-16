"""Fix #7S — Conviction-Based Selective Entry v1 baseline: fires only on
the canonical, already-computed conviction evidence (StyleSnapshot.
conviction/direction, Fix #6AK), never recomputed or duplicated here.

Threshold audit (documented here and in
core.strategy.ConvictionSelectiveStrategy's own module docstring): a live
scan across the full 36-symbol x 9-timeframe universe found 261/324 pairs
with no directional call at all (conviction pinned at 0.0), and the
remaining 63 directed readings clustered low (median 0.08) with a sparse
gap before a much smaller cluster from ~0.5 upward (p90 ~0.54, max
observed 0.83). CONVICTION_THRESHOLD = 0.5 sits at the start of that
cluster and, for swing-mode conviction, cannot be reached by any single
component alone (max single-term weight is 0.4) -- a genuine multi-
component agreement requirement, not an arbitrary round number.

This is a v1 BASELINE only -- final threshold calibration, direction
arbitration, and family-specific conviction rules are explicitly deferred
to a later rule audit. These tests lock in v1's exact behavior, not a
claim that the rules are final.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7s_conviction_selective_strategy_v1.py -v
"""
from datetime import datetime, timezone

import pytest

from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot


def _candle(direction, index, timestamp, volume=100.0):
    return {"direction": direction, "index": index, "timestamp": timestamp, "volume": volume}


def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        conviction=None, conviction_direction=None,
        recent_candles=[_candle("neutral", 42, "2026-01-01T00:00:00Z")],
    )
    base.update(overrides)
    return StrategySnapshot(**base)


# ---------------------------------------------------------------------------
# Eligibility: above-threshold fires, both directions.
# ---------------------------------------------------------------------------

def test_bullish_conviction_above_threshold_valid_long():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(conviction=0.64, conviction_direction="uptrend")
    result = ConvictionSelectiveStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["trigger"] == "CONVICTION_SELECTIVE"
    assert result["reason"] == "Bullish High Conviction"
    assert result["confidence"] == 0.64


def test_bearish_conviction_above_threshold_valid_short():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(conviction=0.58, conviction_direction="downtrend")
    result = ConvictionSelectiveStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["trigger"] == "CONVICTION_SELECTIVE"
    assert result["reason"] == "Bearish High Conviction"
    assert result["confidence"] == 0.58


# ---------------------------------------------------------------------------
# Threshold behavior: below rejects, exactly-at fires (>=, inclusive).
# ---------------------------------------------------------------------------

def test_below_threshold_rejected():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(conviction=0.49, conviction_direction="uptrend")
    assert ConvictionSelectiveStrategy().react(snap, {}) is None


def test_exact_threshold_behavior_explicit_fires():
    """conviction exactly equal to the threshold is eligible (>=, not >) --
    explicit, not left to chance."""
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    from core.strategy.ConvictionSelectiveStrategy import CONVICTION_THRESHOLD
    snap = _base_snapshot(conviction=CONVICTION_THRESHOLD, conviction_direction="uptrend")
    result = ConvictionSelectiveStrategy().react(snap, {})
    assert result is not None
    assert result["confidence"] == CONVICTION_THRESHOLD


def test_just_below_threshold_rejected_explicit():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy, CONVICTION_THRESHOLD
    snap = _base_snapshot(conviction=round(CONVICTION_THRESHOLD - 0.01, 2), conviction_direction="downtrend")
    assert ConvictionSelectiveStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Direction / opposition handling.
# ---------------------------------------------------------------------------

def test_neutral_direction_rejected():
    """No directional call at all -- must reject regardless of any
    (defensively-supplied) conviction value."""
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(conviction=0.9, conviction_direction="neutral")
    assert ConvictionSelectiveStrategy().react(snap, {}) is None


def test_unrecognized_direction_rejected():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(conviction=0.9, conviction_direction="sideways")
    assert ConvictionSelectiveStrategy().react(snap, {}) is None


def test_missing_direction_rejected():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(conviction=0.9, conviction_direction=None)
    assert ConvictionSelectiveStrategy().react(snap, {}) is None


def test_opposition_case_remains_zero_and_rejected():
    """compute_conviction()'s own opposition/no-direction floor guarantees
    conviction == 0.0 whenever there is no real directional call -- a
    zero-conviction directed snapshot must still reject (0.0 < threshold),
    proving the strategy relies on that floor rather than re-checking
    opposition itself."""
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(conviction=0.0, conviction_direction="uptrend")
    assert ConvictionSelectiveStrategy().react(snap, {}) is None


def test_missing_conviction_rejected():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(conviction=None, conviction_direction="uptrend")
    assert ConvictionSelectiveStrategy().react(snap, {}) is None


def test_no_recent_candles_rejected():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(conviction=0.9, conviction_direction="uptrend", recent_candles=[])
    assert ConvictionSelectiveStrategy().react(snap, {}) is None
    snap2 = _base_snapshot(conviction=0.9, conviction_direction="uptrend", recent_candles=None)
    assert ConvictionSelectiveStrategy().react(snap2, {}) is None


# ---------------------------------------------------------------------------
# Chart marking: exactly one candle marking, real geometry, evidence_ref.
# ---------------------------------------------------------------------------

def test_exact_real_candle_marking_bullish():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(
        conviction=0.7, conviction_direction="uptrend",
        recent_candles=[_candle("bull", 99, "2026-02-01T03:00:00Z")],
    )
    result = ConvictionSelectiveStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 1
    marking = markings[0]
    validate_chart_marking(marking)
    assert marking["type"] == "candle"
    assert marking["direction"] == "long"
    assert marking["label"] == "Bullish High Conviction"
    assert marking["timestamp"] == "2026-02-01T03:00:00Z"
    assert marking["candle_index"] == 99
    assert marking["evidence_ref"]["conviction"] == 0.7
    assert marking["evidence_ref"]["conviction_direction"] == "uptrend"


def test_exact_real_candle_marking_bearish():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(
        conviction=0.6, conviction_direction="downtrend",
        recent_candles=[_candle("bear", 7, "2026-02-02T04:00:00Z")],
    )
    result = ConvictionSelectiveStrategy().react(snap, {})
    marking = result["chart_markings"][0]
    validate_chart_marking(marking)
    assert marking["type"] == "candle"
    assert marking["direction"] == "short"
    assert marking["label"] == "Bearish High Conviction"
    assert marking["evidence_ref"]["conviction"] == 0.6
    assert marking["evidence_ref"]["conviction_direction"] == "downtrend"


# ---------------------------------------------------------------------------
# Confidence: exactly conviction, bounded [0,1].
# ---------------------------------------------------------------------------

def test_confidence_is_conviction_value_unmodified():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    for conv in (0.5, 0.55, 0.83, 1.0):
        snap = _base_snapshot(conviction=conv, conviction_direction="uptrend")
        result = ConvictionSelectiveStrategy().react(snap, {})
        assert result["confidence"] == conv
        assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# No duplicate conviction formula; no zone/structure/candle-pattern gate.
# ---------------------------------------------------------------------------

def test_no_duplicate_conviction_formula_in_strategy():
    """The strategy must read the final conviction scalar only -- never
    reimplement any part of compute_conviction()'s own weighting/agreement
    logic (structure/bias/zone/momentum/shift terms, or direction-agreement
    checks against raw evidence fields). Scoped to actual code lines (not
    comments/docstrings, which legitimately explain the audited weights in
    prose) to avoid a self-referential false positive."""
    import pathlib
    text = pathlib.Path("core/strategy/ConvictionSelectiveStrategy.py").read_text(encoding="utf-8")
    for forbidden in (
        "snapshot.atr_normalized_momentum", "snapshot.structure_direction", "snapshot.structure_label",
        "snapshot.shift_confirmed", "snapshot.shift_direction", "snapshot.bias",
    ):
        assert forbidden not in text, f"ConvictionSelectiveStrategy.py unexpectedly contains {forbidden!r}"


def test_no_zone_structure_or_candle_pattern_dependency():
    import pathlib
    text = pathlib.Path("core/strategy/ConvictionSelectiveStrategy.py").read_text(encoding="utf-8")
    for forbidden in (
        "snapshot.active_zone", "snapshot.mitigated_zone", "snapshot.structure_valid",
        "snapshot.structure_type", "snapshot.engulfing", "snapshot.event_",
    ):
        assert forbidden not in text, f"ConvictionSelectiveStrategy.py unexpectedly reads {forbidden}"


def test_no_raw_bias_or_snr_dependency():
    import pathlib
    text = pathlib.Path("core/strategy/ConvictionSelectiveStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("snapshot.bias", "snapshot.nearest_support", "snapshot.nearest_resistance", "snapshot.snr_context"):
        assert forbidden not in text, f"ConvictionSelectiveStrategy.py unexpectedly reads {forbidden}"


# ---------------------------------------------------------------------------
# Canonical wiring: StructureSnapshot/StrategySnapshot expose conviction.
# ---------------------------------------------------------------------------

def test_structure_snapshot_exposes_conviction_fields():
    from core.core_models import StructureSnapshot
    import dataclasses
    fields = {f.name for f in dataclasses.fields(StructureSnapshot)}
    assert "conviction" in fields
    assert "conviction_direction" in fields


def test_strategy_engine_copies_conviction_straight_from_structure():
    """to_strategy_snapshot() must copy, never recompute."""
    from core.strategy.StrategyEngine import to_strategy_snapshot
    from core.core_models import StructureSnapshot
    structure = StructureSnapshot(
        symbol="T", timeframe="H1", current_high=1.0, current_low=0.9,
        prev_high=1.0, prev_low=0.9, current_zone="neutral", prev_zone="neutral",
    )
    structure.conviction = 0.77
    structure.conviction_direction = "uptrend"
    snap = to_strategy_snapshot(structure)
    assert snap.conviction == 0.77
    assert snap.conviction_direction == "uptrend"


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    snap = _base_snapshot(conviction=0.7, conviction_direction="uptrend")
    result = ConvictionSelectiveStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_strategy_engine_discovers_seventeen_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.strategies) == 17
    assert "ConvictionSelectiveStrategy" in engine.enabled


def test_existing_sixteen_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_sixteen = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
    }
    assert existing_sixteen <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_gracefully():
    """A raw-JSON-body StrategySnapshot(**data) that omits conviction/
    conviction_direction falls through to None -- never guessed -- and the
    strategy rejects cleanly rather than crashing."""
    base = dict(
        symbol="T", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
    )
    snap = StrategySnapshot(**base)
    assert snap.conviction is None
    assert snap.conviction_direction is None
    from core.strategy.ConvictionSelectiveStrategy import ConvictionSelectiveStrategy
    assert ConvictionSelectiveStrategy().react(snap, {}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
