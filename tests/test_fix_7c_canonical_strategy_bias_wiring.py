"""Fix #7C — wired StructureSnapshot.bias (and therefore StrategySnapshot.bias,
via StrategyEngine.to_strategy_snapshot()'s straight copy) to the real
canonical bias BiasEngine.evaluate_bias() already computes for every
symbol/timeframe, instead of the dataclass default "Neutral" it was
permanently stuck at (Fix #7B's audit).

Traced the exact path:
  BiasEngine.evaluate_bias() -> BiasEngine.get_bias_map() -> Output.py's
  bias_map -> (NEW) Output.py._build_symbol_snapshot() sets
  structure_map[tf].bias = _canonical_structure_bias(bias_map[tf]["bias_label"])
  -> StructureSnapshot.bias -> StrategyEngine.to_strategy_snapshot() ->
  StrategySnapshot.bias -> every Strategy plugin's .bias reads.

Wiring point chosen deliberately: NOT inside StructureEngine.get_snapshot()
(which has zero BiasEngine dependency today -- adding one would create a
cycle, since BiasEngine already depends on StructureEngine via
_resolve_structure()). Output.py's _build_symbol_snapshot() already
orchestrates both engines sequentially and already has bias_map and
structure_map both in hand at the same point -- no new engine call, no
new candle fetch, no new formula, just a vocabulary mapping
("uptrend"/"downtrend"/"neutral" -> "Bullish"/"Bearish"/"Neutral") that
mirrors the exact inverse of what BiasEngine.evaluate_bias() itself
already does internally.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7c_canonical_strategy_bias_wiring.py -v
"""
import copy

import api.core_router as cr
from core.candle_cache import CandleCache
from core.CandleEngine import CandleEngine
from core.SnapshotCache import snapshot_cache
import core.Output.Output as out_mod
from mt5.constants import TIMEFRAMES


SYMBOLS_SAMPLE = [
    "EURUSD_i", "GBPUSD_i", "USDJPY_i", "XAUUSD_i", "BTCUSD_i", "AUDUSD_i",
    "NZDUSD_i", "GBPJPY_i", "EURJPY_i", "XAGUSD_i", "ETHUSD_i", "XTIUSD_i",
    "AUDCAD_i", "AUDCHF_i", "AUDJPY_i", "AUDNZD_i", "CADCHF_i", "CADJPY_i",
    "CHFJPY_i", "EURAUD_i",
]


# ---------------------------------------------------------------------------
# Mapping helper itself.
# ---------------------------------------------------------------------------

def test_canonical_structure_bias_mapping():
    assert out_mod._canonical_structure_bias("uptrend") == "Bullish"
    assert out_mod._canonical_structure_bias("downtrend") == "Bearish"
    assert out_mod._canonical_structure_bias("neutral") == "Neutral"
    assert out_mod._canonical_structure_bias("anything_unrecognized") == "Neutral"
    assert out_mod._canonical_structure_bias(None) == "Neutral"


# ---------------------------------------------------------------------------
# StructureSnapshot.bias is no longer permanently Neutral once routed
# through Output.py's assembly (the path Strategy actually uses).
# ---------------------------------------------------------------------------

def test_live_strategy_snapshot_bias_no_longer_permanently_neutral():
    from collections import Counter

    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(SYMBOLS_SAMPLE, TIMEFRAMES, count=100)

    captured = []
    original_to_strategy_snapshot = out_mod.to_strategy_snapshot

    def spy(structure):
        snap = original_to_strategy_snapshot(structure)
        captured.append(snap.bias)
        return snap

    out_mod.to_strategy_snapshot = spy
    try:
        for symbol in SYMBOLS_SAMPLE:
            snapshot_cache.clear()
            out_mod._build_symbol_snapshot(
                symbol, {}, cr.bias_engine, cr.candle_engine, cr.momentum_engine, cr.demand_engine,
                cr.structure_engine, cr.shift_engine, cache=cache,
            )
    finally:
        out_mod.to_strategy_snapshot = original_to_strategy_snapshot

    counts = Counter(captured)
    assert len(captured) > 0
    assert set(counts.keys()) <= {"Bullish", "Bearish", "Neutral"}
    # The whole point of this fix: not EVERY value is "Neutral" any more.
    assert counts["Bullish"] > 0 or counts["Bearish"] > 0, (
        f"expected at least some non-Neutral bias across a {len(captured)}-sample "
        f"live sweep, got only: {counts}"
    )


