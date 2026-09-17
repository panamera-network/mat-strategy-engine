"""Fix #7Y — Balance Range Volume Profile v1: the second range source
built on Fix #7X's committed Volume Profile foundation (candle_
approximation, 24-bin instrument-aware bins, POC/VAH/VAL, 70% value
area) -- reused entirely unchanged, never a second implementation.

CANONICAL NAMING (this fix's own later naming-alignment follow-up, before
first commit): this module, the detector, the StructureSnapshot/
StrategySnapshot fields, and the strategy file were all originally named
"Accumulation Candidate Range" / "AccumulationRangeEngine" /
"accumulation_range_*" / "AccumulationRangeVAHVALReactionStrategy".
Renamed to the neutral "Balance Range" / "core.BalanceRangeEngine" /
"balance_range_*" / "BalanceRangeVAHVALReactionStrategy" -- SAME
calculation, SAME thresholds, SAME behavior, naming only (see
core/BalanceRangeEngine.py's own module docstring for the full
rationale). A future PO3 strategy may consume this exact same range
evidence and re-label it "PO3 Accumulation" only once Manipulation and
Distribution are independently proven elsewhere -- this module never
makes that call itself.

BALANCE-RANGE EVIDENCE AUDIT (performed before writing any detector --
see core/BalanceRangeEngine.py's own module docstring for the full
detail): core/TrendEngine.py's "Sideways" label and both of its callers
(core/bias_mode.py, core/strategy_snapshot.py) are entirely orphaned --
grep-confirmed, nothing else in this repo imports either caller.
structure_utils.detect_trend() (the one StructureEngine actually uses)
only reports Bullish/Bearish/Neutral off a 2-swing comparison --
"Neutral" is not a bounded range with a high/low/duration/touch history.
No committed, LIVE evidence anywhere identifies consolidation/balance/
compression/containment/session-phase, and nothing anywhere in this
codebase (committed or ambient) can distinguish accumulation from
distribution from generic sideways chop -- there is no volume-based or
order-flow evidence that could. v1 therefore exposes only a neutral
"Balance Range" -- never a confirmed-accumulation (or distribution)
claim.

TIMEFRAME CHOICE (reported before implementation): detection runs on the
CURRENT STRATEGY TIMEFRAME (StructureEngine's own already-fetched
`candles` window for that (symbol, tf)) -- NOT a fixed analysis
timeframe like Fix #7X's previous-week M30 -- because "compression" is
inherently scale-relative. This also means NO NEW MT5 FETCH is needed.

THRESHOLD AUDIT (live, before choosing values): a probe script ran the
backward-expansion algorithm across 324 (symbol, tf) pairs (36 symbols x
9 timeframes). At a 1.5x-ATR compression multiplier / 6-candle minimum
duration / 0.20-ATR touch tolerance / 2 touches per side, 5.2% of pairs
qualified live -- selective, matching this whole strategy series'
"eligibility, not blanket firing" convention (looser multipliers reached
20-26%, too loose to mean anything as compression).

RANGE IDENTITY: detection anchors at the CURRENT candle and expands
BACKWARD (the same current-leg-identity principle Fix #7P/#7T/#7W already
established) -- a range price has cleanly broken and left is never
carried forward as stale evidence; it simply stops being the active
candidate once "now" no longer belongs to any qualifying window.

TEMPORAL INTEGRITY (this fix's own follow-up audit, before first commit):
the range and its Volume Profile are built from candles through N-1
ONLY -- the reaction candle N is always held back from detection and
profile construction, and is evaluated only against the resulting frozen
VAH/VAL. See core/BalanceRangeEngine.py's own module docstring and this
file's own "Temporal integrity" test section below for the full audit
(a live check found including the reaction candle could shift VAH by a
real amount, and could even make detection fail entirely for the exact
rejection geometry the strategy is meant to catch).

V1 STRATEGY RULE (reported before implementation): of VAH rejection / VAL
rejection / POC reclaim-rejection / breakout-then-profile-relationship,
this v1 implements ONLY the VAH/VAL reaction (Fix #7X/#7V's own
touch-and-hold geometry, reused unchanged) -- POC and breakout-relationship
are deliberately deferred, not bundled in.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7y_balance_range_volume_profile_v1.py -v
"""
import inspect
from datetime import datetime, timezone

