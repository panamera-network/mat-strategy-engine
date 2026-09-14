"""Fix #6BN — removed two items proven dead/inert by Fix #6BL:

1. StyleSnapshot.engulfing_sequence: declared but never populated by
   StyleEngine.get_style_snapshot() -- always None, and always stripped
   from /core/output and /core/slim by strip_nulls() before a caller ever
   sees it. StructureSnapshot.engulfing_sequence (a separate, genuinely
   populated field feeding core/strategy/) is untouched.
2. swing_diag.py's normalize_struct_label() call before the
   structure_ok = label in {"BOS", "CHOCH"} check: proven inert, since
   normalize_struct_label() only changes None->"None" and
   "neutral"->"Neutral", neither of which affects membership in
   {"BOS", "CHOCH"}. build_scalping.py's equivalent check already reads
   structure_label raw with no normalization and produces the identical
   result.

Fix #6BO — this file originally asserted StructureSnapshot.engulfing_sequence
must exist. That field turned out to belong to separate, still-uncommitted
ambient WIP (leg_origin/origin_zone/pre_break_trend-adjacent structure work),
not to anything Fix #6BN's own commit added or depends on. Asserting its
existence made this test file fail on a fresh checkout of committed history
(or any environment without that unrelated WIP applied) -- a false regression
signal for a commit that never touched StructureSnapshot at all. The
assertion was rewritten to be conditional: it checks the field's default only
when the field happens to be present, and asserts nothing otherwise. Fix #6BN
itself never added, removed, or depends on StructureSnapshot.engulfing_sequence
-- see core/core_models.py and core/Output/swing_diag.py, both outside this
fix's scope.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_6bn_dead_field_and_inert_normalization.py -v
"""
import dataclasses

from core.core_models import StyleSnapshot, StructureSnapshot
from core.Output.diagnostic_models import normalize_struct_label
from core.Output.swing_diag import enrich_swing_with_diagnostic


# ---------------------------------------------------------------------------
# Change 1 — StyleSnapshot.engulfing_sequence removed;
# StructureSnapshot.engulfing_sequence untouched.
# ---------------------------------------------------------------------------

def test_style_snapshot_has_no_engulfing_sequence_field():
    field_names = {f.name for f in dataclasses.fields(StyleSnapshot)}
    assert "engulfing_sequence" not in field_names


def test_structure_snapshot_engulfing_sequence_untouched_if_present():
    """StructureSnapshot.engulfing_sequence belongs to separate, currently
    still-uncommitted ambient WIP -- not something Fix #6BN added, removed,
    or depends on. This must never require the field to exist (that would
    make this regression guard depend on unrelated uncommitted work, which
    is exactly what broke it before Fix #6BO). When the field IS present
    (e.g. in the current working-tree/WIP environment), confirm Fix #6BN
    left its default untouched; when it is absent (e.g. a fresh checkout
    of committed history without that unrelated WIP), there is nothing to
    assert -- and that is the correct, passing outcome."""
    fields_by_name = {f.name: f for f in dataclasses.fields(StructureSnapshot)}
    if "engulfing_sequence" in fields_by_name:
        assert fields_by_name["engulfing_sequence"].default is None


def test_style_snapshot_constructs_fine_without_engulfing_sequence_kwarg():
    """StyleEngine.get_style_snapshot() never passed engulfing_sequence=
    to begin with -- confirms the field's removal doesn't break the one
    live construction site's calling convention."""
    snap = StyleSnapshot(
        symbol="T", timeframe="M15", mode="swing", direction="uptrend",
        momentum=1.0, bias=2.0,
    )
    assert not hasattr(snap, "engulfing_sequence")


