"""Fix #6BG — signal_health label wording made direction-neutral.

Fix #6BF's audit found signal_health.score_pct is built entirely from
abs()-valued components (bias_conf/momentum_conf/align_conf all use abs()),
so it carries no sign at all -- a strongly bearish reading produces the
exact same score as a strongly bullish one, yet the old label
("Strong Long Bias") implied a direction the score never determines.

This fix changes ONLY the label wording (audit confirmed zero internal
consumer of the exact label strings anywhere in the repo, and no schema
enumerates them) -- the score formula, thresholds, and object/schema shape
are all byte-identical to before.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_signal_health_label_neutral.py -v
"""
from core.Output.alignment_signal import compute_signal_health


# ---------------------------------------------------------------------------
# No label contains "Long"/"Short".
# ---------------------------------------------------------------------------

def test_no_label_contains_long_or_short_across_full_range():
    for avg in [0, 10, 24.9, 25, 49.9, 50, 74.9, 75, 90, 100]:
        health = compute_signal_health(avg, 0, 0)
        assert "Long" not in health["label"]
        assert "Short" not in health["label"]


# ---------------------------------------------------------------------------
# Candidate wording exactly as specified.
# ---------------------------------------------------------------------------

def test_strong_signal_label_at_and_above_75():
    assert compute_signal_health(75, 75, 75)["label"] == "Strong Signal"
    assert compute_signal_health(100, 100, 100)["label"] == "Strong Signal"


def test_moderate_signal_label_between_50_and_75():
    assert compute_signal_health(50, 50, 50)["label"] == "Moderate Signal"
    assert compute_signal_health(74, 74, 74)["label"] == "Moderate Signal"


def test_weak_signal_label_between_25_and_50():
    assert compute_signal_health(25, 25, 25)["label"] == "Weak Signal"
    assert compute_signal_health(49, 49, 49)["label"] == "Weak Signal"


def test_no_clear_signal_label_below_25():
    assert compute_signal_health(0, 0, 0)["label"] == "No Clear Signal"
    assert compute_signal_health(24, 24, 24)["label"] == "No Clear Signal"


# ---------------------------------------------------------------------------
# Thresholds preserved exactly (boundary values unchanged).
# ---------------------------------------------------------------------------

def test_threshold_boundaries_unchanged():
    # Just below each boundary -> the lower tier; at the boundary -> the
    # higher tier (>=, matching the original operator exactly). All three
    # args set equal to `avg` so avg_conf == avg exactly (avg_conf is the
    # mean of the three inputs, not any single one of them).
    assert compute_signal_health(24.9, 24.9, 24.9)["label"] == "No Clear Signal"
    assert compute_signal_health(25.0, 25.0, 25.0)["label"] == "Weak Signal"
    assert compute_signal_health(49.9, 49.9, 49.9)["label"] == "Weak Signal"
    assert compute_signal_health(50.0, 50.0, 50.0)["label"] == "Moderate Signal"
    assert compute_signal_health(74.9, 74.9, 74.9)["label"] == "Moderate Signal"
    assert compute_signal_health(75.0, 75.0, 75.0)["label"] == "Strong Signal"


# ---------------------------------------------------------------------------
# Score formula/value identical before/after -- only the label string
# changed. Since avg_conf is built entirely from abs() inputs, "bearish"
# and "bullish" mirrored inputs (same magnitude, opposite sign) already
# produce the identical score today -- this fix doesn't change that, it
# just stops mislabeling it as directional.
# ---------------------------------------------------------------------------

def test_score_pct_formula_unchanged():
    health = compute_signal_health(10.0, 20.0, 30.0)
    assert health["score_pct"] == round((10.0 + 20.0 + 30.0) / 3, 1)


def test_bearish_and_bullish_mirrored_inputs_produce_same_neutral_label():
    """bias_conf/momentum_conf/align_conf are already direction-agnostic
    (abs()-based) by the time they reach compute_signal_health() -- a
    'bearish' 80%-magnitude reading and a 'bullish' 80%-magnitude reading
    arrive as the identical number. This test documents that the resulting
    label is the same, direction-neutral string either way (the fix this
    file targets), not that this function itself computes direction."""
    bearish_like = compute_signal_health(80.0, 80.0, 80.0)
    bullish_like = compute_signal_health(80.0, 80.0, 80.0)
    assert bearish_like == bullish_like
    assert bearish_like["label"] == "Strong Signal"
    assert "Long" not in bearish_like["label"]
    assert "Short" not in bearish_like["label"]


def test_color_unaffected():
    from core.Output.helper import confidence_color
    for avg in [0, 30, 60, 90]:
        health = compute_signal_health(avg, avg, avg)
        assert health["color"] == confidence_color(round(avg, 1))


def test_object_shape_unchanged():
    health = compute_signal_health(10.0, 20.0, 30.0)
    assert set(health.keys()) == {"score_pct", "color", "label"}


# ---------------------------------------------------------------------------
# Live: /core/output and /core/slim/{symbols} shape unchanged, score
# identical to a fresh recomputation, no "Long"/"Short" in the live label.
# ---------------------------------------------------------------------------

def test_live_output_signal_health_shape_and_label_unchanged():
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbols = ["EURUSD_i", "XAUUSD_i", "BTCUSD_i"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all(symbols, ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"], count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine, candle_engine=cr.candle_engine, momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine, shift_engine=cr.shift_engine, structure_engine=cr.structure_engine,
        cache=cache, symbols=symbols,
    )

    checked_any = False
    for symbol in symbols:
        assert "error" not in out[symbol]
        health = out[symbol]["signal_health"]
        checked_any = True
        assert set(health.keys()) == {"score_pct", "color", "label"}
        assert "Long" not in health["label"]
        assert "Short" not in health["label"]
        assert health["label"] in ("Strong Signal", "Moderate Signal", "Weak Signal", "No Clear Signal")

    assert checked_any


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
        health = block["signal_health"]
        assert set(health.keys()) == {"score_pct", "color", "label"}
        assert "Long" not in health["label"]
        assert "Short" not in health["label"]

    assert checked_any


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
