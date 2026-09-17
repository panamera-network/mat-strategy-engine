"""Fix #7Z — Manual Range Volume Profile v1: the third Volume Profile
range source, built entirely on Fix #7X's committed foundation
(build_volume_profile(): candle_approximation, 24 instrument-aware bins,
70% value area, POC/VAH/VAL) and Fix #7Y's build_profile_marking() -- no
second Volume Profile calculation anywhere.

ARCHITECTURE AUDIT (performed before writing anything -- see
core/ManualRangeVolumeProfile.py's own module docstring for the full
detail): the live per-cycle pipeline (StructureEngine -> StrategyEngine,
driven once per (symbol, tf) every request/tick) has no concept of a
user-selected range and must not gain one -- a Manual Range only exists
once a person picks two points on a chart. This is therefore exposed as
its own explicitly-triggered function + its own dedicated API route
(POST /core/volume-profile/manual), NEVER as a `Strategy` subclass --
StrategyEngine._discover_strategies() auto-loads every Strategy subclass
under core/strategy/ and evaluates it every cycle, so this module
deliberately lives outside that package and defines no Strategy at all.

DATA RETRIEVAL: a timestamp-addressed request uses the mt5.copy_rates_
range() path (genuinely bounded to [start, end], not a count-based
over-fetch) -- timestamps are the CANONICAL, preferred identity: stable
forever, including across newly closed candles.

STABLE MANUAL RANGE IDENTITY FOLLOW-UP (before this fix's first commit):
the original index-addressed path fetched via a count-based
`get_snapshots(count=N)`, which always returns the LAST N candles ending
at "now" -- silently drifting to different real candles on every repeat
call as time passes. Fixed: index-addressing now REQUIRES a
`reference_end_timestamp` (a stable anchor), fetched via
`mt5.copy_rates_from(symbol, tf, anchor, count)`
(live-verified: returns `count` candles ending at/before the FIXED
anchor, never "now"). A NAKED (start_index, end_index) request with no
anchor is rejected outright -- it is no longer part of the public/
internal contract at all. Neither retrieval path goes through the
shared per-request CandleCache (no date-range/anchor concept there) --
Manual Range keeps its own simple, indefinite in-process memo dict
instead (a manual range's own historical candles never change once
closed, unlike Fix #7X/#7Y's per-cycle "now" evidence) -- and this is
now equally safe for BOTH paths, since both are anchored to something
stable.

RANGE SEMANTICS: the user's selection is used exactly as given -- no
automatic Balance-Range expansion, previous-week adjustment, or S&R/
swing/session snapping. Both the start and end candle are included
(inclusive-inclusive); the next candle beyond either boundary is
excluded.

V1 INTERPRETATION: no trade signal is generated. Optional descriptive
evidence (price_vs_value_area, nearest_level) is computed from the
RANGE'S OWN last candle close -- never a fresh "live now" price lookup
(that would make the result non-deterministic/non-cacheable and answer a
different question than "what is the profile of the range I selected").

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7z_manual_range_volume_profile_v1.py -v
"""
import calendar
import inspect
from datetime import datetime

import pytest

from core.core_models import CandleSnapshot
from core.strategy.chart_markings import validate_chart_marking
from core.ManualRangeVolumeProfile import build_manual_range_marking, build_manual_range_profile


def _c(price, ts, spread=0.3, v=10.0):
    return CandleSnapshot(open=price, high=price + spread, low=price - spread, close=price, volume=v, timestamp=ts)


