"""Fix #6AQ — build_scalping.py's and swing_diag.py's momentum_ok check
migrated from raw, per-instrument-scale-dependent StyleSnapshot.momentum
(compared against cfg.t_momentum_min=0.3) to canonical, instrument-scale-
independent atr_normalized_momentum (compared against the new
cfg.t_momentum_min_atr=0.5 -- the existing weak/moderate ATR boundary,
Fix #6Z).

Fix #6AP's audit found the old raw comparison structurally broken across
instruments: EURUSD/GBPUSD raw momentum sits in the 0.0002-0.004 range even
during genuinely strong (ATR-normalized >1.0) moves, so momentum_ok was
almost always False for FX regardless of true strength; BTCUSD raw momentum
routinely exceeds 100, so momentum_ok was almost always True regardless of
true strength.

momentum_ok's own semantic (preserved, not just its numeric threshold):
"meaningful momentum IN THE UP direction this diagnostic evaluates" --
every other check in both functions (bias_*_up, *_flip_up) is up-only, so
this stays a signed ">=" against a positive threshold, never abs() >=.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_diagnostic_momentum_ok_atr_migration.py -v
"""
from core.core_models import StyleSnapshot
from core.Output.build_scalping import build_scalping_diagnostic
from core.Output.diagnostic_models import ScalpCfg
from core.Output.swing_diag import enrich_swing_with_diagnostic

CFG = ScalpCfg()


def make_bias_entry(label="neutral"):
    return {"bias_label": label, "strength_diagnostic": None}


# ---------------------------------------------------------------------------
# build_scalping.py::build_scalping_diagnostic() — scalping_map holds real
# StyleSnapshot objects (attribute access), per Output.py's own call shape.
# ---------------------------------------------------------------------------

def make_style_snapshot(tf, momentum=0.0, atr_normalized_momentum=None):
    return StyleSnapshot(
        symbol="FIX6AQ_TEST", timeframe=tf, mode="scalping", direction="neutral",
        momentum=momentum, bias=0.0, demand="neutral",
        structure_label="None", shift_confirmed=False, zone_interaction=False,
        atr_normalized_momentum=atr_normalized_momentum,
    )


def _run_build_scalping(m1_raw, m1_atr, m5_raw, m5_atr):
    scalping_map = {
        "M1": make_style_snapshot("M1", momentum=m1_raw, atr_normalized_momentum=m1_atr),
        "M5": make_style_snapshot("M5", momentum=m5_raw, atr_normalized_momentum=m5_atr),
        "M15": make_style_snapshot("M15"),
        "M30": make_style_snapshot("M30"),
    }
    bias_map = {tf: make_bias_entry() for tf in ("M1", "M5", "M15")}
    result = build_scalping_diagnostic(symbol="FIX6AQ_BS", scalping_map=scalping_map, bias_map=bias_map, cfg=CFG)
    return result["diagnostic"]


def test_build_scalping_momentum_ok_true_at_and_above_moderate_boundary():
    diag = _run_build_scalping(m1_raw=0.0, m1_atr=0.5, m5_raw=0.0, m5_atr=0.5)
    assert diag["checks"]["momentum_ok"] is True


def test_build_scalping_momentum_ok_false_just_below_moderate_boundary():
    diag = _run_build_scalping(m1_raw=0.0, m1_atr=0.4999, m5_raw=0.0, m5_atr=0.4999)
    assert diag["checks"]["momentum_ok"] is False


def test_build_scalping_momentum_ok_requires_both_tfs():
    diag = _run_build_scalping(m1_raw=0.0, m1_atr=2.0, m5_raw=0.0, m5_atr=0.2)
    assert diag["checks"]["momentum_ok"] is False


def test_build_scalping_momentum_ok_ignores_raw_scale_fx_case():
    """FX-scale raw momentum (tiny, price-unit) must not block a genuinely
    strong ATR-normalized reading -- the exact EURUSD/GBPUSD case Fix #6AP
    found broken under the old raw >= 0.3 comparison."""
    diag = _run_build_scalping(m1_raw=0.00015, m1_atr=1.5, m5_raw=0.00096, m5_atr=2.2)
    assert diag["checks"]["momentum_ok"] is True


def test_build_scalping_momentum_ok_ignores_raw_scale_crypto_case():
    """Crypto-scale raw momentum (huge, price-unit) must not manufacture a
    pass when true ATR-normalized strength is weak -- the exact BTCUSD case
    Fix #6AP found broken under the old raw >= 0.3 comparison."""
    diag = _run_build_scalping(m1_raw=500.0, m1_atr=0.1, m5_raw=300.0, m5_atr=0.2)
    assert diag["checks"]["momentum_ok"] is False