import pytest

from core.core_models import CandleSnapshot
from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot
from core.BalanceRangeEngine import (
    COMPRESSION_ATR_MULTIPLIER,
    MIN_RANGE_DURATION,
    MIN_TOUCHES_PER_SIDE,
    TOUCH_TOLERANCE_ATR_FRACTION,
    detect_balance_range,
)
from core.VolumeProfileEngine import build_volume_profile


def _c(h, l, ts, o=None, cl=None, v=10.0):
    o = o if o is not None else (h + l) / 2
    cl = cl if cl is not None else (h + l) / 2
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=v, timestamp=ts)


ATR = 1.0  # a fixed, simple ATR for hand-verified geometry tests


def _bounded_range_candles():
    """10 candles, width 1.3 (<= 1.5*ATR), >=2 touches each side, duration
    10 (>= MIN_RANGE_DURATION=6) -- every value hand-verified in this
    file's own docstring/PR notes: backward expansion from index 9
    includes the WHOLE window, range_high=100.8, range_low=99.5."""
    return [
        _c(100.7, 99.9, 0), _c(100.65, 99.6, 1), _c(100.5, 99.8, 2), _c(100.8, 99.9, 3),
        _c(100.4, 99.5, 4), _c(100.6, 99.8, 5), _c(100.5, 99.9, 6), _c(100.7, 99.8, 7),
        _c(100.4, 99.6, 8), _c(100.5, 99.7, 9),
    ]


# ---------------------------------------------------------------------------
# detect_balance_range() — hand-verified geometry.
# ---------------------------------------------------------------------------

def test_valid_bounded_balance_range():
    candles = _bounded_range_candles()
    result = detect_balance_range(candles, ATR)
    assert result["confirmed"] is True
    assert result["start_index"] == 0
    assert result["end_index"] == 9
    assert result["range_high"] == pytest.approx(100.8)
    assert result["range_low"] == pytest.approx(99.5)


def test_too_short_range_rejected():
    candles = _bounded_range_candles()[5:]  # only 5 candles -- below MIN_RANGE_DURATION=6
    result = detect_balance_range(candles, ATR)
    assert result["confirmed"] is False


def test_trending_market_rejected():
    """Each consecutive candle displaces further than the compression
    bound allows -- expansion halts almost immediately (duration < 6)."""
    candles = [_c(100 + 2 * i, 99.5 + 2 * i, i) for i in range(10)]
    result = detect_balance_range(candles, ATR)
    assert result["confirmed"] is False


def test_clean_breakout_current_candle_standalone_rejected():
    """The current (most recent) candle is a large, isolated displacement
    away from any prior consolidation -- explicit clean-breakout handling:
    duration collapses to 1 and is rejected, never mistaken for a range."""
    old_range = _bounded_range_candles()[:6]
    breakout_candle = _c(110, 105, 6)  # far away, wide range on its own
    candles = old_range + [breakout_candle]
    result = detect_balance_range(candles, ATR)
    assert result["confirmed"] is False


def test_stale_older_range_never_selected_over_newer_range():
    """An older, genuine range exists (idx 0-5), then a clean breakout
    (idx 6) into a BRAND NEW range (idx 7-12, still active at 'now'). The
    detector must select the NEW range only -- never reach back through
    the breakout candle to re-include the stale older one."""
    old_range = [
        _c(100.7, 99.9, 0), _c(100.6, 99.6, 1), _c(100.5, 99.8, 2),
        _c(100.8, 99.9, 3), _c(100.4, 99.5, 4), _c(100.6, 99.8, 5),
    ]
    breakout = _c(110, 105, 6)
    new_range = [
        _c(110.7, 109.9, 7), _c(110.6, 109.6, 8), _c(110.5, 109.8, 9),
        _c(110.8, 109.9, 10), _c(110.4, 109.5, 11), _c(110.6, 109.8, 12),
    ]
    candles = old_range + [breakout] + new_range
    result = detect_balance_range(candles, ATR)
    assert result["confirmed"] is True
    assert result["start_index"] == 7
    assert result["end_index"] == 12
    assert result["range_high"] == pytest.approx(110.8)
    assert result["range_low"] == pytest.approx(109.5)


