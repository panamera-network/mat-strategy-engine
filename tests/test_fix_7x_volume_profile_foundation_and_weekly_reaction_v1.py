"""Fix #7X — Volume Profile Foundation + Last-Week M30 Strategy v1.

DATA/EVIDENCE AUDIT (performed before writing any code -- see
core/VolumeProfileEngine.py's own module docstring for the full detail):

  - No tick-fetching exists anywhere in this codebase (`mt5.copy_ticks_
    range()`/`copy_ticks_from()` are never called -- mt5/fetcher.py only
    calls `mt5.copy_rates_from_pos()`, OHLC + tick_volume). `real_volume`
    is already confirmed 0 for every symbol on this account's feed (Fix
    #7R's own live audit) -- this broker's feed carries no genuine
    exchange-reported traded size at ANY granularity, so genuine ticks
    would only add resolution to the same quote-count proxy, not a
    qualitatively truer signal, at the cost of an unbounded new per-symbol
    fetch. Conclusion: this fix builds ONLY a candle-level APPROXIMATION,
    explicitly labelled source_type="candle_approximation" -- never
    "tick_activity". This is Option B from the fix's own audit framing,
    not Option A, and is never silently presented as true traded volume.

  - Timestamp audit: a live check against this account (Weltrade-Real)
    found MT5 candle timestamps are broker-server time (UTC+3) encoded as
    a raw epoch, NOT genuine UTC -- `datetime.utcfromtimestamp(candle.
    time)` read exactly 3 hours ahead of real `datetime.now(timezone.
    utc)` at the same instant. No code anywhere in this repo corrects for
    this. Week-boundary detection therefore groups candles by ISO
    calendar week computed directly off that same broker-time reference
    frame -- self-consistent (every candle uses the identical reference),
    never a claim of alignment to a real-world UTC Monday.

  - Bin sizing is instrument-aware WITHOUT any fixed pip width or MT5
    symbol-metadata lookup: bin width = (observed range) / NUM_BINS (24),
    so a JPY pair, a metal, a crypto, and an FX major each get bins scaled
    to their OWN price range automatically.

  - Value area convention: 70% (CME's own convention; the default across
    TradingView/NinjaTrader/ThinkorSwim), computed via the standard
    "expand from POC one bin at a time, always toward the larger
    adjacent side" algorithm -- explicitly documented, not invented
    silently.

V1 STRATEGY RULE (reported before implementation, per this fix's own
requirement): three candidate VP reactions exist -- VAH reaction, VAL
reaction, POC interaction/reclaim/rejection. This v1 implements ONLY the
VAH/VAL reaction (Fix #7V's exact touch-and-hold reaction geometry, reused
for VP evidence instead of an SNR level) as ONE symmetric strategy (VAH
touch-and-hold-below -> short; VAL touch-and-hold-above -> long). POC
interaction is a materially different, more complex idea and is
deliberately DEFERRED to a future strategy -- not bundled here.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7x_volume_profile_foundation_and_weekly_reaction_v1.py -v
"""
import calendar
import inspect
from datetime import datetime, timezone

import pytest

from core.core_models import CandleSnapshot
from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot
from core.VolumeProfileEngine import (
    NUM_BINS,
    VALUE_AREA_PCT,
    build_volume_profile,
    get_previous_completed_week_candles,
)


def _epoch(y, m, d, hh=10, mm=0):
    return calendar.timegm(datetime(y, m, d, hh, mm).timetuple())


def _flat_candle(price, volume, ts):
    """A flat (high == low == open == close) candle -- drops fully into
    exactly one bin, no overlap-splitting, easiest to hand-verify."""
    return CandleSnapshot(open=price, high=price, low=price, close=price, volume=volume, timestamp=ts)


# ---------------------------------------------------------------------------
# build_volume_profile() — POC/VAH/VAL determinism (small, hand-verified).
# ---------------------------------------------------------------------------

