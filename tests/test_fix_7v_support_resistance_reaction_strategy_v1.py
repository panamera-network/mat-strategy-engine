"""Fix #7V — Support/Resistance Reaction v1 baseline: a REACTION strategy
(genuine wick interaction with a canonical S&R level + a held close), not
merely "price near S&R".

Evidence audit (committed canonical S&R contract vs ambient-only WIP):
  - StrategyEngine._snr_context() (Fix #7J) computes nearest_support/
    nearest_resistance as the nearest Support/Resistance level PRICE by
    distance to the current candle's MID-price (StructureSnapshot.
    snr_levels, Fix #2's swing-based engine) -- raw numbers only, no
    interaction/touch/hold evidence.
  - snr_context ("at_support"/"at_resistance"/"between_snr"/
    "above_support"/"below_resistance"/"neutral") already gates on a
    distance-vs-tolerance proximity band (tolerance = max(half the
    current candle's range, a small price-relative floor)) -- closer
    than blind "nearest", but a LIVE audit across the full 36x9 universe
    found 35/118 (30%) of "at_support"/"at_resistance" readings did NOT
    even have a genuine wick touch of the level (the price-relative
    tolerance floor can exceed half the candle's own range on a quiet
    candle) -- proving snr_context ALONE is not sufficient proof of
    interaction. Another 38/118 (32%) touched but closed through (no
    hold). Only 45/118 (38%) were genuine touch-and-hold reactions.
  - snr_strength is a proximity score (1.0 exactly at the level, 0.0 at
    the tolerance boundary) -- not a reaction-quality or level-
    significance score, but semantically reusable as a confidence
    ingredient once eligibility has independently proven a real reaction.
  - The committed SNRLevel dataclass (structure_utils.derive_snr_levels(),
    Fix #2) carries only type/level/source/valid -- there is NO
    historical tested/untested/touch-count field in committed code. The
    status/touches/timestamp/label fields sometimes visible on SNRLevel
    in an ambient-WIP working tree are NOT committed and must never be
    depended on.
  - StrategySnapshot had no current-candle CLOSE price before this fix
    (only current_high/current_low) -- current_close (this fix's own
    minimal additive wiring, straight copy of the same already-fetched
    current candle) closes that one real gap, needed to determine whether
    the candle held on the favorable side of the level.

This is a v1 BASELINE only -- repeated-test quality, strong/weak level
tuning, rejection candle quality, false-break handling, role reversal,
breakout+retest, and S&R clustering/confluence are explicitly deferred to
a later rule audit. These tests lock in v1's exact behavior, not a claim
that the rules are final.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7v_support_resistance_reaction_strategy_v1.py -v
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
        nearest_support=None, nearest_resistance=None, snr_context="neutral", snr_strength=0.0,
        current_high=None, current_low=None, current_close=None,
        recent_candles=[_candle("bull", 42, "2026-01-01T00:00:00Z")],
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_SUPPORT_HOLD = dict(
    nearest_support=1.2000, snr_context="at_support", snr_strength=0.8,
    current_high=1.2050, current_low=1.1980, current_close=1.2030,
)
_RESISTANCE_HOLD = dict(
    nearest_resistance=1.3000, snr_context="at_resistance", snr_strength=0.6,
    current_high=1.3040, current_low=1.2970, current_close=1.2985,
)


# ---------------------------------------------------------------------------
# Eligibility: the two genuine reaction states.
# ---------------------------------------------------------------------------

def test_support_touched_holds_bullish_reaction_valid_long():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(**_SUPPORT_HOLD)
    result = SupportResistanceReactionStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["trigger"] == "SUPPORT_RESISTANCE_REACTION"
    assert result["reason"] == "Support Reaction"


def test_resistance_touched_holds_bearish_reaction_valid_short():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(**_RESISTANCE_HOLD)
    result = SupportResistanceReactionStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["trigger"] == "SUPPORT_RESISTANCE_REACTION"
    assert result["reason"] == "Resistance Reaction"


# ---------------------------------------------------------------------------
# Rejections.
# ---------------------------------------------------------------------------

def test_nearest_support_but_price_far_away_rejected():
    """snr_context reflects "far away" (not at_support) even though a
    nearest_support price exists -- must reject on context alone, never
    fire merely because a nearest level exists."""
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(
        nearest_support=1.1000, snr_context="above_support", snr_strength=0.0,
        current_high=1.2050, current_low=1.1980, current_close=1.2030,
    )
    assert SupportResistanceReactionStrategy().react(snap, {}) is None


def test_nearest_resistance_but_price_far_away_rejected():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(
        nearest_resistance=1.4000, snr_context="below_resistance", snr_strength=0.0,
        current_high=1.2050, current_low=1.1980, current_close=1.2030,
    )
    assert SupportResistanceReactionStrategy().react(snap, {}) is None


def test_support_context_but_wick_never_actually_touches_rejected():
    """The core audit finding, reproduced directly: snr_context=="at_support"
    (proximity-band gate satisfied) does NOT by itself guarantee the wick
    reached the level -- a quiet candle whose mid is within the (price-
    relative-floor-driven) tolerance but whose low never reaches the level
    must still reject."""
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(
        nearest_support=1.2000, snr_context="at_support", snr_strength=0.9,
        current_high=1.2050, current_low=1.2010, current_close=1.2030,  # low (1.2010) never reaches 1.2000
    )
    assert SupportResistanceReactionStrategy().react(snap, {}) is None


def test_support_touched_but_closes_through_rejected():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    overrides = dict(_SUPPORT_HOLD)
    overrides["current_close"] = 1.1990  # closes below the support level
    snap = _base_snapshot(**overrides)
    assert SupportResistanceReactionStrategy().react(snap, {}) is None


def test_resistance_touched_but_closes_through_rejected():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    overrides = dict(_RESISTANCE_HOLD)
    overrides["current_close"] = 1.3010  # closes above the resistance level
    snap = _base_snapshot(**overrides)
    assert SupportResistanceReactionStrategy().react(snap, {}) is None


def test_support_close_exactly_on_level_rejected():
    """Closing exactly ON the level (not strictly above) does not count as
    holding -- an explicit boundary decision, not left ambiguous."""
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    overrides = dict(_SUPPORT_HOLD)
    overrides["current_close"] = overrides["nearest_support"]
    snap = _base_snapshot(**overrides)
    assert SupportResistanceReactionStrategy().react(snap, {}) is None


def test_wrong_direction_reaction_rejected():
    """A support-level touch whose close ends up on the WRONG (bearish)
    side must reject outright -- never silently reinterpreted as a
    resistance/short reaction (role identity is fixed, never swapped)."""
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(
        nearest_support=1.2000, snr_context="at_support", snr_strength=0.5,
        current_high=1.2050, current_low=1.1950, current_close=1.1970,
    )
    assert SupportResistanceReactionStrategy().react(snap, {}) is None


def test_missing_support_level_rejected():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(
        nearest_support=None, snr_context="at_support", snr_strength=0.5,
        current_high=1.2050, current_low=1.1980, current_close=1.2030,
    )
    assert SupportResistanceReactionStrategy().react(snap, {}) is None


def test_missing_resistance_level_rejected():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(
        nearest_resistance=None, snr_context="at_resistance", snr_strength=0.5,
        current_high=1.3040, current_low=1.2970, current_close=1.2985,
    )
    assert SupportResistanceReactionStrategy().react(snap, {}) is None


def test_missing_current_candle_geometry_rejected():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    overrides = dict(_SUPPORT_HOLD)
    overrides["current_close"] = None
    snap = _base_snapshot(**overrides)
    assert SupportResistanceReactionStrategy().react(snap, {}) is None


def test_no_recent_candles_rejected():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(**_SUPPORT_HOLD, recent_candles=[])
    assert SupportResistanceReactionStrategy().react(snap, {}) is None
    snap2 = _base_snapshot(**_SUPPORT_HOLD, recent_candles=None)
    assert SupportResistanceReactionStrategy().react(snap2, {}) is None


# ---------------------------------------------------------------------------
# Identity never swapped.
# ---------------------------------------------------------------------------

def test_support_reaction_never_produces_short():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(**_SUPPORT_HOLD)
    result = SupportResistanceReactionStrategy().react(snap, {})
    assert result["direction"] == "long"
    assert result["direction"] != "short"


def test_resistance_reaction_never_produces_long():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(**_RESISTANCE_HOLD)
    result = SupportResistanceReactionStrategy().react(snap, {})
    assert result["direction"] == "short"
    assert result["direction"] != "long"


# ---------------------------------------------------------------------------
# Chart markings: exactly 2 real markings, no fabricated geometry.
# ---------------------------------------------------------------------------

def test_exactly_two_real_markings_support():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(**_SUPPORT_HOLD)
    result = SupportResistanceReactionStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 2
    level_marking, candle_marking = markings
    validate_chart_marking(level_marking)
    validate_chart_marking(candle_marking)
    assert level_marking["type"] == "level"
    assert level_marking["price"] == 1.2000
    assert level_marking["direction"] == "long"
    assert level_marking["label"] == "Support Reaction"
    assert candle_marking["type"] == "candle"
    assert candle_marking["timestamp"] == "2026-01-01T00:00:00Z"
    assert candle_marking["candle_index"] == 42


def test_exactly_two_real_markings_resistance():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(**_RESISTANCE_HOLD)
    result = SupportResistanceReactionStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 2
    level_marking, candle_marking = markings
    validate_chart_marking(level_marking)
    validate_chart_marking(candle_marking)
    assert level_marking["type"] == "level"
    assert level_marking["price"] == 1.3000
    assert level_marking["direction"] == "short"
    assert level_marking["label"] == "Resistance Reaction"
    assert candle_marking["type"] == "candle"


def test_no_fabricated_geometry():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(**_SUPPORT_HOLD)
    result = SupportResistanceReactionStrategy().react(snap, {})
    level_marking, candle_marking = result["chart_markings"]
    assert level_marking["price"] == snap.nearest_support
    assert candle_marking["timestamp"] == snap.recent_candles[-1]["timestamp"]
    assert candle_marking["candle_index"] == snap.recent_candles[-1]["index"]


# ---------------------------------------------------------------------------
# Confidence: exact formula, bounded.
# ---------------------------------------------------------------------------

def test_confidence_bounded_and_exact_formula():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    overrides_no_momentum = dict(_SUPPORT_HOLD)
    overrides_no_momentum["snr_strength"] = 0.5
    snap = _base_snapshot(atr_normalized_momentum=None, **overrides_no_momentum)
    result = SupportResistanceReactionStrategy().react(snap, {})
    assert result["confidence"] == 0.5

    overrides_with_momentum = dict(_SUPPORT_HOLD)
    overrides_with_momentum["snr_strength"] = 0.5
    snap2 = _base_snapshot(atr_normalized_momentum=2.0, **overrides_with_momentum)
    result2 = SupportResistanceReactionStrategy().react(snap2, {})
    # strategy_momentum_confidence(2.0, "long") = min(2.0/2.0, 1.0) = 1.0
    assert result2["confidence"] == round(min(0.5 + 0.3 * 1.0, 1.0), 2)

    overrides_zero = dict(_SUPPORT_HOLD)
    overrides_zero["snr_strength"] = 0.0
    snap3 = _base_snapshot(atr_normalized_momentum=None, **overrides_zero)
    result3 = SupportResistanceReactionStrategy().react(snap3, {})
    assert result3["confidence"] == 0.0

    for r in (result, result2, result3):
        assert 0.0 <= r["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# No S&D dependency; no ambient-only SNR dependency.
# ---------------------------------------------------------------------------

def test_no_zone_or_supply_demand_dependency():
    import pathlib
    text = pathlib.Path("core/strategy/SupportResistanceReactionStrategy.py").read_text(encoding="utf-8")
    body = text[text.index("def react("):]
    for forbidden in (
        "snapshot.active_zone", "snapshot.mitigated_zone", "snapshot.context_zone", "snapshot.context_level",
    ):
        assert forbidden not in body, f"SupportResistanceReactionStrategy.py unexpectedly reads {forbidden}"


def test_no_ambient_only_snr_field_dependency():
    """Only the committed Fix #7J SNR contract (nearest_support/
    nearest_resistance/snr_context/snr_strength) may be read -- never the
    ambient-only SNRLevel.status/touches/timestamp/label fields, which
    StrategySnapshot never even exposes (they live only on the raw
    StructureSnapshot.snr_levels list, which this strategy never touches
    at all)."""
    import pathlib
    text = pathlib.Path("core/strategy/SupportResistanceReactionStrategy.py").read_text(encoding="utf-8")
    body = text[text.index("def react("):]
    for forbidden in ("snapshot.snr_levels", ".touches", ".status", "nearest_snr", "snr_distance"):
        assert forbidden not in body, f"SupportResistanceReactionStrategy.py unexpectedly references {forbidden}"


def test_no_bias_structure_or_raw_momentum_dependency():
    import pathlib
    text = pathlib.Path("core/strategy/SupportResistanceReactionStrategy.py").read_text(encoding="utf-8")
    body = text[text.index("def react("):]
    for forbidden in ("snapshot.bias", "snapshot.structure_type", "snapshot.structure_direction", "snapshot.structure_valid"):
        assert forbidden not in body, f"SupportResistanceReactionStrategy.py unexpectedly reads {forbidden}"
    assert "snapshot.momentum " not in body and "snapshot.momentum)" not in body and "snapshot.momentum," not in body


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    snap = _base_snapshot(**_SUPPORT_HOLD)
    result = SupportResistanceReactionStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_strategy_engine_discovers_twenty_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.strategies) == 20
    assert "SupportResistanceReactionStrategy" in engine.enabled


def test_existing_nineteen_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_nineteen = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy", "CHOCHBOSConfirmationStrategy", "MomentumPullbackRecoveryStrategy",
    }
    assert existing_nineteen <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_gracefully():
    """A raw-JSON-body StrategySnapshot(**data) that omits current_close
    falls through to None -- never guessed -- and the strategy rejects
    cleanly rather than crashing."""
    base = dict(
        symbol="T", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        nearest_support=1.2000, snr_context="at_support", snr_strength=0.8,
        current_high=1.2050, current_low=1.1980,
    )
    snap = StrategySnapshot(**base)
    assert snap.current_close is None
    from core.strategy.SupportResistanceReactionStrategy import SupportResistanceReactionStrategy
    assert SupportResistanceReactionStrategy().react(snap, {}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