def test_missing_atr_or_candles_rejected():
    assert detect_balance_range([], ATR)["confirmed"] is False
    assert detect_balance_range(_bounded_range_candles(), 0.0)["confirmed"] is False
    assert detect_balance_range(_bounded_range_candles(), None)["confirmed"] is False


def test_thresholds_are_the_documented_live_audit_values():
    assert COMPRESSION_ATR_MULTIPLIER == 1.5
    assert MIN_RANGE_DURATION == 6
    assert TOUCH_TOLERANCE_ATR_FRACTION == 0.20
    assert MIN_TOUCHES_PER_SIDE == 2


# ---------------------------------------------------------------------------
# Volume Profile built from the detected range only.
# ---------------------------------------------------------------------------

def test_vp_uses_only_candles_inside_selected_range():
    old_range = [
        _c(100.7, 99.9, 0), _c(100.6, 99.6, 1), _c(100.5, 99.8, 2),
        _c(100.8, 99.9, 3), _c(100.4, 99.5, 4), _c(100.6, 99.8, 5),
    ]
    breakout = _c(110, 105, 6)
    new_range = [
        _c(110.7, 109.9, 7), _c(110.6, 109.6, 8), _c(110.5, 109.8, 9),
        _c(110.8, 109.9, 10), _c(110.4, 109.5, 11), _c(110.6, 109.8, 12),
    ]
    candles = old_range + [breakout] + new_range
    result = detect_balance_range(candles, ATR)
    range_candles = candles[result["start_index"]:result["end_index"] + 1]
    profile = build_volume_profile(range_candles, symbol="TEST", timeframe="M15")
    # Only the new range's candles (~109.5-110.8) may influence the
    # profile -- the old range (~99.5-100.8) and the breakout candle
    # (105-110) must never appear.
    assert profile.range_start_timestamp == "7"
    assert profile.range_end_timestamp == "12"
    assert all(b.price_low >= 109.4 for b in profile.bins if b.volume > 0)


def test_poc_vah_val_deterministic_from_detected_range():
    candles = _bounded_range_candles()
    result = detect_balance_range(candles, ATR)
    range_candles = candles[result["start_index"]:result["end_index"] + 1]
    profile1 = build_volume_profile(range_candles, symbol="TEST", timeframe="M15")
    profile2 = build_volume_profile(range_candles, symbol="TEST", timeframe="M15")
    assert profile1.poc_price == profile2.poc_price
    assert profile1.value_area_high == profile2.value_area_high
    assert profile1.value_area_low == profile2.value_area_low
    assert profile1.value_area_low <= profile1.poc_price <= profile1.value_area_high


def test_source_remains_candle_approximation():
    candles = _bounded_range_candles()
    result = detect_balance_range(candles, ATR)
    range_candles = candles[result["start_index"]:result["end_index"] + 1]
    profile = build_volume_profile(range_candles, symbol="TEST", timeframe="M15")
    assert profile.source_type == "candle_approximation"


# ---------------------------------------------------------------------------
# FX / metal / crypto scale sanity.
# ---------------------------------------------------------------------------

def _scaled_range_candles(base_price, atr):
    """Same relative shape as _bounded_range_candles(), scaled to any
    absolute price level and ATR."""
    offsets_h = [0.7, 0.65, 0.5, 0.8, 0.4, 0.6, 0.5, 0.7, 0.4, 0.5]
    offsets_l = [-0.1, -0.4, -0.2, -0.1, -0.5, -0.2, -0.1, -0.2, -0.4, -0.3]
    return [
        _c(base_price + h * atr, base_price + l * atr, i)
        for i, (h, l) in enumerate(zip(offsets_h, offsets_l))
    ]


def test_fx_scale_range_detected_and_profiled():
    candles = _scaled_range_candles(1.1000, 0.0010)
    result = detect_balance_range(candles, 0.0010)
    assert result["confirmed"] is True
    profile = build_volume_profile(candles[result["start_index"]:result["end_index"] + 1], symbol="EURUSD_i", timeframe="M15")
    assert 1.0990 <= profile.poc_price <= 1.1010


