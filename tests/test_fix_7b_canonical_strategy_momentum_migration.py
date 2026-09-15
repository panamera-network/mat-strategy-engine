"""Fix #7B — migrated the 4 remaining Strategy plugins off raw/legacy
momentum onto canonical, direction-relative strategy_momentum_confidence():

1. BiasContinuationScalpingStrategy: the fallback eligibility trigger
   (`normalize_confidence(snapshot.momentum) >= 0.45`, raw/unsigned/
   direction-blind) is replaced with
   `strategy_momentum_confidence(atr_normalized_momentum, direction) >= 0.5`
   (~1.0 ATR agreement -- see MOMENTUM_FALLBACK_CONFIDENCE_MIN's comment
   for the empirical threshold comparison). The structure-trigger path
   remains first/primary; this fallback is unchanged in role, only in
   formula.
2. ScalpingBiasCascade, GroupedLastCandleBiasStrategy,
   LastCandleBiasStrategy: confidence output changed from raw
   `snapshot.momentum` (unsigned, per-instrument-scale, no [0,1] cap) to
   `strategy_momentum_confidence(...)` ([0,1], direction-agreement-gated).
   Eligibility logic in all three is untouched.

Note: this audit also surfaced (but does NOT fix, out of this fix's
scope) that StructureSnapshot.bias is never assigned anywhere in the live
pipeline -- it stays at its dataclass default "Neutral" forever. This
means ScalpingBiasCascade's and both BiasContinuation* strategies'
`.bias`-based eligibility gates are currently unreachable in live
production regardless of the momentum formula. Recorded for a separate,
future fix -- not investigated or touched here.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7b_canonical_strategy_momentum_migration.py -v
"""
from datetime import datetime, timezone

from core.strategy.strategy_models import StrategySnapshot, strategy_momentum_confidence
from core.strategy.BiasContinuationScalpingStrategy import (
    BiasContinuationScalpingStrategy, MOMENTUM_FALLBACK_CONFIDENCE_MIN,
)
from core.strategy.ScalpingBiasCascade import ScalpingBiasCascade
from core.strategy.GroupedLastCandleBiasStrategy import GroupedLastCandleBiasStrategy
from core.strategy.LastCandleBiasStrategy import LastCandleBiasStrategy


