"""Fix #6BK — /core/bias/shift and /core/bias/shift/multi retired.

Fix #6BJ's audit found detect_bias_shift() never actually detected a bias
shift: its `prev_bias` argument was hardcoded to "Neutral" at both call
sites and, critically, never read or compared against anything anywhere in
the function's own logic. The only real gate was "is there currently a
confirmed, valid structural event" -- a fact already exposed, correctly
cached and batched, via /core/output's structure_events block. With no
previous-state tracking either, the same currently-confirmed event would
be re-reported as a "new" shift on every single call.

This fix retires the calculation while keeping the route, response model,
and query signature exactly as they were: both routes now always return an
empty list, with zero StructureEngine instantiation or candle fetch, and
detect_bias_shift() itself is a stub that always returns None. No state
tracking added, no new bias logic, no fake placeholder BiasShiftEvent.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_bias_shift_route_retired.py -v
"""
from fastapi.testclient import TestClient

from core.core_models import BiasShiftEvent
from core.ShiftEngine import detect_bias_shift


# ---------------------------------------------------------------------------
# detect_bias_shift() always returns None.
# ---------------------------------------------------------------------------

def test_detect_bias_shift_returns_none_regardless_of_input():
    from datetime import datetime, timezone
    from core.core_models import StructureSnapshot

    snapshot = StructureSnapshot(
        symbol="T", timeframe="M15", current_high=1.0, current_low=0.9,
        prev_high=1.0, prev_low=0.9, current_zone="Neutral", prev_zone="Neutral",
    )
    snapshot.structure = "breakout"
    snapshot.structure_valid = True
    snapshot.bias = "Bullish"

    assert detect_bias_shift(prev_bias="Neutral", snapshot=snapshot, symbol="T") is None
    assert detect_bias_shift(prev_bias="Bullish", snapshot=snapshot, symbol="T") is None
    assert detect_bias_shift(prev_bias="anything at all", snapshot=snapshot, symbol="T") is None


def test_detect_bias_shift_returns_none_live_even_for_a_real_confirmed_event():
    """Proves retirement against real, live data -- not just a synthetic
    snapshot engineered to look eligible."""
    import api.core_router as cr

    symbols = ["XAUUSD_i", "BTCUSD_i", "EURUSD_i", "USDJPY_i", "GBPUSD_i"]
    timeframes = ["M15", "H1", "H4", "D1"]
    checked_a_confirmed_event = False
    for symbol in symbols:
        for tf in timeframes:
            structure = cr.structure_engine.get_snapshot(symbol, tf)
            if not structure or not structure.structure_valid:
                continue
            checked_a_confirmed_event = True
            assert detect_bias_shift(prev_bias="Neutral", snapshot=structure, symbol=symbol) is None

    assert checked_a_confirmed_event


# ---------------------------------------------------------------------------
# Both routes: HTTP 200, always [], response schema still List[BiasShiftEvent].
# ---------------------------------------------------------------------------

def test_bias_shift_route_returns_200_and_empty_list():
    from main import app
    client = TestClient(app)
    resp = client.get("/core/bias/shift")
    assert resp.status_code == 200
    assert resp.json() == []


def test_bias_shift_route_returns_empty_list_with_explicit_params():
    from main import app
    client = TestClient(app)
    resp = client.get("/core/bias/shift", params={"symbols": ["XAUUSD_i", "BTCUSD_i"], "tf": "H1"})
    assert resp.status_code == 200
    assert resp.json() == []


def test_bias_shift_multi_route_returns_200_and_empty_list():
    from main import app
    client = TestClient(app)
    resp = client.get("/core/bias/shift/multi")
    assert resp.status_code == 200
    assert resp.json() == []


def test_bias_shift_multi_route_returns_empty_list_with_explicit_params():
    from main import app
    client = TestClient(app)
    resp = client.get("/core/bias/shift/multi", params={
        "symbols": ["XAUUSD_i", "EURUSD_i"], "timeframes": ["M15", "H4"],
    })
    assert resp.status_code == 200
    assert resp.json() == []


def test_response_model_still_declared_as_list_of_bias_shift_event():
    """Verified via the generated OpenAPI schema rather than app.routes --
    this FastAPI/Starlette version doesn't flatten included routers into
    app.routes as plain APIRoute objects, so the schema is the reliable,
    version-independent way to confirm the declared response_model."""
    from main import app

    schema = app.openapi()
    for path in ("/core/bias/shift", "/core/bias/shift/multi"):
        response_schema = schema["paths"][path]["get"]["responses"]["200"]["content"]["application/json"]["schema"]
        assert response_schema["type"] == "array"
        assert response_schema["items"]["$ref"] == "#/components/schemas/BiasShiftEvent"

    # And the schema component itself still matches BiasShiftEvent's real fields.
    bias_shift_schema = schema["components"]["schemas"]["BiasShiftEvent"]
    assert set(bias_shift_schema["properties"].keys()) == set(BiasShiftEvent.model_fields.keys())


# ---------------------------------------------------------------------------
# No StructureEngine instantiation / candle fetch occurs through the
# retired routes.
# ---------------------------------------------------------------------------

def test_no_structure_engine_or_candle_fetch_through_retired_routes():
    import api.core_router as cr
    from core.StructureEngine import StructureEngine
    from core.CandleEngine import CandleEngine

    original_init = StructureEngine.__init__
    original_get_snapshots = CandleEngine.get_snapshots
    init_calls = []
    fetch_calls = []

    def spy_init(self, *args, **kwargs):
        init_calls.append(1)
        return original_init(self, *args, **kwargs)

    def spy_get_snapshots(self, *args, **kwargs):
        fetch_calls.append(1)
        return original_get_snapshots(self, *args, **kwargs)

    StructureEngine.__init__ = spy_init
    CandleEngine.get_snapshots = spy_get_snapshots
    try:
        from main import app
        client = TestClient(app)
        resp1 = client.get("/core/bias/shift")
        resp2 = client.get("/core/bias/shift/multi")
    finally:
        StructureEngine.__init__ = original_init
        CandleEngine.get_snapshots = original_get_snapshots

    assert resp1.status_code == 200
    assert resp2.status_code == 200
    assert init_calls == []
    assert fetch_calls == []


# ---------------------------------------------------------------------------
# No debug prints remain in the retired route bodies.
# ---------------------------------------------------------------------------

def test_no_debug_prints_in_route_source():
    import inspect
    import api.core_router as cr

    for fn in (cr.get_bias_shift_events, cr.get_multi_tf_bias_shift_events):
        source = inspect.getsource(fn)
        assert "print(" not in source


# ---------------------------------------------------------------------------
# Canonical /core/output structure_events unchanged by this fix.
# ---------------------------------------------------------------------------

def test_live_output_structure_events_unchanged():
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
    assert "structure_events" in block
    # shape unchanged: whichever timeframes have a confirmed event still
    # carry the same canonical evidence fields.
    for tf, event in block["structure_events"].items():
        assert set(event.keys()) == {
            "type", "direction", "broken_level", "event_index", "event_timestamp",
            "leg_origin_index", "leg_origin_timestamp", "leg_origin_price", "leg_origin_swing_label",
            "origin_zone_type", "origin_zone_timestamp", "origin_zone_top", "origin_zone_bottom",
            "pre_break_trend",
        }


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