def test_poc_vah_val_determinism_hand_verified():
    """3 flat candles, 3 bins, round numbers -- every value hand-computed
    in this fix's own docstring/PR notes before writing this assertion:
    range [100,106], bin_width=2 -> bins [100,102)/[102,104)/[104,106].
    Volumes 10/50/20 -> POC bin1 (vol 50, price 103), value area expands
    to bin2 (vol 20 > bin0's vol 10) reaching 70/80=87.5% >= 70%."""
    candles = [
        _flat_candle(100, 10, _epoch(2026, 1, 5)),
        _flat_candle(103, 50, _epoch(2026, 1, 5, 11)),
        _flat_candle(106, 20, _epoch(2026, 1, 5, 12)),
    ]
    profile = build_volume_profile(candles, symbol="TEST", timeframe="M30", num_bins=3, value_area_pct=0.70)
    assert profile is not None
    assert profile.total_volume == 80.0
    assert profile.poc_price == 103.0
    assert profile.value_area_high == 106.0
    assert profile.value_area_low == 102.0
    assert profile.num_bins == 3
    assert len(profile.bins) == 3


def test_poc_is_always_the_highest_volume_bin():
    candles = [
        _flat_candle(100, 5, _epoch(2026, 1, 5)),
        _flat_candle(101, 5, _epoch(2026, 1, 5, 11)),
        _flat_candle(102, 999, _epoch(2026, 1, 5, 12)),
        _flat_candle(103, 5, _epoch(2026, 1, 5, 13)),
    ]
    profile = build_volume_profile(candles, symbol="TEST", timeframe="M30", num_bins=4, value_area_pct=0.70)
    max_vol_bin = max(profile.bins, key=lambda b: b.volume)
    assert max_vol_bin.price_low <= profile.poc_price <= max_vol_bin.price_high


def test_value_area_captures_at_least_configured_percentage():
    candles = [_flat_candle(100 + i, 1.0 + (i % 5), _epoch(2026, 1, 5, 10, i)) for i in range(30)]
    profile = build_volume_profile(candles, symbol="TEST", timeframe="M30", num_bins=6, value_area_pct=0.70)
    va_volume = sum(
        b.volume for b in profile.bins
        if b.price_low >= profile.value_area_low and b.price_high <= profile.value_area_high
    )
    assert va_volume >= 0.70 * profile.total_volume - 1e-9


def test_total_volume_conserved_across_bins_with_wick_overlap():
    """Non-flat candles distributed across multiple bins must still sum to
    exactly the input total volume -- the overlap-weighted split must
    never lose or fabricate volume."""
    candles = [
        CandleSnapshot(open=100, high=104, low=100, close=102, volume=40.0, timestamp=_epoch(2026, 1, 5)),
        CandleSnapshot(open=102, high=108, low=101, close=106, volume=60.0, timestamp=_epoch(2026, 1, 5, 11)),
    ]
    profile = build_volume_profile(candles, symbol="TEST", timeframe="M30", num_bins=4, value_area_pct=0.70)
    assert profile.total_volume == pytest.approx(100.0)
    assert sum(b.volume for b in profile.bins) == pytest.approx(100.0)


# ---------------------------------------------------------------------------
# Instrument-aware bin sizing — FX / metal / crypto materially different
# price scales, same NUM_BINS, no fixed pip width anywhere.
# ---------------------------------------------------------------------------

def test_fx_scale_profile_bins_within_instrument_range():
    candles = [_flat_candle(1.0950 + i * 0.0005, 10.0, _epoch(2026, 1, 5, 10, i)) for i in range(20)]
    profile = build_volume_profile(candles, symbol="EURUSD_i", timeframe="M30")
    assert 1.0950 <= profile.poc_price <= 1.1050
    assert 1.0950 <= profile.value_area_low <= profile.value_area_high <= 1.1050


def test_metal_scale_profile_bins_within_instrument_range():
    candles = [_flat_candle(1980 + i * 2, 10.0, _epoch(2026, 1, 5, 10, i)) for i in range(20)]
    profile = build_volume_profile(candles, symbol="XAUUSD_i", timeframe="M30")
    assert 1980 <= profile.poc_price <= 2020
    assert 1980 <= profile.value_area_low <= profile.value_area_high <= 2020


def test_crypto_scale_profile_bins_within_instrument_range():
    candles = [_flat_candle(29000 + i * 100, 10.0, _epoch(2026, 1, 5, 10, i)) for i in range(20)]
    profile = build_volume_profile(candles, symbol="BTCUSD_i", timeframe="M30")
    assert 29000 <= profile.poc_price <= 31000
    assert 29000 <= profile.value_area_low <= profile.value_area_high <= 31000


