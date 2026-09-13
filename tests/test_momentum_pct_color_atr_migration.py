"""Fix #6AC — targeted tests for migrating the LIVE momentum_pct/momentum_color
path (Fix #6AA's "scheme C", core/Output/helper.py's add_display_percentages())
to canonical atr_normalized_momentum, against a single shared 2.0 ATR
presentation reference instead of the old per-mode 50.0 (scalping) /
2000.0 (swing) split.

Scope: ONLY the live momentum_pct/momentum_color in helper.py migrate.
momentum_conf (Fix #6AB), momentum_band (Fix #6Z), the dead scheme A in
Output.py's _normalize_snapshot(), MAX_MOMENTUM, display_max_config's
momentum entries, Alignment, conviction, and Suppression/Strategy are all
untouched by this fix -- tests below explicitly confirm several of these.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_momentum_pct_color_atr_migration.py -v
"""
from core.Output.helper import (
    add_display_percentages,
    scale_to_pct,
    pct_to_color,
    MOMENTUM_PCT_ATR_REFERENCE,
    display_max_config,
)
from core.Output.diagnostic_models import BIAS_ORDER, SCALPING_ORDER, SWING_ORDER


def _make_block(scalping_moms: dict = None, swing_moms: dict = None, legacy_momentum=None):
    """Build a minimal symbol_block shape add_display_percentages() expects:
    bias section (needed so its loop doesn't KeyError), scalping/swing
    diagnostic dicts, and per-tf snapshots carrying atr_normalized_momentum
    (and optionally a legacy `momentum` key, to prove it's ignored)."""
    scalping_moms = scalping_moms or {}
    swing_moms = swing_moms or {}

    block = {
        "bias": {tf: {} for tf in BIAS_ORDER},
        "scalping": {"diagnostic": {"score": 0.0}},
        "swing": {"diagnostic": {"score": 0.0}},
    }
    for tf in SCALPING_ORDER:
        snap = {"bias": 0.0}
        if tf in scalping_moms:
            snap["atr_normalized_momentum"] = scalping_moms[tf]
        if legacy_momentum is not None:
            snap["momentum"] = legacy_momentum
        block["scalping"][tf] = snap
    for tf in SWING_ORDER:
        snap = {"bias": 0.0}
        if tf in swing_moms:
            snap["atr_normalized_momentum"] = swing_moms[tf]
        if legacy_momentum is not None:
            snap["momentum"] = legacy_momentum
        block["swing"][tf] = snap
    return block


# ---------------------------------------------------------------------------
# Constant
# ---------------------------------------------------------------------------

def test_atr_reference_is_2_0():
    assert MOMENTUM_PCT_ATR_REFERENCE == 2.0


# ---------------------------------------------------------------------------
# Exact signed percentage boundaries (scalping)
# ---------------------------------------------------------------------------

def test_plus_0_5_atr_is_plus_25_pct():
    block = _make_block(scalping_moms={"M1": 0.5})
    out = add_display_percentages(block, "TESTSYM")
    assert out["scalping"]["M1"]["momentum_pct"] == 25.0


def test_minus_0_5_atr_is_minus_25_pct():
    block = _make_block(scalping_moms={"M1": -0.5})
    out = add_display_percentages(block, "TESTSYM")
    assert out["scalping"]["M1"]["momentum_pct"] == -25.0


def test_plus_1_0_atr_is_plus_50_pct():
    block = _make_block(scalping_moms={"M1": 1.0})
    out = add_display_percentages(block, "TESTSYM")
    assert out["scalping"]["M1"]["momentum_pct"] == 50.0


def test_minus_1_0_atr_is_minus_50_pct():
    block = _make_block(scalping_moms={"M1": -1.0})
    out = add_display_percentages(block, "TESTSYM")
    assert out["scalping"]["M1"]["momentum_pct"] == -50.0


def test_plus_2_0_atr_is_plus_100_pct():
    block = _make_block(scalping_moms={"M1": 2.0})
    out = add_display_percentages(block, "TESTSYM")
    assert out["scalping"]["M1"]["momentum_pct"] == 100.0


def test_minus_2_0_atr_is_minus_100_pct():
    block = _make_block(scalping_moms={"M1": -2.0})
    out = add_display_percentages(block, "TESTSYM")
    assert out["scalping"]["M1"]["momentum_pct"] == -100.0


# ---------------------------------------------------------------------------
# Clamp beyond +/-2.0 ATR -- never exceeds +/-100
# ---------------------------------------------------------------------------

