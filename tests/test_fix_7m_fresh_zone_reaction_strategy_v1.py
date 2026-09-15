"""Fix #7M — Fresh Zone Reaction v1 baseline: reacts to the canonical
active zone only when it is genuinely fresh.

This is a v1 BASELINE only -- the eligibility rule and the confidence
formula are both explicitly provisional (final zone quality/touch rules
deferred to a later strategy rule audit). These tests lock in v1's exact
behavior, not a claim that the rules are final.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7m_fresh_zone_reaction_strategy_v1.py -v
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
        active_zone_type=None, active_zone_top=None, active_zone_bottom=None,
        active_zone_freshness=None, active_zone_structural_evidence=None,
        active_zone_timestamp=None, active_zone_index=None,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_FRESH_DEMAND = dict(
    active_zone_type="demand", active_zone_top=1.2100, active_zone_bottom=1.2000,
    active_zone_freshness="fresh", active_zone_structural_evidence="unconfirmed",
    active_zone_timestamp="2026-01-01T00:00:00Z", active_zone_index=42,
)
_FRESH_SUPPLY = dict(
    active_zone_type="supply", active_zone_top=1.3100, active_zone_bottom=1.3000,
    active_zone_freshness="fresh", active_zone_structural_evidence="unconfirmed",
    active_zone_timestamp="2026-01-02T00:00:00Z", active_zone_index=43,
)


# ---------------------------------------------------------------------------
# Eligibility: fresh demand/supply valid.
# ---------------------------------------------------------------------------

def test_fresh_demand_valid_fires_long():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    snap = _base_snapshot(**_FRESH_DEMAND)
    result = FreshZoneReactionStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["trigger"] == "FRESH_ZONE"
    assert result["reason"] == "Fresh Demand Zone"


def test_fresh_supply_valid_fires_short():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    snap = _base_snapshot(**_FRESH_SUPPLY)
    result = FreshZoneReactionStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["trigger"] == "FRESH_ZONE"
    assert result["reason"] == "Fresh Supply Zone"


# ---------------------------------------------------------------------------
# Rejections.
# ---------------------------------------------------------------------------

def test_touched_rejected():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    overrides = dict(_FRESH_DEMAND)
    overrides["active_zone_freshness"] = "touched"
    snap = _base_snapshot(**overrides)
    assert FreshZoneReactionStrategy().react(snap, {}) is None


def test_mitigated_rejected():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    overrides = dict(_FRESH_DEMAND)
    overrides["active_zone_freshness"] = "mitigated"
    snap = _base_snapshot(**overrides)
    assert FreshZoneReactionStrategy().react(snap, {}) is None


def test_invalidated_rejected():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    overrides = dict(_FRESH_DEMAND)
    overrides["active_zone_freshness"] = "invalidated"
    snap = _base_snapshot(**overrides)
    assert FreshZoneReactionStrategy().react(snap, {}) is None


def test_unknown_freshness_rejected():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    overrides = dict(_FRESH_DEMAND)
    overrides["active_zone_freshness"] = None
    snap = _base_snapshot(**overrides)
    assert FreshZoneReactionStrategy().react(snap, {}) is None


def test_wrong_zone_type_rejected():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    overrides = dict(_FRESH_DEMAND)
    overrides["active_zone_type"] = "neutral"
    snap = _base_snapshot(**overrides)
    assert FreshZoneReactionStrategy().react(snap, {}) is None


def test_missing_zone_type_rejected():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    snap = _base_snapshot()  # everything defaults to None
    assert FreshZoneReactionStrategy().react(snap, {}) is None


def test_fresh_zone_missing_geometry_rejected():
    """Defensive: freshness says fresh and type is valid, but top/bottom
    are somehow missing -- must never fabricate geometry to fire anyway."""
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    snap = _base_snapshot(active_zone_type="demand", active_zone_freshness="fresh", active_zone_top=None, active_zone_bottom=None)
    assert FreshZoneReactionStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Chart marking: exactly one, real geometry, no fabrication.
# ---------------------------------------------------------------------------

def test_exactly_one_zone_marking_emitted():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    snap = _base_snapshot(**_FRESH_DEMAND)
    result = FreshZoneReactionStrategy().react(snap, {})
    assert len(result["chart_markings"]) == 1
    assert result["chart_markings"][0]["type"] == "zone"


def test_marking_label_matches_direction():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    r_demand = FreshZoneReactionStrategy().react(_base_snapshot(**_FRESH_DEMAND), {})
    r_supply = FreshZoneReactionStrategy().react(_base_snapshot(**_FRESH_SUPPLY), {})
    assert r_demand["chart_markings"][0]["label"] == "Fresh Demand Zone"
    assert r_supply["chart_markings"][0]["label"] == "Fresh Supply Zone"


def test_marking_geometry_uses_real_zone_evidence():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    snap = _base_snapshot(**_FRESH_DEMAND)
    result = FreshZoneReactionStrategy().react(snap, {})
    m = result["chart_markings"][0]
    assert m["top"] == 1.2100
    assert m["bottom"] == 1.2000
    assert m["timestamp"] == "2026-01-01T00:00:00Z"
    assert m["candle_index"] == 42
    assert m["timeframe"] == "H1"
    assert m["direction"] == "long"
    assert m["evidence_ref"] == {"source": "supply_demand_zones", "timeframe": "H1", "freshness": "fresh"}


def test_marking_self_validates():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    snap = _base_snapshot(**_FRESH_DEMAND)
    result = FreshZoneReactionStrategy().react(snap, {})
    validate_chart_marking(result["chart_markings"][0])


def test_no_fabricated_geometry_when_timestamp_and_index_absent():
    """A genuine active zone always carries top/bottom, but timestamp/index
    may legitimately be absent -- the marking must still be valid from
    top/bottom alone (the "zone" type's own geometry requirement), never
    inventing a timestamp or index to fill the gap."""
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    overrides = dict(_FRESH_DEMAND)
    overrides["active_zone_timestamp"] = None
    overrides["active_zone_index"] = None
    snap = _base_snapshot(**overrides)
    result = FreshZoneReactionStrategy().react(snap, {})
    m = result["chart_markings"][0]
    assert "timestamp" not in m
    assert "candle_index" not in m
    validate_chart_marking(m)


# ---------------------------------------------------------------------------
# Confidence: bounded [0, 1], exact v1 formula.
# ---------------------------------------------------------------------------

def test_confidence_bounded_zero_to_one_base_only():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    snap = _base_snapshot(**_FRESH_DEMAND)  # structural_evidence="unconfirmed", no momentum
    result = FreshZoneReactionStrategy().react(snap, {})
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["confidence"] == 0.5


def test_confidence_structural_confirmation_bonus():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    overrides = dict(_FRESH_DEMAND)
    overrides["active_zone_structural_evidence"] = "confirmed_current_event"
    snap = _base_snapshot(**overrides)
    result = FreshZoneReactionStrategy().react(snap, {})
    assert result["confidence"] == 0.7  # 0.5 base + 0.2 structural bonus, no momentum


def test_confidence_supported_evidence_gets_no_bonus_in_v1():
    """v1 baseline: only "confirmed_current_event" earns the structural
    bonus -- "supported" intentionally gets none yet (deferred)."""
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    overrides = dict(_FRESH_DEMAND)
    overrides["active_zone_structural_evidence"] = "supported"
    snap = _base_snapshot(**overrides)
    result = FreshZoneReactionStrategy().react(snap, {})
    assert result["confidence"] == 0.5


def test_confidence_saturates_at_cap_with_bonus_and_strong_momentum():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    overrides = dict(_FRESH_DEMAND)
    overrides["active_zone_structural_evidence"] = "confirmed_current_event"
    snap = _base_snapshot(atr_normalized_momentum=5.0, **overrides)
    result = FreshZoneReactionStrategy().react(snap, {})
    assert result["confidence"] == 1.0


def test_confidence_floors_at_base_on_disagreeing_momentum():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    snap = _base_snapshot(atr_normalized_momentum=-2.0, **_FRESH_DEMAND)
    result = FreshZoneReactionStrategy().react(snap, {})
    assert result["confidence"] == 0.5


def test_exact_confidence_formula_value_with_momentum():
    """Locks the exact v1 formula: 0.5 base + 0.3 * strategy_momentum_confidence
    -- 1.0 ATR agreeing momentum -> momentum term 0.5 -> +0.15 -> 0.65."""
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    snap = _base_snapshot(atr_normalized_momentum=1.0, **_FRESH_DEMAND)
    result = FreshZoneReactionStrategy().react(snap, {})
    assert result["confidence"] == 0.65


# ---------------------------------------------------------------------------
# No candle/bias dependency.
# ---------------------------------------------------------------------------

def test_eligibility_ignores_bias_and_candle_evidence():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    overrides = dict(_FRESH_DEMAND)
    snap = _base_snapshot(
        bias="Bearish",
        recent_candles=[
            {"direction": "bear", "index": 1, "timestamp": "t1"},
            {"direction": "bear", "index": 2, "timestamp": "t2"},
            {"direction": "bear", "index": 3, "timestamp": "t3"},
        ],
        **overrides,
    )
    result = FreshZoneReactionStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"


def test_source_file_does_not_read_bias_or_candle_fields():
    """Static check reinforcing the eligibility-ignores test above."""
    import pathlib
    text = pathlib.Path("core/strategy/FreshZoneReactionStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("snapshot.bias", "snapshot.recent_candles", "snapshot.structure_type",
                      "snapshot.structure_direction", "snapshot.structure_valid"):
        assert forbidden not in text, f"FreshZoneReactionStrategy.py unexpectedly reads {forbidden}"


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    snap = _base_snapshot(**_FRESH_DEMAND)
    result = FreshZoneReactionStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_strategy_engine_discovers_fresh_zone_reaction_strategy():
    """Originally asserted the discovered count equals exactly 11 -- Fix
    #7N later added a genuinely new 12th strategy
    (MitigationSecondTouchStrategy), which made that exact-count snapshot
    stale (a real, intended addition, not a regression -- see
    tests/test_fix_7n_mitigation_second_touch_strategy_v1.py::test_strategy_engine_discovers_twelve_strategies_now
    for that fix's own count assertion). Rewritten to check the actual
    invariant this test exists for -- FreshZoneReactionStrategy is
    discovered alongside the original 10 -- rather than a total count
    that any future new strategy would otherwise make stale again."""
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert "FreshZoneReactionStrategy" in engine.enabled
    existing_ten = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
    }
    assert existing_ten <= set(engine.enabled.keys())


def test_existing_ten_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_ten = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
    }
    assert existing_ten <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_to_none():
    """A raw-JSON-body StrategySnapshot(**data) that omits active_zone_*
    (e.g. an older /core/evaluate caller) falls through to None, same
    convention as every other Fix #7-era additive field -- never guessed."""
    base = dict(
        symbol="T", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
    )
    snap = StrategySnapshot(**base)
    assert snap.active_zone_type is None
    assert snap.active_zone_freshness is None
    from core.strategy.FreshZoneReactionStrategy import FreshZoneReactionStrategy
    assert FreshZoneReactionStrategy().react(snap, {}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
