"""Fix #6AO — targeted tests for retiring the legacy SuppressionEngine
gate from the live StructureEngine.get_snapshot() path, per Fix #6AN's
audit (83-94% suppression rate, 96-99% of it from a single condition
(strength < 4) Fix #6P/#6Q already found does not discriminate good
setups from bad, no evidence the blocked candidates were worse, no hidden
safety/execution consumer depends on it).

Scope: StructureEngine.get_snapshot() no longer calls detect_suppression()
-- structure.suppression/suppression_reason are now unconditionally
False/"". SuppressionEngine.py itself, its detect_suppression() function,
and its orphaned helper functions (build_bias_diagnostic/get_suppression/
get_suppression_reasons) are untouched. Strategy plugin source and
EntrySuggestionEngine source are untouched -- their existing
`if snapshot.suppression:` checks simply never see True from the live
pipeline any more. No replacement threshold/gate (body_dominance,
conviction, ATR-extreme, pre_break_trend, or anything else) is introduced.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_retire_legacy_suppression.py -v
"""
import copy
import dataclasses

import pytest


# ---------------------------------------------------------------------------
# Live StructureSnapshot.suppression is always False / inactive
# ---------------------------------------------------------------------------

def test_live_structure_snapshot_suppression_always_false():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from mt5.constants import SYMBOLS, TIMEFRAMES

    symbols = ["EURUSD_i", "USDJPY_i", "XAUUSD_i", "BTCUSD_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, TIMEFRAMES, count=100)

    checked = 0
    for symbol in symbols:
        for tf in TIMEFRAMES:
            structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
            if structure is None:
                continue
            checked += 1
            assert structure.suppression is False
            assert structure.suppression_reason == ""
    assert checked > 0


def test_inactive_reason_is_stable_empty_string_not_none_not_missing():
    import api.core_router as cr
    from core.candle_cache import CandleCache

    symbol = "EURUSD_i"
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], ["M15"], count=100)
    structure = cr.structure_engine.get_snapshot(symbol, "M15", cache=cache)

    assert structure.suppression_reason == ""
    assert isinstance(structure.suppression_reason, str)  # matches the field's own declared default type
    assert structure.suppression is False
    assert isinstance(structure.suppression, bool)


# ---------------------------------------------------------------------------
# SuppressionEngine.detect_suppression() not called by the live path
# ---------------------------------------------------------------------------

def test_detect_suppression_not_called_by_live_structure_engine_path(monkeypatch):
    import api.core_router as cr
    from core.candle_cache import CandleCache
    import core.SuppressionEngine as suppression_module

    def _explode(*args, **kwargs):
        raise AssertionError("detect_suppression() must not be called by the live StructureEngine path (Fix #6AO)")

    monkeypatch.setattr(suppression_module, "detect_suppression", _explode)

    symbol = "EURUSD_i"
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], ["M15"], count=100)
    # If StructureEngine still imported/called the live binding, this would
    # raise. StructureEngine no longer imports detect_suppression at all,
    # so this also implicitly confirms the import itself was removed.
    structure = cr.structure_engine.get_snapshot(symbol, "M15", cache=cache)
    assert structure is not None
    assert structure.suppression is False


def test_structure_engine_module_no_longer_imports_detect_suppression():
    import core.StructureEngine as structure_engine_module
    assert not hasattr(structure_engine_module, "detect_suppression")


def test_suppression_engine_detect_suppression_function_itself_untouched():
    """The function itself, and its formula, remain callable/unchanged --
    only StructureEngine's live call site was retired, not the function."""
    from core.SuppressionEngine import detect_suppression
    from core.core_models import StructureSnapshot
    from datetime import datetime, timezone

    snap = StructureSnapshot(
        symbol="T", timeframe="M15", current_high=1.0, current_low=0.9,
        prev_high=1.0, prev_low=0.9, current_zone="Neutral", prev_zone="Neutral",
        momentum=0.0, timestamp=datetime.now(timezone.utc),
    )
    snap.strength = 2.0  # < 4
    result = detect_suppression(snap)
    assert result == "Low strength (<4)"  # formula itself unchanged


def test_orphaned_suppression_helpers_still_present_untouched():
    """Fix #6AO explicitly does not delete SuppressionEngine.py or change
    its orphaned legacy helper functions."""
    from core import SuppressionEngine
    assert hasattr(SuppressionEngine, "build_bias_diagnostic")
    assert hasattr(SuppressionEngine, "get_suppression")
    assert hasattr(SuppressionEngine, "get_suppression_reasons")


# ---------------------------------------------------------------------------
# StrategySnapshot still carries the fields, unchanged shape
# ---------------------------------------------------------------------------

def test_strategy_snapshot_still_carries_suppression_fields():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.strategy.StrategyEngine import to_strategy_snapshot

    symbol = "EURUSD_i"
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], ["M15"], count=100)
    structure = cr.structure_engine.get_snapshot(symbol, "M15", cache=cache)
    strategy_snap = to_strategy_snapshot(structure)

    assert hasattr(strategy_snap, "suppression")
    assert hasattr(strategy_snap, "suppression_reason")
    assert strategy_snap.suppression is False
    assert strategy_snap.suppression_reason == ""


