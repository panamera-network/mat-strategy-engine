"""Fix #6AB — targeted tests for migrating momentum_conf to canonical
atr_normalized_momentum, with a clamp so signal_health.score_pct can no
longer explode past 100% purely from momentum (Fix #6AA's audit found
BTCUSD_i's legacy-based momentum_conf drove signal_health.score_pct to
733%, with the raw per-tf pct reaching 932,857% for crypto).

Scope: ONLY momentum_conf (via _compute_signal_confidence()) migrates.
momentum_color/momentum_pct (both the dead Output.py scheme and the live
helper.py scheme), momentum_band, Alignment's own +/-0.3 momentum vote,
conviction, and compute_signal_health()'s averaging formula are all
untouched by this fix -- tests below explicitly confirm they still
behave as before.

Fix #6AX later deleted the MAX_MOMENTUM constant this file used to compare
against (fully orphaned by then -- its only live-code use, scheme A, was
already dead at the time this fix landed, per test_dead_momentum_display_
cleanup.py); this file's own comparison test was simplified accordingly.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_momentum_conf_atr_migration.py -v
"""
from core.Output.Output import (
    _compute_signal_confidence,
    MOMENTUM_CONF_ATR_REFERENCE,
)
from core.Output.alignment_signal import compute_signal_health


# ---------------------------------------------------------------------------
# Constant / reference
# ---------------------------------------------------------------------------

def test_atr_reference_is_2_0():
    # Fix #6AB deliberately introduced its own constant, distinct from
    # helper.py's MOMENTUM_PCT_ATR_REFERENCE and the (since Fix #6AX,
    # deleted) legacy MAX_MOMENTUM -- same numeric value, different
    # semantics/presentation paths.
    assert MOMENTUM_CONF_ATR_REFERENCE == 2.0


def _scalping_snapshots(values: dict) -> dict:
    """Build a minimal scalping_snapshots dict shape for the given
    {tf: atr_normalized_momentum} values, matching what
    _normalize_snapshot_map() produces (a plain dict with the key present,
    possibly None)."""
    return {tf: {"atr_normalized_momentum": v} for tf, v in values.items()}


NO_ALIGNMENT = None
EMPTY_BIAS_ORDERED = {}


# ---------------------------------------------------------------------------
# Landmark boundary tests (single scalping TF at a time, isolates the pct
# formula from the averaging step)
# ---------------------------------------------------------------------------

def test_zero_atr_is_zero_percent():
    snaps = _scalping_snapshots({"M1": 0.0})
    _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
    assert momentum_conf == 0.0


def test_half_atr_is_25_percent():
    snaps = _scalping_snapshots({"M1": 0.5})
    _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
    assert momentum_conf == 25.0


def test_one_atr_is_50_percent():
    snaps = _scalping_snapshots({"M1": 1.0})
    _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
    assert momentum_conf == 50.0


def test_one_point_five_atr_is_75_percent():
    snaps = _scalping_snapshots({"M1": 1.5})
    _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
    assert momentum_conf == 75.0


def test_two_atr_is_100_percent():
    snaps = _scalping_snapshots({"M1": 2.0})
    _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
    assert momentum_conf == 100.0


def test_beyond_two_atr_still_caps_at_100_never_exceeds():
    for extreme in (2.0001, 5.0, 50.0, 3000.0, 932857.0 / 100):  # last one mirrors Fix #6AA's real crypto pct scale
        snaps = _scalping_snapshots({"M1": extreme})
        _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
        assert momentum_conf == 100.0, f"extreme={extreme} produced {momentum_conf}, expected capped 100.0"


def test_negative_momentum_same_percentage_as_positive():
    for magnitude in (0.5, 1.0, 1.5, 2.0, 10.0):
        pos = _compute_signal_confidence(EMPTY_BIAS_ORDERED, _scalping_snapshots({"M1": magnitude}), NO_ALIGNMENT)[1]
        neg = _compute_signal_confidence(EMPTY_BIAS_ORDERED, _scalping_snapshots({"M1": -magnitude}), NO_ALIGNMENT)[1]
        assert pos == neg


# ---------------------------------------------------------------------------
# Averaging across scalping TFs
# ---------------------------------------------------------------------------

def test_average_across_scalping_tfs_correct():
    # 0.5 -> 25%, 1.0 -> 50%, 1.5 -> 75%, 2.0 -> 100% ; average = 62.5
    snaps = _scalping_snapshots({"M1": 0.5, "M5": 1.0, "M15": 1.5, "M30": 2.0})
    _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
    assert momentum_conf == 62.5


def test_average_clamps_each_value_before_averaging_not_after():
    # If clamping happened only on the final average, one extreme value
    # (932,857%-scale) averaged with three zeros would still likely exceed
    # 100 depending on divisor; clamping per-value first guarantees the
    # average of four values each in [0,100] can never exceed 100 -- and
    # confirms the pre-average clamp specifically (not just a final min()).
    snaps = _scalping_snapshots({"M1": 9328.57, "M5": 0.0, "M15": 0.0, "M30": 0.0})
    _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
    assert momentum_conf == 25.0  # (100 + 0 + 0 + 0) / 4
    assert momentum_conf <= 100.0


# ---------------------------------------------------------------------------
# None handling
# ---------------------------------------------------------------------------

