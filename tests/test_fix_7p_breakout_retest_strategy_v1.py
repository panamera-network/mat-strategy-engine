"""Fix #7P — Breakout + Retest v1 baseline: a valid BOS breakout whose
broken level was later genuinely retested (touched again and held).

This is a v1 BASELINE only -- final tolerance, hold-quality,
rejection-candle, and retest-depth rules are explicitly deferred to a
later rule audit. These tests lock in v1's exact behavior, not a claim
that the rules are final.

Evidence audit (Fix #7P, documented in detect_breakout_retest()'s own
docstring): detect_structure_event() evaluates ONLY the most recent
candle, so event_index/event_timestamp always point at "now" whenever
structure_valid is True -- they cannot prove a break happened several
candles ago and is only now being retested. Fix #7P adds
detect_breakout_retest() (structure_utils.py) to close that gap by
scanning the SAME already-fetched window for the break's true origin
candle and any later retest, without re-deriving BOS-vs-CHoCH
classification (structure_event's own decision is reused, never
recomputed). v1 scope is BOS only -- CHoCH's retest semantics (a
trend-flip level, not a continuation level) are a materially different
question, not audited here.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7p_breakout_retest_strategy_v1.py -v
"""
from datetime import datetime, timezone

import pytest

from core.core_models import CandleSnapshot
from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot
from core.structure_utils import detect_breakout_retest


def _candle(o, h, l, c, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=c, volume=1.0, timestamp=str(ts))


def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        event_broken_level=None, breakout_origin_index=None, breakout_origin_timestamp=None,
        retest_index=None, retest_timestamp=None, retest_confirmed=False,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_BULLISH_VALID = dict(
    structure_type="BOS", structure_direction="Bullish", structure_valid=True,
    event_broken_level=1.2000, breakout_origin_index=5, breakout_origin_timestamp="2026-01-01T00:00:00Z",
    retest_index=10, retest_timestamp="2026-01-01T05:00:00Z", retest_confirmed=True,
)
_BEARISH_VALID = dict(
    structure_type="BOS", structure_direction="Bearish", structure_valid=True,
    event_broken_level=1.3000, breakout_origin_index=6, breakout_origin_timestamp="2026-01-02T00:00:00Z",
    retest_index=12, retest_timestamp="2026-01-02T06:00:00Z", retest_confirmed=True,
)


# ---------------------------------------------------------------------------
# detect_breakout_retest() — unit-level audit checks on the utility itself.
# ---------------------------------------------------------------------------

