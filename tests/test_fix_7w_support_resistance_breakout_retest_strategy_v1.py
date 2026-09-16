"""Fix #7W — Support/Resistance Breakout + Retest v1 baseline: a genuine
ROLE-FLIP strategy (Resistance broken bullishly and later held as Support,
or Support broken bearishly and later held as Resistance) -- unlike Fix
#7V's SupportResistanceReactionStrategy, which explicitly defers role
reversal, role reversal IS the point here.

Evidence audit: StrategyEngine._snr_context() (Fix #7J) only ever reports
the CURRENT nearest support/resistance by proximity to "now"
(nearest_support/nearest_resistance/snr_context/snr_strength) -- it has no
memory of whether a level was ever broken, nor of when. A single
StrategySnapshot cannot, by itself, prove "this used to be Resistance,
price broke above it, and later held above it as Support" -- only that
some level is nearby right now. This is the same class of historical-
evidence gap Fix #7P/#7T/#7U each closed with a replay-based helper over
the same already-fetched candle window. Closed here with
structure_utils.detect_snr_role_flip()/detect_snr_breakout_retest() (new):
reuses the SAME already-derived StructureSnapshot.snr_levels list (Fix
#2's canonical S&R engine, never redefined) and the SAME already-fetched
lookback window -- no new fetch, no new S&R detection. Deliberately NOT
built on Fix #7P's detect_breakout_retest()/structure_event (a BOS/CHoCH's
broken_level is a swing-based STRUCTURE level, a different concept from an
S&R level) -- only the geometric ALGORITHM is reused: _find_current_leg_
origin() (already a single shared, structure-agnostic implementation) and
the identical wick-overlap tolerance detect_breakout_retest() already
established (max(candle_range * 0.25, abs(level) * 0.0003)).

snr_strength is NOT used for confidence: it is a CURRENT-moment proximity
score with no historical replay capability, never computed AT the retest
candle's own moment (which is frequently not the current candle at all) --
per this fix's own instruction, since that cannot be proven historically,
it is not used. Confidence is a flat BASE_CONFIDENCE (0.5) for the
confirmed sequence, plus canonical momentum support only (MOMENTUM_WEIGHT
0.5) -- the same "confirmed sequence, momentum supports only" pattern
already established by Fix #7P/#7S/#7T.

This is a v1 BASELINE only -- false-break filters, max bars between
breakout/retest, multiple retests, retest depth, volume confirmation, and
higher-timeframe S&R confluence are explicitly deferred to a later rule
audit. These tests lock in v1's exact behavior, not a claim the rules are
final.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7w_support_resistance_breakout_retest_strategy_v1.py -v
"""
import inspect
from datetime import datetime, timezone

import pytest

from core.core_models import CandleSnapshot, SNRLevel
from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot
from core.structure_utils import detect_snr_breakout_retest, detect_snr_role_flip


# ---------------------------------------------------------------------------
# Synthetic candle builders (explicit, engineered values -- not random data).
# detect_snr_breakout_retest()/detect_snr_role_flip() work directly off a
# plain (level, direction) or a snr_levels list, so no swing/structure
# machinery is needed to build these timelines, unlike Fix #7T's.
# ---------------------------------------------------------------------------

def _c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100.0, timestamp=str(ts))


LEVEL = 100.0


def _bullish_break_then_retest_candles():
    """idx0 pre-break (below) -> idx1 breakout (close beyond) -> idx2
    continues beyond -> idx3 genuine retest (wick touches LEVEL, close
    holds above) -> idx4 current (still beyond)."""
    return [
        _c(89, 91, 88, 90, 0),
        _c(99.5, 106, 99, 105, 1),   # breakout origin — range 7 -> tolerance 1.75
        _c(106, 112, 105, 110, 2),
        _c(102, 101, 99.5, 101, 3),  # retest: touches [98.25..101.75+], closes 101 >= 100
        _c(101, 104, 100.5, 103, 4),
    ]


def _bearish_break_then_retest_candles():
    """Mirror of the bullish timeline for a Support level breaking down."""
    return [
        _c(111, 112, 109, 110, 0),
        _c(100.5, 101, 94, 95, 1),   # breakout origin — range 7 -> tolerance 1.75
        _c(94, 95, 88, 90, 2),
        _c(99, 100.5, 97, 99, 3),    # retest: touches [95.25..102.25], closes 99 <= 100
        _c(99, 99.5, 96, 97, 4),
    ]


