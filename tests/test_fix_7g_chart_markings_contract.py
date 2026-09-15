"""Fix #7G — canonical chart_markings contract (Fix #7F's design).

Tests the shared marking type/validator/builder in
core/strategy/chart_markings.py: valid marking construction per type,
invalid geometry rejection, clean omission of unset optional fields,
multiple markings per signal, and -- critically -- that this purely
additive infrastructure changes nothing about the 7 existing strategies'
output (none of them are retrofitted by this fix).

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7g_chart_markings_contract.py -v
"""
from datetime import datetime, timezone

import pytest

from core.strategy.chart_markings import (
    ChartMarkingError, MARKING_TYPES, add_chart_marking, make_chart_marking, validate_chart_marking,
)


# ---------------------------------------------------------------------------
# Valid marking per type.
# ---------------------------------------------------------------------------

def test_zone_marking_valid():
    m = make_chart_marking("zone", "TestStrategy", "H1", "Demand zone", top=1.2050, bottom=1.2000)
    assert m["type"] == "zone"
    assert m["top"] == 1.2050 and m["bottom"] == 1.2000


def test_level_marking_valid():
    m = make_chart_marking("level", "TestStrategy", "H4", "Broken level", price=1.2500)
    assert m["type"] == "level"
    assert m["price"] == 1.2500


def test_candle_marking_valid_with_timestamp():
    m = make_chart_marking("candle", "TestStrategy", "M15", "Last bias candle", timestamp="2026-01-01T00:00:00Z")
    assert m["timestamp"] == "2026-01-01T00:00:00Z"


def test_candle_marking_valid_with_candle_index():
    m = make_chart_marking("candle", "TestStrategy", "M15", "Last bias candle", candle_index=42)
    assert m["candle_index"] == 42


def test_range_marking_valid_with_timestamps():
    m = make_chart_marking(
        "range", "TestStrategy", "H1", "Pullback leg",
        start_timestamp="2026-01-01T00:00:00Z", end_timestamp="2026-01-01T02:00:00Z",
    )
    assert m["start_timestamp"] and m["end_timestamp"]


def test_range_marking_valid_with_indices():
    m = make_chart_marking("range", "TestStrategy", "H1", "Pullback leg", start_index=10, end_index=15)
    assert m["start_index"] == 10 and m["end_index"] == 15


def test_range_marking_valid_with_both_timestamp_and_index_pairs():
    m = make_chart_marking(
        "range", "TestStrategy", "H1", "Pullback leg",
        start_timestamp="t0", end_timestamp="t1", start_index=10, end_index=15,
    )
    assert m["start_timestamp"] and m["start_index"] == 10


def test_phase_marking_valid():
    m = make_chart_marking(
        "phase", "PowerOf3Strategy", "H1", "Manipulation phase",
        start_timestamp="2026-01-01T00:00:00Z", end_timestamp="2026-01-01T04:00:00Z",
    )
    assert m["type"] == "phase"


def test_structure_marking_valid_with_timestamp():
    m = make_chart_marking("structure", "TestStrategy", "H4", "CHoCH confirmation", timestamp="2026-01-01T00:00:00Z")
    assert m["timestamp"]


def test_structure_marking_valid_with_candle_index():
    m = make_chart_marking("structure", "TestStrategy", "H4", "CHoCH confirmation", candle_index=7)
    assert m["candle_index"] == 7


def test_structure_marking_valid_with_price():
    m = make_chart_marking("structure", "TestStrategy", "H4", "CHoCH confirmation", price=1.3000)
    assert m["price"] == 1.3000


def test_profile_marking_valid_with_poc_only():
    m = make_chart_marking("profile", "VolumeProfileStrategy", "D1", "VPOC", price=1.2345)
    assert m["price"] == 1.2345
    assert "top" not in m and "bottom" not in m


def test_profile_marking_valid_with_value_area_only():
    m = make_chart_marking("profile", "VolumeProfileStrategy", "D1", "Value area", top=1.25, bottom=1.20)
    assert m["top"] == 1.25 and m["bottom"] == 1.20
    assert "price" not in m


def test_profile_marking_valid_with_both():
    m = make_chart_marking(
        "profile", "VolumeProfileStrategy", "D1", "Profile", price=1.22, top=1.25, bottom=1.20,
    )
    assert m["price"] == 1.22 and m["top"] == 1.25 and m["bottom"] == 1.20


# ---------------------------------------------------------------------------
# Invalid geometry rejected.
# ---------------------------------------------------------------------------