def test_metal_scale_range_detected_and_profiled():
    candles = _scaled_range_candles(2000.0, 2.0)
    result = detect_balance_range(candles, 2.0)
    assert result["confirmed"] is True
    profile = build_volume_profile(candles[result["start_index"]:result["end_index"] + 1], symbol="XAUUSD_i", timeframe="M15")
    assert 1980 <= profile.poc_price <= 2020


def test_crypto_scale_range_detected_and_profiled():
    candles = _scaled_range_candles(30000.0, 30.0)
    result = detect_balance_range(candles, 30.0)
    assert result["confirmed"] is True
    profile = build_volume_profile(candles[result["start_index"]:result["end_index"] + 1], symbol="BTCUSD_i", timeframe="M15")
    assert 29900 <= profile.poc_price <= 30100


# ---------------------------------------------------------------------------
# Strategy react() — VAH/VAL reaction only, POC/breakout deferred.
# ---------------------------------------------------------------------------

def _candle(direction, index, timestamp, volume=100.0):
    return {"direction": direction, "index": index, "timestamp": timestamp, "volume": volume}


def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="M15", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        current_high=None, current_low=None, current_close=None,
        recent_candles=[_candle("bull", 9, "2026-01-01T00:00:00Z")],
        balance_range_confirmed=False,
        balance_range_start_index=None, balance_range_start_timestamp=None,
        balance_range_end_index=None, balance_range_end_timestamp=None,
        balance_range_high=None, balance_range_low=None,
        balance_range_poc=None, balance_range_vah=None, balance_range_val=None,
        balance_range_total_volume=None, balance_range_value_area_pct=0.70,
        balance_range_num_bins=24, balance_range_source_type="candle_approximation",
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_VAH_REACTION = dict(
    balance_range_confirmed=True,
    balance_range_start_index=0, balance_range_start_timestamp="0",
    balance_range_end_index=9, balance_range_end_timestamp="9",
    balance_range_high=100.8, balance_range_low=99.5,
    balance_range_poc=100.15, balance_range_vah=100.5, balance_range_val=99.8,
    balance_range_total_volume=100.0,
    current_high=100.55, current_low=100.45, current_close=100.48,
)
_VAL_REACTION = dict(
    balance_range_confirmed=True,
    balance_range_start_index=0, balance_range_start_timestamp="0",
    balance_range_end_index=9, balance_range_end_timestamp="9",
    balance_range_high=100.8, balance_range_low=99.5,
    balance_range_poc=100.15, balance_range_vah=100.5, balance_range_val=99.8,
    balance_range_total_volume=100.0,
    current_high=99.85, current_low=99.75, current_close=99.82,
)


def test_vah_touch_and_hold_below_valid_short():
    from core.strategy.BalanceRangeVAHVALReactionStrategy import BalanceRangeVAHVALReactionStrategy
    snap = _base_snapshot(**_VAH_REACTION)
    result = BalanceRangeVAHVALReactionStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Balance Range VAH Reaction"
    assert result["price"] == 100.5


def test_val_touch_and_hold_above_valid_long():
    from core.strategy.BalanceRangeVAHVALReactionStrategy import BalanceRangeVAHVALReactionStrategy
    snap = _base_snapshot(**_VAL_REACTION)
    result = BalanceRangeVAHVALReactionStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Balance Range VAL Reaction"
    assert result["price"] == 99.8


def test_no_range_confirmed_rejected():
    from core.strategy.BalanceRangeVAHVALReactionStrategy import BalanceRangeVAHVALReactionStrategy
    snap = _base_snapshot(current_high=100.55, current_low=100.45, current_close=100.48)
    assert BalanceRangeVAHVALReactionStrategy().react(snap, {}) is None


def test_touched_but_closes_through_rejected():
    from core.strategy.BalanceRangeVAHVALReactionStrategy import BalanceRangeVAHVALReactionStrategy
    overrides = dict(_VAH_REACTION)
    overrides["current_close"] = 100.60  # closes ABOVE vah -- not held
    snap = _base_snapshot(**overrides)
    assert BalanceRangeVAHVALReactionStrategy().react(snap, {}) is None