def test_bin_width_scales_with_observed_range_not_fixed_pips():
    fx = build_volume_profile(
        [_flat_candle(1.10 + i * 0.001, 1.0, _epoch(2026, 1, 5, 10, i)) for i in range(10)],
        symbol="EURUSD_i", timeframe="M30", num_bins=NUM_BINS,
    )
    metal = build_volume_profile(
        [_flat_candle(2000 + i, 1.0, _epoch(2026, 1, 5, 10, i)) for i in range(10)],
        symbol="XAUUSD_i", timeframe="M30", num_bins=NUM_BINS,
    )
    fx_bin_width = fx.bins[0].price_high - fx.bins[0].price_low
    metal_bin_width = metal.bins[0].price_high - metal.bins[0].price_low
    # FX's observed range (~0.009) is tiny vs metal's (~9) -- bin widths
    # must reflect that, not share a common fixed pip size.
    assert fx_bin_width < 0.01
    assert metal_bin_width > 0.1


# ---------------------------------------------------------------------------
# Previous-completed-week boundary / no current-week leakage.
# ---------------------------------------------------------------------------

def test_previous_completed_week_selected_not_current():
    older_week = [_flat_candle(100, 5, _epoch(2026, 1, 5, 10, i)) for i in range(3)]
    previous_week = [_flat_candle(200, 7, _epoch(2026, 1, 12, 10, i)) for i in range(3)]
    current_week = [_flat_candle(300, 9, _epoch(2026, 1, 19, 10, 0))]  # only 1 candle -- still forming
    all_candles = older_week + previous_week + current_week

    result = get_previous_completed_week_candles(all_candles)
    assert len(result) == 3
    assert all(c.close == 200 for c in result)


def test_current_week_never_leaks_into_previous_week_result():
    previous_week = [_flat_candle(200, 7, _epoch(2026, 1, 12, 10, i)) for i in range(3)]
    current_week = [_flat_candle(999, 999, _epoch(2026, 1, 19, 10, i)) for i in range(5)]
    result = get_previous_completed_week_candles(previous_week + current_week)
    assert all(c.close != 999 for c in result)
    assert len(result) == 3


def test_only_one_week_present_returns_empty_no_previous_week_available():
    only_week = [_flat_candle(100, 5, _epoch(2026, 1, 5, 10, i)) for i in range(4)]
    result = get_previous_completed_week_candles(only_week)
    assert result == []


def test_profile_range_timestamps_match_previous_week_boundaries():
    older_week = [_flat_candle(100, 5, _epoch(2026, 1, 5, 10, i)) for i in range(2)]
    previous_week = [
        _flat_candle(200, 7, _epoch(2026, 1, 12, 8, 0)),
        _flat_candle(201, 7, _epoch(2026, 1, 14, 16, 0)),
    ]
    current_week = [_flat_candle(300, 9, _epoch(2026, 1, 19, 10, 0))]
    prev_candles = get_previous_completed_week_candles(older_week + previous_week + current_week)
    profile = build_volume_profile(prev_candles, symbol="TEST", timeframe="M30")
    assert profile.range_start_timestamp == str(_epoch(2026, 1, 12, 8, 0))
    assert profile.range_end_timestamp == str(_epoch(2026, 1, 14, 16, 0))


# ---------------------------------------------------------------------------
# Empty / missing data.
# ---------------------------------------------------------------------------

def test_build_volume_profile_empty_candles_returns_none():
    assert build_volume_profile([], symbol="TEST", timeframe="M30") is None


def test_get_previous_completed_week_candles_empty_input():
    assert get_previous_completed_week_candles([]) == []


def test_degenerate_zero_range_candles_do_not_crash():
    candles = [_flat_candle(100, 5, _epoch(2026, 1, 5, 10, i)) for i in range(3)]  # all same price
    profile = build_volume_profile(candles, symbol="TEST", timeframe="M30", num_bins=4)
    assert profile is not None
    assert profile.total_volume == 15.0
    assert profile.poc_price == 100.0


def test_volume_profile_engine_no_previous_week_returns_none(monkeypatch):
    from core.VolumeProfileEngine import VolumeProfileEngine

    class FakeCandleEngine:
        def get_snapshots(self, symbol, tf, count=100, cache=None):
            return [_flat_candle(100, 5, _epoch(2026, 1, 19, 10, i)) for i in range(3)]  # one week only

    engine = VolumeProfileEngine(FakeCandleEngine())
    assert engine.get_previous_week_m30_profile("EURUSD_i") is None


