"""Fix #5H2B — locks/documents the CURRENT public output contract for
supply_demand_zones (no behavior changed by this fix; test-only).

Fix #5H2A's audit concluded: KEEP the existing `if z.valid` (i.e.
"exclude invalidated") filter in core.Output.Output._build_supply_demand_zones()
as-is for now (a separate all-zones/history contract is a possible future
addition, not this fix). These tests pin down exactly what that decision
means today, so a future change to the filter is a deliberate, visible
break of these tests rather than a silent drift:

1. _build_supply_demand_zones() still excludes invalidated=True zones.
2. Therefore the public supply_demand_zones output can only ever expose
   freshness_state in {"fresh", "touched", "mitigated"} — never
   "invalidated" — because a zone reaching derive_freshness_state() here
   is always valid==True (invalidated==False) by construction.
3. The PURE derive_freshness_state() helper itself is untouched and still
   returns "invalidated" for an invalidated zone — it's the canonical,
   internal reasoning primitive, usable as-is for any future all-zone/
   history contract without modification.
4. structure_events.origin_zone_* (the current-event zone<->leg-origin
   link) can still reference a zone that is invalidated / absent from
   supply_demand_zones — link_zone_to_leg_origin() reads the same raw
   zones_map, independent of Output's serialization filter (confirmed in
   Fix #5H2A's audit, section 4).

No production filtering is changed here — this file adds coverage only.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_zone_output_validity_lock.py -v
"""
from core.demand_engine import (
    SupplyDemandZone,
    derive_freshness_state,
    link_zone_to_leg_origin,
)


def make_zone(zone_type="demand", top=101.0, bottom=100.0, timestamp="1000",
              valid=True, mitigated=False, invalidated=False, touch_count=0,
              classification="unknown", impulse_strength=1.0):
    return SupplyDemandZone(
        type=zone_type, top=top, bottom=bottom, timestamp=timestamp,
        valid=valid, mitigated=mitigated, invalidated=invalidated,
        touch_count=touch_count, classification=classification, impulse_strength=impulse_strength,
    )


class FakeDemandEngine:
    """Unused when zones_map is supplied — present only because
    _build_supply_demand_zones()'s signature requires a demand_engine
    positional arg; mirrors the existing convention in
    tests/test_zone_impulse_strength_rename.py."""

    def get_zones(self, symbol, tf, cache=None):
        return []


# ---------------------------------------------------------------------------
# 1 & 2 — production filter still excludes invalidated; surviving zones can
# only read fresh/touched/mitigated, never invalidated.
# ---------------------------------------------------------------------------

def test_invalidated_zone_excluded_from_supply_demand_zones_output():
    from core.Output.Output import _build_supply_demand_zones

    fresh = make_zone(timestamp="1", touch_count=0, mitigated=False, invalidated=False)
    touched = make_zone(timestamp="2", touch_count=1, mitigated=False, invalidated=False)
    mitigated = make_zone(timestamp="3", touch_count=2, mitigated=True, invalidated=False)
    invalidated = make_zone(timestamp="4", touch_count=3, mitigated=True, invalidated=True, valid=False)

    zones_map = {"H1": [fresh, touched, mitigated, invalidated]}
    result = _build_supply_demand_zones("TEST", FakeDemandEngine(), zones_map=zones_map)

    h1_zones = result.get("H1", [])
    assert len(h1_zones) == 3, "the invalidated zone must not survive serialization"
    serialized_timestamps = {z["timestamp"] for z in h1_zones}
    assert serialized_timestamps == {"1", "2", "3"}
    assert "4" not in serialized_timestamps


def test_public_freshness_state_values_never_include_invalidated():
    from core.Output.Output import _build_supply_demand_zones

    fresh = make_zone(timestamp="1", touch_count=0, mitigated=False, invalidated=False)
    touched = make_zone(timestamp="2", touch_count=1, mitigated=False, invalidated=False)
    mitigated = make_zone(timestamp="3", touch_count=2, mitigated=True, invalidated=False)
    invalidated = make_zone(timestamp="4", touch_count=3, mitigated=True, invalidated=True, valid=False)

    zones_map = {"H1": [fresh, touched, mitigated, invalidated]}
    result = _build_supply_demand_zones("TEST", FakeDemandEngine(), zones_map=zones_map)

    freshness_values = {z["freshness_state"] for z in result["H1"]}
    assert freshness_values == {"fresh", "touched", "mitigated"}
    assert "invalidated" not in freshness_values


# ---------------------------------------------------------------------------
# 3 — the pure helper itself is untouched: still reports "invalidated" for
# internal/canonical reasoning and any future all-zone/history contract.
# ---------------------------------------------------------------------------

def test_pure_derive_freshness_state_still_reports_invalidated():
    zone = make_zone(invalidated=True, valid=False, mitigated=True, touch_count=5)
    assert derive_freshness_state(zone) == "invalidated"


# ---------------------------------------------------------------------------
# 4 — origin_zone_* linkage is independent of the output filter: an
# invalidated zone can still be the current structural leg origin, even
# though it will never appear in supply_demand_zones.
# ---------------------------------------------------------------------------

def test_invalidated_zone_can_still_be_the_current_origin_link_despite_output_exclusion():
    from core.Output.Output import _build_supply_demand_zones

    invalidated_origin = make_zone(
        zone_type="demand", top=100.0, bottom=99.0, timestamp="100000",
        invalidated=True, valid=False, mitigated=True, touch_count=4,
    )
    zones_map = {"H1": [invalidated_origin]}

    # Same raw zones_map, evaluated two independent ways:

    # (a) the structural link — reads raw zones_map, ignores valid/mitigated/invalidated.
    linked = link_zone_to_leg_origin(
        zones_map["H1"], structure_valid=True, structure_direction="Bullish",
        leg_origin_timestamp="100000", leg_origin_price=99.5,
        event_timestamp="100000", timeframe="H1",
    )
    assert linked is invalidated_origin

    # (b) the public output — reads the SAME raw zones_map, excludes it.
    output = _build_supply_demand_zones("TEST", FakeDemandEngine(), zones_map=zones_map)
    assert output == {}, "the invalidated origin zone must not leak into the public zones list"
