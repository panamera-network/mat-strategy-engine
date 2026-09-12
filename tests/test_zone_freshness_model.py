"""Fix #5E3 — targeted state-sequence tests for the canonical zone
freshness model: touch_count (distinct visit episodes), mitigated
(close-inside, soft), invalidated (close-through-distal, decisive),
valid = not invalidated. Runs detect_zones() end-to-end over constructed
candle sequences so the exact state machine inside the loop is exercised,
not a reimplementation of it.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_zone_freshness_model.py -v
"""
from dataclasses import fields

from core.core_models import CandleSnapshot
from core.demand_engine import SupplyDemandZone, detect_zones


def c(o, h, l, cl, ts):
    return CandleSnapshot(open=o, high=h, low=l, close=cl, volume=100, timestamp=ts)


def baseline(n=14, start_ts=0):
    """Small, consistent-range candles purely to give compute_atr() a
    stable, small ATR — bodies tiny so none of these qualify as zones."""
    return [c(100 + i * 0.001, 100.1, 99.9, 100.05, str(start_ts + i)) for i in range(n)]


def build_demand_zone(later_candles):
    """One oversized bullish candle -> demand zone [bottom=99.5, top=100],
    followed by the given `later_candles`. Returns the single resulting
    zone (asserts exactly one forms, to keep every scenario unambiguous)."""
    candles = baseline()
    zone_candle = c(100, 101.6, 99.5, 101.5, "14")  # body=1.5, top=open=100, bottom=low=99.5
    candles.append(zone_candle)
    candles.extend(later_candles)
    zones = detect_zones(candles)
    demand_zones = [z for z in zones if z.type == "demand"]
    assert len(demand_zones) == 1, f"expected exactly one demand zone, got {len(zones)} zones total: {zones}"
    return demand_zones[0]


def build_supply_zone(later_candles):
    """One oversized bearish candle -> supply zone [bottom=101, top=102]
    (supply: top=high, bottom=open). open=101, close=99.6 -> body=1.4."""
    candles = baseline()
    zone_candle = c(101, 102, 99.5, 99.6, "14")
    candles.append(zone_candle)
    candles.extend(later_candles)
    zones = detect_zones(candles)
    supply_zones = [z for z in zones if z.type == "supply"]
    assert len(supply_zones) == 1, f"expected exactly one supply zone, got {len(zones)} zones total: {zones}"
    return supply_zones[0]


# ── touch_count: distinct visits, not candle count ───────────────────────

def test_no_later_candles_zero_touches_fresh():
    zone = build_demand_zone([])
    assert zone.touch_count == 0
    assert zone.mitigated is False
    assert zone.invalidated is False
    assert zone.valid is True


def test_wick_only_touch_registers_as_touch_without_mitigation():
    """Wick dips into the zone, close stays outside -> counts as a visit,
    but does not mitigate (close never landed inside) or invalidate."""
    later = [c(100.2, 100.4, 99.7, 100.3, "15")]  # low=99.7 inside zone, close=100.3 outside (above top)
    zone = build_demand_zone(later)
    assert zone.touch_count == 1
    assert zone.mitigated is False
    assert zone.invalidated is False
    assert zone.valid is True


def test_consecutive_overlapping_candles_count_as_one_visit():
    """Three candles in a row all overlapping the zone = one episode, not three."""
    later = [
        c(99.9, 100.0, 99.6, 99.8, "15"),
        c(99.8, 99.95, 99.6, 99.7, "16"),
        c(99.7, 99.9, 99.6, 99.75, "17"),
    ]
    zone = build_demand_zone(later)
    assert zone.touch_count == 1


def test_exit_then_reenter_is_a_new_visit():
    """Overlap, then a candle entirely clear of the zone, then overlap
    again -> two distinct visits."""
    later = [
        c(99.9, 100.0, 99.6, 99.8, "15"),   # visit 1 starts
        c(100.5, 100.8, 100.4, 100.6, "16"),  # entirely above zone (low=100.4 > top=100) -> exits
        c(99.9, 100.0, 99.6, 99.8, "17"),   # visit 2 starts
    ]
    zone = build_demand_zone(later)
    assert zone.touch_count == 2