def test_build_scalping_momentum_ok_signed_not_abs():
    """Strong BEARISH momentum must not satisfy momentum_ok -- every other
    check in this diagnostic (bias_m1_up, bias_m5_up, m5_flip_up_on_close)
    is up-only, so momentum_ok must stay direction-gated, not magnitude-only."""
    diag = _run_build_scalping(m1_raw=0.0, m1_atr=-5.0, m5_raw=0.0, m5_atr=-5.0)
    assert diag["checks"]["momentum_ok"] is False


def test_build_scalping_momentum_ok_none_atr_is_not_ok():
    diag = _run_build_scalping(m1_raw=100.0, m1_atr=None, m5_raw=100.0, m5_atr=None)
    assert diag["checks"]["momentum_ok"] is False


def test_build_scalping_thresholds_expose_new_atr_key_and_keep_old_key():
    diag = _run_build_scalping(m1_raw=0.0, m1_atr=1.0, m5_raw=0.0, m5_atr=1.0)
    assert diag["thresholds"]["t_momentum_min_atr"] == 0.5
    assert diag["thresholds"]["t_momentum_min"] == 0.3  # compatibility field, unchanged


def test_build_scalping_checks_key_count_unchanged():
    """Guard against accidentally adding/removing a checks key -- cascade_score
    reads an explicit named list, but the checks dict shape itself should
    still carry exactly the same 12 keys as before this fix (includes
    zone_interaction_ok, unlike swing_diag.py's 11 -- Fix #6E)."""
    diag = _run_build_scalping(m1_raw=0.0, m1_atr=1.0, m5_raw=0.0, m5_atr=1.0)
    assert len(diag["checks"]) == 12


# ---------------------------------------------------------------------------
# swing_diag.py::enrich_swing_with_diagnostic() — swing_map holds dicts
# (Output.py normalizes via _normalize_snapshot before calling this).
# ---------------------------------------------------------------------------

def make_swing_snap(sl="None", sh=False, momentum=0.0, atr=None):
    return {
        "structure_label": sl, "shift_confirmed": sh, "demand": "neutral",
        "suppression": False, "momentum": momentum, "atr_normalized_momentum": atr,
        "direction": "Neutral",
    }


def _run_swing_diag(h1_raw, h1_atr, h4_raw, h4_atr):
    swing_map = {
        "H1": make_swing_snap(momentum=h1_raw, atr=h1_atr),
        "H4": make_swing_snap(momentum=h4_raw, atr=h4_atr),
        "D1": make_swing_snap(),
    }
    bias_map = {tf: make_bias_entry() for tf in ("H1", "H4", "D1")}
    result = enrich_swing_with_diagnostic(symbol="FIX6AQ_SW", swing_map=swing_map, bias_map=bias_map, cfg=CFG)
    return result["diagnostic"]


def test_swing_diag_momentum_ok_true_at_and_above_moderate_boundary():
    diag = _run_swing_diag(h1_raw=0.0, h1_atr=0.5, h4_raw=0.0, h4_atr=0.5)
    assert diag["checks"]["momentum_ok"] is True


def test_swing_diag_momentum_ok_false_just_below_moderate_boundary():
    diag = _run_swing_diag(h1_raw=0.0, h1_atr=0.4999, h4_raw=0.0, h4_atr=0.4999)
    assert diag["checks"]["momentum_ok"] is False


def test_swing_diag_momentum_ok_ignores_raw_scale_fx_case():
    diag = _run_swing_diag(h1_raw=-0.00085, h1_atr=0.83, h4_raw=-0.0026, h4_atr=1.14)
    assert diag["checks"]["momentum_ok"] is True


def test_swing_diag_momentum_ok_ignores_raw_scale_crypto_case():
    diag = _run_swing_diag(h1_raw=642.0, h1_atr=0.1, h4_raw=736.0, h4_atr=0.2)
    assert diag["checks"]["momentum_ok"] is False


def test_swing_diag_momentum_ok_signed_not_abs():
    diag = _run_swing_diag(h1_raw=0.0, h1_atr=-2.0, h4_raw=0.0, h4_atr=-2.0)
    assert diag["checks"]["momentum_ok"] is False


def test_swing_diag_momentum_ok_none_atr_is_not_ok():
    diag = _run_swing_diag(h1_raw=642.0, h1_atr=None, h4_raw=736.0, h4_atr=None)
    assert diag["checks"]["momentum_ok"] is False


def test_swing_diag_thresholds_expose_new_atr_key_and_keep_old_key():
    diag = _run_swing_diag(h1_raw=0.0, h1_atr=1.0, h4_raw=0.0, h4_atr=1.0)
    assert diag["thresholds"]["t_momentum_min_atr"] == 0.5
    assert diag["thresholds"]["t_momentum_min"] == 0.3


def test_swing_diag_checks_key_count_unchanged():
    diag = _run_swing_diag(h1_raw=0.0, h1_atr=1.0, h4_raw=0.0, h4_atr=1.0)
    assert len(diag["checks"]) == 11