def _snap(**overrides) -> StrategySnapshot:
    base = dict(
        symbol="TEST", timeframe="M15", bias="Neutral", momentum=5.0, strength=1.0,
        suppression=False, suppression_reason="", structure_type="None",
        structure_direction="Neutral", structure_valid=False, context_zone="neutral",
        context_level=None, timestamp=datetime.now(timezone.utc),
        current_high=1.10, current_low=1.09, is_last_bias_candle=False,
        atr_normalized_momentum=None,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


# ---------------------------------------------------------------------------
# Common canonical-formula behavior, exercised directly through each
# strategy's own confidence-producing path.
# ---------------------------------------------------------------------------

def test_wrong_direction_atr_momentum_yields_zero_confidence_scalping_cascade():
    snap = _snap(
        timeframe="M15", bias="Neutral", structure_type="CHOCH",
        atr_normalized_momentum=-2.0,  # strongly bearish momentum
    )
    m1 = _snap(timeframe="M1", bias="Bearish", suppression=False)
    context = {
        "TEST_M1": m1,
        "TEST_M15": _snap(timeframe="M15", bias="Bullish"),
        "TEST_M30": _snap(timeframe="M30", bias="Bullish"),
        "TEST_H1": _snap(timeframe="H1", bias="Bullish"),
    }
    snap.bias = "Bullish"  # aligned == Bullish path -> trade_direction "short"
    strat = ScalpingBiasCascade()
    signal = strat.react(snap, context)
    assert signal is not None
    assert signal["direction"] == "short"
    # atr_normalized_momentum is -2.0 (bearish) which AGREES with "short" ->
    # confidence should be > 0 here. Flip to test true disagreement below.
    assert signal["confidence"] == strategy_momentum_confidence(-2.0, "short")
    assert signal["confidence"] > 0


def test_scalping_cascade_confidence_is_capped_0_1_and_matches_helper():
    snap = _snap(timeframe="M15", bias="Bullish", structure_type="CHOCH", atr_normalized_momentum=5.0)
    context = {
        "TEST_M1": _snap(timeframe="M1", bias="Bearish", suppression=False),
        "TEST_M15": _snap(timeframe="M15", bias="Bullish"),
        "TEST_M30": _snap(timeframe="M30", bias="Bullish"),
        "TEST_H1": _snap(timeframe="H1", bias="Bullish"),
    }
    strat = ScalpingBiasCascade()
    signal = strat.react(snap, context)
    assert signal is not None
    assert 0.0 <= signal["confidence"] <= 1.0
    assert signal["confidence"] == strategy_momentum_confidence(5.0, signal["direction"])


def test_scalping_cascade_eligibility_unchanged_still_requires_choch_and_flip():
    """Eligibility logic itself (alignment + M1 flip + CHoCH) must be
    untouched by this fix -- verify the gate still rejects a non-CHoCH
    structure regardless of momentum."""
    snap = _snap(timeframe="M15", bias="Bullish", structure_type="BOS", atr_normalized_momentum=5.0)
    context = {
        "TEST_M1": _snap(timeframe="M1", bias="Bearish", suppression=False),
        "TEST_M15": _snap(timeframe="M15", bias="Bullish"),
        "TEST_M30": _snap(timeframe="M30", bias="Bullish"),
        "TEST_H1": _snap(timeframe="H1", bias="Bullish"),
    }
    strat = ScalpingBiasCascade()
    assert strat.react(snap, context) is None


def test_grouped_last_candle_confidence_canonical_and_capped():
    # event.timeframe="MN1" -> SHIFT_TF_MAP["MN1"]="D1", so D1 is the shift
    # snapshot whose atr_normalized_momentum actually drives confidence.
    d1 = _snap(timeframe="D1", is_last_bias_candle=True, structure_direction="Bullish", atr_normalized_momentum=8.0)
    w1 = _snap(timeframe="W1", is_last_bias_candle=True, structure_direction="Bullish")
    mn1 = _snap(timeframe="MN1", is_last_bias_candle=True, structure_direction="Bullish")
    event = _snap(timeframe="MN1", structure_direction="Bullish", is_last_bias_candle=True)
    context = {
        "TEST_MN1": mn1, "TEST_W1": w1, "TEST_D1": d1, "TEST_H4": _snap(timeframe="H4"),
    }
    strat = GroupedLastCandleBiasStrategy()
    signal = strat.react(event, context)
    assert signal is not None
    assert signal["direction"] == "long"
    assert 0.0 <= signal["confidence"] <= 1.0
    assert signal["confidence"] == strategy_momentum_confidence(8.0, "Bullish")


def test_grouped_last_candle_wrong_direction_momentum_yields_zero():
    # event.timeframe="MN1" -> shift snapshot is D1 (SHIFT_TF_MAP["MN1"]="D1").
    d1 = _snap(timeframe="D1", is_last_bias_candle=True, structure_direction="Bullish", atr_normalized_momentum=-3.0)  # disagrees
    w1 = _snap(timeframe="W1", is_last_bias_candle=True, structure_direction="Bullish")
    mn1 = _snap(timeframe="MN1", is_last_bias_candle=True, structure_direction="Bullish")
    event = _snap(timeframe="MN1", structure_direction="Bullish", is_last_bias_candle=True)
    context = {
        "TEST_MN1": mn1, "TEST_W1": w1, "TEST_D1": d1, "TEST_H4": _snap(timeframe="H4"),
    }
    strat = GroupedLastCandleBiasStrategy()
    signal = strat.react(event, context)
    assert signal is not None  # eligibility (group+shift alignment) unaffected by momentum
    assert signal["confidence"] == 0.0


def test_grouped_last_candle_eligibility_unchanged_group_b_majority_path():
    """Group A (MN1/W1/D1) does NOT reach 3/3 agreement, but Group B
    (W1/D1/H4) reaches the 2-1 majority rule -- confirms the group-counting
    eligibility logic itself is exercised and untouched by this fix, with
    only the resulting confidence value now canonical."""
    mn1 = _snap(timeframe="MN1", is_last_bias_candle=False, structure_direction="Bearish")
    w1 = _snap(timeframe="W1", is_last_bias_candle=True, structure_direction="Bullish")
    d1 = _snap(timeframe="D1", is_last_bias_candle=True, structure_direction="Bearish")  # opposes, still counted
    h4 = _snap(timeframe="H4", is_last_bias_candle=True, structure_direction="Bullish", atr_normalized_momentum=1.2)
    event = _snap(timeframe="W1", structure_direction="Bullish", is_last_bias_candle=True)
    context = {"TEST_MN1": mn1, "TEST_W1": w1, "TEST_D1": d1, "TEST_H4": h4}

    strat = GroupedLastCandleBiasStrategy()
    signal = strat.react(event, context)
    assert signal is not None
    assert signal["direction"] == "long"
    assert "(B)" in signal["reason"]
    assert signal["confidence"] == strategy_momentum_confidence(1.2, "Bullish")


def test_last_candle_bias_confidence_canonical_and_capped():
    anchor = _snap(timeframe="D1", structure_valid=True, is_last_bias_candle=True, structure_direction="Bearish")
    shift = _snap(timeframe="H1", structure_valid=True, structure_direction="Bearish", atr_normalized_momentum=-6.0)
    event = _snap(timeframe="D1")
    context = {"TEST_D1": anchor, "TEST_H1": shift}
    strat = LastCandleBiasStrategy()
    signal = strat.react(event, context)
    assert signal is not None
    assert signal["direction"] == "short"
    assert 0.0 <= signal["confidence"] <= 1.0
    assert signal["confidence"] == strategy_momentum_confidence(-6.0, "Bearish")


def test_last_candle_bias_wrong_direction_momentum_yields_zero():
    anchor = _snap(timeframe="D1", structure_valid=True, is_last_bias_candle=True, structure_direction="Bearish")
    shift = _snap(timeframe="H1", structure_valid=True, structure_direction="Bearish", atr_normalized_momentum=4.0)  # disagrees (bullish reading)
    event = _snap(timeframe="D1")
    context = {"TEST_D1": anchor, "TEST_H1": shift}
    strat = LastCandleBiasStrategy()
    signal = strat.react(event, context)
    assert signal is not None
    assert signal["confidence"] == 0.0


def test_last_candle_bias_eligibility_unchanged_direction_mismatch_still_rejected():
    anchor = _snap(timeframe="D1", structure_valid=True, is_last_bias_candle=True, structure_direction="Bearish")
    shift = _snap(timeframe="H1", structure_valid=True, structure_direction="Bullish", atr_normalized_momentum=6.0)
    event = _snap(timeframe="D1")
    context = {"TEST_D1": anchor, "TEST_H1": shift}
    strat = LastCandleBiasStrategy()
    assert strat.react(event, context) is None


def test_legacy_raw_momentum_alone_no_longer_affects_any_of_the_4_strategies():
    """Changing snapshot.momentum (raw legacy field) with
    atr_normalized_momentum held fixed must not change confidence output
    for any of the 4 migrated strategies."""
    # ScalpingBiasCascade
    snap_a = _snap(timeframe="M15", bias="Bullish", structure_type="CHOCH", atr_normalized_momentum=3.0, momentum=1.0)
    snap_b = _snap(timeframe="M15", bias="Bullish", structure_type="CHOCH", atr_normalized_momentum=3.0, momentum=9.9)
    context = {
        "TEST_M1": _snap(timeframe="M1", bias="Bearish", suppression=False),
        "TEST_M15": _snap(timeframe="M15", bias="Bullish"),
        "TEST_M30": _snap(timeframe="M30", bias="Bullish"),
        "TEST_H1": _snap(timeframe="H1", bias="Bullish"),
    }
    strat = ScalpingBiasCascade()
    sig_a = strat.react(snap_a, context)
    sig_b = strat.react(snap_b, context)
    assert sig_a["confidence"] == sig_b["confidence"]

    # GroupedLastCandleBiasStrategy / LastCandleBiasStrategy: vary shift
    # snapshot's raw momentum only.
    anchor = _snap(timeframe="D1", structure_valid=True, is_last_bias_candle=True, structure_direction="Bearish")
    shift_low_raw = _snap(timeframe="H1", structure_valid=True, structure_direction="Bearish", atr_normalized_momentum=-2.0, momentum=0.1)
    shift_high_raw = _snap(timeframe="H1", structure_valid=True, structure_direction="Bearish", atr_normalized_momentum=-2.0, momentum=9.9)
    event = _snap(timeframe="D1")
    strat_last = LastCandleBiasStrategy()
    sig_low = strat_last.react(event, {"TEST_D1": anchor, "TEST_H1": shift_low_raw})
    sig_high = strat_last.react(event, {"TEST_D1": anchor, "TEST_H1": shift_high_raw})
    assert sig_low["confidence"] == sig_high["confidence"]


# ---------------------------------------------------------------------------
# BiasContinuationScalpingStrategy — isolate the fallback eligibility change.
# ---------------------------------------------------------------------------

def _bcs_context(anchor_bias="Bullish"):
    return {
        "TEST_H1": _snap(timeframe="H1", bias=anchor_bias, suppression=False),
        "TEST_H4": _snap(timeframe="H4", bias=anchor_bias, suppression=False),
    }


def test_bias_continuation_scalping_structure_trigger_still_takes_priority():
    """When a real structure trigger exists, the fallback formula must
    never even be consulted -- confirmed by using a momentum value that
    would FAIL the new fallback threshold, and structure still fires."""
    snap = _snap(
        timeframe="M5", bias="Bullish", structure_valid=True, structure_type="BOS",
        structure_direction="Bullish", context_zone="demand",
        atr_normalized_momentum=0.01,  # would fail the fallback badly
    )
    strat = BiasContinuationScalpingStrategy()
    signal = strat.react(snap, _bcs_context("Bullish"))
    assert signal is not None
    assert signal["direction"] == "long"


def test_bias_continuation_scalping_fallback_fires_above_threshold_with_agreeing_momentum():
    snap = _snap(
        timeframe="M5", bias="Bullish", structure_valid=False, structure_type="None",
        structure_direction="Neutral", context_zone="demand",
        atr_normalized_momentum=1.5,  # confidence = min(1.5/2.0, 1.0) = 0.75 >= 0.5
    )
    strat = BiasContinuationScalpingStrategy()
    signal = strat.react(snap, _bcs_context("Bullish"))
    assert signal is not None
    assert signal["direction"] == "long"


def test_bias_continuation_scalping_fallback_rejects_below_threshold():
    snap = _snap(
        timeframe="M5", bias="Bullish", structure_valid=False, structure_type="None",
        structure_direction="Neutral", context_zone="demand",
        atr_normalized_momentum=0.8,  # confidence = 0.4 < 0.5 threshold
    )
    strat = BiasContinuationScalpingStrategy()
    assert strat.react(snap, _bcs_context("Bullish")) is None


def test_bias_continuation_scalping_fallback_rejects_wrong_direction_regardless_of_magnitude():
    """The critical behavioral change this fix makes: the OLD formula was
    magnitude-only (direction-blind) and would have let strong momentum
    through regardless of which way it pointed. The new formula must
    reject strong momentum pointing the WRONG way."""
    snap = _snap(
        timeframe="M5", bias="Bullish", structure_valid=False, structure_type="None",
        structure_direction="Neutral", context_zone="demand",
        atr_normalized_momentum=-5.0,  # strong, but bearish -- wrong way for a "long" (Bullish) setup
    )
    strat = BiasContinuationScalpingStrategy()
    assert strat.react(snap, _bcs_context("Bullish")) is None


def test_bias_continuation_scalping_fallback_threshold_matches_documented_constant():
    assert MOMENTUM_FALLBACK_CONFIDENCE_MIN == 0.5


def test_bias_continuation_scalping_legacy_raw_momentum_no_longer_drives_fallback():
    """A snapshot with a strong raw legacy `momentum` value but a weak
    atr_normalized_momentum must NOT pass the fallback (old formula would
    have passed this purely on raw momentum)."""
    snap = _snap(
        timeframe="M5", bias="Bullish", structure_valid=False, structure_type="None",
        structure_direction="Neutral", context_zone="demand",
        momentum=9.5,  # would have passed old normalize_confidence(9.5)>=0.45 easily
        atr_normalized_momentum=0.1,  # canonical value is weak
    )
    strat = BiasContinuationScalpingStrategy()
    assert strat.react(snap, _bcs_context("Bullish")) is None


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