def test_beyond_2_0_atr_clamps_to_100_never_exceeds():
    for extreme in (2.0001, 5.0, 50.0, 9328.57):
        block = _make_block(scalping_moms={"M1": extreme})
        out = add_display_percentages(block, "TESTSYM")
        assert out["scalping"]["M1"]["momentum_pct"] == 100.0, f"extreme={extreme}"


def test_beyond_minus_2_0_atr_clamps_to_minus_100_never_exceeds():
    for extreme in (-2.0001, -5.0, -50.0, -9328.57):
        block = _make_block(scalping_moms={"M1": extreme})
        out = add_display_percentages(block, "TESTSYM")
        assert out["scalping"]["M1"]["momentum_pct"] == -100.0, f"extreme={extreme}"


# ---------------------------------------------------------------------------
# Sign / color symmetry
# ---------------------------------------------------------------------------

def test_sign_symmetry_magnitude_equal_pct_opposite_sign():
    for magnitude in (0.1, 0.5, 1.0, 1.5, 2.0, 10.0):
        pos = add_display_percentages(_make_block(scalping_moms={"M1": magnitude}), "TESTSYM")
        neg = add_display_percentages(_make_block(scalping_moms={"M1": -magnitude}), "TESTSYM")
        assert pos["scalping"]["M1"]["momentum_pct"] == -neg["scalping"]["M1"]["momentum_pct"]


def test_positive_momentum_is_green_negative_is_red():
    pos = add_display_percentages(_make_block(scalping_moms={"M1": 1.0}), "TESTSYM")
    neg = add_display_percentages(_make_block(scalping_moms={"M1": -1.0}), "TESTSYM")
    pos_color = pos["scalping"]["M1"]["momentum_color"]
    neg_color = neg["scalping"]["M1"]["momentum_color"]
    assert pos_color.startswith("#00") and pos_color.endswith("00") and pos_color != "#000000"
    assert neg_color.startswith("#") and neg_color.endswith("0000") and neg_color != "#000000"
    # green channel nonzero for positive, red channel nonzero for negative
    assert int(pos_color[3:5], 16) > 0  # green byte
    assert int(neg_color[1:3], 16) > 0  # red byte


def test_color_intensity_scales_with_magnitude():
    small = add_display_percentages(_make_block(scalping_moms={"M1": 0.2}), "TESTSYM")
    large = add_display_percentages(_make_block(scalping_moms={"M1": 1.8}), "TESTSYM")
    small_intensity = int(small["scalping"]["M1"]["momentum_color"][3:5], 16)
    large_intensity = int(large["scalping"]["M1"]["momentum_color"][3:5], 16)
    assert large_intensity > small_intensity


# ---------------------------------------------------------------------------
# Zero -> neutral grey
# ---------------------------------------------------------------------------

def test_zero_atr_is_zero_pct_and_neutral_grey():
    block = _make_block(scalping_moms={"M1": 0.0})
    out = add_display_percentages(block, "TESTSYM")
    assert out["scalping"]["M1"]["momentum_pct"] == 0.0
    assert out["scalping"]["M1"]["momentum_color"] == "#CCCCCC"


# ---------------------------------------------------------------------------
# None handling
# ---------------------------------------------------------------------------

def test_none_atr_momentum_gives_none_pct_and_none_color():
    block = _make_block()  # M1 snap has no atr_normalized_momentum key at all
    out = add_display_percentages(block, "TESTSYM")
    snap = out["scalping"][SCALPING_ORDER[0]]
    assert snap["momentum_pct"] is None
    assert snap["momentum_color"] is None


def test_explicit_none_value_same_as_missing_key():
    block = _make_block(scalping_moms={"M1": None})
    out = add_display_percentages(block, "TESTSYM")
    assert out["scalping"]["M1"]["momentum_pct"] is None
    assert out["scalping"]["M1"]["momentum_color"] is None


# ---------------------------------------------------------------------------
# Scalping and swing use the identical ATR semantic (no separate scale)
# ---------------------------------------------------------------------------

def test_scalping_and_swing_use_identical_atr_reference():
    for magnitude in (0.5, 1.0, 1.5, 2.0):
        block = _make_block(scalping_moms={"M1": magnitude}, swing_moms={"H1": magnitude})
        out = add_display_percentages(block, "TESTSYM")
        assert out["scalping"]["M1"]["momentum_pct"] == out["swing"]["H1"]["momentum_pct"]
        assert out["scalping"]["M1"]["momentum_color"] == out["swing"]["H1"]["momentum_color"]


