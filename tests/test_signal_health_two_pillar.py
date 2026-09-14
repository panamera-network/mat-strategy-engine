"""Fix #6BI — signal_health migrated from a 3-pillar (bias_conf +
momentum_conf + align_conf) average to a 2-pillar (bias_conf + momentum_conf)
average. Fix #6BH's audit found align_conf strongly duplicates momentum_conf
specifically (0.825 correlation; 68% of align_conf's own variance already
explained by bias_conf+momentum_conf combined) -- averaging it in as an
equal third pillar was effectively double-weighting momentum evidence.

align_conf's own computation (compute_alignment_signal()) is completely
untouched, and its value remains independently published exactly as before
via alignment_signal.confidence_pct in the scalping/swing blocks -- this fix
only removes it from compute_signal_health()'s composite average.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_signal_health_two_pillar.py -v
"""
from core.Output.alignment_signal import compute_signal_health, compute_alignment_signal


# ---------------------------------------------------------------------------
# Exact 2-pillar arithmetic.
# ---------------------------------------------------------------------------

def test_score_pct_is_average_of_bias_and_momentum_only():
    health = compute_signal_health(10.0, 20.0, 999.0)
    assert health["score_pct"] == round((10.0 + 20.0) / 2, 1)


def test_score_pct_matches_hand_computed_values():
    assert compute_signal_health(30.0, 50.0, 0.0)["score_pct"] == 40.0
    assert compute_signal_health(0.0, 0.0, 100.0)["score_pct"] == 0.0
    assert compute_signal_health(100.0, 100.0, 0.0)["score_pct"] == 100.0


# ---------------------------------------------------------------------------
# align_conf no longer changes score_pct; bias_conf/momentum_conf still do.
# ---------------------------------------------------------------------------

def test_align_conf_no_longer_changes_score_pct():
    low_align = compute_signal_health(40.0, 60.0, 0.0)
    high_align = compute_signal_health(40.0, 60.0, 100.0)
    mid_align = compute_signal_health(40.0, 60.0, 50.0)
    assert low_align["score_pct"] == high_align["score_pct"] == mid_align["score_pct"] == 50.0
    assert low_align == high_align == mid_align


def test_bias_conf_still_changes_score_pct():
    low_bias = compute_signal_health(0.0, 50.0, 50.0)
    high_bias = compute_signal_health(100.0, 50.0, 50.0)
    assert low_bias["score_pct"] != high_bias["score_pct"]
    assert low_bias["score_pct"] == 25.0
    assert high_bias["score_pct"] == 75.0


def test_momentum_conf_still_changes_score_pct():
    low_momentum = compute_signal_health(50.0, 0.0, 50.0)
    high_momentum = compute_signal_health(50.0, 100.0, 50.0)
    assert low_momentum["score_pct"] != high_momentum["score_pct"]
    assert low_momentum["score_pct"] == 25.0
    assert high_momentum["score_pct"] == 75.0


# ---------------------------------------------------------------------------
# Label thresholds unchanged (75/50/25), neutral wording from #6BG preserved.
# ---------------------------------------------------------------------------

def test_threshold_boundaries_unchanged():
    assert compute_signal_health(24.9, 24.9, 0.0)["label"] == "No Clear Signal"
    assert compute_signal_health(25.0, 25.0, 0.0)["label"] == "Weak Signal"
    assert compute_signal_health(49.9, 49.9, 0.0)["label"] == "Weak Signal"
    assert compute_signal_health(50.0, 50.0, 0.0)["label"] == "Moderate Signal"
    assert compute_signal_health(74.9, 74.9, 0.0)["label"] == "Moderate Signal"
    assert compute_signal_health(75.0, 75.0, 0.0)["label"] == "Strong Signal"


def test_no_label_contains_long_or_short():
    for b in [0, 25, 50, 75, 100]:
        health = compute_signal_health(b, b, 0.0)
        assert "Long" not in health["label"]
        assert "Short" not in health["label"]
    labels = {compute_signal_health(b, b, 0.0)["label"] for b in [0, 30, 60, 90]}
    assert labels <= {"No Clear Signal", "Weak Signal", "Moderate Signal", "Strong Signal"}


# ---------------------------------------------------------------------------
# Color mapping unchanged for an identical resulting score.
# ---------------------------------------------------------------------------

def test_color_mapping_unchanged_for_identical_score():
    from core.Output.helper import confidence_color
    for score in [0.0, 24.9, 25.0, 49.9, 50.0, 74.9, 75.0, 100.0]:
        health = compute_signal_health(score, score, 0.0)
        assert health["color"] == confidence_color(score)


# ---------------------------------------------------------------------------
# Object shape unchanged.
# ---------------------------------------------------------------------------