def test_far_from_vah_and_val_rejected():
    from core.strategy.BalanceRangeVAHVALReactionStrategy import BalanceRangeVAHVALReactionStrategy
    overrides = dict(_VAH_REACTION)
    overrides["current_high"] = 100.20
    overrides["current_low"] = 100.10
    overrides["current_close"] = 100.15
    snap = _base_snapshot(**overrides)
    assert BalanceRangeVAHVALReactionStrategy().react(snap, {}) is None


def test_exactly_two_markings_profile_and_level():
    from core.strategy.BalanceRangeVAHVALReactionStrategy import BalanceRangeVAHVALReactionStrategy
    snap = _base_snapshot(**_VAH_REACTION)
    result = BalanceRangeVAHVALReactionStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 2
    types = {m["type"] for m in markings}
    assert types == {"profile", "level"}
    for m in markings:
        validate_chart_marking(m)
    profile_marking = next(m for m in markings if m["type"] == "profile")
    assert profile_marking["price"] == 100.15
    assert profile_marking["top"] == 100.5
    assert profile_marking["bottom"] == 99.8
    assert profile_marking["start_index"] == 0
    assert profile_marking["end_index"] == 9
    assert profile_marking["evidence_ref"]["range_type"] == "balance_range"


def test_confidence_formula_reported_exactly():
    from core.strategy.BalanceRangeVAHVALReactionStrategy import (
        BASE_CONFIDENCE, MOMENTUM_WEIGHT, BalanceRangeVAHVALReactionStrategy,
    )
    assert BASE_CONFIDENCE == 0.5
    assert MOMENTUM_WEIGHT == 0.5
    overrides = dict(_VAH_REACTION)
    overrides["atr_normalized_momentum"] = -1.0  # agrees with "short"
    snap = _base_snapshot(**overrides)
    result = BalanceRangeVAHVALReactionStrategy().react(snap, {})
    assert result["confidence"] == round(0.5 + 0.5 * 0.5, 2)


def test_standard_output_fields_present():
    from core.strategy.BalanceRangeVAHVALReactionStrategy import BalanceRangeVAHVALReactionStrategy
    snap = _base_snapshot(**_VAH_REACTION)
    result = BalanceRangeVAHVALReactionStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_poc_and_breakout_relationship_not_implemented_in_v1():
    """POC is legitimately DISPLAYED on the profile marking (passed as
    `poc=snapshot.balance_range_poc` to build_profile_marking()) --
    this only confirms it is never used for ELIGIBILITY: no comparison
    against balance_range_poc anywhere in react()'s own logic."""
    import core.strategy.BalanceRangeVAHVALReactionStrategy as mod
    source = inspect.getsource(mod.BalanceRangeVAHVALReactionStrategy.react)
    forbidden_comparisons = (
        "if snapshot.balance_range_poc",
        "> snapshot.balance_range_poc",
        "< snapshot.balance_range_poc",
        "<= snapshot.balance_range_poc",
        ">= snapshot.balance_range_poc",
    )
    for forbidden in forbidden_comparisons:
        assert forbidden not in source
    # POC is passed through only as a marking value, on its own line.
    assert "poc=snapshot.balance_range_poc" in source


def test_naming_never_claims_confirmed_accumulation():
    """The reason text and reused labels must always say "Balance Range",
    per this fix's own canonical naming alignment -- never "Accumulation"
    and never any implication of confirmed accumulation/distribution
    intent (nothing in this codebase can tell those apart)."""
    from core.strategy.BalanceRangeVAHVALReactionStrategy import BalanceRangeVAHVALReactionStrategy
    snap = _base_snapshot(**_VAH_REACTION)
    result = BalanceRangeVAHVALReactionStrategy().react(snap, {})
    assert "Balance Range" in result["reason"]
    assert "Accumulation" not in result["reason"]
    assert "Candidate" not in result["reason"]


def test_no_manual_range_behavior_yet():
    import core.strategy.BalanceRangeVAHVALReactionStrategy as strategy_mod
    import core.BalanceRangeEngine as engine_mod
    for mod in (strategy_mod, engine_mod):
        source = inspect.getsource(mod)
        assert "manual_range" not in source.lower()
        assert "user_selected" not in source.lower()