def test_util_bullish_breakout_then_later_retest_holds():
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(99.0, 99.2, 98.8, 99.0, "pre1"),
        _candle(100.5, 100.8, 100.2, 100.6, "origin"),
        _candle(101.0, 101.3, 100.9, 101.1, "away0"),
        _candle(100.2, 100.4, 99.9, 100.3, "retest"),
        _candle(101.5, 101.7, 101.2, 101.6, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["breakout_origin_index"] == 2
    assert result["retest_index"] == 4
    assert result["retest_confirmed"] is True


def test_util_bearish_breakout_then_later_retest_holds():
    candles = [
        _candle(101.0, 101.2, 100.8, 101.0, "pre0"),
        _candle(99.5, 99.8, 99.2, 99.4, "origin"),
        _candle(99.0, 99.2, 98.7, 98.9, "away0"),
        _candle(99.9, 100.1, 99.6, 99.7, "retest"),
        _candle(98.5, 98.7, 98.2, 98.4, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bearish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["breakout_origin_index"] == 1
    assert result["retest_index"] == 3
    assert result["retest_confirmed"] is True


def test_util_breakout_without_retest():
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(100.5, 100.8, 100.2, 100.6, "origin"),
        _candle(101.0, 101.3, 100.9, 101.1, "away0"),
        _candle(101.5, 101.7, 101.2, 101.6, "away1"),
        _candle(102.0, 102.3, 101.9, 102.1, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["retest_confirmed"] is False


def test_util_origin_is_current_candle_no_time_for_retest():
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(99.0, 99.2, 98.8, 99.0, "pre1"),
        _candle(100.5, 100.8, 100.2, 100.6, "now_is_origin"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["retest_confirmed"] is False
    assert result["breakout_origin_index"] is None


def test_util_wrong_side_retest_rejected():
    """Touches the level but CLOSES through to the wrong side -- not a
    genuine hold, must not count as a valid retest."""
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(100.5, 100.8, 100.2, 100.6, "origin"),
        _candle(101.0, 101.3, 100.9, 101.1, "away0"),
        _candle(100.2, 100.4, 99.8, 99.9, "wrongside"),
        _candle(101.5, 101.7, 101.2, 101.6, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["retest_confirmed"] is False


def test_util_choch_event_yields_no_evidence():
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(100.5, 100.8, 100.2, 100.6, "origin"),
        _candle(101.0, 101.3, 100.9, 101.1, "away0"),
        _candle(100.2, 100.4, 99.9, 100.3, "retest"),
        _candle(101.5, 101.7, 101.2, 101.6, "now"),
    ]
    event = {"valid": True, "type": "CHOCH", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["retest_confirmed"] is False
    assert result["breakout_origin_index"] is None


def test_util_invalid_structure_yields_no_evidence():
    candles = [_candle(99.0, 99.2, 98.8, 99.0, "pre0")]
    event = {"valid": False, "type": "None", "direction": "Neutral", "broken_level": None}
    result = detect_breakout_retest(candles, event)
    assert result["retest_confirmed"] is False


def test_util_retest_index_always_strictly_after_origin_by_construction():
    """Structural guarantee: the scan range excludes the origin candle
    itself and the current candle, so retest_index (when found) can never
    equal or precede breakout_origin_index."""
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(100.5, 100.8, 100.2, 100.6, "origin"),
        _candle(100.2, 100.4, 99.9, 100.3, "retest_immediately_after"),
        _candle(101.5, 101.7, 101.2, 101.6, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["retest_confirmed"] is True
    assert result["retest_index"] > result["breakout_origin_index"]
    assert result["retest_index"] < len(candles) - 1  # strictly before "now"


def test_util_origin_identity_skips_stale_old_breakout_of_same_level():
    """Fix #7P origin-identity audit: an OLD breakout of the same
    numerical level, followed by price reversing back through it, followed
    by a genuinely NEW breakout of that same level, must identify the NEW
    breakout as the origin -- never the stale, already-invalidated old
    one, even though the old one is numerically the first close-cross in
    the window."""
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(100.5, 100.8, 100.2, 100.6, "stale_old_breakout"),
        _candle(100.8, 101.0, 100.5, 100.9, "still_above_1"),
        _candle(99.0, 99.3, 98.5, 98.8, "reversed_below_level"),  # closes BELOW -- old leg is dead
        _candle(98.5, 98.7, 98.2, 98.4, "still_below"),
        _candle(100.4, 100.7, 100.1, 100.5, "true_origin"),  # fresh close-cross of the SAME level
        _candle(101.0, 101.2, 100.8, 101.1, "away0"),
        _candle(100.2, 100.4, 99.9, 100.3, "true_retest"),
        _candle(101.5, 101.7, 101.2, 101.6, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["breakout_origin_index"] == 5  # true_origin, not 1 (stale_old_breakout)
    assert result["breakout_origin_timestamp"] == "true_origin"
    assert result["retest_index"] == 7  # true_retest
    assert result["retest_confirmed"] is True


def test_util_origin_identity_skips_failed_breakout_before_later_real_one():
    """Same class of bug as above, phrased as a 'failed back through the
    level' breakout rather than a plain reversal -- must still resolve to
    the later, genuine breakout as the origin."""
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(100.3, 100.5, 100.0, 100.4, "failed_breakout"),
        _candle(99.2, 99.5, 98.9, 99.1, "failed_back_through"),  # closes BELOW -- failed
        _candle(99.0, 99.2, 98.7, 98.9, "still_below"),
        _candle(100.6, 100.9, 100.3, 100.7, "true_origin"),
        _candle(101.2, 101.4, 100.9, 101.3, "away0"),
        _candle(100.1, 100.3, 99.85, 100.2, "true_retest"),
        _candle(101.5, 101.7, 101.2, 101.6, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["breakout_origin_index"] == 4  # true_origin, not 1 (failed_breakout)
    assert result["breakout_origin_timestamp"] == "true_origin"
    assert result["retest_index"] == 6  # true_retest
    assert result["retest_confirmed"] is True


def test_util_origin_identity_bearish_mirrors_bullish():
    candles = [
        _candle(101.0, 101.2, 100.8, 101.0, "pre0"),
        _candle(99.5, 99.8, 99.2, 99.4, "stale_old_breakout"),
        _candle(101.0, 101.3, 100.8, 101.2, "reversed_above_level"),  # closes ABOVE -- old leg is dead
        _candle(101.2, 101.4, 100.9, 101.3, "still_above"),
        _candle(99.6, 99.9, 99.3, 99.5, "true_origin"),
        _candle(99.0, 99.2, 98.7, 98.9, "away0"),
        _candle(99.9, 100.1, 99.6, 99.7, "true_retest"),
        _candle(98.5, 98.7, 98.2, 98.4, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bearish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["breakout_origin_index"] == 4  # true_origin, not 1 (stale_old_breakout)
    assert result["retest_index"] == 6  # true_retest
    assert result["retest_confirmed"] is True


def test_util_multiple_closes_beyond_still_finds_the_single_true_origin():
    """Timeline #3 from Fix #7P's origin-identity audit: a clean breakout
    followed by several MORE candles that also close beyond the level
    (no reversal in between) must still resolve to the original breakout
    candle as the origin, not any of the later ones."""
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(100.5, 100.8, 100.2, 100.6, "true_origin"),
        _candle(101.0, 101.3, 100.9, 101.1, "beyond1"),
        _candle(101.5, 101.8, 101.2, 101.6, "beyond2"),
        _candle(102.0, 102.3, 101.7, 102.1, "beyond3"),
        _candle(100.2, 100.4, 99.9, 100.3, "true_retest"),
        _candle(101.5, 101.7, 101.2, 101.6, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["breakout_origin_index"] == 1
    assert result["retest_index"] == 5
    assert result["retest_confirmed"] is True


def test_util_historical_wick_touch_without_close_cross_is_not_an_origin():
    """Timeline #5 from Fix #7P's origin-identity audit: a candle whose
    WICK pokes past the level but whose CLOSE stays on the wrong side must
    never be treated as an origin -- only a genuine close-cross counts."""
    candles = [
        _candle(99.0, 100.3, 98.8, 99.0, "wick_touch_only"),  # high=100.3 pokes above, close=99.0 stays below
        _candle(99.0, 99.2, 98.8, 99.0, "pre1"),
        _candle(100.5, 100.8, 100.2, 100.6, "true_origin"),
        _candle(101.0, 101.3, 100.9, 101.1, "away0"),
        _candle(100.2, 100.4, 99.9, 100.3, "true_retest"),
        _candle(101.5, 101.7, 101.2, 101.6, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["breakout_origin_index"] == 2  # true_origin, not 0 (wick_touch_only)
    assert result["retest_confirmed"] is True


def test_util_retest_tolerance_is_purely_geometric_no_snr_semantics():
    """Confirms the tolerance formula borrowed from _snr_status() (Fix
    #7P's own audit requirement) imports only a numeric touch tolerance
    (candle range + price magnitude) -- never an SNRLevel object, a
    "tested"/"untested" status string, a touch COUNT, or any other S&R-
    specific classification concept. The retest evidence dict must
    contain none of those SNR-specific keys."""
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(100.5, 100.8, 100.2, 100.6, "origin"),
        _candle(101.0, 101.3, 100.9, 101.1, "away0"),
        _candle(100.2, 100.4, 99.9, 100.3, "retest"),
        _candle(101.5, 101.7, 101.2, 101.6, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert set(result.keys()) == {
        "breakout_origin_index", "breakout_origin_timestamp",
        "retest_index", "retest_timestamp", "retest_confirmed",
    }
    assert "status" not in result
    assert "touches" not in result
    assert "label" not in result


def test_util_retest_tolerance_scales_with_price_magnitude_not_a_fixed_pip_value():
    """The SAME formula (max(candle_range * 0.25, abs(level) * 0.0003))
    must behave identically regardless of instrument price scale -- a
    geometric/proportional tolerance, not a hardcoded price-unit
    threshold. Verified at two very different price magnitudes."""
    def build(level, digits_scale):
        return [
            _candle(level * 0.99, level * 0.992, level * 0.988, level * 0.99, "pre0"),
            _candle(level * 1.005, level * 1.008, level * 1.002, level * 1.006, "origin"),
            _candle(level * 1.01, level * 1.013, level * 1.009, level * 1.011, "away0"),
            _candle(level * 1.002, level * 1.004, level * 0.9992, level * 1.003, "retest"),
            _candle(level * 1.015, level * 1.017, level * 1.012, level * 1.016, "now"),
        ]

    event_low = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 1.2000}
    result_low = detect_breakout_retest(build(1.2000, 4), event_low)

    event_high = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 120000.0}
    result_high = detect_breakout_retest(build(120000.0, 4), event_high)

    assert result_low["retest_confirmed"] is True
    assert result_high["retest_confirmed"] is True


# ---------------------------------------------------------------------------
# Strategy eligibility: bullish/bearish valid.
# ---------------------------------------------------------------------------

def test_bullish_breakout_and_later_retest_valid():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    result = BreakoutRetestStrategy().react(_base_snapshot(**_BULLISH_VALID), {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Bullish Breakout + Retest"
    assert result["trigger"] == "BOS_RETEST"


def test_bearish_breakout_and_later_retest_valid():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    result = BreakoutRetestStrategy().react(_base_snapshot(**_BEARISH_VALID), {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Bearish Breakout + Retest"


# ---------------------------------------------------------------------------
# Rejections.
# ---------------------------------------------------------------------------

def test_breakout_without_retest_rejected():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    overrides = dict(_BULLISH_VALID)
    overrides["retest_confirmed"] = False
    overrides["retest_index"] = None
    overrides["retest_timestamp"] = None
    assert BreakoutRetestStrategy().react(_base_snapshot(**overrides), {}) is None


def test_retest_before_breakout_rejected():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    overrides = dict(_BULLISH_VALID)
    overrides["breakout_origin_index"] = 10
    overrides["retest_index"] = 5
    assert BreakoutRetestStrategy().react(_base_snapshot(**overrides), {}) is None


def test_retest_on_same_breakout_candle_rejected():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    overrides = dict(_BULLISH_VALID)
    overrides["breakout_origin_index"] = 5
    overrides["retest_index"] = 5
    assert BreakoutRetestStrategy().react(_base_snapshot(**overrides), {}) is None


def test_wrong_side_retest_rejected_end_to_end():
    """End-to-end: a wrong-side touch never sets retest_confirmed=True in
    the first place (proven by test_util_wrong_side_retest_rejected
    above), so the strategy naturally rejects it via its
    retest_confirmed gate."""
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(100.5, 100.8, 100.2, 100.6, "origin"),
        _candle(101.0, 101.3, 100.9, 101.1, "away0"),
        _candle(100.2, 100.4, 99.8, 99.9, "wrongside"),
        _candle(101.5, 101.7, 101.2, 101.6, "now"),
    ]
    event = {"valid": True, "type": "BOS", "direction": "Bullish", "broken_level": 100.0}
    evidence = detect_breakout_retest(candles, event)
    snap = _base_snapshot(
        structure_type="BOS", structure_direction="Bullish", structure_valid=True,
        event_broken_level=100.0, **evidence,
    )
    assert BreakoutRetestStrategy().react(snap, {}) is None


def test_invalid_structure_rejected():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    overrides = dict(_BULLISH_VALID)
    overrides["structure_valid"] = False
    assert BreakoutRetestStrategy().react(_base_snapshot(**overrides), {}) is None


def test_no_confirmed_event_rejected():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    assert BreakoutRetestStrategy().react(_base_snapshot(), {}) is None


# ---------------------------------------------------------------------------
# CHoCH behavior explicitly tested (v1 BOS-only scope).
# ---------------------------------------------------------------------------

def test_choch_rejected_even_with_retest_evidence_present():
    """Defense in depth: even if a hand-built/future-caller snapshot sets
    retest_confirmed=True alongside structure_type=CHOCH (which
    detect_breakout_retest() itself would never produce), the strategy's
    own eligibility check independently requires structure_type=='BOS'."""
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    overrides = dict(_BULLISH_VALID)
    overrides["structure_type"] = "CHOCH"
    assert BreakoutRetestStrategy().react(_base_snapshot(**overrides), {}) is None


def test_detect_breakout_retest_never_populates_evidence_for_choch():
    candles = [
        _candle(99.0, 99.2, 98.8, 99.0, "pre0"),
        _candle(100.5, 100.8, 100.2, 100.6, "origin"),
        _candle(101.0, 101.3, 100.9, 101.1, "away0"),
        _candle(100.2, 100.4, 99.9, 100.3, "retest"),
        _candle(101.5, 101.7, 101.2, 101.6, "now"),
    ]
    event = {"valid": True, "type": "CHOCH", "direction": "Bullish", "broken_level": 100.0}
    result = detect_breakout_retest(candles, event)
    assert result["retest_confirmed"] is False


# ---------------------------------------------------------------------------
# Exact real breakout + retest markings, no fabricated geometry.
# ---------------------------------------------------------------------------

def test_exactly_two_markings_emitted():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    result = BreakoutRetestStrategy().react(_base_snapshot(**_BULLISH_VALID), {})
    assert len(result["chart_markings"]) == 2


def test_breakout_marking_is_structure_type_with_real_geometry():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    result = BreakoutRetestStrategy().react(_base_snapshot(**_BULLISH_VALID), {})
    m = result["chart_markings"][0]
    assert m["type"] == "structure"
    assert m["price"] == 1.2000
    assert m["timestamp"] == "2026-01-01T00:00:00Z"
    assert m["candle_index"] == 5
    assert m["direction"] == "long"


def test_retest_marking_is_candle_type_with_real_geometry():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    result = BreakoutRetestStrategy().react(_base_snapshot(**_BULLISH_VALID), {})
    m = result["chart_markings"][1]
    assert m["type"] == "candle"
    assert m["timestamp"] == "2026-01-01T05:00:00Z"
    assert m["candle_index"] == 10
    assert m["direction"] == "long"


def test_both_markings_self_validate():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    result = BreakoutRetestStrategy().react(_base_snapshot(**_BULLISH_VALID), {})
    for m in result["chart_markings"]:
        validate_chart_marking(m)


def test_no_marking_when_geometry_missing():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    overrides = dict(_BULLISH_VALID)
    overrides["event_broken_level"] = None
    assert BreakoutRetestStrategy().react(_base_snapshot(**overrides), {}) is None


# ---------------------------------------------------------------------------
# No zone/bias dependency.
# ---------------------------------------------------------------------------

def test_eligibility_ignores_zone_and_bias():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    overrides = dict(_BULLISH_VALID)
    snap = _base_snapshot(bias="Bearish", context_zone="supply", **overrides)
    result = BreakoutRetestStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"


def test_source_file_does_not_read_zone_or_bias_fields():
    import pathlib
    text = pathlib.Path("core/strategy/BreakoutRetestStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("snapshot.context_zone", "snapshot.context_level", "snapshot.bias",
                      "snapshot.active_zone_type", "snapshot.mitigated_zone_type"):
        assert forbidden not in text, f"BreakoutRetestStrategy.py unexpectedly reads {forbidden}"


def test_source_file_does_not_gate_on_raw_momentum():
    import pathlib
    text = pathlib.Path("core/strategy/BreakoutRetestStrategy.py").read_text(encoding="utf-8")
    assert "snapshot.momentum" not in text


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    result = BreakoutRetestStrategy().react(_base_snapshot(**_BULLISH_VALID), {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_confidence_bounded_and_exact_formula():
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    result = BreakoutRetestStrategy().react(_base_snapshot(atr_normalized_momentum=None, **_BULLISH_VALID), {})
    assert result["confidence"] == 0.5
    result2 = BreakoutRetestStrategy().react(_base_snapshot(atr_normalized_momentum=1.0, **_BULLISH_VALID), {})
    assert result2["confidence"] == 0.75
    result3 = BreakoutRetestStrategy().react(_base_snapshot(atr_normalized_momentum=5.0, **_BULLISH_VALID), {})
    assert result3["confidence"] == 1.0
    for r in (result, result2, result3):
        assert 0.0 <= r["confidence"] <= 1.0


def test_strategy_engine_discovers_fourteen_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.strategies) == 14
    assert "BreakoutRetestStrategy" in engine.enabled


def test_existing_thirteen_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_thirteen = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
    }
    assert existing_thirteen <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_to_none():
    base = dict(
        symbol="T", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="BOS", structure_direction="Bullish", structure_valid=True,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
    )
    snap = StrategySnapshot(**base)
    assert snap.retest_confirmed is False
    assert snap.breakout_origin_index is None
    from core.strategy.BreakoutRetestStrategy import BreakoutRetestStrategy
    assert BreakoutRetestStrategy().react(snap, {}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