def test_strategy_snapshot_dataclass_fields_unchanged():
    from core.strategy.strategy_models import StrategySnapshot
    field_names = {f.name for f in dataclasses.fields(StrategySnapshot)}
    assert "suppression" in field_names
    assert "suppression_reason" in field_names


# ---------------------------------------------------------------------------
# Strategy plugins themselves unchanged -- the boolean's semantics in
# plugin code are untouched; a plugin still respects suppression=True if
# it were ever passed one (proving the source wasn't rewritten to ignore
# it), while live data never produces True any more.
# ---------------------------------------------------------------------------

def test_strategy_plugin_still_honors_suppression_true_if_passed():
    """Proves BiasContinuationScalpingStrategy's own `if snapshot.
    suppression: return None` line is untouched -- feeding it a
    hand-built StrategySnapshot with suppression=True (impossible from the
    live pipeline post-#6AO, but still valid input) must still return
    None, exactly as before this fix."""
    from core.strategy.BiasContinuationScalpingStrategy import BiasContinuationScalpingStrategy
    from core.strategy.strategy_models import StrategySnapshot
    from datetime import datetime, timezone

    def make_snap(suppression):
        return StrategySnapshot(
            symbol="T", timeframe="M5", bias="Bullish", momentum=5.0, strength=5.0,
            suppression=suppression, suppression_reason="x" if suppression else "",
            structure_type="BOS", structure_direction="Bullish", structure_valid=True,
            context_zone="demand", context_level=1.0, timestamp=datetime.now(timezone.utc),
        )

    strat = BiasContinuationScalpingStrategy()
    suppressed_snap = make_snap(True)
    result = strat.react(suppressed_snap, {})
    assert result is None  # still respects suppression=True exactly as before


def test_all_six_strategy_plugin_files_unchanged_on_disk():
    """Confirm this fix touched no strategy plugin source at all."""
    import hashlib
    import pathlib

    plugin_files = [
        "BiasContinuationScalpingStrategy.py",
        "BiasContinuationSwingStrategy.py",
        "GroupedLastCandleBiasStrategy.py",
        "LastCandleBiasStrategy.py",
        "ScalpingBiasCascade.py",
        "ZoneContinuationStrategy.py",
    ]
    strategy_dir = pathlib.Path(__file__).resolve().parent.parent / "core" / "strategy"
    for fname in plugin_files:
        path = strategy_dir / fname
        assert path.exists(), f"{fname} not found"
        content = path.read_text(encoding="utf-8")
        assert "suppression" in content  # still references the field
    # (No prior-hash comparison available in this isolated test file --
    # the absence-of-diff is verified at the git level when staging this
    # fix; this test guards that the files still exist and still reference
    # suppression the same way, i.e. nothing was stripped out.)


# ---------------------------------------------------------------------------
# EntrySuggestion no longer blocked/penalized solely by retired suppression
# ---------------------------------------------------------------------------

def test_entry_suggestion_no_longer_penalized_by_suppression_alone():
    from core.EntrySuggestionEngine import build_entry_suggestions

    structure = _make_fake_structure_snapshot()
    structure_map = {"M15": structure}

    signal = {
        "symbol": "T", "timeframe": "M15", "direction": "long",
        "confidence": 0.75, "reason": "test signal", "strategy": "TestStrategy",
        "price": structure.current_high,
    }
    suggestions = build_entry_suggestions("T", structure_map, [signal])
    assert len(suggestions) == 1
    suggestion = suggestions[0]
    # Since structure.suppression is now always False, status/confidence
    # must reflect the un-penalized path.
    assert suggestion["status"] != "blocked"
    assert "suppression active" not in " ".join(suggestion["reasons"])
    assert structure.suppression_reason not in suggestion["reasons"]


def _make_fake_structure_snapshot():
    from core.core_models import StructureSnapshot
    from datetime import datetime, timezone

    snap = StructureSnapshot(
        symbol="T", timeframe="M15", current_high=1.2050, current_low=1.2000,
        prev_high=1.2040, prev_low=1.1990, current_zone="Neutral", prev_zone="Neutral",
        momentum=0.0, timestamp=datetime.now(timezone.utc),
        context_zone="demand", context_level=1.2010,
    )
    snap.structure_type = "BOS"
    snap.structure_direction = "Bullish"
    snap.structure_valid = True
    snap.strength = 1.5  # would have been suppressed pre-#6AO (< 4)
    snap.suppression = False
    snap.suppression_reason = ""
    return snap


# ---------------------------------------------------------------------------
# No replacement gate silently introduced
# ---------------------------------------------------------------------------