def test_object_shape_unchanged():
    health = compute_signal_health(10.0, 20.0, 30.0)
    assert set(health.keys()) == {"score_pct", "color", "label"}


# ---------------------------------------------------------------------------
# alignment_signal.confidence_pct remains independently exposed, unchanged.
# ---------------------------------------------------------------------------

def test_compute_alignment_signal_output_unchanged():
    """compute_alignment_signal() itself is untouched by this fix -- its own
    output shape and confidence_pct value are exactly as before."""
    snaps = {
        "M1": {"direction": "bullish", "atr_normalized_momentum": 1.5},
        "M5": {"direction": "bullish", "atr_normalized_momentum": 1.5},
        "M15": {"direction": "bullish", "atr_normalized_momentum": 0.2},
        "M30": {"direction": "neutral", "atr_normalized_momentum": None},
    }
    result = compute_alignment_signal(snaps, mode="scalping")
    assert set(result.keys()) == {"decision", "total_score", "confidence_pct", "confidence_color", "summary", "breakdown"}
    # M1: +1(dir)+1(momentum>1.0)=2, M5: +1+1=2, M15: +1+0=1, M30: 0 -> total=5, max=8 -> 62.5%
    assert result["confidence_pct"] == 62.5
    assert result["decision"] == "Go Long"


# ---------------------------------------------------------------------------
# Live: /core/output and /core/slim shape unchanged; align_conf's own
# published value (alignment_signal.confidence_pct) matches what
# _compute_signal_confidence() read as align_conf, but no longer equals a
# term inside signal_health.score_pct's arithmetic.
# ---------------------------------------------------------------------------

def test_live_output_signal_health_is_two_pillar_average():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output, _build_bias_ordered
    from mt5.constants import TIMEFRAMES

    symbols = ["EURUSD_i", "XAUUSD_i", "BTCUSD_i", "USDJPY_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, TIMEFRAMES, count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=symbols,
    )

    MAX_BIAS = 4.0
    MOMENTUM_CONF_ATR_REFERENCE = 2.0
    SCALPING_ORDER = ["M1", "M5", "M15", "M30"]

    checked_any = False
    for symbol in symbols:
        block = out[symbol]
        assert "error" not in block
        bias_ordered = block["bias"]
        scalping_snapshots = block["scalping"]
        scalping_alignment = scalping_snapshots.get("alignment_signal")

        bias_scores = [v["score"] for v in bias_ordered.values() if v.get("score") is not None]
        bias_conf = round(sum(abs(s) / MAX_BIAS * 100 for s in bias_scores) / len(bias_scores), 1) if bias_scores else 0
        mom_vals = [
            min(abs(scalping_snapshots[tf]["atr_normalized_momentum"]) / MOMENTUM_CONF_ATR_REFERENCE * 100, 100.0)
            for tf in SCALPING_ORDER if scalping_snapshots.get(tf, {}).get("atr_normalized_momentum") is not None
        ]
        momentum_conf = round(sum(mom_vals) / len(mom_vals), 1) if mom_vals else 0
        align_conf = scalping_alignment["confidence_pct"] if scalping_alignment else 0

        checked_any = True
        expected_score = round((bias_conf + momentum_conf) / 2, 1)
        assert block["signal_health"]["score_pct"] == expected_score

        # align_conf is still independently published, unchanged, via the
        # scalping alignment_signal block.
        assert scalping_snapshots["alignment_signal"]["confidence_pct"] == align_conf

    assert checked_any


def test_live_output_shape_unchanged():
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
    expected_top_keys = {
        "last_updated", "bias", "scalping", "swing", "health", "signal_health",
        "strategy_signals", "snr_levels", "order_blocks",
        "fvg", "swing_points", "structure_events", "momentum_evidence", "supply_demand_zones",
    }
    assert expected_top_keys.issubset(set(block.keys()))
    assert set(block["signal_health"].keys()) == {"score_pct", "color", "label"}
    assert "alignment_signal" in block["scalping"]
    assert "confidence_pct" in block["scalping"]["alignment_signal"]


def test_live_slim_endpoint_shape_unchanged():
    from fastapi.testclient import TestClient
    from main import app

    client = TestClient(app)
    resp = client.get("/core/slim/XAUUSD_i,EURUSD_i")
    assert resp.status_code == 200
    data = resp.json()

    checked_any = False
    for symbol, block in data.items():
        if "error" in block:
            continue
        checked_any = True
        assert set(block.keys()) == {
            "bias", "signal_health", "scalping", "swing",
            "snr_levels", "order_blocks", "fvg", "supply_demand_zones", "strategy_signals",
        }
        assert set(block["signal_health"].keys()) == {"score_pct", "color", "label"}
        assert "confidence_pct" in block["scalping"]["alignment_signal"]

    assert checked_any


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