# ---------------------------------------------------------------------------
# No Previous-Week VP regression.
# ---------------------------------------------------------------------------

def test_previous_week_strategy_source_untouched_by_balance_range_fields():
    import core.strategy.VolumeProfileWeeklyReactionStrategy as mod
    source = inspect.getsource(mod)
    assert "balance_range" not in source


def test_previous_week_strategy_still_fires_correctly():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import VolumeProfileWeeklyReactionStrategy
    snap = _base_snapshot(
        volume_profile_source_type="candle_approximation",
        volume_profile_vah=1.2000, volume_profile_val=1.1800,
        current_high=1.2050, current_low=1.1980, current_close=1.1985,
    )
    result = VolumeProfileWeeklyReactionStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Previous-Week VAH Reaction"


# ---------------------------------------------------------------------------
# Temporal integrity — the reaction candle (N) must never participate in
# its own profile's construction (StructureEngine.get_snapshot() passes
# candles[:-1] into detection, holding back the true current candle).
# ---------------------------------------------------------------------------

class _FakeCache:
    """Mimics CandleCache's .get() interface with a fixed candle list, so
    StructureEngine.get_snapshot() can be exercised deterministically
    without touching MT5 at all."""
    def __init__(self, candles):
        self._candles = candles

    def get(self, symbol, tf, count=100):
        if count < len(self._candles):
            return self._candles[-count:]
        return self._candles


def _long_established_range(cycles=5):
    """A long-running, genuine consolidation (5 repeats of a 5-candle
    oscillation, all within [99.6, 100.75] -- comfortably under this
    live-computed window's own 1.5xATR bound, hand-verified before
    writing these tests) -- long enough that StructureEngine's own
    FETCH_COUNT (26) window sits entirely inside one established range,
    so the ONLY thing that can plausibly differ between two runs is
    whatever candle N itself contributes. This range's own frozen
    evidence (hand-verified): range_high=100.75, range_low=99.6,
    vah=100.4625, val=99.8875, poc=99.959375."""
    cycle = [
        (100.65, 99.9), (100.55, 99.65), (100.45, 99.8), (100.75, 99.9), (100.35, 99.6),
    ]
    candles = []
    idx = 0
    for _ in range(cycles):
        for h, l in cycle:
            candles.append(_c(h, l, idx))
            idx += 1
    return candles


def test_reaction_candle_excluded_from_detected_range_end_index():
    from core.StructureEngine import StructureEngine
    from core.CandleEngine import CandleEngine

    historical = _long_established_range()
    reaction_candle = _c(100.55, 99.85, len(historical), cl=100.50)
    candles = historical + [reaction_candle]

    engine = StructureEngine(CandleEngine())
    structure = engine.get_snapshot("TESTSYM", "M15", cache=_FakeCache(candles))
    assert structure is not None
    assert structure.balance_range_confirmed is True
    last_index = len(candles) - 1
    assert structure.balance_range_end_index is not None
    assert structure.balance_range_end_index < last_index
    assert structure.balance_range_end_timestamp != str(reaction_candle.timestamp)


def test_reaction_candle_volume_never_shifts_frozen_vah_val_poc():
    """The exact live-audited scenario: a reaction candle with unusually
    large tick volume must NEVER move VAH/VAL/POC -- it is excluded from
    profile construction entirely."""
    from core.StructureEngine import StructureEngine
    from core.CandleEngine import CandleEngine

    historical = _long_established_range()
    engine = StructureEngine(CandleEngine())

    normal_reaction = _c(100.55, 99.85, len(historical), cl=100.50, v=10.0)
    huge_volume_reaction = _c(100.55, 99.85, len(historical), cl=100.50, v=5000.0)

    structure_normal = engine.get_snapshot("TESTSYM", "M15", cache=_FakeCache(historical + [normal_reaction]))
    structure_huge = engine.get_snapshot("TESTSYM", "M15", cache=_FakeCache(historical + [huge_volume_reaction]))

    assert structure_normal.balance_range_confirmed is True
    assert structure_huge.balance_range_confirmed is True
    assert structure_normal.balance_range_poc == structure_huge.balance_range_poc
    assert structure_normal.balance_range_vah == structure_huge.balance_range_vah
    assert structure_normal.balance_range_val == structure_huge.balance_range_val
    assert structure_normal.balance_range_total_volume == structure_huge.balance_range_total_volume