class _FakeCandleEngine:
    """Mimics CandleEngine's read paths with a fixed, ordered (oldest-
    first) candle list -- no MT5 involved. get_snapshots_by_range mirrors
    MT5's own copy_rates_range() semantics (inclusive of both endpoints);
    get_snapshots_from_anchor mirrors mt5.copy_rates_from()'s live-
    verified semantics: `count` candles ending at/before the FIXED
    `anchor`, never "now" -- unaffected by any candle appended to
    `_candles` AFTER the anchor (the exact property this fix's stability
    proof depends on)."""
    def __init__(self, candles):
        self._candles = candles

    def get_snapshots(self, symbol, tf, count=100, cache=None):
        if count < len(self._candles):
            return self._candles[-count:]
        return self._candles

    def get_snapshots_by_range(self, symbol, tf, date_from, date_to):
        start_epoch = calendar.timegm(date_from.timetuple())
        end_epoch = calendar.timegm(date_to.timetuple())
        return [c for c in self._candles if start_epoch <= int(c.timestamp) <= end_epoch]

    def get_snapshots_from_anchor(self, symbol, tf, anchor, count):
        anchor_epoch = calendar.timegm(anchor.timetuple())
        eligible = [c for c in self._candles if int(c.timestamp) <= anchor_epoch]
        if count < len(eligible):
            return eligible[-count:]
        return eligible


def _ten_candles():
    """10 candles, epoch timestamps 0,100,...,900 (index i -> ts=100*i),
    each at a distinct price (100+i) so exact inclusion is verifiable."""
    return [_c(100 + i, 100 * i) for i in range(10)]


# ---------------------------------------------------------------------------
# Exact range / inclusivity — timestamp-addressed.
# ---------------------------------------------------------------------------

def test_exact_user_selected_range_by_timestamp():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=300, end_timestamp=700)
    assert result["confirmed"] is True
    assert result["range_type"] == "manual_range"
    assert result["start_timestamp"] == "300"
    assert result["end_timestamp"] == "700"
    # Candles at ts 300,400,500,600,700 (indices 3-7) -> prices 103..107
    assert result["range_high"] == pytest.approx(107.3)
    assert result["range_low"] == pytest.approx(102.7)


def test_first_and_last_candle_included_by_timestamp():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=300, end_timestamp=700)
    # The boundary candles' own high/low (103.3 at start, 107.3 at end)
    # must contribute to range_high/range_low -- proving they're IN.
    assert result["range_low"] == pytest.approx(102.7)  # candle at ts=300 low
    assert result["range_high"] == pytest.approx(107.3)  # candle at ts=700 high


def test_one_candle_outside_each_boundary_excluded_by_timestamp():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=300, end_timestamp=700)
    # Candle at ts=200 (price 102, high 102.3) and ts=800 (price 108, high
    # 108.3) must NOT influence range_high/range_low.
    assert result["range_low"] < 102.3 or result["range_low"] >= 102.7
    assert result["range_high"] <= 107.3
    assert result["range_high"] != pytest.approx(108.3)
    assert result["range_low"] != pytest.approx(101.7)


# ---------------------------------------------------------------------------
# Exact range / inclusivity — index-addressed.
# ---------------------------------------------------------------------------

def test_exact_user_selected_range_by_index_with_stable_reference():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(
        engine, "EURUSD_i", "M15", start_index=3, end_index=7, reference_end_timestamp=900,
    )
    assert result["confirmed"] is True
    assert result["start_index"] == 3
    assert result["end_index"] == 7
    assert result["range_high"] == pytest.approx(107.3)
    assert result["range_low"] == pytest.approx(102.7)


def test_one_candle_outside_each_boundary_excluded_by_index():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(
        engine, "EURUSD_i", "M15", start_index=3, end_index=7, reference_end_timestamp=900,
    )
    assert result["range_high"] != pytest.approx(108.3)  # index 8's high
    assert result["range_low"] != pytest.approx(101.7)   # index 2's low


def test_naked_index_request_rejected_no_stable_reference():
    """The core fix of this follow-up: an index-addressed request with
    NO reference_end_timestamp must never be accepted, since its meaning
    would otherwise silently drift as new candles close."""
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_index=3, end_index=7)
    assert result["confirmed"] is False
    assert result["error"] is not None
    assert "reference_end_timestamp" in result["error"]