# ---------------------------------------------------------------------------
# Bullish/Bearish canonical bias propagates correctly; Neutral still
# propagates when genuinely Neutral -- using synthetic, deterministic
# BiasEngine.evaluate_bias() inputs to remove live-market dependence.
# ---------------------------------------------------------------------------

def _make_bullish_structure_snapshot():
    from core.core_models import StructureSnapshot
    snap = StructureSnapshot(
        symbol="T", timeframe="M15", current_high=1.0, current_low=0.9,
        prev_high=1.0, prev_low=0.9, current_zone="Neutral", prev_zone="Neutral",
    )
    snap.structure_type = "CHOCH"
    snap.structure_direction = "Bullish"
    snap.structure_valid = True
    return snap


def _make_bearish_structure_snapshot():
    from core.core_models import StructureSnapshot
    snap = StructureSnapshot(
        symbol="T", timeframe="M15", current_high=1.0, current_low=0.9,
        prev_high=1.0, prev_low=0.9, current_zone="Neutral", prev_zone="Neutral",
    )
    snap.structure_type = "CHOCH"
    snap.structure_direction = "Bearish"
    snap.structure_valid = True
    return snap


def _make_neutral_structure_snapshot():
    from core.core_models import StructureSnapshot
    snap = StructureSnapshot(
        symbol="T", timeframe="M15", current_high=1.0, current_low=0.9,
        prev_high=1.0, prev_low=0.9, current_zone="Neutral", prev_zone="Neutral",
    )
    snap.structure_type = "None"
    snap.structure_direction = "Neutral"
    snap.structure_valid = False
    return snap


def _dummy_candles(n=3):
    from core.core_models import CandleSnapshot
    return [
        CandleSnapshot(open=1.0, high=1.01, low=0.99, close=1.0, volume=100, timestamp=str(i))
        for i in range(n)
    ]


def test_bullish_canonical_bias_propagates_to_structure_and_strategy_snapshot():
    from core.BiasEngine import BiasEngine
    structure = _make_bullish_structure_snapshot()
    bias_label, _ = BiasEngine.evaluate_bias(
        BiasEngine.__new__(BiasEngine), candles=_dummy_candles(), structure_snapshot=structure,
    )
    # CHoCH always confirms regardless of pre_break_trend -> "uptrend"
    assert bias_label == "uptrend"
    structure.bias = out_mod._canonical_structure_bias(bias_label)
    assert structure.bias == "Bullish"

    strategy_snap = out_mod.to_strategy_snapshot(structure)
    assert strategy_snap.bias == "Bullish"


def test_bearish_canonical_bias_propagates_to_structure_and_strategy_snapshot():
    from core.BiasEngine import BiasEngine
    structure = _make_bearish_structure_snapshot()
    bias_label, _ = BiasEngine.evaluate_bias(
        BiasEngine.__new__(BiasEngine), candles=_dummy_candles(), structure_snapshot=structure,
    )
    assert bias_label == "downtrend"
    structure.bias = out_mod._canonical_structure_bias(bias_label)
    assert structure.bias == "Bearish"

    strategy_snap = out_mod.to_strategy_snapshot(structure)
    assert strategy_snap.bias == "Bearish"