# ---------------------------------------------------------------------------
# structure_utils.detect_snr_breakout_retest() — pure geometric evidence.
# ---------------------------------------------------------------------------

def test_util_bullish_breakout_then_hold_above_retest_confirmed():
    candles = _bullish_break_then_retest_candles()
    result = detect_snr_breakout_retest(candles, LEVEL, "Bullish")
    assert result["retest_confirmed"] is True
    assert result["breakout_index"] == 1
    assert result["retest_index"] == 3


def test_util_bearish_breakdown_then_hold_below_retest_confirmed():
    candles = _bearish_break_then_retest_candles()
    result = detect_snr_breakout_retest(candles, LEVEL, "Bearish")
    assert result["retest_confirmed"] is True
    assert result["breakout_index"] == 1
    assert result["retest_index"] == 3


def test_util_breakout_without_retest_rejected():
    candles = _bullish_break_then_retest_candles()
    candles[3] = _c(105, 112, 104, 108, 3)  # never comes near LEVEL
    result = detect_snr_breakout_retest(candles, LEVEL, "Bullish")
    assert result["retest_confirmed"] is False
    assert result["retest_index"] is None


def test_util_touch_before_breakout_not_counted_as_retest():
    """A wick touch that happens BEFORE the level is ever genuinely broken
    must never be picked up as "the retest" -- the scan only looks after
    the breakout's own origin index."""
    candles = [
        _c(96, 96.5, 99.5, 95, 0),   # touches LEVEL from below, but never closes beyond it
        _c(99.5, 106, 99, 105, 1),   # true breakout origin
        _c(106, 112, 105, 108, 2),   # no later retest
    ]
    result = detect_snr_breakout_retest(candles, LEVEL, "Bullish")
    assert result["retest_confirmed"] is False


def test_util_same_candle_breakout_and_retest_structurally_impossible():
    """The retest scan starts at breakout_index + 1, so the breakout
    candle itself -- even if it also happens to wick through the level --
    can never simultaneously be reported as its own retest."""
    candles = [
        _c(89, 91, 88, 90, 0),
        _c(99.5, 106, 99.5, 105, 1),  # breakout candle's own low sits right at LEVEL
        _c(106, 112, 105, 108, 2),    # no OTHER candle touches afterward
    ]
    result = detect_snr_breakout_retest(candles, LEVEL, "Bullish")
    # The retest scan never includes the breakout index itself (it starts
    # at breakout_index + 1), so with no OTHER candle touching afterward,
    # no retest is found at all -- not even a false-positive "same-candle"
    # one.
    assert result["retest_confirmed"] is False
    assert result["retest_index"] is None


def test_util_bullish_retest_closes_back_below_level_rejected():
    candles = _bullish_break_then_retest_candles()
    candles[3] = _c(101, 100.8, 99, 99.5, 3)  # touches, but closes BELOW LEVEL -- failed hold
    candles[4] = _c(96, 97, 94, 95, 4)  # no longer beyond either, current check fails first
    result = detect_snr_breakout_retest(candles, LEVEL, "Bullish")
    assert result["retest_confirmed"] is False


def test_util_bearish_retest_closes_back_above_level_rejected():
    candles = _bearish_break_then_retest_candles()
    candles[3] = _c(99, 101.5, 99, 100.5, 3)  # touches, but closes ABOVE LEVEL -- failed hold
    result = detect_snr_breakout_retest(candles, LEVEL, "Bearish")
    assert result["retest_confirmed"] is False


def test_util_stale_old_breakout_ignored_for_new_leg_after_failure():
    """An old breakout that later FAILS (closes back through the level)
    must never be paired with a retest belonging to a brand new, later
    breakout of the same level -- same current-leg-identity principle Fix
    #7P/#7T already proved for structure breaks."""
    candles = [
        _c(99.5, 106, 99, 105, 0),   # stale OLD breakout
        _c(94, 95, 88, 90, 1),       # fails back through LEVEL -- invalidates the old leg
        _c(99.5, 109, 99, 108, 2),   # NEW breakout origin
        _c(102, 101, 99.5, 101, 3),  # genuine retest of the NEW leg
        _c(101, 104, 100.5, 103, 4),
    ]
    result = detect_snr_breakout_retest(candles, LEVEL, "Bullish")
    assert result["retest_confirmed"] is True
    assert result["breakout_index"] == 2  # NOT the stale idx 0
    assert result["retest_index"] == 3


