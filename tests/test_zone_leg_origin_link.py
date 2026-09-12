"""Fix #5G1 — targeted tests for the canonical, deterministic zone <-> leg
origin link (core.demand_engine.link_zone_to_leg_origin()). Pure zone
objects, no MT5 needed for the unit-level tests; a live check confirms the
wiring end-to-end.

Fix #5G1A adds a required `event_timestamp` parameter (the causality
guard: a candidate's timestamp must not be later than the break candle's
own timestamp). Every existing call below was updated to pass an
`event_timestamp` that sits at/after the zone(s) each test cares about, so
none of the original 17 tests' outcomes changed — only the call signature.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_zone_leg_origin_link.py -v
"""
from core.demand_engine import (
    SupplyDemandZone,
    _swing_tolerance_seconds,
    link_zone_to_leg_origin,
)


def make_zone(zone_type, top, bottom, timestamp, valid=True, mitigated=False, invalidated=False, touch_count=0, classification="unknown", impulse_strength=1.0):
    return SupplyDemandZone(
        type=zone_type, top=top, bottom=bottom, timestamp=timestamp,
        valid=valid, mitigated=mitigated, invalidated=invalidated,
        touch_count=touch_count, classification=classification, impulse_strength=impulse_strength,
    )


TOL_H1 = _swing_tolerance_seconds("H1")


def test_bullish_links_demand_zone():
    demand = make_zone("demand", top=100.0, bottom=99.0, timestamp="100000")
    supply = make_zone("supply", top=100.0, bottom=99.0, timestamp="100000")
    result = link_zone_to_leg_origin(
        [supply, demand], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5, event_timestamp="100000", timeframe="H1",
    )
    assert result is demand


def test_bearish_links_supply_zone():
    demand = make_zone("demand", top=100.0, bottom=99.0, timestamp="100000")
    supply = make_zone("supply", top=100.0, bottom=99.0, timestamp="100000")
    result = link_zone_to_leg_origin(
        [demand, supply], structure_valid=True, structure_direction="Bearish",
        leg_origin_timestamp="100000", leg_origin_price=99.5, event_timestamp="100000", timeframe="H1",
    )
    assert result is supply


def test_wrong_direction_zone_rejected():
    """Only a supply zone exists, but the leg is Bullish -> no eligible
    candidate at all, even though it would otherwise match on time/price."""
    supply = make_zone("supply", top=100.0, bottom=99.0, timestamp="100000")
    result = link_zone_to_leg_origin(
        [supply], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5, event_timestamp="100000", timeframe="H1",
    )
    assert result is None


def test_time_outside_tolerance_rejected():
    zone_ts = 100000 + TOL_H1 + 1
    demand = make_zone("demand", top=100.0, bottom=99.0, timestamp=str(zone_ts))
    result = link_zone_to_leg_origin(
        [demand], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5,
        event_timestamp=str(zone_ts + 100),  # at/after the zone, so tolerance (not causality) is what rejects it
        timeframe="H1",
    )
    assert result is None


def test_time_at_exact_tolerance_boundary_accepted():
    zone_ts = 100000 + TOL_H1
    demand = make_zone("demand", top=100.0, bottom=99.0, timestamp=str(zone_ts))
    result = link_zone_to_leg_origin(
        [demand], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5,
        event_timestamp=str(zone_ts), timeframe="H1",
    )
    assert result is demand


def test_price_outside_zone_rejected():
    """Zone is within timestamp tolerance but leg_origin_price falls
    outside [bottom, top] -> rejected."""
    demand = make_zone("demand", top=100.0, bottom=99.0, timestamp="100000")
    result = link_zone_to_leg_origin(
        [demand], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=98.0, event_timestamp="100000", timeframe="H1",
    )
    assert result is None


def test_price_at_exact_boundary_accepted():
    demand = make_zone("demand", top=100.0, bottom=99.0, timestamp="100000")
    result_top = link_zone_to_leg_origin(
        [demand], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=100.0, event_timestamp="100000", timeframe="H1",
    )
    result_bottom = link_zone_to_leg_origin(
        [demand], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.0, event_timestamp="100000", timeframe="H1",
    )
    assert result_top is demand
    assert result_bottom is demand


def test_mitigated_and_invalidated_zone_can_still_link():
    """Freshness (valid/mitigated/touch_count) must not be used as a
    filter — a historically-correct origin zone can link even if it has
    since been touched or fully invalidated."""
    stale_demand = make_zone(
        "demand", top=100.0, bottom=99.0, timestamp="100000",
        valid=False, mitigated=True, invalidated=True, touch_count=5,
    )
    result = link_zone_to_leg_origin(
        [stale_demand], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5, event_timestamp="100000", timeframe="H1",
    )
    assert result is stale_demand


def test_classification_and_impulse_strength_not_used_as_filters():
    """A zone classified "unknown" with low impulse_strength must still
    link if it passes the direction/time/price gates — those fields are
    deliberately not consulted."""
    zone = make_zone(
        "demand", top=100.0, bottom=99.0, timestamp="100000",
        classification="unknown", impulse_strength=0.61,
    )
    result = link_zone_to_leg_origin(
        [zone], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5, event_timestamp="100000", timeframe="H1",
    )
    assert result is zone


def test_closest_timestamp_wins_among_multiple_candidates():
    far = make_zone("demand", top=100.0, bottom=99.0, timestamp=str(100000 - 5000))
    close = make_zone("demand", top=100.0, bottom=99.0, timestamp=str(100000 - 100))
    medium = make_zone("demand", top=100.0, bottom=99.0, timestamp=str(100000 + 2000))
    result = link_zone_to_leg_origin(
        [far, medium, close], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5,
        event_timestamp=str(100000 + 5000),  # at/after every candidate, so causality doesn't filter any out
        timeframe="H1",
    )
    assert result is close