def test_live_output_and_slim_never_expose_engulfing_sequence():
    """engulfing_sequence was always None on StyleSnapshot and always
    stripped by strip_nulls() before reaching a consumer -- confirms it
    never appeared in the live per-tf output, before or after removal."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output
    from mt5.constants import TIMEFRAMES

    symbol = "XAUUSD_i"
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], TIMEFRAMES, count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=[symbol],
    )
    block = out[symbol]
    assert "error" not in block

    for section in ("scalping", "swing"):
        for tf, vals in block[section].items():
            if tf == "diagnostic" or not isinstance(vals, dict):
                continue
            assert "engulfing_sequence" not in vals


# ---------------------------------------------------------------------------
# Change 2 — structure_ok behavior identical for every input, with or
# without normalize_struct_label().
# ---------------------------------------------------------------------------

def _swing_map_with_structure_label(structure_label):
    h1_snap = {"direction": "uptrend", "structure_label": "None", "atr_normalized_momentum": 0.0, "bias": 0.0}
    h4_snap = {
        "direction": "uptrend", "structure_label": structure_label,
        "atr_normalized_momentum": 0.0, "shift_confirmed": False,
        "demand": "neutral", "suppression": False,
    }
    d1_snap = {"direction": "uptrend", "structure_label": "None"}
    return {"H1": h1_snap, "H4": h4_snap, "D1": d1_snap}


def _bias_map_stub():
    return {
        "H1": {"bias_label": "up", "strength_diagnostic": None},
        "H4": {"bias_label": "up", "strength_diagnostic": None},
        "D1": {"bias_label": "up", "strength_diagnostic": None},
    }


def test_structure_ok_identical_for_all_representative_structure_labels():
    test_values = ["BOS", "CHOCH", "Neutral", "neutral", None, "unknown", "trend"]
    for value in test_values:
        swing_map = _swing_map_with_structure_label(value)
        result = enrich_swing_with_diagnostic(
            symbol="T", swing_map=swing_map, bias_map=_bias_map_stub(), prev_bias_map=None,
        )
        actual_structure_ok = result["diagnostic"]["checks"]["structure_ok"]

        # Re-derive what the OLD code (with normalize_struct_label()) would
        # have produced for this same input, to prove equivalence directly.
        old_normalized = normalize_struct_label(value if value is not None else "None")
        expected_structure_ok = old_normalized in {"BOS", "CHOCH"}

        assert actual_structure_ok == expected_structure_ok, (
            f"structure_label={value!r}: got {actual_structure_ok}, "
            f"old normalize_struct_label()-based result was {expected_structure_ok}"
        )

    # BOS/CHOCH must be True; everything else False -- pin the actual
    # semantics, not just old-vs-new equivalence.
    expectations = {
        "BOS": True, "CHOCH": True, "Neutral": False, "neutral": False,
        None: False, "unknown": False, "trend": False,
    }
    for value, expected in expectations.items():
        swing_map = _swing_map_with_structure_label(value)
        result = enrich_swing_with_diagnostic(
            symbol="T", swing_map=swing_map, bias_map=_bias_map_stub(), prev_bias_map=None,
        )
        assert result["diagnostic"]["checks"]["structure_ok"] is expected


def test_alignment_text_still_reads_raw_structure_label_unaffected():
    """The separately-displayed alignment string was never touched by
    normalize_struct_label() (it re-reads structure_label raw at its own
    call site) -- confirm this fix didn't change that."""
    swing_map = _swing_map_with_structure_label("CHOCH")
    result = enrich_swing_with_diagnostic(
        symbol="T", swing_map=swing_map, bias_map=_bias_map_stub(), prev_bias_map=None,
    )
    assert "CHOCH" in result["diagnostic"]["alignment"]


def test_live_swing_diagnostic_structure_ok_matches_raw_label():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output
    from mt5.constants import TIMEFRAMES

    symbols = ["XAUUSD_i", "BTCUSD_i", "EURUSD_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, TIMEFRAMES, count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=symbols,
    )
    checked_any = False
    for symbol in symbols:
        block = out[symbol]
        if "error" in block:
            continue
        h4 = block["swing"].get("H4", {})
        raw_label = h4.get("structure_label", "None")
        structure_ok = block["swing"]["diagnostic"]["checks"]["structure_ok"]
        assert structure_ok == (raw_label in {"BOS", "CHOCH"})
        checked_any = True
    assert checked_any


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