# ---------------------------------------------------------------------------
# Cross-instrument symmetry: identical atr_normalized_momentum must produce
# the identical momentum_ok result regardless of what raw price scale it
# came from -- FX (tiny), JPY (small), metals (mid), crypto (huge).
# ---------------------------------------------------------------------------

def test_build_scalping_symmetry_same_atr_different_raw_scale_same_result():
    fx = _run_build_scalping(m1_raw=0.0002, m1_atr=0.9, m5_raw=0.0004, m5_atr=0.9)
    jpy = _run_build_scalping(m1_raw=0.03, m1_atr=0.9, m5_raw=0.06, m5_atr=0.9)
    metals = _run_build_scalping(m1_raw=3.0, m1_atr=0.9, m5_raw=6.0, m5_atr=0.9)
    crypto = _run_build_scalping(m1_raw=300.0, m1_atr=0.9, m5_raw=600.0, m5_atr=0.9)
    results = {fx["checks"]["momentum_ok"], jpy["checks"]["momentum_ok"],
               metals["checks"]["momentum_ok"], crypto["checks"]["momentum_ok"]}
    assert results == {True}


def test_swing_diag_symmetry_same_atr_different_raw_scale_same_result():
    fx = _run_swing_diag(h1_raw=0.0003, h1_atr=0.2, h4_raw=0.0006, h4_atr=0.2)
    jpy = _run_swing_diag(h1_raw=0.05, h1_atr=0.2, h4_raw=0.1, h4_atr=0.2)
    metals = _run_swing_diag(h1_raw=5.0, h1_atr=0.2, h4_raw=10.0, h4_atr=0.2)
    crypto = _run_swing_diag(h1_raw=500.0, h1_atr=0.2, h4_raw=1000.0, h4_atr=0.2)
    results = {fx["checks"]["momentum_ok"], jpy["checks"]["momentum_ok"],
               metals["checks"]["momentum_ok"], crypto["checks"]["momentum_ok"]}
    assert results == {False}  # all below the 0.5 moderate boundary, regardless of raw scale


# ---------------------------------------------------------------------------
# Live regression: real pipeline, real MT5 data, across FX/JPY/metals/crypto.
# ---------------------------------------------------------------------------

def test_live_momentum_ok_matches_recomputed_atr_gate():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.StyleEngine import get_style_snapshot
    from core.Output.Output import _normalize_snapshot_map, SCALPING_ORDER, SWING_ORDER, BIAS_ORDER
    from mt5.constants import TIMEFRAMES

    symbols = ["EURUSD_i", "GBPUSD_i", "USDJPY_i", "XAUUSD_i", "BTCUSD_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, BIAS_ORDER, count=100)

    checked_any = False
    for symbol in symbols:
        structure_map = {}
        for tf in BIAS_ORDER:
            s = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
            if s:
                structure_map[tf] = s

        bias_map = cr.bias_engine.get_bias_map(symbol, TIMEFRAMES, structure_map=structure_map, cache=cache)

        scalping_map = {
            tf: get_style_snapshot(symbol, tf, "scalping", cr.bias_engine, cr.momentum_engine, cr.demand_engine,
                                    cr.structure_engine, cr.shift_engine, cache=cache,
                                    structure_snapshot=structure_map.get(tf))
            for tf in SCALPING_ORDER
        }
        result = build_scalping_diagnostic(symbol=symbol, scalping_map=scalping_map, bias_map=bias_map, cfg=CFG)
        m1_atr = scalping_map["M1"].atr_normalized_momentum
        m5_atr = scalping_map["M5"].atr_normalized_momentum
        expected = (m1_atr is not None and m5_atr is not None
                    and m1_atr >= CFG.t_momentum_min_atr and m5_atr >= CFG.t_momentum_min_atr)
        assert result["diagnostic"]["checks"]["momentum_ok"] == expected
        checked_any = True

        swing_map_raw = {
            tf: get_style_snapshot(symbol, tf, "swing", cr.bias_engine, cr.momentum_engine, cr.demand_engine,
                                    cr.structure_engine, cr.shift_engine, cache=cache,
                                    structure_snapshot=structure_map.get(tf))
            for tf in SWING_ORDER
        }
        swing_map = _normalize_snapshot_map(swing_map_raw)
        swing_result = enrich_swing_with_diagnostic(symbol=symbol, swing_map=swing_map, bias_map=bias_map, cfg=CFG)
        h1_atr = swing_map_raw["H1"].atr_normalized_momentum
        h4_atr = swing_map_raw["H4"].atr_normalized_momentum
        expected_swing = (h1_atr is not None and h4_atr is not None
                           and h1_atr >= CFG.t_momentum_min_atr and h4_atr >= CFG.t_momentum_min_atr)
        assert swing_result["diagnostic"]["checks"]["momentum_ok"] == expected_swing

    assert checked_any


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
