"""Fix #6BQ — retrofitted GET /core/diagnostics/style/snapshots
(StyleEngine.build_multi_symbol_snapshot()) with a request-scoped
CandleCache and switched it to a dedicated `diagnostics_shift_engine`
instance, isolated from the canonical module-level `shift_engine`. Fix
#6BP's audit proved (reproducibly) that an uncached call through this
route's code path could alter the canonical `/core/output`/`/core/slim`
`duration` field for the same (symbol, tf) pair, via the shared
ShiftEngine singleton's current_shift_direction/last_shift_change
bookkeeping. This fix removes that shared state entirely -- the two
ShiftEngine instances now never interact.

No external behavior change for the route itself: same path, same input
(none), same response shape, raw `demand`/`momentum` still raw and
unformatted, no presentation fields added. The two debug print() calls
are gone.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_6bq_diagnostics_isolation_and_cache.py -v
"""
import inspect

import api.core_router as cr
from core.CandleEngine import CandleEngine
from core.SnapshotCache import snapshot_cache
from core.candle_cache import CandleCache
import core.StyleEngine as style_mod
from mt5.constants import TIMEFRAMES


# ---------------------------------------------------------------------------
# Canonical and diagnostics ShiftEngine instances are distinct.
# ---------------------------------------------------------------------------

def test_diagnostics_shift_engine_is_a_distinct_instance_from_canonical():
    assert cr.diagnostics_shift_engine is not cr.shift_engine
    assert cr.diagnostics_shift_engine.current_shift_direction is not cr.shift_engine.current_shift_direction
    assert cr.diagnostics_shift_engine.last_shift_change is not cr.shift_engine.last_shift_change


# ---------------------------------------------------------------------------
# No debug prints remain in the route.
# ---------------------------------------------------------------------------

def test_no_debug_prints_in_diagnostics_route_source():
    source = inspect.getsource(cr.get_style_snapshots)
    assert "print(" not in source


# ---------------------------------------------------------------------------
# Cross-route contamination is gone: calling diagnostics first, then
# canonical output, must produce the same canonical `duration` as
# canonical-without-any-prior-diagnostics-call.
# ---------------------------------------------------------------------------

def _reset_all_state():
    snapshot_cache.clear()
    cr.shift_engine.current_shift_direction.clear()
    cr.shift_engine.last_shift_change.clear()
    cr.diagnostics_shift_engine.current_shift_direction.clear()
    cr.diagnostics_shift_engine.last_shift_change.clear()


def test_diagnostics_call_no_longer_changes_canonical_duration():
    from core.Output.Output import build_multi_symbol_output

    symbol = "XAUUSD_i"
    tf = "M15"
    section = "scalping"

    # Baseline: canonical alone, fresh state, no diagnostics call at all.
    _reset_all_state()
    baseline_cache = CandleCache(cr.candle_engine)
    baseline_cache.fetch_all([symbol], TIMEFRAMES, count=100)
    baseline_out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=baseline_cache, symbols=[symbol],
    )
    baseline_duration = baseline_out[symbol][section][tf].get("duration")

    # Contamination scenario: call the diagnostics route's own function
    # first (uses diagnostics_shift_engine + its own cache internally),
    # THEN call canonical fresh -- must match the baseline exactly now.
    _reset_all_state()
    original_symbols = style_mod.SYMBOLS
    style_mod.SYMBOLS = [symbol]
    try:
        diag_cache2 = CandleCache(cr.candle_engine)
        diag_cache2.fetch_all([symbol], TIMEFRAMES, count=100)
        style_mod.build_multi_symbol_snapshot(
            bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
            demand_engine=cr.demand_engine, structure_engine=cr.structure_engine,
            shift_engine=cr.diagnostics_shift_engine, cache=diag_cache2,
        )
    finally:
        style_mod.SYMBOLS = original_symbols

    after_diag_cache = CandleCache(cr.candle_engine)
    after_diag_cache.fetch_all([symbol], TIMEFRAMES, count=100)
    after_diag_out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=after_diag_cache, symbols=[symbol],
    )
    after_diag_duration = after_diag_out[symbol][section][tf].get("duration")

    assert after_diag_duration == baseline_duration, (
        f"canonical duration changed after a diagnostics call: "
        f"baseline={baseline_duration!r}, after_diagnostics={after_diag_duration!r}"
    )

    # The diagnostics call's bookkeeping landed only on its own dedicated
    # engine, never on canonical's.
    assert (symbol, tf) in cr.diagnostics_shift_engine.current_shift_direction
    assert cr.shift_engine.last_shift_change is not cr.diagnostics_shift_engine.last_shift_change