def test_neutral_bias_still_propagates_as_neutral():
    from core.BiasEngine import BiasEngine
    structure = _make_neutral_structure_snapshot()
    # No confirmed structure event and no candles -> evaluate_bias()'s own
    # early-return path.
    bias_label, _ = BiasEngine.evaluate_bias(BiasEngine.__new__(BiasEngine), candles=[], structure_snapshot=structure)
    assert bias_label == "neutral"
    structure.bias = out_mod._canonical_structure_bias(bias_label)
    assert structure.bias == "Neutral"

    strategy_snap = out_mod.to_strategy_snapshot(structure)
    assert strategy_snap.bias == "Neutral"


# ---------------------------------------------------------------------------
# Affected Strategy plugins can now actually reach their .bias-gated logic.
# ---------------------------------------------------------------------------

def test_bias_continuation_scalping_strategy_can_now_pass_the_bias_gate():
    from datetime import datetime, timezone
    from core.strategy.BiasContinuationScalpingStrategy import BiasContinuationScalpingStrategy
    from core.strategy.strategy_models import StrategySnapshot

    def snap(**overrides):
        base = dict(
            symbol="T", timeframe="M5", bias="Bullish", momentum=1.0, strength=1.0,
            suppression=False, suppression_reason="", structure_type="BOS",
            structure_direction="Bullish", structure_valid=True, context_zone="demand",
            context_level=None, timestamp=datetime.now(timezone.utc),
            current_high=1.10, current_low=1.09, atr_normalized_momentum=1.0,
        )
        base.update(overrides)
        return StrategySnapshot(**base)

    anchor_h1 = snap(timeframe="H1", bias="Bullish")
    anchor_h4 = snap(timeframe="H4", bias="Bullish")
    trigger = snap(timeframe="M5", bias="Bullish")
    context = {"T_H1": anchor_h1, "T_H4": anchor_h4}

    strat = BiasContinuationScalpingStrategy()
    signal = strat.react(trigger, context)
    assert signal is not None
    assert signal["direction"] == "long"


def test_scalping_bias_cascade_can_now_pass_the_bias_gate():
    from datetime import datetime, timezone
    from core.strategy.ScalpingBiasCascade import ScalpingBiasCascade
    from core.strategy.strategy_models import StrategySnapshot

    def snap(**overrides):
        base = dict(
            symbol="T", timeframe="M15", bias="Bearish", momentum=1.0, strength=1.0,
            suppression=False, suppression_reason="", structure_type="CHOCH",
            structure_direction="Bearish", structure_valid=True, context_zone="neutral",
            context_level=None, timestamp=datetime.now(timezone.utc),
            current_high=1.10, current_low=1.09, atr_normalized_momentum=-1.0,
        )
        base.update(overrides)
        return StrategySnapshot(**base)

    trigger = snap(timeframe="M15", bias="Bearish", structure_type="CHOCH")
    context = {
        "T_M1": snap(timeframe="M1", bias="Bullish", suppression=False),  # opposite of the aligned bias -> flip
        "T_M15": snap(timeframe="M15", bias="Bearish"),
        "T_M30": snap(timeframe="M30", bias="Bearish"),
        "T_H1": snap(timeframe="H1", bias="Bearish"),
    }

    strat = ScalpingBiasCascade()
    signal = strat.react(trigger, context)
    assert signal is not None
    assert signal["direction"] == "long"  # Bearish alignment + Bullish M1 flip -> trade long


# ---------------------------------------------------------------------------
# No V12-core semantic change: /core/output is byte-identical whether the
# new wiring runs or is disabled, on identical cached candle data.
# ---------------------------------------------------------------------------