# ---------------------------------------------------------------------------
# Rejections.
# ---------------------------------------------------------------------------

def test_start_after_end_rejected_by_timestamp():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=700, end_timestamp=300)
    assert result["confirmed"] is False
    assert result["error"] is not None


def test_start_after_end_rejected_by_index():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(
        engine, "EURUSD_i", "M15", start_index=7, end_index=3, reference_end_timestamp=900,
    )
    assert result["confirmed"] is False


def test_empty_range_rejected():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    # No candle exists between these two timestamps in this fixture.
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=350, end_timestamp=360)
    assert result["confirmed"] is False
    assert result["error"] is not None


def test_missing_range_parameters_rejected():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15")
    assert result["confirmed"] is False


def test_both_timestamp_and_index_given_rejected():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(
        engine, "EURUSD_i", "M15",
        start_timestamp=300, end_timestamp=700, start_index=3, end_index=7,
    )
    assert result["confirmed"] is False


def test_index_beyond_available_history_rejected():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(
        engine, "EURUSD_i", "M15", start_index=3, end_index=99, reference_end_timestamp=900,
    )
    assert result["confirmed"] is False


def test_symbol_timeframe_with_no_candles_rejected():
    engine = _FakeCandleEngine([])  # simulates an unresolvable symbol/timeframe
    result = build_manual_range_profile(engine, "NOPE_i", "M15", start_timestamp=0, end_timestamp=1000)
    assert result["confirmed"] is False
    assert result["error"] is not None


# ---------------------------------------------------------------------------
# POC/VAH/VAL determinism, range_type, source labelling.
# ---------------------------------------------------------------------------

def test_poc_vah_val_deterministic():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    r1 = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=300, end_timestamp=700)
    # Clear the cache key manually is not needed -- same inputs must
    # deterministically reproduce identical output even from cache.
    r2 = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=300, end_timestamp=700)
    assert r1["poc"] == r2["poc"]
    assert r1["vah"] == r2["vah"]
    assert r1["val"] == r2["val"]
    assert r1["val"] <= r1["poc"] <= r1["vah"]


def test_range_type_is_manual_range():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=300, end_timestamp=700)
    assert result["range_type"] == "manual_range"


def test_source_remains_candle_approximation():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=300, end_timestamp=700)
    assert result["source_type"] == "candle_approximation"


def test_output_contract_fields_present():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=300, end_timestamp=700)
    required = (
        "range_type", "symbol", "timeframe", "start_timestamp", "end_timestamp",
        "start_index", "end_index", "range_high", "range_low",
        "poc", "vah", "val", "total_volume", "value_area_pct", "num_bins", "source_type",
    )
    for key in required:
        assert key in result


def test_descriptive_evidence_uses_range_own_last_close_not_live_price():
    """price_vs_value_area/nearest_level must be derivable purely from
    the fetched range candles -- no separate live-price fetch anywhere in
    this function."""
    import core.ManualRangeVolumeProfile as mod
    source = inspect.getsource(mod.build_manual_range_profile)
    assert "last_close = candles[-1].close" in source
    assert "get_snapshots(" not in source or "count=1" not in source  # no separate 1-candle "now" fetch


def test_no_trade_signal_fields_in_result():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=300, end_timestamp=700)
    for forbidden in ("direction", "confidence", "trigger", "reason"):
        assert forbidden not in result


# ---------------------------------------------------------------------------
# No Balance Range / Previous-Week dependency, no StrategyEngine coupling,
# shared VP builder + marking reuse.
# ---------------------------------------------------------------------------

def test_no_balance_range_detector_dependency():
    import core.ManualRangeVolumeProfile as mod
    source = inspect.getsource(mod)
    assert "BalanceRangeEngine" not in source
    assert "detect_balance_range" not in source


def test_no_previous_week_range_dependency():
    import core.ManualRangeVolumeProfile as mod
    source = inspect.getsource(mod)
    assert "get_previous_completed_week_candles" not in source
    assert "get_previous_week_m30_profile" not in source