def test_util_wick_near_but_not_touching_rejected():
    candles = _bullish_break_then_retest_candles()
    candles[3] = _c(103, 104, 102.5, 103, 3)  # low 102.5, tolerance 1.75 -> 100.75, never reaches 100
    result = detect_snr_breakout_retest(candles, LEVEL, "Bullish")
    assert result["retest_confirmed"] is False


def test_util_missing_level_or_bad_direction_rejected():
    candles = _bullish_break_then_retest_candles()
    assert detect_snr_breakout_retest(candles, None, "Bullish")["retest_confirmed"] is False
    assert detect_snr_breakout_retest(candles, LEVEL, "Neutral")["retest_confirmed"] is False


# ---------------------------------------------------------------------------
# structure_utils.detect_snr_role_flip() — full snr_levels list evidence.
# ---------------------------------------------------------------------------

def test_util_role_flip_resistance_to_support_confirmed():
    candles = _bullish_break_then_retest_candles()
    levels = [SNRLevel(type="Resistance", level=LEVEL, source="HH")]
    result = detect_snr_role_flip(candles, levels)
    assert result["confirmed"] is True
    assert result["direction"] == "Bullish"
    assert result["original_role"] == "Resistance"
    assert result["new_role"] == "Support"
    assert result["level"] == LEVEL
    assert result["breakout_index"] == 1
    assert result["retest_index"] == 3


def test_util_role_flip_support_to_resistance_confirmed():
    candles = _bearish_break_then_retest_candles()
    levels = [SNRLevel(type="Support", level=LEVEL, source="LL")]
    result = detect_snr_role_flip(candles, levels)
    assert result["confirmed"] is True
    assert result["direction"] == "Bearish"
    assert result["original_role"] == "Support"
    assert result["new_role"] == "Resistance"


def test_util_role_flip_far_away_nearest_level_rejected():
    """A level nowhere near any candle's actual price range never gets
    "broken" by a close -- distance/proximity alone proves nothing."""
    candles = _bullish_break_then_retest_candles()
    levels = [SNRLevel(type="Resistance", level=5000.0, source="HH")]
    result = detect_snr_role_flip(candles, levels)
    assert result["confirmed"] is False


def test_util_role_flip_prefers_most_recent_retest_among_candidates():
    candles = _bullish_break_then_retest_candles()
    # A second, non-qualifying Resistance level (never broken) must not
    # block or replace the one genuine, confirmed candidate.
    levels = [
        SNRLevel(type="Resistance", level=LEVEL, source="HH"),
        SNRLevel(type="Resistance", level=5000.0, source="HH"),
    ]
    result = detect_snr_role_flip(candles, levels)
    assert result["confirmed"] is True
    assert result["level"] == LEVEL


def test_util_role_flip_ignores_non_resistance_non_support_type():
    candles = _bullish_break_then_retest_candles()
    levels = [SNRLevel(type="Other", level=LEVEL, source="HH")]
    result = detect_snr_role_flip(candles, levels)
    assert result["confirmed"] is False


def test_util_role_flip_empty_levels_no_evidence():
    candles = _bullish_break_then_retest_candles()
    result = detect_snr_role_flip(candles, [])
    assert result["confirmed"] is False
    assert result["direction"] is None


# ---------------------------------------------------------------------------
# Strategy react() — operates purely off the pre-computed snr_flip_* bundle.
# ---------------------------------------------------------------------------