def test_volume_profile_engine_builds_from_previous_week(monkeypatch):
    from core.VolumeProfileEngine import VolumeProfileEngine

    class FakeCandleEngine:
        def get_snapshots(self, symbol, tf, count=100, cache=None):
            assert tf == "M30"
            previous_week = [_flat_candle(200 + i, 10, _epoch(2026, 1, 12, 10, i)) for i in range(5)]
            current_week = [_flat_candle(300, 9, _epoch(2026, 1, 19, 10, 0))]
            return previous_week + current_week

    engine = VolumeProfileEngine(FakeCandleEngine())
    profile = engine.get_previous_week_m30_profile("EURUSD_i")
    assert profile is not None
    assert profile.source_type == "candle_approximation"
    assert profile.symbol == "EURUSD_i"
    assert profile.timeframe == "M30"


# ---------------------------------------------------------------------------
# Exact profile source labelling.
# ---------------------------------------------------------------------------

def test_default_source_type_is_candle_approximation_not_tick_activity():
    candles = [_flat_candle(100, 5, _epoch(2026, 1, 5, 10, i)) for i in range(3)]
    profile = build_volume_profile(candles, symbol="TEST", timeframe="M30")
    assert profile.source_type == "candle_approximation"
    assert profile.source_type != "tick_activity"


def test_no_tick_fetch_anywhere_in_volume_profile_module():
    """This module reads audit prose about copy_ticks/real_volume in its
    own docstring (explaining why they are NOT used) -- scope the check to
    the actual CODE, not the module docstring, to avoid a self-referential
    false failure (this exact trap has bitten this series before)."""
    import core.VolumeProfileEngine as vp_mod
    source = inspect.getsource(vp_mod)
    module_doc_end = source.index('"""', source.index('"""') + 3) + 3
    code_only = source[module_doc_end:]
    assert "MetaTrader5" not in code_only
    assert "mt5." not in code_only
    assert "copy_ticks" not in code_only
    assert "real_volume" not in code_only


def test_value_area_pct_is_documented_seventy_percent():
    assert VALUE_AREA_PCT == 0.70


# ---------------------------------------------------------------------------
# Strategy react() — VAH/VAL reaction only, POC deferred.
# ---------------------------------------------------------------------------

def _candle(direction, index, timestamp, volume=100.0):
    return {"direction": direction, "index": index, "timestamp": timestamp, "volume": volume}


def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        current_high=None, current_low=None, current_close=None,
        recent_candles=[_candle("bull", 42, "2026-01-01T00:00:00Z")],
        volume_profile_source_type="candle_approximation",
        volume_profile_vah=None, volume_profile_val=None,
        volume_profile_poc=None, volume_profile_total_volume=None,
        volume_profile_range_start_timestamp=None, volume_profile_range_end_timestamp=None,
        volume_profile_value_area_pct=0.70, volume_profile_num_bins=24,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_VAH_REACTION = dict(
    volume_profile_vah=1.2000, volume_profile_val=1.1800,
    current_high=1.2050, current_low=1.1980, current_close=1.1985,
)
_VAL_REACTION = dict(
    volume_profile_vah=1.2000, volume_profile_val=1.1800,
    current_high=1.1830, current_low=1.1770, current_close=1.1820,
)


def test_vah_touch_and_hold_below_valid_short():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import VolumeProfileWeeklyReactionStrategy
    snap = _base_snapshot(**_VAH_REACTION)
    result = VolumeProfileWeeklyReactionStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Previous-Week VAH Reaction"
    assert result["price"] == 1.2000


def test_val_touch_and_hold_above_valid_long():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import VolumeProfileWeeklyReactionStrategy
    snap = _base_snapshot(**_VAL_REACTION)
    result = VolumeProfileWeeklyReactionStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Previous-Week VAL Reaction"
    assert result["price"] == 1.1800


def test_no_profile_evidence_rejected():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import VolumeProfileWeeklyReactionStrategy
    snap = _base_snapshot()
    assert VolumeProfileWeeklyReactionStrategy().react(snap, {}) is None


def test_missing_current_candle_geometry_rejected():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import VolumeProfileWeeklyReactionStrategy
    overrides = dict(_VAH_REACTION)
    overrides["current_close"] = None
    snap = _base_snapshot(**overrides)
    assert VolumeProfileWeeklyReactionStrategy().react(snap, {}) is None