def test_no_strategy_subclass_defined_here():
    import core.ManualRangeVolumeProfile as mod
    from core.strategy.strategy_models import Strategy
    for _, obj in inspect.getmembers(mod, inspect.isclass):
        assert not (issubclass(obj, Strategy) and obj is not Strategy)


def test_manual_range_volume_profile_never_discovered_as_a_strategy():
    """This fix adds ZERO new strategies. The exact discovery COUNT
    assertion goes stale the moment a later fix adds a real strategy
    (Fix #7AA adds InsideBarBreakoutStrategy) -- this checks only that
    ManualRangeVolumeProfile itself was never discovered, not the total
    count. See test_fix_7aa_inside_bar_breakout_strategy_v1.py for the
    current total-count/full-roster tests."""
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert "ManualRangeVolumeProfile" not in engine.enabled


def test_shared_volume_profile_builder_reused_not_reimplemented():
    import core.ManualRangeVolumeProfile as mod
    source = inspect.getsource(mod)
    assert "from core.VolumeProfileEngine import build_profile_marking, build_volume_profile" in source
    # No second bin-construction loop anywhere in this module.
    assert "bins.append(VolumeProfileBin" not in source
    assert "NUM_BINS" not in source
    assert "VALUE_AREA_PCT" not in source


def test_shared_profile_marking_reused():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=300, end_timestamp=700)
    marking = build_manual_range_marking(result)
    assert marking is not None
    validate_chart_marking(marking)
    assert marking["type"] == "profile"
    assert marking["price"] == result["poc"]
    assert marking["top"] == result["vah"]
    assert marking["bottom"] == result["val"]
    assert marking["evidence_ref"]["range_type"] == "manual_range"
    assert marking["evidence_ref"]["range_high"] == result["range_high"]
    assert marking["evidence_ref"]["range_low"] == result["range_low"]


def test_marking_returns_none_for_unconfirmed_result():
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_timestamp=700, end_timestamp=300)
    assert build_manual_range_marking(result) is None


# ---------------------------------------------------------------------------
# FX / XAU / crypto scale sanity.
# ---------------------------------------------------------------------------

def test_fx_scale_manual_range():
    candles = [_c(1.1000 + i * 0.001, 100 * i, spread=0.0005) for i in range(10)]
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "EURUSD_i", "M15", start_index=2, end_index=7, reference_end_timestamp=900)
    assert result["confirmed"] is True
    assert 1.0990 <= result["poc"] <= 1.1090


def test_xau_scale_manual_range():
    candles = [_c(2000 + i * 2, 100 * i, spread=1.0) for i in range(10)]
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "XAUUSD_i", "M15", start_index=2, end_index=7, reference_end_timestamp=900)
    assert result["confirmed"] is True
    assert 1990 <= result["poc"] <= 2030


def test_crypto_scale_manual_range():
    candles = [_c(30000 + i * 100, 100 * i, spread=50.0) for i in range(10)]
    engine = _FakeCandleEngine(candles)
    result = build_manual_range_profile(engine, "BTCUSD_i", "M15", start_index=2, end_index=7, reference_end_timestamp=900)
    assert result["confirmed"] is True
    assert 29900 <= result["poc"] <= 30800


# ---------------------------------------------------------------------------
# Stable Manual Range identity — the core proof this follow-up fix exists
# to establish: a new candle closing must never change what an existing
# manual range (timestamp- or stable-index-addressed) resolves to.
# ---------------------------------------------------------------------------