def test_reaction_candle_range_expansion_never_changes_frozen_range():
    """A reaction candle that wicks beyond the old range high/low (the
    exact shape of a genuine VAH/VAL rejection) must never change the
    frozen range_high/range_low, and must never cause detection to fail
    outright -- both real failure modes found in the live audit before
    this fix."""
    from core.StructureEngine import StructureEngine
    from core.CandleEngine import CandleEngine

    historical = _long_established_range()
    engine = StructureEngine(CandleEngine())

    normal_reaction = _c(100.55, 99.85, len(historical), cl=100.50)
    expanding_reaction = _c(101.5, 98.8, len(historical), cl=100.20)  # wicks well beyond both sides

    structure_normal = engine.get_snapshot("TESTSYM", "M15", cache=_FakeCache(historical + [normal_reaction]))
    structure_expand = engine.get_snapshot("TESTSYM", "M15", cache=_FakeCache(historical + [expanding_reaction]))

    assert structure_normal.balance_range_confirmed is True
    assert structure_expand.balance_range_confirmed is True
    assert structure_normal.balance_range_high == structure_expand.balance_range_high
    assert structure_normal.balance_range_low == structure_expand.balance_range_low
    assert structure_normal.balance_range_vah == structure_expand.balance_range_vah
    assert structure_normal.balance_range_val == structure_expand.balance_range_val


def test_clean_breakout_reaction_candle_does_not_touch_frozen_levels():
    """A clean breakout candle as N must not retroactively destroy the
    range (it is excluded from detection) -- the strategy instead
    correctly finds no eligibility because the breakout candle simply
    doesn't touch the frozen VAH/VAL, not because detection failed."""
    from core.StructureEngine import StructureEngine
    from core.CandleEngine import CandleEngine
    from core.strategy.StrategyEngine import to_strategy_snapshot
    from core.strategy.BalanceRangeVAHVALReactionStrategy import BalanceRangeVAHVALReactionStrategy

    historical = _long_established_range()
    breakout_candle = _c(105.0, 103.0, len(historical))  # far outside [99.5, 100.8]
    engine = StructureEngine(CandleEngine())
    structure = engine.get_snapshot("TESTSYM", "M15", cache=_FakeCache(historical + [breakout_candle]))

    assert structure.balance_range_confirmed is True  # frozen range survives the breakout candle
    snap = to_strategy_snapshot(structure)
    result = BalanceRangeVAHVALReactionStrategy().react(snap, {})
    assert result is None  # breakout candle doesn't touch the (still-valid) frozen VAH/VAL


def test_detector_itself_still_treats_its_own_input_last_candle_as_current():
    """The pure detect_balance_range() function is
    unchanged -- it is the CALLER's responsibility (StructureEngine) to
    pass candles[:-1]. Confirms this contract directly: feeding the full
    list (including the reaction candle) to the bare function still
    anchors at that reaction candle, which is exactly why the wiring must
    slice it off first."""
    historical = _long_established_range()
    reaction_candle = _c(100.55, 99.85, len(historical), cl=100.50)
    full = historical + [reaction_candle]
    atr = 1.0
    result_full = detect_balance_range(full, atr)
    result_historical_only = detect_balance_range(historical, atr)
    assert result_full["end_index"] == len(full) - 1
    assert result_historical_only["end_index"] == len(historical) - 1
    assert result_full["end_index"] != result_historical_only["end_index"]


# ---------------------------------------------------------------------------
# Discovery.
# ---------------------------------------------------------------------------

def test_strategy_engine_discovers_twentythree_strategies_now():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert len(engine.strategies) == 23
    assert "BalanceRangeVAHVALReactionStrategy" in engine.enabled


def test_existing_twentytwo_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_twentytwo = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy", "CHOCHBOSConfirmationStrategy", "MomentumPullbackRecoveryStrategy",
        "SupportResistanceReactionStrategy", "SupportResistanceBreakoutRetestStrategy",
        "VolumeProfileWeeklyReactionStrategy",
    }
    assert existing_twentytwo <= set(engine.enabled.keys())