def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        snr_flip_confirmed=False, snr_flip_direction=None,
        snr_flip_original_role=None, snr_flip_new_role=None, snr_flip_level=None,
        snr_flip_breakout_index=None, snr_flip_breakout_timestamp=None,
        snr_flip_retest_index=None, snr_flip_retest_timestamp=None,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_RESISTANCE_TO_SUPPORT = dict(
    snr_flip_confirmed=True, snr_flip_direction="Bullish",
    snr_flip_original_role="Resistance", snr_flip_new_role="Support", snr_flip_level=1.2000,
    snr_flip_breakout_index=10, snr_flip_breakout_timestamp="2026-01-01T10:00:00Z",
    snr_flip_retest_index=14, snr_flip_retest_timestamp="2026-01-01T14:00:00Z",
)
_SUPPORT_TO_RESISTANCE = dict(
    snr_flip_confirmed=True, snr_flip_direction="Bearish",
    snr_flip_original_role="Support", snr_flip_new_role="Resistance", snr_flip_level=1.3000,
    snr_flip_breakout_index=20, snr_flip_breakout_timestamp="2026-01-02T10:00:00Z",
    snr_flip_retest_index=24, snr_flip_retest_timestamp="2026-01-02T14:00:00Z",
)


def test_resistance_break_hold_above_retest_valid_long():
    from core.strategy.SupportResistanceBreakoutRetestStrategy import SupportResistanceBreakoutRetestStrategy
    snap = _base_snapshot(**_RESISTANCE_TO_SUPPORT)
    result = SupportResistanceBreakoutRetestStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Resistance → Support Retest"
    assert result["price"] == 1.2000


def test_support_break_hold_below_retest_valid_short():
    from core.strategy.SupportResistanceBreakoutRetestStrategy import SupportResistanceBreakoutRetestStrategy
    snap = _base_snapshot(**_SUPPORT_TO_RESISTANCE)
    result = SupportResistanceBreakoutRetestStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Support → Resistance Retest"
    assert result["price"] == 1.3000


def test_not_confirmed_rejected():
    from core.strategy.SupportResistanceBreakoutRetestStrategy import SupportResistanceBreakoutRetestStrategy
    snap = _base_snapshot()
    assert SupportResistanceBreakoutRetestStrategy().react(snap, {}) is None


def test_confirmed_but_missing_level_rejected():
    from core.strategy.SupportResistanceBreakoutRetestStrategy import SupportResistanceBreakoutRetestStrategy
    overrides = dict(_RESISTANCE_TO_SUPPORT)
    overrides["snr_flip_level"] = None
    snap = _base_snapshot(**overrides)
    assert SupportResistanceBreakoutRetestStrategy().react(snap, {}) is None


def test_unrecognized_flip_direction_rejected():
    from core.strategy.SupportResistanceBreakoutRetestStrategy import SupportResistanceBreakoutRetestStrategy
    overrides = dict(_RESISTANCE_TO_SUPPORT)
    overrides["snr_flip_direction"] = "Neutral"
    snap = _base_snapshot(**overrides)
    assert SupportResistanceBreakoutRetestStrategy().react(snap, {}) is None


def test_exactly_two_markings_both_valid():
    from core.strategy.SupportResistanceBreakoutRetestStrategy import SupportResistanceBreakoutRetestStrategy
    snap = _base_snapshot(**_RESISTANCE_TO_SUPPORT)
    result = SupportResistanceBreakoutRetestStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 2
    types = {m["type"] for m in markings}
    assert types == {"level", "candle"}
    for m in markings:
        validate_chart_marking(m)
        assert m["evidence_ref"]["original_role"] == "Resistance"
        assert m["evidence_ref"]["new_role"] == "Support"
        assert m["evidence_ref"]["breakout_index"] == 10
        assert m["evidence_ref"]["retest_index"] == 14


def test_confidence_formula_reported_exactly():
    from core.strategy.SupportResistanceBreakoutRetestStrategy import (
        BASE_CONFIDENCE, MOMENTUM_WEIGHT, SupportResistanceBreakoutRetestStrategy,
    )
    assert BASE_CONFIDENCE == 0.5
    assert MOMENTUM_WEIGHT == 0.5
    overrides = dict(_RESISTANCE_TO_SUPPORT)
    overrides["atr_normalized_momentum"] = 1.0  # agrees with "long" (Bullish)
    snap = _base_snapshot(**overrides)
    result = SupportResistanceBreakoutRetestStrategy().react(snap, {})
    # strategy_momentum_confidence(1.0, "long") = min(1.0/2.0, 1.0) = 0.5
    assert result["confidence"] == round(0.5 + 0.5 * 0.5, 2)


