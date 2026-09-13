"""Fix #6G — targeted tests proving zone interaction (legacy
shift_confirmed/shift_direction, canonical zone_interaction/
zone_interaction_direction) no longer votes in
core.Output.alignment_signal.compute_alignment_signal()'s score, while
bias direction and momentum still do, exactly as before (Fix #6F's audit
found a mere zone touch voting equally with both, able to single-handedly
cross the Go Long/Go Short threshold on higher-weighted swing timeframes).

Note (Fix #6AF): the momentum vote itself was later migrated from legacy
raw `momentum` (+/-0.3 threshold) to canonical `atr_normalized_momentum`
(+/-1.0 threshold) -- see test_alignment_momentum_atr_migration.py for
that migration's own tests. The fixtures below were updated at that time
to set atr_normalized_momentum (not just the now-inert legacy `momentum`)
wherever a momentum vote needs to fire, so this file's original intent
(zone interaction never votes; weights/thresholds unchanged) still holds
under the current alignment formula.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_alignment_signal_zone_interaction_removed.py -v
"""
from core.Output.alignment_signal import compute_alignment_signal


def snap(direction="neutral", momentum=0.0, atr_normalized_momentum=0.0, shift_confirmed=False, shift_direction="Neutral"):
    """Plain dict snapshot — compute_alignment_signal() supports dict
    access. shift_confirmed/shift_direction are included on every fixture
    (even when irrelevant) specifically to prove they no longer affect
    the score. `momentum` (legacy) is kept alongside atr_normalized_momentum
    (canonical, Fix #6AF) specifically to prove the legacy field is inert."""
    return {
        "direction": direction, "momentum": momentum,
        "atr_normalized_momentum": atr_normalized_momentum,
        "shift_confirmed": shift_confirmed, "shift_direction": shift_direction,
    }


# ---------------------------------------------------------------------------
# bias neutral + momentum neutral + bullish zone interaction -> Stand Aside
# ---------------------------------------------------------------------------

def test_neutral_bias_and_momentum_with_zone_interaction_stands_aside():
    tf_snapshots = {
        "M1": snap(),
        "M5": snap(),
        "M15": snap(shift_confirmed=True, shift_direction="Bullish"),
        "M30": snap(),
    }
    result = compute_alignment_signal(tf_snapshots, mode="scalping")
    assert result["decision"] == "Stand Aside"
    assert result["total_score"] == 0
    assert result["breakdown"]["M15"] == 0


# ---------------------------------------------------------------------------
# bias bullish + momentum bearish + bullish zone interaction -> still nets
# to a neutral (0) contribution for that TF, same as if zone interaction
# didn't exist at all.
# ---------------------------------------------------------------------------

def test_bullish_bias_bearish_momentum_with_zone_interaction_nets_zero():
    tf_snapshots = {
        "M1": snap(direction="uptrend", momentum=-0.5, atr_normalized_momentum=-1.5, shift_confirmed=True, shift_direction="Bullish"),
        "M5": snap(),
        "M15": snap(),
        "M30": snap(),
    }
    result = compute_alignment_signal(tf_snapshots, mode="scalping")
    assert result["breakdown"]["M1"] == 0
    assert result["decision"] == "Stand Aside"


# ---------------------------------------------------------------------------
# bias bullish + momentum bullish -> still bullish even with zero zone
# interaction anywhere.
# ---------------------------------------------------------------------------

def test_bullish_bias_and_momentum_still_go_long_without_zone_interaction():
    tf_snapshots = {
        "M1": snap(direction="uptrend", momentum=0.5, atr_normalized_momentum=1.5),
        "M5": snap(direction="uptrend", momentum=0.5, atr_normalized_momentum=1.5),
        "M15": snap(direction="uptrend", momentum=0.0),
        "M30": snap(direction="neutral", momentum=0.0),
    }
    result = compute_alignment_signal(tf_snapshots, mode="scalping")
    # M1: +1+1=2, M5: +1+1=2, M15: +1+0=1, M30: 0 -> total = 5 >= 3
    assert result["total_score"] == 5
    assert result["decision"] == "Go Long"


# ---------------------------------------------------------------------------
# MN1 zone interaction alone can no longer trigger Go Long (Fix #6F's
# single-TF-flips-the-decision finding).
# ---------------------------------------------------------------------------

def test_mn1_zone_interaction_alone_cannot_trigger_go_long():
    tf_snapshots = {
        "H1": snap(),
        "H4": snap(),
        "D1": snap(),
        "W1": snap(),
        "MN1": snap(shift_confirmed=True, shift_direction="Bullish"),
    }
    result = compute_alignment_signal(tf_snapshots, mode="swing")
    assert result["total_score"] == 0
    assert result["breakdown"]["MN1"] == 0
    assert result["decision"] == "Stand Aside"


# ---------------------------------------------------------------------------
# confidence_pct can no longer exceed 100% (the demonstrated Fix #6F bug:
# 3 contributors against a max_possible sized for 2).
# ---------------------------------------------------------------------------

def test_confidence_pct_cannot_exceed_100_even_with_zone_interaction_everywhere():
    tf_snapshots = {
        tf: snap(direction="uptrend", momentum=0.5, atr_normalized_momentum=1.5, shift_confirmed=True, shift_direction="Bullish")
        for tf in ("M1", "M5", "M15", "M30")
    }
    result = compute_alignment_signal(tf_snapshots, mode="scalping")
    assert result["confidence_pct"] <= 100.0
    # Every tf: direction(+1) + momentum(+1) = 2 (zone interaction ignored).
    # max_possible = sum(1.0*2 for 4 tfs) = 8; total = 2*1.0*4 = 8 -> exactly 100%.
    assert result["confidence_pct"] == 100.0
    assert result["total_score"] == 8


# ---------------------------------------------------------------------------
# Existing timeframe weights/thresholds unchanged.
# ---------------------------------------------------------------------------

def test_swing_timeframe_weights_unchanged():
    tf_snapshots = {
        "H1": snap(direction="uptrend", momentum=0.5, atr_normalized_momentum=1.5),  # score 2 * 1.0 = 2.0
        "H4": snap(),
        "D1": snap(),
        "W1": snap(),
        "MN1": snap(),
    }
    result = compute_alignment_signal(tf_snapshots, mode="swing")
    assert result["breakdown"]["H1"] == 2.0
    assert result["total_score"] == 2.0
    assert result["decision"] == "Stand Aside"  # below the unchanged +/-3 threshold

    tf_snapshots["H4"] = snap(direction="uptrend", momentum=0.0)  # score 1 * 1.5 = 1.5
    result = compute_alignment_signal(tf_snapshots, mode="swing")
    assert result["breakdown"]["H4"] == 1.5
    assert result["total_score"] == 3.5
    assert result["decision"] == "Go Long"  # unchanged +3 threshold


def test_decision_threshold_exactly_three_unchanged():
    tf_snapshots = {
        "M1": snap(direction="uptrend", momentum=0.5, atr_normalized_momentum=1.5),   # 2.0
        "M5": snap(direction="uptrend", momentum=0.0),   # 1.0
        "M15": snap(),
        "M30": snap(),
    }
    result = compute_alignment_signal(tf_snapshots, mode="scalping")
    assert result["total_score"] == 3.0
    assert result["decision"] == "Go Long"  # exactly at threshold, still triggers


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