def test_gap_candle_that_jumps_over_the_zone_does_not_touch():
    """A candle whose full range never overlaps the zone at all must not
    register as a touch (sanity check on the overlap condition itself).
    Small body so it doesn't form a spurious zone of its own."""
    later = [c(102.0, 102.1, 101.9, 102.05, "15")]  # entirely above zone [99.5,100]
    zone = build_demand_zone(later)
    assert zone.touch_count == 0


# ── mitigated: close inside zone, decoupled from invalidated/valid ──────

def test_close_inside_zone_mitigates_but_stays_valid():
    """The core semantic decoupling: a close landing inside the zone sets
    mitigated=True without invalidating the zone (no distal breach)."""
    later = [c(100.1, 100.2, 99.7, 99.8, "15")]  # close=99.8 inside [99.5,100]
    zone = build_demand_zone(later)
    assert zone.mitigated is True
    assert zone.invalidated is False
    assert zone.valid is True
    assert zone.touch_count == 1


def test_mitigated_is_a_one_way_flag_once_set():
    """After a close-inside candle, mitigated stays True even though a
    later candle exits the zone entirely (mitigated is not reset)."""
    later = [
        c(100.1, 100.2, 99.7, 99.8, "15"),      # close inside -> mitigated=True
        c(100.5, 100.8, 100.4, 100.6, "16"),    # exits zone entirely
    ]
    zone = build_demand_zone(later)
    assert zone.mitigated is True
    assert zone.valid is True


# ── invalidated: close through distal boundary, decisive, stops scanning ─

def test_demand_zone_invalidated_when_close_below_bottom():
    later = [c(99.52, 99.6, 99.4, 99.45, "15")]  # close=99.45 < bottom=99.5
    zone = build_demand_zone(later)
    assert zone.invalidated is True
    assert zone.valid is False


def test_supply_zone_invalidated_when_close_above_top():
    later = [c(102.0, 102.1, 101.9, 102.05, "15")]  # close=102.05 > top=102 (zone [101,102])
    zone = build_supply_zone(later)
    assert zone.invalidated is True
    assert zone.valid is False


def test_scanning_stops_after_invalidation_no_further_touches_counted():
    """Once invalidated, the loop breaks — any candles after the
    invalidating one must not affect touch_count or mitigated."""
    later = [
        c(99.52, 99.6, 99.4, 99.45, "15"),   # invalidates here
        c(99.9, 100.0, 99.6, 99.8, "16"),    # would have been a 2nd visit + mitigation, must be ignored
        c(99.9, 100.0, 99.6, 99.8, "17"),
    ]
    zone = build_demand_zone(later)
    assert zone.invalidated is True
    assert zone.valid is False
    # Only the invalidating candle itself contributes: it also overlaps the
    # zone's range, so touch_count reflects that one episode, not the two
    # later candles that are never scanned.
    assert zone.touch_count == 1
    assert zone.mitigated is False  # the invalidating candle's close (99.45) was NOT inside [99.5,100]


def test_invalidation_candle_itself_can_also_register_as_a_touch():
    """The candle whose close breaches the distal boundary still overlaps
    the zone's range via its wick, so it correctly counts as a visit too."""
    later = [c(99.52, 99.6, 99.4, 99.45, "15")]
    zone = build_demand_zone(later)
    assert zone.touch_count == 1
    assert zone.invalidated is True


def test_mitigated_then_later_invalidated_both_flags_reflect_history():
    """A soft close-inside touch followed later by a decisive distal
    breach: mitigated stays True (it happened), invalidated becomes True
    (the zone then failed), valid follows invalidated."""
    later = [
        c(100.1, 100.2, 99.7, 99.8, "15"),    # close inside -> mitigated=True
        c(100.5, 100.8, 100.4, 100.6, "16"),  # exits
        c(99.52, 99.6, 99.4, 99.45, "17"),    # breaches distal -> invalidated=True
    ]
    zone = build_demand_zone(later)
    assert zone.mitigated is True
    assert zone.invalidated is True
    assert zone.valid is False
    assert zone.touch_count == 2  # visit 1 (candle 15) + visit 2 (candle 17, after exiting on 16)


# ── status is gone entirely ──────────────────────────────────────────────

def test_status_field_no_longer_exists():
    field_names = {f.name for f in fields(SupplyDemandZone)}
    assert "status" not in field_names
    assert "touch_count" in field_names
    assert "invalidated" in field_names
    assert "touches" not in field_names  # old name fully replaced


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