def test_confidence_floor_with_no_momentum_support():
    from core.strategy.SupportResistanceBreakoutRetestStrategy import SupportResistanceBreakoutRetestStrategy
    snap = _base_snapshot(**_RESISTANCE_TO_SUPPORT)  # atr_normalized_momentum defaults to None
    result = SupportResistanceBreakoutRetestStrategy().react(snap, {})
    assert result["confidence"] == 0.5


def test_standard_output_fields_present():
    from core.strategy.SupportResistanceBreakoutRetestStrategy import SupportResistanceBreakoutRetestStrategy
    snap = _base_snapshot(**_RESISTANCE_TO_SUPPORT)
    result = SupportResistanceBreakoutRetestStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


# ---------------------------------------------------------------------------
# No coupling to S&D / Structure-event / ambient-only SNR evidence.
# ---------------------------------------------------------------------------

def test_no_supply_demand_dependency():
    import core.strategy.SupportResistanceBreakoutRetestStrategy as mod
    source = inspect.getsource(mod)
    for forbidden in ("active_zone", "mitigated_zone", "context_zone", "demand", "supply"):
        assert forbidden not in source.lower()


def test_no_structure_event_dependency():
    """Must never read Fix #7P's own structure-based breakout+retest
    fields, nor any BOS/CHoCH structure evidence -- role-flip evidence is
    sourced exclusively from snr_flip_* (S&R-native)."""
    import core.strategy.SupportResistanceBreakoutRetestStrategy as mod
    source = inspect.getsource(mod)
    for forbidden in (
        "structure_type", "structure_direction", "structure_valid",
        "breakout_origin_index", "retest_confirmed", "choch_confirmed", "bos_origin_index",
    ):
        assert forbidden not in source


def test_no_ambient_only_snr_field_dependency():
    """The committed SNRLevel dataclass carries only type/level/source/
    valid -- status/touches/timeframe/label/timestamp are ambient-WIP-only
    and must never be read by this strategy or by the new evidence
    helpers."""
    import core.strategy.SupportResistanceBreakoutRetestStrategy as mod
    strategy_source = inspect.getsource(mod)
    for forbidden in (".status", ".touches", ".label"):
        assert forbidden not in strategy_source

    import core.structure_utils as su_mod
    util_source = inspect.getsource(su_mod.detect_snr_breakout_retest) + inspect.getsource(su_mod.detect_snr_role_flip)
    for forbidden in ("lvl.status", "lvl.touches", "lvl.label", ".status", ".touches"):
        assert forbidden not in util_source


def _strip_docstring(func):
    """Scopes a source-text check to a function's CODE BODY only -- its
    own docstring prose can otherwise trip a naive substring check (this
    exact self-referential trap has bitten this series before, e.g. Fix
    #7U's momentum-field check matching its own docstring)."""
    src = inspect.getsource(func)
    first = src.find('"""')
    if first == -1:
        return src
    second = src.find('"""', first + 3)
    if second == -1:
        return src
    return src[:first] + src[second + 3:]


def test_detect_snr_role_flip_never_calls_structure_detection():
    """Confirms the new evidence path is not coupled to BOS/CHoCH
    classification -- it must never call detect_structure_event() or
    find_swings(), only reuse the structure-agnostic _find_current_leg_
    origin() helper."""
    import core.structure_utils as su_mod
    source = _strip_docstring(su_mod.detect_snr_role_flip) + _strip_docstring(su_mod.detect_snr_breakout_retest)
    assert "detect_structure_event(" not in source
    assert "find_swings(" not in source


# ---------------------------------------------------------------------------
# Discovery.
# ---------------------------------------------------------------------------

def test_support_resistance_breakout_retest_strategy_present_in_engine():
    """Fix #7W's own discovery-count test goes stale the moment a later
    fix adds another strategy (Fix #7X bumps 21 -> 22) -- this checks only
    that THIS fix's own strategy is present, not the total count. See
    test_fix_7x_volume_profile_foundation_and_weekly_reaction_v1.py for
    the current total-count/full-roster tests."""
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert "SupportResistanceBreakoutRetestStrategy" in engine.enabled


def test_existing_twenty_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_twenty = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy", "CHOCHBOSConfirmationStrategy", "MomentumPullbackRecoveryStrategy",
        "SupportResistanceReactionStrategy",
    }
    assert existing_twenty <= set(engine.enabled.keys())