def test_no_v12_core_output_change_from_bias_wiring():
    symbols = ["XAUUSD_i", "EURUSD_i", "BTCUSD_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, TIMEFRAMES, count=100)

    def reset_state():
        snapshot_cache.clear()
        cr.shift_engine.current_shift_direction.clear()
        cr.shift_engine.last_shift_change.clear()

    def strip_volatile(block):
        b = copy.deepcopy(block)
        b.pop("last_updated", None)
        for section in ("scalping", "swing"):
            for tf, v in b.get(section, {}).items():
                if isinstance(v, dict):
                    v.pop("duration", None)
        return b

    reset_state()
    after = out_mod.build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=symbols,
    )
    after = {s: strip_volatile(after[s]) for s in symbols}

    original_mapping = out_mod._canonical_structure_bias
    out_mod._canonical_structure_bias = lambda bias_label: "Neutral"  # simulate pre-fix (always default)
    try:
        reset_state()
        before = out_mod.build_multi_symbol_output(
            bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
            demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
            cache=cache, symbols=symbols,
        )
        before = {s: strip_volatile(before[s]) for s in symbols}
    finally:
        out_mod._canonical_structure_bias = original_mapping

    assert before == after


# ---------------------------------------------------------------------------
# No extra MT5 fetch: the wiring reuses bias_map/structure_map already
# computed, introducing zero new CandleEngine.get_snapshots() calls beyond
# the initial CandleCache batch.
#
# Fix #7X — one new, deliberate, DIFFERENT exception is now expected: a
# single (symbol, "M30") direct fetch from VolumeProfileEngine.
# get_previous_week_m30_profile(), called once per symbol from Output.py
# (unrelated to bias wiring). This fetch is intentionally NOT routed
# through the shared CandleCache — that cache is keyed by (symbol, tf)
# only and stores whatever count fetch_all() was called with (100 here),
# which is nowhere near enough for a previous-completed-week M30 profile
# (needs ~600 to safely span 2+ weeks); reusing it would silently return
# only 100 candles with no error. See VolumeProfileEngine's own module
# docstring for the full audit. This test still asserts no OTHER, still-
# unexpected fetch occurs beyond that one documented exception -- the
# original guarantee for BIAS wiring specifically is unchanged.
# ---------------------------------------------------------------------------

def test_no_extra_fetch_from_bias_wiring():
    symbol = "XAUUSD_i"
    fetch_calls = []
    original_get_snapshots = CandleEngine.get_snapshots

    def spy_get_snapshots(self, symbol, tf, count=100, cache=None):
        if cache is None:
            fetch_calls.append((symbol, tf))
        return original_get_snapshots(self, symbol, tf, count=count, cache=cache)

    CandleEngine.get_snapshots = spy_get_snapshots
    try:
        snapshot_cache.clear()
        cr.shift_engine.current_shift_direction.clear()
        cr.shift_engine.last_shift_change.clear()
        cache = CandleCache(cr.candle_engine)
        cache.fetch_all([symbol], TIMEFRAMES, count=100)
        fetch_calls.clear()
        out_mod.build_multi_symbol_output(
            bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
            demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
            cache=cache, symbols=[symbol],
        )
        # Fix #7X's own explicit, bounded, documented VolumeProfileEngine
        # fetch is the ONLY exception permitted here.
        assert fetch_calls == [(symbol, "M30")]
    finally:
        CandleEngine.get_snapshots = original_get_snapshots


# ---------------------------------------------------------------------------
# No circular dependency: StructureEngine.get_snapshot() still never
# assigns .bias itself and has no BiasEngine coupling.
# ---------------------------------------------------------------------------

def test_structure_engine_itself_still_never_sets_bias_no_new_coupling():
    import inspect
    from core.StructureEngine import StructureEngine
    source = inspect.getsource(StructureEngine)
    assert "BiasEngine" not in source
    assert ".bias =" not in source
    assert ".bias=" not in source

    # Calling StructureEngine directly (bypassing Output.py) still shows
    # the untouched dataclass default -- proves the wiring lives solely at
    # the Output.py assembly layer, not inside StructureEngine itself.
    structure = cr.structure_engine.get_snapshot("EURUSD_i", "M15")
    if structure is not None:
        assert structure.bias == "Neutral"


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
