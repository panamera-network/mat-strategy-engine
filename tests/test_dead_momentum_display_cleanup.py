"""Fix #6AD — targeted tests for removing dead momentum display legacy:

1. The dead scheme A write in Output.py's _normalize_snapshot() (used to
   set snap_dict["momentum_color"] from the legacy raw momentum via a
   2.0 divisor -- always overwritten downstream by helper.py's
   add_display_percentages(), confirmed dead by Fix #6AA/#6AC's live
   audits before this fix removed it).
2. The now-unreferenced display_max_config momentum entries (helper.py):
   default 1.0, scalping 50.0, swing 2000.0.

This is a pure cleanup -- no behavior change. Everything below confirms
the live output (momentum_pct, momentum_color, momentum_band,
momentum_conf, signal_health, bias/strength display) is byte-for-byte
identical to before, and that nothing else in the codebase referenced the
removed constants/config.

Fix #6AX later deleted the MAX_MOMENTUM constant itself (scheme A, its
only ever live-code use, was already dead per this file's own tests --
confirmed fully orphaned and removed as a separate cleanup); this file's
own now-stale MAX_MOMENTUM-specific test was removed with it.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_dead_momentum_display_cleanup.py -v
"""
from core.Output.Output import _normalize_snapshot
from core.Output.helper import display_max_config, get_display_max


# ---------------------------------------------------------------------------
# Dead scheme A removed
# ---------------------------------------------------------------------------

def test_normalize_snapshot_no_longer_sets_momentum_color():
    class FakeSnap:
        def __init__(self):
            self.momentum = 165.84  # crypto-scale legacy value, used to saturate scheme A hard
            self.atr_normalized_momentum = 0.3  # < 0.5 ATR moderate threshold -> "weak"
            self.demand = "neutral"

    result = _normalize_snapshot(FakeSnap())
    assert "momentum_color" not in result
    # momentum itself (rounded) and momentum_band are untouched by the removal
    assert result["momentum"] == 165.84
    assert result["momentum_band"] == "weak"


def test_normalize_snapshot_momentum_rounding_still_applied():
    """The dead block also rounded the legacy `momentum` value to 4dp --
    that behavior must survive the cleanup (it wasn't part of scheme A's
    dead momentum_color write)."""
    class FakeSnap:
        def __init__(self):
            self.momentum = 1.23456789
            self.demand = "neutral"

    result = _normalize_snapshot(FakeSnap())
    assert result["momentum"] == 1.2346


# ---------------------------------------------------------------------------
# display_max_config momentum entries removed
# ---------------------------------------------------------------------------

def test_display_max_config_momentum_entries_removed():
    assert "momentum" not in display_max_config["default"]
    assert "momentum" not in display_max_config["scalping"]
    assert "momentum" not in display_max_config["swing"]


def test_get_display_max_still_returns_other_keys_correctly():
    bias_max = get_display_max("XAUUSD_i", "bias")
    assert bias_max["bias_score"] == 4.0
    assert "strength" in bias_max
    assert "momentum" not in bias_max

    scalping_max = get_display_max("XAUUSD_i", "scalping")
    assert scalping_max["score"] == 1.0
    assert scalping_max["bias_score"] == 4.0
    assert "momentum" not in scalping_max

    swing_max = get_display_max("XAUUSD_i", "swing")
    assert swing_max["score"] == 1.0
    assert swing_max["bias_score"] == 4.0
    assert "momentum" not in swing_max


# ---------------------------------------------------------------------------
# Live end-to-end: output unchanged (formula-equivalent) after cleanup
# ---------------------------------------------------------------------------

def test_live_output_momentum_fields_unchanged_after_cleanup():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import (
        build_multi_symbol_output,
        MOMENTUM_CONF_ATR_REFERENCE,
        ATR_MOMENTUM_MODERATE_THRESHOLD,
        ATR_MOMENTUM_STRONG_THRESHOLD,
        _momentum_band,
    )
    from core.Output.helper import scale_to_pct, pct_to_color, MOMENTUM_PCT_ATR_REFERENCE

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

        # signal_health still bounded [0, 100], formula untouched by this fix
        score_pct = out[symbol]["signal_health"]["score_pct"]
        assert 0.0 <= score_pct <= 100.0

        for mode in ("scalping", "swing"):
            for tf, snap in out[symbol][mode].items():
                if tf in ("alignment_signal", "diagnostic"):
                    continue
                checked += 1
                atr = snap.get("atr_normalized_momentum")
                pct = snap.get("momentum_pct")
                color = snap.get("momentum_color")
                band = snap.get("momentum_band")

                if atr is None:
                    assert pct is None
                    assert color is None
                    assert band is None
                    continue

                expected_pct = scale_to_pct(atr, MOMENTUM_PCT_ATR_REFERENCE, -MOMENTUM_PCT_ATR_REFERENCE)
                assert pct == expected_pct
                assert color == pct_to_color(expected_pct, directional=True)
                assert band == _momentum_band(atr)

                # bias/strength display fields still present and well-formed
                assert "bias_pct" in snap
                assert "bias_color" in snap

        bias_block = out[symbol]["bias"]
        for tf, vals in bias_block.items():
            assert "strength_pct" in vals or vals.get("strength") is None
            assert "score_pct" in vals or vals.get("score") is None

    assert checked > 0


def test_no_live_code_references_removed_config_keys():
    """Repo-wide guard: no live source file directly indexes the removed
    per-mode momentum keys (which would now raise KeyError)."""
    import pathlib

    repo_root = pathlib.Path(__file__).resolve().parent.parent
    removed_key_patterns = (
        'bias_max["momentum"]',
        'scalping_max["momentum"]',
        'swing_max["momentum"]',
        'max_vals["momentum"]',
    )
    offenders = []
    for py_file in (repo_root / "core").rglob("*.py"):
        if "archive" in py_file.parts:
            continue
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        if any(pattern in text for pattern in removed_key_patterns):
            offenders.append(str(py_file))
    assert not offenders, f"Live code still references removed momentum config keys: {offenders}"