def test_exact_tie_later_list_item_wins():
    earlier = make_zone("demand", top=100.0, bottom=99.0, timestamp=str(100000 - 500))
    later = make_zone("demand", top=100.0, bottom=99.0, timestamp=str(100000 + 500))
    result = link_zone_to_leg_origin(
        [earlier, later], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5,
        event_timestamp=str(100000 + 500), timeframe="H1",
    )
    assert result is later, "equidistant candidates must resolve to the LATER list item"


def test_no_candidate_at_all_returns_none():
    result = link_zone_to_leg_origin(
        [], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5, event_timestamp="100000", timeframe="H1",
    )
    assert result is None


def test_invalid_structure_event_returns_none():
    demand = make_zone("demand", top=100.0, bottom=99.0, timestamp="100000")
    result = link_zone_to_leg_origin(
        [demand], structure_valid=False, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5, event_timestamp="100000", timeframe="H1",
    )
    assert result is None


def test_neutral_direction_returns_none():
    demand = make_zone("demand", top=100.0, bottom=99.0, timestamp="100000")
    result = link_zone_to_leg_origin(
        [demand], structure_valid=True, structure_direction="Neutral",
        leg_origin_timestamp="100000", leg_origin_price=99.5, event_timestamp="100000", timeframe="H1",
    )
    assert result is None


def test_missing_leg_origin_evidence_returns_none():
    demand = make_zone("demand", top=100.0, bottom=99.0, timestamp="100000")
    assert link_zone_to_leg_origin(
        [demand], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp=None, leg_origin_price=99.5, event_timestamp="100000", timeframe="H1",
    ) is None
    assert link_zone_to_leg_origin(
        [demand], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=None, event_timestamp="100000", timeframe="H1",
    ) is None


# ── Fix #5G1A — causality guard ───────────────────────────────────────────

def test_zone_after_event_timestamp_rejected_even_if_near_origin_and_price_matches():
    """A zone that formed AFTER the break itself was detected cannot be
    the origin of the leg that produced that break — even though it's
    well within timestamp tolerance of leg_origin_timestamp and its price
    range contains leg_origin_price exactly."""
    zone_after_event = make_zone("demand", top=100.0, bottom=99.0, timestamp="100050")
    result = link_zone_to_leg_origin(
        [zone_after_event], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5,
        event_timestamp="100010",  # event happened BEFORE the zone formed
        timeframe="H1",
    )
    assert result is None


def test_zone_before_or_on_event_timestamp_can_link():
    """The same candidate zone, now at/before the event timestamp, must be
    able to link — proving the guard only rejects true after-the-fact
    zones, not proximity/price-valid ones in general."""
    zone_before_event = make_zone("demand", top=100.0, bottom=99.0, timestamp="100000")
    result_before = link_zone_to_leg_origin(
        [zone_before_event], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5,
        event_timestamp="100050",  # event happens well after the zone -> causally valid
        timeframe="H1",
    )
    assert result_before is zone_before_event

    zone_exactly_on_event = make_zone("demand", top=100.0, bottom=99.0, timestamp="100050")
    result_on = link_zone_to_leg_origin(
        [zone_exactly_on_event], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5,
        event_timestamp="100050",  # zone formed on the SAME candle as the break -> still allowed (<=)
        timeframe="H1",
    )
    assert result_on is zone_exactly_on_event


def test_missing_event_timestamp_returns_none():
    demand = make_zone("demand", top=100.0, bottom=99.0, timestamp="100000")
    result = link_zone_to_leg_origin(
        [demand], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5, event_timestamp=None, timeframe="H1",
    )
    assert result is None


# ── Live: wiring end-to-end ───────────────────────────────────────────────

def test_live_structure_snapshot_carries_origin_zone_fields():
    """Live regression: StructureSnapshot must always expose the four
    origin_zone_* fields (None or populated), and when populated they must
    describe a zone that genuinely satisfies the linking rule."""
    import api.core_router as cr
    from core.candle_cache import CandleCache

    symbol = "XAUUSD_i"
    timeframes = ["M1", "M5", "M15", "M30", "H1", "H4", "D1", "W1", "MN1"]
    cache = CandleCache(cr.candle_engine)
    cache.fetch_all([symbol], timeframes, count=100)

    for tf in timeframes:
        snap = cr.structure_engine.get_snapshot(symbol, tf, cache=cache)
        if snap is None:
            continue
        assert hasattr(snap, "origin_zone_type")
        assert hasattr(snap, "origin_zone_timestamp")
        assert hasattr(snap, "origin_zone_top")
        assert hasattr(snap, "origin_zone_bottom")
        if not snap.structure_valid:
            assert snap.origin_zone_type is None
            assert snap.origin_zone_timestamp is None
            assert snap.origin_zone_top is None
            assert snap.origin_zone_bottom is None
        elif snap.origin_zone_type is not None:
            expected_type = "demand" if snap.structure_direction == "Bullish" else "supply"
            assert snap.origin_zone_type == expected_type
            assert snap.origin_zone_bottom <= snap.leg_origin_price <= snap.origin_zone_top


def test_structure_events_output_shape_includes_origin_zone_fields():
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
    for tf, event in out[symbol].get("structure_events", {}).items():
        assert "origin_zone_type" in event
        assert "origin_zone_timestamp" in event
        assert "origin_zone_top" in event
        assert "origin_zone_bottom" in event


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