def test_timestamp_range_identical_before_and_after_new_candle_closes():
    """The defining guarantee of timestamp-addressed identity: the SAME
    [start_timestamp, end_timestamp] must resolve to the identical
    candles/profile whether or not a new candle has closed since."""
    before_candles = _ten_candles()  # ts 0..900
    after_candles = before_candles + [_c(200, 1000)]  # a new candle closed at ts=1000

    engine_before = _FakeCandleEngine(before_candles)
    engine_after = _FakeCandleEngine(after_candles)

    result_before = build_manual_range_profile(engine_before, "STABLETS_i", "M15", start_timestamp=300, end_timestamp=700)
    result_after = build_manual_range_profile(engine_after, "STABLETS_i", "M15", start_timestamp=300, end_timestamp=700)

    assert result_before["confirmed"] is True
    assert result_before["poc"] == result_after["poc"]
    assert result_before["vah"] == result_after["vah"]
    assert result_before["val"] == result_after["val"]
    assert result_before["range_high"] == result_after["range_high"]
    assert result_before["range_low"] == result_after["range_low"]
    assert result_before["end_timestamp"] == result_after["end_timestamp"]


def test_index_with_stable_reference_identical_before_and_after_new_candle_closes():
    """Same guarantee for the stable-reference index path: the SAME
    (reference_end_timestamp, start_index, end_index) must resolve to
    the identical candles/profile regardless of a newly closed candle
    AFTER the anchor."""
    before_candles = _ten_candles()  # ts 0..900, anchor will be 900
    after_candles = before_candles + [_c(200, 1000)]  # closed AFTER the anchor

    engine_before = _FakeCandleEngine(before_candles)
    engine_after = _FakeCandleEngine(after_candles)

    result_before = build_manual_range_profile(
        engine_before, "STABLEIDX_i", "M15", start_index=3, end_index=7, reference_end_timestamp=900,
    )
    result_after = build_manual_range_profile(
        engine_after, "STABLEIDX_i", "M15", start_index=3, end_index=7, reference_end_timestamp=900,
    )

    assert result_before["confirmed"] is True
    assert result_before["poc"] == result_after["poc"]
    assert result_before["vah"] == result_after["vah"]
    assert result_before["val"] == result_after["val"]
    assert result_before["range_high"] == result_after["range_high"]
    assert result_before["range_low"] == result_after["range_low"]


def test_timestamp_cache_remains_valid_after_new_candle_closes():
    """The in-process cache for a timestamp-addressed range must keep
    serving the correct, unchanged result even after a new candle closes
    -- the cached entry was never invalidated because it never needed to
    be (the underlying historical candles are immutable)."""
    candles = _ten_candles()
    engine = _FakeCandleEngine(candles)
    first = build_manual_range_profile(engine, "CACHEVALID_i", "M15", start_timestamp=300, end_timestamp=700)

    # Simulate a new candle closing -- engine now serves more data, but
    # the SAME cached range must still be returned unchanged.
    engine._candles = candles + [_c(999, 1000)]
    second = build_manual_range_profile(engine, "CACHEVALID_i", "M15", start_timestamp=300, end_timestamp=700)

    assert first == second


def test_no_index_drift_in_public_contract():
    """API-contract-level proof: the Pydantic request model itself
    requires reference_end_timestamp alongside any index pair, and the
    route passes it straight through -- a naked index request can never
    reach MT5 as if it were meaningful."""
    import inspect as _inspect
    import api.core_router as router_mod
    source = _inspect.getsource(router_mod.ManualRangeVolumeProfileRequest)
    assert "reference_end_timestamp" in source
    route_source = _inspect.getsource(router_mod.get_manual_range_volume_profile)
    assert "reference_end_timestamp=body.reference_end_timestamp" in route_source


# ---------------------------------------------------------------------------
# #7X / #7Y regressions unchanged (run alongside this file too, but a
# direct smoke check here confirms no accidental cross-import coupling).
# ---------------------------------------------------------------------------

def test_no_import_coupling_with_fix_7x_or_7y_strategies():
    import core.ManualRangeVolumeProfile as mod
    source = inspect.getsource(mod)
    assert "VolumeProfileWeeklyReactionStrategy" not in source
    assert "BalanceRangeVAHVALReactionStrategy" not in source