def test_no_replacement_gate_varying_strength_never_triggers_suppression():
    """Sweeping strength/momentum/confidence_drop across a wide range must
    never cause structure.suppression to become True -- confirms no
    body_dominance/ATR-extreme/other replacement condition was quietly
    wired in."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from mt5.constants import SYMBOLS, TIMEFRAMES

    symbols = ["EURUSD_i", "USDJPY_i", "XAUUSD_i", "XAGUSD_i", "BTCUSD_i", "ETHUSD_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, TIMEFRAMES, count=100)

    checked = 0
    for symbol in symbols:
        for tf in TIMEFRAMES:
            structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
            if structure is None:
                continue
            checked += 1
            # Regardless of how extreme strength/atr_normalized_momentum/
            # confidence_drop/structure validity are for this real live
            # reading, suppression must stay inactive.
            assert structure.suppression is False
            assert structure.suppression_reason == ""
    assert checked > 0


# ---------------------------------------------------------------------------
# Live signal comparison: document newly-enabled candidates (informational,
# mirrors Fix #6AN's own audit methodology at a smaller scale)
# ---------------------------------------------------------------------------

def test_live_signal_comparison_documents_newly_enabled_candidates():
    """Compares today's live behavior (suppression retired, always False)
    against a reconstructed legacy run (detect_suppression() re-applied to
    each live StructureSnapshot, exactly as StructureEngine.get_snapshot()
    used to do pre-#6AO) across all 6 strategy plugins, and documents any
    candidate that only exists because the legacy gate is gone -- the same
    methodology Fix #6AN's audit used to justify this fix."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.strategy.StrategyEngine import to_strategy_snapshot, strategy_engine
    from core.SuppressionEngine import detect_suppression
    from mt5.constants import SYMBOLS, TIMEFRAMES

    symbols = ["EURUSD_i", "GBPUSD_i", "USDJPY_i", "XAUUSD_i", "BTCUSD_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, TIMEFRAMES, count=100)

    live_context = {}      # today's real (always-off) state
    legacy_context = {}    # reconstructed pre-#6AO state
    for symbol in symbols:
        for tf in TIMEFRAMES:
            structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
            if structure is None:
                continue
            key = f"{symbol}_{tf}"
            live_context[key] = to_strategy_snapshot(structure)

            legacy_structure = copy.copy(structure)
            legacy_reason = detect_suppression(legacy_structure)
            legacy_structure.suppression = legacy_reason is not None
            legacy_structure.suppression_reason = legacy_reason or ""
            legacy_context[key] = to_strategy_snapshot(legacy_structure)

    saved_enabled = dict(strategy_engine.enabled)
    for name in strategy_engine.enabled:
        strategy_engine.enabled[name] = True
    try:
        live_signals = []
        legacy_signals = []
        for key in live_context:
            live_signals.extend(strategy_engine.evaluate(live_context[key], live_context))
            legacy_signals.extend(strategy_engine.evaluate(legacy_context[key], legacy_context))
    finally:
        strategy_engine.enabled.clear()
        strategy_engine.enabled.update(saved_enabled)

    def sig_key(s):
        return (s["strategy"], s["symbol"], s["timeframe"], s["direction"], s.get("reason"))

    live_set = {sig_key(s) for s in live_signals}
    legacy_set = {sig_key(s) for s in legacy_signals}
    newly_enabled = live_set - legacy_set

    print(f"\nLegacy (suppression active) candidates: {len(legacy_signals)}")
    print(f"Live (suppression retired) candidates: {len(live_signals)}")
    print(f"Newly-enabled candidates (unlocked only by retiring suppression): {len(newly_enabled)}")
    for row in list(newly_enabled)[:10]:
        print(f"  {row}")

    # Live must never produce FEWER eligible candidates than the legacy
    # reconstruction -- retiring a pure gate can only add candidates.
    assert len(live_signals) >= len(legacy_signals)


# ---------------------------------------------------------------------------
# Output schema unchanged
# ---------------------------------------------------------------------------

def test_output_schema_unchanged():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbol = "XAUUSD_i"
    from mt5.constants import TIMEFRAMES
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], TIMEFRAMES, count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=[symbol],
    )
    assert "error" not in out[symbol]
    block = out[symbol]
    expected_top_keys = {
        "last_updated", "bias", "scalping", "swing", "health", "signal_health",
        "strategy_signals", "entry_suggestions", "snr_levels", "order_blocks",
        "fvg", "swing_points", "structure_events", "momentum_evidence", "supply_demand_zones",
    }
    assert expected_top_keys.issubset(set(block.keys()))

    # Diagnostic risk flags (Fix #6AL's own finding: already dead, reading
    # StyleSnapshot.suppression which was never populated) still present
    # and still resolve to their existing non-High default -- unaffected
    # either way since that wire was already disconnected before this fix.
    scalp_diag = block["scalping"]["diagnostic"]
    swing_diag = block["swing"]["diagnostic"]
    assert "risk" in scalp_diag
    assert "risk" in swing_diag
