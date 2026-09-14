"""Fix #6BM — removed two dead _normalize_snapshot() rename branches
(conviction_breakdown["demand"]->"zone_score", checks["demand_supports"]->
"zone_supports") and _build_bias_ordered()'s dead score_color computation,
all proven unreachable by Fix #6BL's audit. Zero output behavior change
intended -- this file proves that empirically:

1. The removed _normalize_snapshot() branches never fired on realistic
   input (live-constructed StyleSnapshot dicts never contain a "checks"
   key, and conviction_breakdown never contains a "demand" key), so
   removing them changes nothing for real data.
2. The live demand->zone rename (the one KEPT branch) still works.
3. _build_bias_ordered() no longer emits its own score_color at all.
4. The final score_color a caller sees is produced exclusively by
   add_display_percentages() regardless of what (if anything)
   _build_bias_ordered() wrote first -- proven by seeding a deliberately
   wrong marker value and confirming it never survives.
5. A live /core/output symbol's checks/conviction_breakdown keys are
   exactly what Fix #6BL's audit said they'd be (demand_supports, never
   renamed; zone_score for swing conviction, no "demand" key anywhere).

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_6bm_dead_normalization_removed.py -v
"""
from dataclasses import asdict

from core.Output.helper import add_display_percentages, pct_to_color, scale_to_pct
from core.Output.Output import _build_bias_ordered, _normalize_snapshot, MAX_BIAS
from core.Output.diagnostic_models import BIAS_ORDER, SCALPING_ORDER, SWING_ORDER


# ---------------------------------------------------------------------------
# The removed branches never fired on realistic input.
# ---------------------------------------------------------------------------

def test_live_style_snapshot_never_has_checks_key():
    """A raw per-tf StyleSnapshot (what _normalize_snapshot() actually
    receives) has no "checks" field at all -- the checks["demand_supports"]
    branch could never have fired on this input shape."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.StyleEngine import get_style_snapshot

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    checked_any = False
    for tf in timeframes:
        mode = "scalping" if tf in ("M1", "M5", "M15", "M30") else "swing"
        snap = get_style_snapshot(
            symbol, tf, mode, cr.bias_engine, cr.momentum_engine,
            cr.demand_engine, cr.structure_engine, cr.shift_engine, cache=cache,
        )
        snap_dict = asdict(snap)
        assert "checks" not in snap_dict
        checked_any = True
    assert checked_any


def test_live_conviction_breakdown_never_has_demand_key():
    """compute_conviction() (core_models.py) already names its zone/demand
    term "zone_score" directly for swing mode, and scalping mode's
    breakdown has no zone/demand term at all -- confirmed live, across
    both modes, that "demand" never appears as a conviction_breakdown key."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.StyleEngine import get_style_snapshot

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    checked_any = False
    for tf in timeframes:
        mode = "scalping" if tf in ("M1", "M5", "M15", "M30") else "swing"
        snap = get_style_snapshot(
            symbol, tf, mode, cr.bias_engine, cr.momentum_engine,
            cr.demand_engine, cr.structure_engine, cr.shift_engine, cache=cache,
        )
        assert "demand" not in snap.conviction_breakdown
        if mode == "swing":
            assert "zone_score" in snap.conviction_breakdown
        checked_any = True
    assert checked_any


# ---------------------------------------------------------------------------
# The one KEPT rename (demand -> zone) still works.
# ---------------------------------------------------------------------------

def test_demand_to_zone_rename_still_works():
    fake_snapshot = {"demand": "strong buy", "momentum": 1.23456, "atr_normalized_momentum": 0.7}
    result = _normalize_snapshot(fake_snapshot)
    assert "demand" not in result
    assert result["zone"] == "strong buy"