def test_zone_missing_bottom_rejected():
    with pytest.raises(ChartMarkingError):
        make_chart_marking("zone", "TestStrategy", "H1", "Demand zone", top=1.2050)


def test_zone_missing_top_rejected():
    with pytest.raises(ChartMarkingError):
        make_chart_marking("zone", "TestStrategy", "H1", "Demand zone", bottom=1.2000)


def test_level_missing_price_rejected():
    with pytest.raises(ChartMarkingError):
        make_chart_marking("level", "TestStrategy", "H4", "Broken level")


def test_candle_missing_both_timestamp_and_index_rejected():
    with pytest.raises(ChartMarkingError):
        make_chart_marking("candle", "TestStrategy", "M15", "Last bias candle")


def test_range_dangling_start_timestamp_without_end_rejected():
    with pytest.raises(ChartMarkingError):
        make_chart_marking("range", "TestStrategy", "H1", "Pullback leg", start_timestamp="t0")


def test_range_dangling_end_index_without_start_rejected():
    with pytest.raises(ChartMarkingError):
        make_chart_marking("range", "TestStrategy", "H1", "Pullback leg", end_index=15)


def test_range_no_geometry_at_all_rejected():
    with pytest.raises(ChartMarkingError):
        make_chart_marking("range", "TestStrategy", "H1", "Pullback leg")


def test_phase_dangling_pair_rejected():
    with pytest.raises(ChartMarkingError):
        make_chart_marking("phase", "PowerOf3Strategy", "H1", "Manipulation phase", start_timestamp="t0")


def test_structure_no_evidence_at_all_rejected():
    with pytest.raises(ChartMarkingError):
        make_chart_marking("structure", "TestStrategy", "H4", "CHoCH confirmation")


def test_profile_no_poc_or_value_area_rejected():
    with pytest.raises(ChartMarkingError):
        make_chart_marking("profile", "VolumeProfileStrategy", "D1", "Profile")


def test_profile_partial_value_area_rejected():
    """top alone (no bottom, no price) is not a usable value area or POC."""
    with pytest.raises(ChartMarkingError):
        make_chart_marking("profile", "VolumeProfileStrategy", "D1", "Profile", top=1.25)


def test_unknown_marking_type_rejected():
    with pytest.raises(ChartMarkingError):
        make_chart_marking("triangle", "TestStrategy", "H1", "Nonsense")


def test_missing_required_field_rejected_via_validate_directly():
    with pytest.raises(ChartMarkingError):
        validate_chart_marking({"type": "level", "strategy": "T", "timeframe": "H1", "label": "", "price": 1.0})


def test_all_marking_types_are_exactly_the_seven_specified():
    assert MARKING_TYPES == {"zone", "level", "candle", "range", "structure", "profile", "phase"}


# ---------------------------------------------------------------------------
# Optional fields omitted cleanly (never filled with None).
# ---------------------------------------------------------------------------

def test_unset_optional_fields_are_omitted_not_none():
    m = make_chart_marking("level", "TestStrategy", "H4", "Broken level", price=1.25)
    for optional_key in (
        "direction", "top", "bottom", "timestamp", "start_timestamp", "end_timestamp",
        "candle_index", "start_index", "end_index", "evidence_ref",
    ):
        assert optional_key not in m, f"{optional_key} should be omitted, not present"
    assert set(m.keys()) == {"type", "strategy", "timeframe", "label", "price"}


def test_evidence_ref_included_only_when_given():
    without = make_chart_marking("level", "TestStrategy", "H4", "Broken level", price=1.25)
    assert "evidence_ref" not in without

    with_ref = make_chart_marking(
        "level", "TestStrategy", "H4", "Broken level", price=1.25,
        evidence_ref={"source": "structure_events", "timeframe": "H4", "index": 3},
    )
    assert with_ref["evidence_ref"] == {"source": "structure_events", "timeframe": "H4", "index": 3}


def test_direction_optional_and_omitted_when_not_directional():
    m = make_chart_marking("profile", "VolumeProfileStrategy", "D1", "VPOC", price=1.25)
    assert "direction" not in m

    directional = make_chart_marking(
        "structure", "TestStrategy", "H4", "CHoCH confirmation", price=1.3, direction="long",
    )
    assert directional["direction"] == "long"


# ---------------------------------------------------------------------------
# Multiple markings per signal.
# ---------------------------------------------------------------------------

