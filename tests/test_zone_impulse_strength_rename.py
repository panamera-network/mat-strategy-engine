"""Fix #5D1 — targeted tests confirming SupplyDemandZone.strength was
renamed to impulse_strength: formula unchanged, old name fully gone, no
leftover zone-strength consumer anywhere, and the public /core/output
contract exposes the new name.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_zone_impulse_strength_rename.py -v
"""
from dataclasses import fields

from core.core_models import CandleSnapshot
from core.demand_engine import SupplyDemandZone, compute_atr, detect_zones


def make_candle(o, h, l, c, ts="0"):
    return CandleSnapshot(open=o, high=h, low=l, close=c, volume=100, timestamp=ts)


def test_old_strength_field_is_gone():
    field_names = {f.name for f in fields(SupplyDemandZone)}
    assert "strength" not in field_names
    assert "impulse_strength" in field_names


def test_zone_has_no_strength_attribute():
    zone = SupplyDemandZone(type="demand", top=1.0, bottom=0.0)
    assert not hasattr(zone, "strength")
    assert hasattr(zone, "impulse_strength")
    assert zone.impulse_strength == 0.0  # default


def test_detect_zones_formula_unchanged_body_over_atr():
    """The value itself must still be exactly round(body / atr, 2) — only
    the field name changed, not the computation."""
    candles = [make_candle(100, 100.2, 99.8, 100.1, str(i)) for i in range(10)]
    # One clearly oversized bullish candle to guarantee a zone forms.
    candles[5] = make_candle(100, 101.0, 99.9, 100.9, "5")

    zones = detect_zones(candles)
    assert zones, "expected at least one zone to form"
    zone = zones[0]

    atr = compute_atr(candles[:6])  # ATR computed over the same candles up to the zone
    # detect_zones() computes ATR once over the full input candles, so
    # recompute the same way for a faithful comparison.
    atr_full = compute_atr(candles)
    body = abs(candles[5].close - candles[5].open)
    expected = round(body / atr_full, 2)
    assert zone.impulse_strength == expected


def test_detect_zones_never_sets_a_strength_attribute():
    candles = [make_candle(100, 100.2, 99.8, 100.1, str(i)) for i in range(10)]
    candles[5] = make_candle(100, 101.0, 99.9, 100.9, "5")
    zones = detect_zones(candles)
    for z in zones:
        assert not hasattr(z, "strength")


# ── Public contract: /core/output serializes impulse_strength ───────────

def test_build_supply_demand_zones_serializes_impulse_strength_key():
    from core.Output.Output import _build_supply_demand_zones

    class FakeDemandEngine:
        def get_zones(self, symbol, tf, cache=None):
            return [SupplyDemandZone(type="demand", top=101.0, bottom=100.0, valid=True, timestamp="1000", impulse_strength=1.23)]

    result = _build_supply_demand_zones("TEST", FakeDemandEngine())
    assert result, "expected at least one timeframe with zones"
    for tf_zones in result.values():
        for zone_dict in tf_zones:
            assert "impulse_strength" in zone_dict
            assert "strength" not in zone_dict
            assert zone_dict["impulse_strength"] == 1.23


def test_live_output_exposes_impulse_strength_not_strength():
    """Live regression: /core/output's supply_demand_zones must key on
    impulse_strength, never the old "strength" name."""
    import api.core_router as cr
    from core.candle_cache import CandleCache
    from core.Output.Output import build_multi_symbol_output

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]

    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    out = build_multi_symbol_output(
        bias_engine=cr.bias_engine,
        candle_engine=cr.candle_engine,
        momentum_engine=cr.momentum_engine,
        demand_engine=cr.demand_engine,
        shift_engine=cr.shift_engine,
        structure_engine=cr.structure_engine,
        cache=cache,
        symbols=[symbol],
    )
    assert "error" not in out[symbol]
    zones = out[symbol].get("supply_demand_zones", {})
    assert zones, "expected at least one timeframe with zones for a live smoke test"
    for tf_zones in zones.values():
        for z in tf_zones:
            assert "impulse_strength" in z
            assert "strength" not in z


if __name__ == "__main__":
    test_old_strength_field_is_gone()
    print("[PASS] old 'strength' field is gone, impulse_strength present")

    test_zone_has_no_strength_attribute()
    print("[PASS] zone instance has no .strength attribute")

    test_detect_zones_formula_unchanged_body_over_atr()
    print("[PASS] impulse_strength formula unchanged (body / ATR)")

    test_detect_zones_never_sets_a_strength_attribute()
    print("[PASS] detect_zones() never produces a .strength attribute")

    test_build_supply_demand_zones_serializes_impulse_strength_key()
    print("[PASS] Output serializes impulse_strength, not strength")

    test_live_output_exposes_impulse_strength_not_strength()
    print("[PASS] live /core/output exposes impulse_strength only")

    print("\nALL FIX #5D1 REGRESSION CHECKS PASSED")