def test_vah_touched_but_closes_through_rejected():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import VolumeProfileWeeklyReactionStrategy
    overrides = dict(_VAH_REACTION)
    overrides["current_close"] = 1.2010  # closes ABOVE vah -- not a held rejection
    snap = _base_snapshot(**overrides)
    assert VolumeProfileWeeklyReactionStrategy().react(snap, {}) is None


def test_val_touched_but_closes_through_rejected():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import VolumeProfileWeeklyReactionStrategy
    overrides = dict(_VAL_REACTION)
    overrides["current_close"] = 1.1790  # closes BELOW val -- not a held bounce
    snap = _base_snapshot(**overrides)
    assert VolumeProfileWeeklyReactionStrategy().react(snap, {}) is None


def test_far_from_vah_and_val_rejected():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import VolumeProfileWeeklyReactionStrategy
    overrides = dict(
        volume_profile_vah=1.2000, volume_profile_val=1.1800,
        current_high=1.1920, current_low=1.1900, current_close=1.1910,
    )
    snap = _base_snapshot(**overrides)
    assert VolumeProfileWeeklyReactionStrategy().react(snap, {}) is None


def test_exactly_two_markings_both_valid():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import VolumeProfileWeeklyReactionStrategy
    snap = _base_snapshot(**_VAH_REACTION)
    result = VolumeProfileWeeklyReactionStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 2
    types = {m["type"] for m in markings}
    assert types == {"level", "candle"}
    for m in markings:
        validate_chart_marking(m)
        assert m["evidence_ref"]["volume_profile_source_type"] == "candle_approximation"


def test_confidence_formula_reported_exactly():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import (
        BASE_CONFIDENCE, MOMENTUM_WEIGHT, VolumeProfileWeeklyReactionStrategy,
    )
    assert BASE_CONFIDENCE == 0.5
    assert MOMENTUM_WEIGHT == 0.5
    overrides = dict(_VAH_REACTION)
    overrides["atr_normalized_momentum"] = -1.0  # agrees with "short" (Bearish direction)
    snap = _base_snapshot(**overrides)
    result = VolumeProfileWeeklyReactionStrategy().react(snap, {})
    assert result["confidence"] == round(0.5 + 0.5 * 0.5, 2)


def test_confidence_floor_with_no_momentum_support():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import VolumeProfileWeeklyReactionStrategy
    snap = _base_snapshot(**_VAH_REACTION)  # atr_normalized_momentum defaults to None
    result = VolumeProfileWeeklyReactionStrategy().react(snap, {})
    assert result["confidence"] == 0.5


def test_standard_output_fields_present():
    from core.strategy.VolumeProfileWeeklyReactionStrategy import VolumeProfileWeeklyReactionStrategy
    snap = _base_snapshot(**_VAH_REACTION)
    result = VolumeProfileWeeklyReactionStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_poc_interaction_not_implemented_in_v1():
    """This fix's own audit explicitly defers POC reclaim/rejection to a
    future strategy -- confirms the react() body never references POC at
    all (only VAH/VAL)."""
    import core.strategy.VolumeProfileWeeklyReactionStrategy as mod
    source = inspect.getsource(mod.VolumeProfileWeeklyReactionStrategy.react)
    assert "volume_profile_poc" not in source


# ---------------------------------------------------------------------------
# Discovery.
# ---------------------------------------------------------------------------

def test_volume_profile_weekly_reaction_strategy_present_in_engine():
    """Fix #7X's own discovery-count test goes stale the moment a later
    fix adds another strategy (Fix #7Y bumps 22 -> 23) -- this checks only
    that THIS fix's own strategy is present, not the total count. See
    test_fix_7y_balance_range_volume_profile_v1.py for the current
    total-count/full-roster tests."""
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert "VolumeProfileWeeklyReactionStrategy" in engine.enabled


def test_existing_twentyone_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_twentyone = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy", "PriceVolumeAtZoneStrategy",
        "ConvictionSelectiveStrategy", "CHOCHBOSConfirmationStrategy", "MomentumPullbackRecoveryStrategy",
        "SupportResistanceReactionStrategy", "SupportResistanceBreakoutRetestStrategy",
    }
    assert existing_twentyone <= set(engine.enabled.keys())