def test_one_signal_can_carry_multiple_markings():
    signal = {"symbol": "T", "timeframe": "M15", "direction": "long", "confidence": 0.6}
    m1 = make_chart_marking("zone", "TestStrategy", "H1", "Demand zone", top=1.21, bottom=1.20)
    m2 = make_chart_marking("structure", "TestStrategy", "M15", "BOS confirmation", price=1.205)
    m3 = make_chart_marking("candle", "TestStrategy", "M5", "Trigger candle", candle_index=99)

    add_chart_marking(signal, m1)
    add_chart_marking(signal, m2)
    add_chart_marking(signal, m3)

    assert signal["chart_markings"] == [m1, m2, m3]
    assert len(signal["chart_markings"]) == 3
    # Everything else on the signal is untouched.
    assert signal["symbol"] == "T"
    assert signal["confidence"] == 0.6


def test_add_chart_marking_returns_the_signal_for_chaining():
    signal = {"symbol": "T"}
    m = make_chart_marking("level", "TestStrategy", "H1", "Level", price=1.0)
    result = add_chart_marking(signal, m)
    assert result is signal


# ---------------------------------------------------------------------------
# Existing strategy result without chart_markings still valid; additive
# contract does not alter current strategy outputs.
# ---------------------------------------------------------------------------

def _base_snapshot(**overrides):
    from core.strategy.strategy_models import StrategySnapshot
    base = dict(
        symbol="T", timeframe="M5", bias="Bullish", momentum=5.0, strength=5.0,
        suppression=False, suppression_reason="",
        structure_type="BOS", structure_direction="Bullish", structure_valid=True,
        context_zone="demand", context_level=1.0, timestamp=datetime.now(timezone.utc),
        current_high=1.1, current_low=0.9, snr_strength=0.0, atr_normalized_momentum=1.0,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


def test_double_engulfing_output_has_no_chart_markings_key():
    from core.strategy.DoubleEngulfingStrategy import DoubleEngulfingStrategy
    snap = _base_snapshot(timeframe="M15", engulfing_sequence=["bull", "bull"], engulfing_strength="Weak")
    result = DoubleEngulfingStrategy().react(snap, {})
    assert result is not None
    assert "chart_markings" not in result
    assert set(result.keys()) == {"symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price"}


def test_zone_continuation_output_has_no_chart_markings_key():
    from core.strategy.ZoneContinuationStrategy import ZoneContinuationStrategy
    htf = _base_snapshot(timeframe="H1", context_zone="demand")
    ctx = {"T_H1": htf, "T_H4": htf}
    snap = _base_snapshot(timeframe="M5", structure_type="breakout", structure_direction="Bullish", structure_valid=True)
    result = ZoneContinuationStrategy().react(snap, ctx)
    assert result is not None
    assert "chart_markings" not in result


def test_bias_continuation_scalping_output_has_no_chart_markings_key():
    from core.strategy.BiasContinuationScalpingStrategy import BiasContinuationScalpingStrategy
    anchor = _base_snapshot(timeframe="H1", bias="Bullish")
    ctx = {"T_H1": anchor, "T_H4": anchor}
    snap = _base_snapshot(timeframe="M5", bias="Bullish", structure_type="BOS", structure_direction="Bullish")
    result = BiasContinuationScalpingStrategy().react(snap, ctx)
    assert result is not None
    assert "chart_markings" not in result
    assert "style" in result  # unchanged pre-existing additive key, unaffected by this fix


def test_all_seven_strategy_files_do_not_import_chart_markings_yet():
    """Fix #7G explicitly does not retrofit the existing 7 -- confirms none
    of them reference the new module."""
    import pathlib
    plugin_dir = pathlib.Path("core/strategy")
    for name in [
        "BiasContinuationScalpingStrategy.py", "BiasContinuationSwingStrategy.py",
        "DoubleEngulfingStrategy.py", "ZoneContinuationStrategy.py",
        "ScalpingBiasCascade.py", "GroupedLastCandleBiasStrategy.py", "LastCandleBiasStrategy.py",
    ]:
        text = (plugin_dir / name).read_text(encoding="utf-8")
        assert "chart_markings" not in text, f"{name} unexpectedly references chart_markings"


def test_strategy_engine_discovery_unchanged_by_new_module():
    """The new chart_markings.py file defines no Strategy subclass, so
    StrategyEngine._discover_strategies() (which auto-loads every .py file
    in this package) must still find exactly the same 7 strategies."""
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert set(engine.enabled.keys()) == {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
    }


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
