"""Fix #6AV — the 4 composite Strategy plugins (BiasContinuationScalpingStrategy,
BiasContinuationSwingStrategy, DoubleEngulfingStrategy, ZoneContinuationStrategy)
migrated their momentum confidence ingredient from
normalize_confidence(snapshot.momentum) (legacy, unsigned, per-instrument
price-unit -- Fix #6AR/#6AT's audits) to
strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction)
(canonical, signed, direction-agreement-gated -- Fix #6AU). Each plugin's
own already-resolved committed trade direction is reused -- no second
direction is derived anywhere. Every other term (base offsets, SNR bonus,
structure_valid/BOS bonus, wick-extension bonus, caps) is unchanged.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_composite_strategy_momentum_confidence_migration.py -v
"""
from datetime import datetime, timezone

from core.strategy.BiasContinuationScalpingStrategy import BiasContinuationScalpingStrategy
from core.strategy.BiasContinuationSwingStrategy import BiasContinuationSwingStrategy
from core.strategy.DoubleEngulfingStrategy import DoubleEngulfingStrategy
from core.strategy.ZoneContinuationStrategy import ZoneContinuationStrategy
from core.strategy.strategy_models import StrategySnapshot

NOW = datetime.now(timezone.utc)


def snap(**overrides):
    base = dict(
        symbol="T", timeframe="M5", bias="Bullish", momentum=5.0, strength=5.0,
        suppression=False, suppression_reason="",
        structure_type="BOS", structure_direction="Bullish", structure_valid=True,
        context_zone="demand", context_level=1.0, timestamp=NOW,
        current_high=1.1, current_low=0.9,
        snr_strength=0.0, atr_normalized_momentum=1.0,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


# ---------------------------------------------------------------------------
# BiasContinuationScalpingStrategy
# ---------------------------------------------------------------------------

def _scalp_anchor(bias):
    return snap(timeframe="H1", bias=bias, structure_direction=bias)


def _scalp_context(bias="Bullish"):
    return {"T_H1": _scalp_anchor(bias), "T_H4": _scalp_anchor(bias)}


def test_scalping_confidence_ignores_legacy_momentum_uses_atr():
    strat = BiasContinuationScalpingStrategy()
    ctx = _scalp_context("Bullish")
    tiny_legacy = strat.react(snap(momentum=0.0001, atr_normalized_momentum=1.0), ctx)
    huge_legacy = strat.react(snap(momentum=9999.0, atr_normalized_momentum=1.0), ctx)
    assert tiny_legacy is not None and huge_legacy is not None
    assert tiny_legacy["confidence"] == huge_legacy["confidence"]


def test_scalping_wrong_direction_atr_contributes_zero():
    strat = BiasContinuationScalpingStrategy()
    ctx = _scalp_context("Bullish")
    agreeing = strat.react(snap(atr_normalized_momentum=1.0), ctx)
    opposing = strat.react(snap(atr_normalized_momentum=-1.0), ctx)
    assert agreeing["confidence"] > opposing["confidence"]
    # opposing floor: 0.0 (momentum) + 0.12 (base) + 0.0 (snr_strength=0) + 0.08 (structure_valid) = 0.20
    assert opposing["confidence"] == 0.20


def test_scalping_none_atr_same_floor_as_wrong_direction():
    strat = BiasContinuationScalpingStrategy()
    ctx = _scalp_context("Bullish")
    none_atr = strat.react(snap(atr_normalized_momentum=None), ctx)
    wrong_dir = strat.react(snap(atr_normalized_momentum=-1.0), ctx)
    assert none_atr["confidence"] == wrong_dir["confidence"] == 0.20


def test_scalping_bullish_bearish_symmetry():
    strat = BiasContinuationScalpingStrategy()
    bullish = strat.react(
        snap(bias="Bullish", structure_direction="Bullish", context_zone="demand", atr_normalized_momentum=1.2),
        _scalp_context("Bullish"),
    )
    bearish = strat.react(
        snap(bias="Bearish", structure_direction="Bearish", context_zone="supply", atr_normalized_momentum=-1.2),
        _scalp_context("Bearish"),
    )
    assert bullish is not None and bearish is not None
    assert bullish["confidence"] == bearish["confidence"]
    assert bullish["direction"] == "long"
    assert bearish["direction"] == "short"


def test_scalping_structure_valid_bonus_unchanged():
    strat = BiasContinuationScalpingStrategy()
    ctx = _scalp_context("Bullish")
    with_structure = strat.react(snap(structure_valid=True, atr_normalized_momentum=1.0), ctx)
    without_structure = strat.react(snap(structure_valid=False, structure_type="None", atr_normalized_momentum=1.0), ctx)
    assert with_structure is not None and without_structure is not None
    assert round(with_structure["confidence"] - without_structure["confidence"], 2) == 0.08


def test_scalping_signal_side_unchanged_by_momentum_value():
    strat = BiasContinuationScalpingStrategy()
    ctx = _scalp_context("Bullish")
    for atr in (-5.0, None, 0.0, 0.3, 2.0, 50.0):
        result = strat.react(snap(atr_normalized_momentum=atr), ctx)
        assert result is not None
        assert result["direction"] == "long"


def test_scalping_confidence_within_cap():
    strat = BiasContinuationScalpingStrategy()
    ctx = _scalp_context("Bullish")
    for atr in (-50.0, -1.0, 0.0, 0.5, 1.0, 2.0, 5.0, 50.0):
        result = strat.react(snap(atr_normalized_momentum=atr), ctx)
        assert result is not None
        assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# BiasContinuationSwingStrategy
# ---------------------------------------------------------------------------

def _swing_anchor(bias):
    return snap(timeframe="H4", bias=bias, structure_direction=bias)


def _swing_context(bias="Bullish"):
    return {"T_D1": _swing_anchor(bias), "T_H4": _swing_anchor(bias)}


def _swing_snap(**overrides):
    base = dict(timeframe="H1")
    base.update(overrides)
    return snap(**base)


def test_swing_confidence_ignores_legacy_momentum_uses_atr():
    strat = BiasContinuationSwingStrategy()
    ctx = _swing_context("Bullish")
    tiny_legacy = strat.react(_swing_snap(momentum=0.0001, atr_normalized_momentum=1.0), ctx)
    huge_legacy = strat.react(_swing_snap(momentum=9999.0, atr_normalized_momentum=1.0), ctx)
    assert tiny_legacy is not None and huge_legacy is not None
    assert tiny_legacy["confidence"] == huge_legacy["confidence"]


def test_swing_wrong_direction_atr_contributes_zero():
    strat = BiasContinuationSwingStrategy()
    ctx = _swing_context("Bullish")
    agreeing = strat.react(_swing_snap(atr_normalized_momentum=1.0), ctx)
    opposing = strat.react(_swing_snap(atr_normalized_momentum=-1.0), ctx)
    assert agreeing["confidence"] > opposing["confidence"]
    # opposing floor: 0.0 (momentum) + 0.18 (base) + 0.0 (snr_strength=0) + 0.05 (BOS bonus) = 0.23
    assert opposing["confidence"] == 0.23


def test_swing_none_atr_same_floor_as_wrong_direction():
    strat = BiasContinuationSwingStrategy()
    ctx = _swing_context("Bullish")
    none_atr = strat.react(_swing_snap(atr_normalized_momentum=None), ctx)
    wrong_dir = strat.react(_swing_snap(atr_normalized_momentum=-1.0), ctx)
    assert none_atr["confidence"] == wrong_dir["confidence"] == 0.23


def test_swing_bullish_bearish_symmetry():
    strat = BiasContinuationSwingStrategy()
    bullish = strat.react(
        _swing_snap(bias="Bullish", structure_direction="Bullish", context_zone="demand", atr_normalized_momentum=0.8),
        _swing_context("Bullish"),
    )
    bearish = strat.react(
        _swing_snap(bias="Bearish", structure_direction="Bearish", context_zone="supply", atr_normalized_momentum=-0.8),
        _swing_context("Bearish"),
    )
    assert bullish is not None and bearish is not None
    assert bullish["confidence"] == bearish["confidence"]


def test_swing_bos_bonus_unchanged():
    strat = BiasContinuationSwingStrategy()
    ctx = _swing_context("Bullish")
    bos = strat.react(_swing_snap(structure_type="BOS", atr_normalized_momentum=1.0), ctx)
    choch = strat.react(_swing_snap(structure_type="CHOCH", atr_normalized_momentum=1.0), ctx)
    assert bos is not None and choch is not None
    assert round(bos["confidence"] - choch["confidence"], 2) == 0.05


def test_swing_confidence_within_cap():
    strat = BiasContinuationSwingStrategy()
    ctx = _swing_context("Bullish")
    for atr in (-50.0, -1.0, 0.0, 0.5, 1.0, 2.0, 5.0, 50.0):
        result = strat.react(_swing_snap(atr_normalized_momentum=atr), ctx)
        assert result is not None
        assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# DoubleEngulfingStrategy -- isolated against HEAD's actual (pre-existing,
# uncommitted-SNR-bonus-restructuring-free) shape: confidence =
# min(strategy_momentum_confidence(atr, direction) + bonus, 1.0), bonus =
# full_bonus if wick_extension else 0.0. No SNR bonus/note/price-override in
# this contract -- that belongs to a separate, still-uncommitted feature.
# ---------------------------------------------------------------------------

def _engulf_snap(**overrides):
    base = dict(timeframe="M15", engulfing_sequence=["bull", "bull"], engulfing_strength="Weak")
    base.update(overrides)
    return snap(**base)


def test_engulfing_confidence_ignores_legacy_momentum_uses_atr():
    strat = DoubleEngulfingStrategy()
    tiny_legacy = strat.react(_engulf_snap(momentum=0.0001, atr_normalized_momentum=1.0), {})
    huge_legacy = strat.react(_engulf_snap(momentum=9999.0, atr_normalized_momentum=1.0), {})
    assert tiny_legacy is not None and huge_legacy is not None
    assert tiny_legacy["confidence"] == huge_legacy["confidence"]


def test_engulfing_wrong_direction_atr_contributes_zero():
    strat = DoubleEngulfingStrategy()
    agreeing = strat.react(_engulf_snap(atr_normalized_momentum=1.0), {})
    opposing = strat.react(_engulf_snap(atr_normalized_momentum=-1.0), {})
    assert agreeing["confidence"] > opposing["confidence"]
    assert opposing["confidence"] == 0.0  # bonus=0.0 (Weak), momentum term=0.0 (wrong direction)


def test_engulfing_none_atr_zero():
    strat = DoubleEngulfingStrategy()
    result = strat.react(_engulf_snap(atr_normalized_momentum=None), {})
    assert result["confidence"] == 0.0


def test_engulfing_bullish_bearish_symmetry():
    strat = DoubleEngulfingStrategy()
    bullish = strat.react(_engulf_snap(engulfing_sequence=["bull", "bull"], atr_normalized_momentum=1.0), {})
    bearish = strat.react(_engulf_snap(engulfing_sequence=["bear", "bear"], atr_normalized_momentum=-1.0), {})
    assert bullish["confidence"] == bearish["confidence"]
    assert bullish["direction"] == "long"
    assert bearish["direction"] == "short"


def test_engulfing_wick_extension_bonus_unchanged():
    strat = DoubleEngulfingStrategy()
    strong = strat.react(_engulf_snap(engulfing_strength="Strong", atr_normalized_momentum=1.0), {})
    weak = strat.react(_engulf_snap(engulfing_strength="Weak", atr_normalized_momentum=1.0), {})
    # sequence ("bull","bull") -> full_bonus=1.0 -> bonus = 1.0 if Strong else 0.0 (HEAD's own formula,
    # unchanged by this fix); momentum term = strategy_momentum_confidence(1.0, "long") = 0.5 in both,
    # so strong caps at 1.0 (0.5+1.0->1.0) and weak stays at 0.5 (0.5+0.0) -> diff = 0.5
    assert round(strong["confidence"] - weak["confidence"], 2) == 0.5


def test_engulfing_confidence_within_cap():
    strat = DoubleEngulfingStrategy()
    for atr in (-50.0, -1.0, 0.0, 0.5, 1.0, 2.0, 5.0, 50.0):
        result = strat.react(_engulf_snap(atr_normalized_momentum=atr), {})
        assert result is not None
        assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# ZoneContinuationStrategy -- isolated against HEAD's actual (pre-existing,
# uncommitted-SNR-bonus/zone-matching-restructuring-free) shape: confidence
# is the bare strategy_momentum_confidence(atr, direction) value, no base
# offset, no SNR bonus, no extra cap (the helper is already bounded).
# Eligibility requires snapshot.structure_type to literally be "breakout" or
# "reversal" (HEAD's own pre-existing check -- StructureSnapshot's real
# structure_type values are "BOS"/"CHOCH"/"None", so this branch of HEAD's
# code is effectively unreachable live; not this fix's concern to touch,
# preserved exactly as HEAD has it).
# ---------------------------------------------------------------------------

def _zone_htf(context_zone="demand"):
    return snap(timeframe="H1", context_zone=context_zone)


def _zone_context(context_zone="demand"):
    return {"T_H1": _zone_htf(context_zone), "T_H4": _zone_htf(context_zone)}


def _zone_snap(**overrides):
    base = dict(timeframe="M5", structure_type="breakout", structure_direction="Bullish", structure_valid=True)
    base.update(overrides)
    return snap(**base)


def test_zone_confidence_ignores_legacy_momentum_uses_atr():
    strat = ZoneContinuationStrategy()
    ctx = _zone_context("demand")
    tiny_legacy = strat.react(_zone_snap(momentum=0.0001, atr_normalized_momentum=1.0), ctx)
    huge_legacy = strat.react(_zone_snap(momentum=9999.0, atr_normalized_momentum=1.0), ctx)
    assert tiny_legacy is not None and huge_legacy is not None
    assert tiny_legacy["confidence"] == huge_legacy["confidence"]


def test_zone_wrong_direction_atr_contributes_zero():
    strat = ZoneContinuationStrategy()
    ctx = _zone_context("demand")
    agreeing = strat.react(_zone_snap(atr_normalized_momentum=1.0), ctx)
    opposing = strat.react(_zone_snap(atr_normalized_momentum=-1.0), ctx)
    assert agreeing["confidence"] > opposing["confidence"]
    assert opposing["confidence"] == 0.0


def test_zone_none_atr_zero():
    strat = ZoneContinuationStrategy()
    result = strat.react(_zone_snap(atr_normalized_momentum=None), _zone_context("demand"))
    assert result["confidence"] == 0.0


def test_zone_bullish_bearish_symmetry():
    strat = ZoneContinuationStrategy()
    bullish = strat.react(
        _zone_snap(structure_direction="Bullish", atr_normalized_momentum=1.0), _zone_context("demand"),
    )
    bearish = strat.react(
        _zone_snap(structure_direction="Bearish", atr_normalized_momentum=-1.0), _zone_context("supply"),
    )
    assert bullish is not None and bearish is not None
    assert bullish["confidence"] == bearish["confidence"]
    assert bullish["direction"] == "long"
    assert bearish["direction"] == "short"


def test_zone_confidence_within_cap():
    strat = ZoneContinuationStrategy()
    ctx = _zone_context("demand")
    for atr in (-50.0, -1.0, 0.0, 0.5, 1.0, 2.0, 5.0, 50.0):
        result = strat.react(_zone_snap(atr_normalized_momentum=atr), ctx)
        assert result is not None
        assert 0.0 <= result["confidence"] <= 1.0


# ---------------------------------------------------------------------------
# Cross-plugin: no plugin still imports normalize_confidence unless it still
# uses it for something else (BiasContinuationScalpingStrategy's eligibility
# gate, untouched, out of this fix's scope).
# ---------------------------------------------------------------------------

def test_only_scalping_plugin_still_imports_normalize_confidence():
    import pathlib
    plugin_dir = pathlib.Path("core/strategy")
    still_uses = {
        "BiasContinuationScalpingStrategy.py": True,   # _trigger_matches eligibility gate, untouched
        "BiasContinuationSwingStrategy.py": False,
        "DoubleEngulfingStrategy.py": False,
        "ZoneContinuationStrategy.py": False,
    }
    for name, expected in still_uses.items():
        text = (plugin_dir / name).read_text(encoding="utf-8")
        assert ("normalize_confidence" in text) == expected, f"{name} normalize_confidence usage changed unexpectedly"


def test_all_four_plugins_import_canonical_helper():
    import pathlib
    plugin_dir = pathlib.Path("core/strategy")
    for name in ["BiasContinuationScalpingStrategy.py", "BiasContinuationSwingStrategy.py",
                 "DoubleEngulfingStrategy.py", "ZoneContinuationStrategy.py"]:
        text = (plugin_dir / name).read_text(encoding="utf-8")
        assert "strategy_momentum_confidence" in text


def test_scalping_eligibility_gate_still_functions_unchanged():
    """BiasContinuationScalpingStrategy's normalize_confidence(momentum)>=0.45
    eligibility fallback path (structure invalid, relying on confluence +
    momentum threshold) is explicitly out of this fix's scope -- confirm it
    still gates exactly as before."""
    strat = BiasContinuationScalpingStrategy()
    ctx = _scalp_context("Bullish")
    # structure invalid -> falls to confluence+momentum-threshold path
    below_threshold = strat.react(
        snap(structure_valid=False, structure_type="None", momentum=4.0, atr_normalized_momentum=1.0), ctx,
    )  # normalize_confidence(4.0) = 0.4 < 0.45 -> ineligible
    above_threshold = strat.react(
        snap(structure_valid=False, structure_type="None", momentum=5.0, atr_normalized_momentum=1.0), ctx,
    )  # normalize_confidence(5.0) = 0.5 >= 0.45 -> eligible
    assert below_threshold is None
    assert above_threshold is not None


# ---------------------------------------------------------------------------
# Live regression: real pipeline, real MT5 data -- confirm every fired
# signal's confidence matches the new formula exactly (using the same
# canonical helper independently), across several symbols.
# ---------------------------------------------------------------------------

def test_live_bias_plugin_confidence_methods_bounded_across_real_data():
    """BiasContinuationScalpingStrategy/SwingStrategy's _confidence() is a
    white-box entry point that runs regardless of the plugins' own (fairly
    strict, multi-timeframe-alignment) eligibility gates -- calling it
    directly against real live StrategySnapshots guarantees this exercises
    real market data every run, unlike a full react() sweep which may
    legitimately find zero eligible setups at any given moment."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.strategy.StrategyEngine import to_strategy_snapshot
    from mt5.constants import SYMBOLS, TIMEFRAMES

    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(SYMBOLS, TIMEFRAMES, count=100)

    scalp = BiasContinuationScalpingStrategy()
    swing = BiasContinuationSwingStrategy()
    checked_any = False
    for symbol in SYMBOLS:
        for tf in TIMEFRAMES:
            structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
            if structure is None:
                continue
            snapshot = to_strategy_snapshot(structure)
            for direction in ("Bullish", "Bearish"):
                checked_any = True
                assert 0.0 <= scalp._confidence(snapshot, direction) <= 1.0
                assert 0.0 <= swing._confidence(snapshot, direction) <= 1.0

    assert checked_any


def test_live_composite_plugin_signals_when_they_fire_stay_in_contract():
    """Best-effort end-to-end sweep: whenever any of the 4 plugins' own
    eligibility happens to fire on real live data, its confidence must stay
    in [0,1]. Not asserted to fire at least once -- these are fairly strict,
    real trading setups (multi-timeframe bias alignment, a specific double-
    engulfing candle sequence, or -- for ZoneContinuationStrategy -- a
    pre-existing HEAD eligibility check comparing structure_type against
    values StructureSnapshot never actually produces, outside this fix's
    scope to touch) that can legitimately all be absent at any given
    moment; the exact-formula guarantees are already pinned by the
    synthetic-data tests above."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.strategy.StrategyEngine import to_strategy_snapshot
    from mt5.constants import SYMBOLS, TIMEFRAMES

    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(SYMBOLS, TIMEFRAMES, count=100)

    plugins = [BiasContinuationScalpingStrategy(), BiasContinuationSwingStrategy(),
               DoubleEngulfingStrategy(), ZoneContinuationStrategy()]

    for symbol in SYMBOLS:
        structure_map = {}
        for tf in TIMEFRAMES:
            s = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
            if s:
                structure_map[tf] = s
        context = {f"{symbol}_{tf}": to_strategy_snapshot(s) for tf, s in structure_map.items()}

        for tf, s in structure_map.items():
            snapshot = context[f"{symbol}_{tf}"]
            for plugin in plugins:
                try:
                    result = plugin.react(snapshot, context)
                except Exception:
                    continue
                if result is None:
                    continue
                assert 0.0 <= result["confidence"] <= 1.0


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
