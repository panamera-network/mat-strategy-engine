"""Fix #6AS — StrategySnapshot gains atr_normalized_momentum (canonical,
instrument-scale-independent momentum, copied straight from
StructureSnapshot.atr_normalized_momentum — Fix #6V). Additive only: no
recomputation, no new candle fetch, no Strategy plugin formula change, and
the legacy `momentum` field (clamped [0,10], per-instrument price-unit)
stays exactly as before.

This fix exists purely to make the canonical value available to the
Strategy layer for a later fix (Fix #6AR's audit found all 7 live plugins
still keyed off the legacy field) — no strategy behavior changes here.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_strategy_snapshot_atr_momentum_exposure.py -v
"""
import dataclasses
from datetime import datetime, timezone

from core.core_models import StructureSnapshot
from core.strategy.strategy_models import StrategySnapshot
from core.strategy.StrategyEngine import to_strategy_snapshot


def make_structure(atr_normalized_momentum=None, momentum=5.0):
    s = StructureSnapshot(
        symbol="FIX6AS_TEST", timeframe="M5",
        current_high=1.0, current_low=0.9, prev_high=1.0, prev_low=0.9,
        current_zone="Neutral", prev_zone="Neutral",
    )
    s.structure_type = "None"
    s.structure_direction = "Neutral"
    s.structure_valid = False
    s.momentum = momentum
    s.atr_normalized_momentum = atr_normalized_momentum
    return s


# ---------------------------------------------------------------------------
# Dataclass shape
# ---------------------------------------------------------------------------

def test_strategy_snapshot_has_atr_normalized_momentum_field():
    field_names = {f.name for f in dataclasses.fields(StrategySnapshot)}
    assert "atr_normalized_momentum" in field_names


def test_strategy_snapshot_atr_field_defaults_to_none():
    field = next(f for f in dataclasses.fields(StrategySnapshot) if f.name == "atr_normalized_momentum")
    assert field.default is None


# ---------------------------------------------------------------------------
# to_strategy_snapshot(): Structure -> Strategy value exact, signed, None-safe
# ---------------------------------------------------------------------------

def test_to_strategy_snapshot_copies_exact_value():
    structure = make_structure(atr_normalized_momentum=1.2345678)
    strat = to_strategy_snapshot(structure)
    assert strat.atr_normalized_momentum == 1.2345678


def test_to_strategy_snapshot_preserves_sign_negative():
    structure = make_structure(atr_normalized_momentum=-2.71828)
    strat = to_strategy_snapshot(structure)
    assert strat.atr_normalized_momentum == -2.71828


def test_to_strategy_snapshot_preserves_sign_positive():
    structure = make_structure(atr_normalized_momentum=3.14159)
    strat = to_strategy_snapshot(structure)
    assert strat.atr_normalized_momentum == 3.14159


def test_to_strategy_snapshot_preserves_none():
    structure = make_structure(atr_normalized_momentum=None)
    strat = to_strategy_snapshot(structure)
    assert strat.atr_normalized_momentum is None


def test_to_strategy_snapshot_preserves_zero():
    """0.0 is a real, meaningful value (perfectly flat momentum) -- must not
    be confused with the None (unavailable) case."""
    structure = make_structure(atr_normalized_momentum=0.0)
    strat = to_strategy_snapshot(structure)
    assert strat.atr_normalized_momentum == 0.0
    assert strat.atr_normalized_momentum is not None


def test_to_strategy_snapshot_no_recomputation_pure_copy():
    """Changing the structure's value after construction must not affect an
    already-built StrategySnapshot -- proves this is a value copy at
    construction time, not a lazy/derived recomputation."""
    structure = make_structure(atr_normalized_momentum=1.0)
    strat = to_strategy_snapshot(structure)
    structure.atr_normalized_momentum = 99.0
    assert strat.atr_normalized_momentum == 1.0


# ---------------------------------------------------------------------------
# Legacy `momentum` field untouched by this fix.
# ---------------------------------------------------------------------------

def test_legacy_momentum_field_untouched():
    structure = make_structure(atr_normalized_momentum=-1.5, momentum=7.25)
    strat = to_strategy_snapshot(structure)
    assert strat.momentum == 7.25


def test_legacy_momentum_independent_of_new_field_value():
    """The two fields must vary independently -- proves this fix didn't
    wire atr_normalized_momentum into the legacy momentum field or vice
    versa."""
    structure_a = make_structure(atr_normalized_momentum=5.0, momentum=1.0)
    structure_b = make_structure(atr_normalized_momentum=5.0, momentum=9.0)
    strat_a = to_strategy_snapshot(structure_a)
    strat_b = to_strategy_snapshot(structure_b)
    assert strat_a.atr_normalized_momentum == strat_b.atr_normalized_momentum == 5.0
    assert strat_a.momentum != strat_b.momentum


# ---------------------------------------------------------------------------
# POST /core/evaluate — backward compatibility of the raw-JSON-body path.
# ---------------------------------------------------------------------------