def test_normalize_snapshot_no_longer_renames_checks_or_breakdown_even_if_present():
    """Documents the removed behavior explicitly: if a caller ever DID pass
    a "checks"/"demand"-shaped dict in (which no real caller does -- see
    the live tests above), the old rename would no longer happen. This is
    the intended, in-scope behavior change for keys that were never
    reachable in production; it does not affect any real output."""
    fake_snapshot = {
        "demand": "neutral",
        "checks": {"demand_supports": True},
        "conviction_breakdown": {"demand": 0.3},
    }
    result = _normalize_snapshot(fake_snapshot)
    assert result["zone"] == "neutral"
    assert result["checks"] == {"demand_supports": True}
    assert result["conviction_breakdown"] == {"demand": 0.3}


# ---------------------------------------------------------------------------
# _build_bias_ordered() no longer emits its own score_color.
# ---------------------------------------------------------------------------

def test_build_bias_ordered_no_longer_sets_score_color():
    bias_map = {
        "M1": {"bias_score": 2.5, "bias_label": "up", "strength_diagnostic": None},
    }
    bias_ordered = _build_bias_ordered(bias_map)
    assert "score_color" not in bias_ordered["M1"]
    assert bias_ordered["M1"]["score"] == 2.5


# ---------------------------------------------------------------------------
# The final score_color is produced exclusively by add_display_percentages(),
# regardless of what _build_bias_ordered() did or didn't write first.
# ---------------------------------------------------------------------------

def _minimal_symbol_block(score_color_seed=None):
    bias_tf = {"label": "up", "score": 2.5, "strength": 1.0, "body_dominance": 0.5}
    if score_color_seed is not None:
        bias_tf["score_color"] = score_color_seed
    bias = {tf: dict(bias_tf) for tf in BIAS_ORDER}

    scalping_diag = {"cascade_score": 0.5}
    scalping = {"diagnostic": scalping_diag}
    for tf in SCALPING_ORDER:
        scalping[tf] = {"atr_normalized_momentum": 0.3, "bias": 1.0}

    swing_diag = {"conviction_score": 0.5}
    swing = {"diagnostic": swing_diag}
    for tf in SWING_ORDER:
        swing[tf] = {"atr_normalized_momentum": 0.3, "bias": 1.0}

    return {"bias": bias, "scalping": scalping, "swing": swing}


def test_final_score_color_matches_add_display_percentages_formula():
    block = _minimal_symbol_block()
    result = add_display_percentages(block, "XAUUSD_i")
    from core.Output.helper import get_display_max
    bias_max = get_display_max("XAUUSD_i", "bias")
    expected_pct = scale_to_pct(2.5, bias_max["bias_score"], -bias_max["bias_score"])
    expected_color = pct_to_color(expected_pct, directional=True)
    for tf in BIAS_ORDER:
        assert result["bias"][tf]["score_color"] == expected_color


def test_final_score_color_ignores_and_overwrites_any_seeded_value():
    """Proves the removed _build_bias_ordered() score_color line could
    never have influenced the final output: even a deliberately wrong
    marker value seeded in its place is unconditionally overwritten."""
    block_with_marker = _minimal_symbol_block(score_color_seed="MARKER_NOT_A_REAL_COLOR")
    block_without = _minimal_symbol_block(score_color_seed=None)

    result_with_marker = add_display_percentages(block_with_marker, "XAUUSD_i")
    result_without = add_display_percentages(block_without, "XAUUSD_i")

    for tf in BIAS_ORDER:
        assert result_with_marker["bias"][tf]["score_color"] != "MARKER_NOT_A_REAL_COLOR"
        assert result_with_marker["bias"][tf]["score_color"] == result_without["bias"][tf]["score_color"]


# ---------------------------------------------------------------------------
# Live end-to-end: checks/conviction_breakdown shapes exactly as Fix #6BL
# documented, unaffected by this fix.
# ---------------------------------------------------------------------------

def test_live_output_checks_and_breakdown_shapes_unchanged():
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

    scalping_checks = block["scalping"]["diagnostic"]["checks"]
    assert "demand_supports" in scalping_checks
    assert "zone_supports" not in scalping_checks

    swing_checks = block["swing"]["diagnostic"]["checks"]
    assert "demand_supports" in swing_checks
    assert "zone_supports" not in swing_checks

    for tf, vals in block["bias"].items():
        if "score" in vals:
            assert "score_color" in vals


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