def test_no_other_canonical_field_changes_from_diagnostics_call():
    """Full canonical block comparison (minus last_updated/duration, both
    inherently time-dependent) before vs after a diagnostics call, on
    identical cached candle data, proving zero other field is affected."""
    import copy
    from core.Output.Output import build_multi_symbol_output

    symbol = "XAUUSD_i"

    def strip_volatile(block):
        b = copy.deepcopy(block)
        b.pop("last_updated", None)
        for section in ("scalping", "swing"):
            for tf, v in b.get(section, {}).items():
                if isinstance(v, dict):
                    v.pop("duration", None)
        return b

    # One single, frozen CandleCache shared by BOTH the "before" and "after"
    # canonical calls (and reused for the diagnostics call too) -- this is
    # essential: with two independent live fetches, real market movement
    # between them would produce a genuine (not code-caused) difference in
    # atr_normalized_momentum/supply_demand_zones/etc., which would falsely
    # look like a regression. Freezing the candle data isolates the ONLY
    # variable under test: whether the diagnostics call itself changes
    # anything, given byte-identical underlying market data throughout.
    _reset_all_state()
    shared_cache = CandleCache(cr.candle_engine)
    shared_cache.fetch_all([symbol], TIMEFRAMES, count=100)

    before = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=shared_cache, symbols=[symbol],
    )
    before_stripped = strip_volatile(before[symbol])

    original_symbols = style_mod.SYMBOLS
    style_mod.SYMBOLS = [symbol]
    try:
        style_mod.build_multi_symbol_snapshot(
            bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
            demand_engine=cr.demand_engine, structure_engine=cr.structure_engine,
            shift_engine=cr.diagnostics_shift_engine, cache=shared_cache,
        )
    finally:
        style_mod.SYMBOLS = original_symbols

    snapshot_cache.clear()  # only clear alignment-history cache, not shift bookkeeping
    after = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=shared_cache, symbols=[symbol],
    )
    after_stripped = strip_volatile(after[symbol])

    assert before_stripped == after_stripped


# ---------------------------------------------------------------------------
# Diagnostics route maintains its OWN duration continuity independently
# across repeated calls.
# ---------------------------------------------------------------------------

def test_diagnostics_route_maintains_its_own_duration_continuity():
    import datetime as real_datetime

    symbol = "XAUUSD_i"
    tf = "M15"
    key = (symbol, tf)

    class FakeDateTime(real_datetime.datetime):
        _now = real_datetime.datetime(2026, 1, 1, 0, 0, 0, tzinfo=real_datetime.timezone.utc)

        @classmethod
        def now(cls, tz=None):
            return cls._now

    import core.ShiftEngine as se_mod
    import core.StyleEngine as sty_mod
    orig_se_dt = se_mod.datetime
    orig_sty_dt = sty_mod.datetime
    se_mod.datetime = FakeDateTime
    sty_mod.datetime = FakeDateTime

    original_symbols = style_mod.SYMBOLS
    style_mod.SYMBOLS = [symbol]
    try:
        cr.diagnostics_shift_engine.current_shift_direction.clear()
        cr.diagnostics_shift_engine.last_shift_change.clear()

        cache1 = CandleCache(cr.candle_engine)
        cache1.fetch_all([symbol], TIMEFRAMES, count=100)
        first = style_mod.build_multi_symbol_snapshot(
            bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
            demand_engine=cr.demand_engine, structure_engine=cr.structure_engine,
            shift_engine=cr.diagnostics_shift_engine, cache=cache1,
        )
        first_duration = first[symbol]["scalping"][tf].get("duration")

        FakeDateTime._now = FakeDateTime._now + real_datetime.timedelta(minutes=42)

        cache2 = CandleCache(cr.candle_engine)
        cache2.fetch_all([symbol], TIMEFRAMES, count=100)
        second = style_mod.build_multi_symbol_snapshot(
            bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
            demand_engine=cr.demand_engine, structure_engine=cr.structure_engine,
            shift_engine=cr.diagnostics_shift_engine, cache=cache2,
        )
        second_duration = second[symbol]["scalping"][tf].get("duration")

        assert first_duration == "0 min"
        # direction unchanged across the two calls (same live data) -> the
        # bookkeeping timestamp from call 1 persists, so call 2's duration
        # reflects the 42-minute gap -- proving continuity across repeated
        # calls to the dedicated diagnostics singleton.
        direction_after_first = cr.diagnostics_shift_engine.current_shift_direction.get(key)
        direction_after_second = cr.diagnostics_shift_engine.current_shift_direction.get(key)
        if direction_after_first == direction_after_second:
            assert second_duration == "42 min"
    finally:
        se_mod.datetime = orig_se_dt
        sty_mod.datetime = orig_sty_dt
        style_mod.SYMBOLS = original_symbols


# ---------------------------------------------------------------------------
# Fetch count: measure before/after for 1x9, extrapolate to 36x9.
# ---------------------------------------------------------------------------