def _base_snapshot_payload(**overrides):
    payload = {
        "symbol": "FIX6AS_API", "timeframe": "M5", "bias": "Bullish",
        "momentum": 5.0, "strength": 5.0, "suppression": False,
        "suppression_reason": "", "structure_type": "None",
        "structure_direction": "Neutral", "structure_valid": False,
        "context_zone": "neutral", "context_level": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    payload.update(overrides)
    return payload


def test_evaluate_route_accepts_payload_without_new_field():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    resp = client.post("/core/evaluate", json={"snapshot": _base_snapshot_payload(), "context": {}})
    assert resp.status_code == 200
    assert "signals" in resp.json()


def test_evaluate_route_omitted_field_defaults_to_none_not_legacy_fallback():
    """Omitting atr_normalized_momentum from the request body must resolve
    to None -- never guessed/backfilled from the legacy `momentum` value
    that IS present in the same payload."""
    strat = StrategySnapshot(**_base_snapshot_payload())
    assert strat.atr_normalized_momentum is None
    assert strat.momentum == 5.0  # legacy field present and unrelated


def test_evaluate_route_preserves_exact_field_when_supplied():
    payload = _base_snapshot_payload(atr_normalized_momentum=-1.834)
    strat = StrategySnapshot(**payload)
    assert strat.atr_normalized_momentum == -1.834


def test_evaluate_route_accepts_payload_with_new_field_end_to_end():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    body = {"snapshot": _base_snapshot_payload(atr_normalized_momentum=0.75), "context": {}}
    resp = client.post("/core/evaluate", json=body)
    assert resp.status_code == 200
    assert "signals" in resp.json()


def test_context_snapshots_also_backward_compatible():
    """context dict entries go through the same StrategySnapshot(**v)
    construction as the primary snapshot -- must be equally tolerant of a
    missing field."""
    old_style_context_entry = _base_snapshot_payload(symbol="FIX6AS_CTX", timeframe="H1")
    strat = StrategySnapshot(**old_style_context_entry)
    assert strat.atr_normalized_momentum is None


# ---------------------------------------------------------------------------
# No behavior change: every live Strategy plugin's signal output is
# unaffected by this fix (none of them read the new field yet).
# ---------------------------------------------------------------------------

def test_no_live_plugin_reads_new_field_yet():
    """Fix #6AR's audit found none of the 7 live plugins read this field.
    Fix #6AV later migrated the 4 composite plugins (BiasContinuation*/
    DoubleEngulfing/ZoneContinuation) to read it via the canonical helper --
    updated here to check only the 3 raw-confidence plugins Fix #6AV
    deliberately left untouched, still pending their own migration."""
    import pathlib
    plugin_dir = pathlib.Path("core/strategy")
    plugin_files = [
        "ScalpingBiasCascade.py", "GroupedLastCandleBiasStrategy.py",
        "LastCandleBiasStrategy.py",
    ]
    for name in plugin_files:
        text = (plugin_dir / name).read_text(encoding="utf-8")
        assert "atr_normalized_momentum" not in text, f"{name} already reads the new field -- out of this fix's scope"


def test_strategy_signal_output_identical_with_and_without_new_field():
    """Same structure snapshot, only difference being atr_normalized_momentum
    present vs absent -- the resulting Strategy signal (or lack of one) must
    be byte-identical either way, for a plugin that doesn't read it.

    Fix #6AV migrated BiasContinuationScalpingStrategy (this test's original
    example) to read the new field via the canonical helper, so its output
    now legitimately differs with/without it -- that plugin's own dedicated
    coverage lives in test_composite_strategy_momentum_confidence_migration.py.
    Swapped to LastCandleBiasStrategy, one of the 3 raw-confidence plugins
    Fix #6AV deliberately left untouched, to keep testing the same
    invariant this test was written for."""
    from core.strategy.LastCandleBiasStrategy import LastCandleBiasStrategy

    def make_event(atr):
        return StrategySnapshot(
            symbol="T", timeframe="D1", bias="Bullish", momentum=5.0, strength=5.0,
            suppression=False, suppression_reason="",
            structure_type="BOS", structure_direction="Bullish", structure_valid=True,
            context_zone="demand", context_level=1.0, timestamp=datetime.now(timezone.utc),
            is_last_bias_candle=True, atr_normalized_momentum=atr,
        )

    def make_shift(atr):
        return StrategySnapshot(
            symbol="T", timeframe="H1", bias="Bullish", momentum=5.0, strength=5.0,
            suppression=False, suppression_reason="",
            structure_type="BOS", structure_direction="Bullish", structure_valid=True,
            context_zone="demand", context_level=1.0, timestamp=datetime.now(timezone.utc),
            atr_normalized_momentum=atr,
        )

    strat = LastCandleBiasStrategy()

    event_without, shift_without = make_event(None), make_shift(None)
    context_without = {"T_D1": event_without, "T_H1": shift_without}
    event_with, shift_with = make_event(2.5), make_shift(2.5)
    context_with = {"T_D1": event_with, "T_H1": shift_with}

    result_without = strat.react(event_without, context_without)
    result_with = strat.react(event_with, context_with)
    assert result_without == result_with


# ---------------------------------------------------------------------------
# Live regression: real pipeline, real MT5 data.
# ---------------------------------------------------------------------------

def test_live_strategy_snapshot_atr_momentum_matches_structure():
    import api.core_router as cr
    from core.candle_cache import CandleCache

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    checked_any = False
    for tf in timeframes:
        structure = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
        if structure is None:
            continue
        strat = to_strategy_snapshot(structure)
        assert strat.atr_normalized_momentum == structure.atr_normalized_momentum
        assert strat.momentum == structure.momentum  # legacy field still exact too
        checked_any = True

    assert checked_any


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