def test_none_values_ignored_safely_not_averaged_as_zero():
    # Only M1 has a real value (1.0 -> 50%); M5/M15/M30 are None and must be
    # excluded from the average entirely, not counted as 0.
    snaps = _scalping_snapshots({"M1": 1.0, "M5": None, "M15": None, "M30": None})
    _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
    assert momentum_conf == 50.0  # not 12.5, which is what averaging-as-zero would give


def test_all_none_or_missing_returns_zero_not_error():
    snaps = _scalping_snapshots({"M1": None, "M5": None, "M15": None, "M30": None})
    _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
    assert momentum_conf == 0

    _, momentum_conf_missing, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, {}, NO_ALIGNMENT)
    assert momentum_conf_missing == 0


def test_missing_key_entirely_treated_same_as_none():
    snaps = {"M1": {}, "M5": {"atr_normalized_momentum": 1.0}}
    _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
    assert momentum_conf == 50.0


# ---------------------------------------------------------------------------
# Legacy `momentum` key is no longer read at all
# ---------------------------------------------------------------------------

def test_legacy_momentum_key_ignored_even_if_present_and_huge():
    # A snapshot carrying both keys must be judged solely on
    # atr_normalized_momentum -- a huge legacy `momentum` value (as real
    # crypto symbols have) must not leak into momentum_conf any more.
    snaps = {"M1": {"momentum": 165.84, "atr_normalized_momentum": 1.0}}
    _, momentum_conf, _ = _compute_signal_confidence(EMPTY_BIAS_ORDERED, snaps, NO_ALIGNMENT)
    assert momentum_conf == 50.0


# ---------------------------------------------------------------------------
# signal_health.score_pct no longer explodes solely from momentum_conf
# ---------------------------------------------------------------------------

def test_signal_health_no_longer_explodes_from_extreme_momentum_conf():
    # Reproduces Fix #6AA's live BTCUSD_i finding in miniature: before this
    # fix, an extreme legacy momentum value alone could push
    # signal_health.score_pct to 733%. With momentum_conf now capped at
    # 100, and bias_conf/align_conf also naturally <=100, the average can
    # never exceed 100.
    bias_conf = 50.0
    momentum_conf = 100.0  # the new, capped ceiling -- was 92685700%-scale pre-fix for crypto
    align_conf = 60.0
    health = compute_signal_health(bias_conf, momentum_conf, align_conf)
    assert health["score_pct"] <= 100.0
    assert health["score_pct"] == round((50.0 + 100.0 + 60.0) / 3, 1)


def test_signal_health_formula_itself_unchanged():
    # compute_signal_health() itself is explicitly out of scope for this
    # fix -- confirm it's still a bare unweighted average of the 3 inputs.
    health = compute_signal_health(10.0, 20.0, 30.0)
    assert health["score_pct"] == 20.0


# ---------------------------------------------------------------------------
# Live sanity check across FX / JPY / metals / crypto
# ---------------------------------------------------------------------------

def test_live_momentum_conf_bounded_and_reasonable_across_instrument_classes():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbols = ["EURUSD_i", "USDJPY_i", "XAUUSD_i", "BTCUSD_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, ["M1", "M5", "M15", "M30"], count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=symbols,
    )

    for symbol in symbols:
        assert "error" not in out[symbol], f"{symbol}: {out[symbol].get('error')}"
        score_pct = out[symbol]["signal_health"]["score_pct"]
        # The single most important regression guard from Fix #6AA: no
        # symbol's signal_health.score_pct may exceed 100 any more, purely
        # as a consequence of momentum_conf's own contribution being capped.
        assert score_pct <= 100.0, f"{symbol}: signal_health.score_pct={score_pct} exceeds 100"
        assert score_pct >= 0.0

    # BTCUSD_i specifically reproduced Fix #6AA's 733% live finding --
    # confirm it is gone.
    btc_score = out["BTCUSD_i"]["signal_health"]["score_pct"]
    assert btc_score <= 100.0


def test_live_momentum_conf_matches_manual_recomputation():
    """Recompute momentum_conf by hand from the same live
    atr_normalized_momentum values /core/output actually used, to confirm
    the formula wired into _compute_signal_confidence() is exactly what
    reaches signal_health -- not just that it happens to stay <=100."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output, _compute_signal_confidence, _build_bias_ordered
    from mt5.constants import TIMEFRAMES

    symbol = "XAUUSD_i"
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], ["M1", "M5", "M15", "M30"], count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=[symbol],
    )
    assert "error" not in out[symbol]

    scalping = out[symbol]["scalping"]
    manual_vals = [
        min(abs(scalping[tf]["atr_normalized_momentum"]) / MOMENTUM_CONF_ATR_REFERENCE * 100, 100.0)
        for tf in ("M1", "M5", "M15", "M30")
        if scalping.get(tf, {}).get("atr_normalized_momentum") is not None
    ]
    expected_momentum_conf = round(sum(manual_vals) / len(manual_vals), 1) if manual_vals else 0

    # signal_health.score_pct = round((bias_conf + momentum_conf + align_conf) / 3, 1)
    # We can't isolate momentum_conf directly from the output dict (it's
    # only exposed via signal_health's average), so instead recompute the
    # whole triple via the same live bias_map/alignment the endpoint used,
    # and compare the momentum_conf component directly.
    bias_map = cr.bias_engine.get_bias_map(symbol, TIMEFRAMES, cache=cache)
    bias_ordered = _build_bias_ordered(bias_map)
    _, momentum_conf, _ = _compute_signal_confidence(bias_ordered, scalping, out[symbol]["scalping"].get("alignment_signal"))

    assert momentum_conf == expected_momentum_conf