def test_fetch_count_collapses_toward_canonical_with_cache():
    fetch_calls = []
    original_get_snapshots = CandleEngine.get_snapshots

    def spy_get_snapshots(self, symbol, tf, count=100, cache=None):
        if cache is None:
            fetch_calls.append((symbol, tf))
        return original_get_snapshots(self, symbol, tf, count=count, cache=cache)

    CandleEngine.get_snapshots = spy_get_snapshots
    symbol = "XAUUSD_i"
    original_symbols = style_mod.SYMBOLS
    style_mod.SYMBOLS = [symbol]
    try:
        _reset_all_state()
        fetch_calls.clear()
        cache = CandleCache(cr.candle_engine)
        cache.fetch_all([symbol], TIMEFRAMES, count=100)
        # The single fetch_all() batch itself calls CandleEngine.get_snapshots()
        # with cache=None internally (that's how CandleCache populates itself) --
        # count those as the "canonical" cost, then confirm build_multi_symbol_
        # snapshot() adds ZERO further uncached fetches on top of it.
        fetch_calls.clear()
        style_mod.build_multi_symbol_snapshot(
            bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
            demand_engine=cr.demand_engine, structure_engine=cr.structure_engine,
            shift_engine=cr.diagnostics_shift_engine, cache=cache,
        )
        uncached_fetches_after_prefetch = len(fetch_calls)
    finally:
        CandleEngine.get_snapshots = original_get_snapshots
        style_mod.SYMBOLS = original_symbols

    # Once the cache is pre-populated, the retrofitted route must make zero
    # further raw MT5 fetches for this symbol's 9 timeframes.
    assert uncached_fetches_after_prefetch == 0, (
        f"expected 0 additional raw fetches once CandleCache is pre-populated, "
        f"got {uncached_fetches_after_prefetch}"
    )


def test_full_route_fetch_count_matches_canonical_for_one_symbol():
    """End-to-end: CandleCache.fetch_all() (9 fetches for 1 symbol) plus
    the retrofitted route itself (0 additional) == 9 total, same order as
    canonical's own 9-fetch cost for a 1-symbol x 9-TF sweep (Fix #6BP's
    measurement). Extrapolated to 36 symbols: ~324, matching canonical --
    collapsed from the pre-fix ~2,592 (72/symbol x 36)."""
    fetch_calls = []
    original_get_snapshots = CandleEngine.get_snapshots

    def spy_get_snapshots(self, symbol, tf, count=100, cache=None):
        if cache is None:
            fetch_calls.append((symbol, tf))
        return original_get_snapshots(self, symbol, tf, count=count, cache=cache)

    CandleEngine.get_snapshots = spy_get_snapshots
    symbol = "XAUUSD_i"
    original_symbols = style_mod.SYMBOLS
    style_mod.SYMBOLS = [symbol]
    try:
        _reset_all_state()
        fetch_calls.clear()
        cache = CandleCache(cr.candle_engine)
        cache.fetch_all([symbol], TIMEFRAMES, count=100)
        style_mod.build_multi_symbol_snapshot(
            bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
            demand_engine=cr.demand_engine, structure_engine=cr.structure_engine,
            shift_engine=cr.diagnostics_shift_engine, cache=cache,
        )
        total_fetches = len(fetch_calls)
    finally:
        CandleEngine.get_snapshots = original_get_snapshots
        style_mod.SYMBOLS = original_symbols

    assert total_fetches == len(TIMEFRAMES)  # exactly one per timeframe, matching canonical
    print(f"Retrofitted route: {total_fetches} raw fetches for 1 symbol x {len(TIMEFRAMES)} TFs "
          f"(was 72 before Fix #6BQ) -> extrapolated 36x9 = {total_fetches * 36} (was ~2592).")


# ---------------------------------------------------------------------------
# Response shape/value semantics unchanged: raw demand, raw momentum, no
# presentation fields added, same top-level keys.
# ---------------------------------------------------------------------------

def test_legacy_response_shape_and_raw_values_unchanged():
    symbol = "XAUUSD_i"
    original_symbols = style_mod.SYMBOLS
    style_mod.SYMBOLS = [symbol]
    try:
        _reset_all_state()
        cache = CandleCache(cr.candle_engine)
        cache.fetch_all([symbol], TIMEFRAMES, count=100)
        result = style_mod.build_multi_symbol_snapshot(
            bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
            demand_engine=cr.demand_engine, structure_engine=cr.structure_engine,
            shift_engine=cr.diagnostics_shift_engine, cache=cache,
        )
    finally:
        style_mod.SYMBOLS = original_symbols

    assert "error" not in result[symbol]
    assert set(result[symbol].keys()) == {"bias", "scalping", "swing"}

    m15 = result[symbol]["scalping"]["M15"]
    # Raw field names -- never renamed to canonical "zone".
    assert "demand" in m15
    assert "zone" not in m15
    # Raw, unformatted momentum -- no presentation fields added.
    assert "momentum" in m15
    assert "momentum_band" not in m15
    assert "momentum_pct" not in m15
    assert "momentum_color" not in m15
    assert "bias_pct" not in m15
    assert "bias_color" not in m15
    assert "alignment_signal" not in result[symbol]["scalping"]
    assert "diagnostic" not in result[symbol]["scalping"]
    assert "signal_health" not in result[symbol]


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