def test_swing_extreme_value_that_used_to_need_2000_scale_now_clamps_at_2_atr():
    # Before this fix, swing used a max of 2000.0 (legacy raw price-scale
    # momentum). A canonical ATR value of, say, 3.0 is now well beyond the
    # shared 2.0 reference and must clamp to 100%, exactly like scalping
    # would -- there is no more swing-specific headroom.
    block = _make_block(swing_moms={"H1": 3.0})
    out = add_display_percentages(block, "TESTSYM")
    assert out["swing"]["H1"]["momentum_pct"] == 100.0


# ---------------------------------------------------------------------------
# Legacy raw `momentum` no longer affects live momentum_pct/color
# ---------------------------------------------------------------------------

def test_legacy_momentum_key_ignored_even_if_present_and_huge():
    # A snapshot carrying both keys (as real live snapshots do) must be
    # judged solely on atr_normalized_momentum -- a huge legacy `momentum`
    # value (crypto-scale) must not leak into momentum_pct/color any more.
    block = _make_block(scalping_moms={"M1": 0.5}, legacy_momentum=165.84)
    out = add_display_percentages(block, "TESTSYM")
    assert out["scalping"]["M1"]["momentum_pct"] == 25.0


def test_display_max_config_momentum_entries_still_present_but_unused():
    # Fix #6AC explicitly does not delete these yet -- confirm they're
    # still there (a later cleanup fix removes them), even though the
    # live momentum_pct/color computation above no longer reads them.
    assert display_max_config["scalping"]["momentum"] == 50.0
    assert display_max_config["swing"]["momentum"] == 2000.0


# ---------------------------------------------------------------------------
# bias_pct/bias_color untouched by this fix (same call, unrelated key)
# ---------------------------------------------------------------------------

def test_bias_pct_unaffected_by_this_fix():
    block = _make_block(scalping_moms={"M1": 1.0})
    block["scalping"]["M1"]["bias"] = 2.0
    out = add_display_percentages(block, "TESTSYM")
    # bias_score default max is 4.0, unrelated to momentum's new reference
    assert out["scalping"]["M1"]["bias_pct"] == 50.0


# ---------------------------------------------------------------------------
# Dead scheme A (Output.py) and momentum_conf (Fix #6AB) untouched
# ---------------------------------------------------------------------------

def test_output_py_scheme_a_and_momentum_conf_untouched_by_this_fix():
    from core.Output.Output import MAX_MOMENTUM, MOMENTUM_CONF_ATR_REFERENCE, _normalize_snapshot
    assert MAX_MOMENTUM == 2.0  # Fix #6AA's dead scheme A constant, left alone
    assert MOMENTUM_CONF_ATR_REFERENCE == 2.0  # Fix #6AB's momentum_conf constant, left alone

    class FakeSnap:
        def __init__(self):
            self.momentum = 165.84
            self.atr_normalized_momentum = 0.5

    result = _normalize_snapshot(FakeSnap())
    # scheme A is still alive in Output.py (still overwritten later by
    # helper.py in the real pipeline, but its own formula is unchanged)
    from core.Output.Output import confidence_color
    expected_scheme_a_color = confidence_color(abs(165.84) / MAX_MOMENTUM * 100)
    assert result["momentum_color"] == expected_scheme_a_color


# ---------------------------------------------------------------------------
# Live FX / JPY / metals / crypto comparison
# ---------------------------------------------------------------------------

def test_live_momentum_pct_color_bounded_and_matches_formula_across_classes():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbols = ["EURUSD_i", "USDJPY_i", "XAUUSD_i", "BTCUSD_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"], count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=symbols,
    )

    checked = 0
    for symbol in symbols:
        assert "error" not in out[symbol], f"{symbol}: {out[symbol].get('error')}"
        for mode in ("scalping", "swing"):
            for tf, snap in out[symbol][mode].items():
                if tf in ("alignment_signal", "diagnostic"):
                    continue
                atr = snap.get("atr_normalized_momentum")
                pct = snap.get("momentum_pct")
                color = snap.get("momentum_color")
                checked += 1
                if atr is None:
                    assert pct is None
                    assert color is None
                    continue
                expected_pct = scale_to_pct(atr, MOMENTUM_PCT_ATR_REFERENCE, -MOMENTUM_PCT_ATR_REFERENCE)
                assert pct == expected_pct, f"{symbol} {mode} {tf}: pct={pct} expected={expected_pct}"
                assert -100.0 <= pct <= 100.0
                assert color == pct_to_color(expected_pct, directional=True)
    assert checked > 0
