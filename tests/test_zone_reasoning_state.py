"""Fix #5H2 — targeted tests for the canonical zone reasoning helpers
(core.demand_engine.derive_structural_evidence() / derive_freshness_state()).
Pure zone objects, no MT5 needed.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_zone_reasoning_state.py -v
"""
from core.demand_engine import (
    SupplyDemandZone,
    derive_freshness_state,
    derive_structural_evidence,
)


def make_zone(zone_type="demand", top=100.0, bottom=99.0, timestamp="100000", valid=True,
              mitigated=False, invalidated=False, touch_count=0, classification="unknown",
              impulse_strength=1.0):
    return SupplyDemandZone(
        type=zone_type, top=top, bottom=bottom, timestamp=timestamp,
        valid=valid, mitigated=mitigated, invalidated=invalidated,
        touch_count=touch_count, classification=classification, impulse_strength=impulse_strength,
    )


# ---------------------------------------------------------------------------
# derive_freshness_state()
# ---------------------------------------------------------------------------

def test_freshness_fresh_when_never_touched():
    zone = make_zone(touch_count=0, mitigated=False, invalidated=False)
    assert derive_freshness_state(zone) == "fresh"


def test_freshness_touched_when_touch_count_positive_but_not_mitigated():
    zone = make_zone(touch_count=2, mitigated=False, invalidated=False)
    assert derive_freshness_state(zone) == "touched"


def test_freshness_mitigated_outranks_touched():
    zone = make_zone(touch_count=3, mitigated=True, invalidated=False)
    assert derive_freshness_state(zone) == "mitigated"


def test_freshness_invalidated_outranks_mitigated():
    zone = make_zone(touch_count=5, mitigated=True, invalidated=True, valid=False)
    assert derive_freshness_state(zone) == "invalidated"


def test_freshness_invalidated_even_with_zero_touch_count():
    # Defensive: invalidated must win regardless of the other fields' state.
    zone = make_zone(touch_count=0, mitigated=False, invalidated=True, valid=False)
    assert derive_freshness_state(zone) == "invalidated"


def test_freshness_ignores_impulse_strength():
    low = make_zone(impulse_strength=0.1, touch_count=1)
    high = make_zone(impulse_strength=99.0, touch_count=1)
    assert derive_freshness_state(low) == derive_freshness_state(high) == "touched"


# ---------------------------------------------------------------------------
# derive_structural_evidence()
# ---------------------------------------------------------------------------

def test_structural_evidence_confirmed_current_event_exact_match():
    zone = make_zone(zone_type="demand", top=105.0, bottom=100.0, timestamp="200000", classification="unknown")
    result = derive_structural_evidence(
        zone,
        origin_zone_type="demand", origin_zone_timestamp="200000",
        origin_zone_top=105.0, origin_zone_bottom=100.0,
    )
    assert result == "confirmed_current_event"


def test_structural_evidence_confirmed_current_event_even_when_invalidated():
    """Fix #5H2 requirement: invalidated zone may still be
    confirmed_current_event — freshness has no bearing on this label."""
    zone = make_zone(
        zone_type="demand", top=105.0, bottom=100.0, timestamp="200000",
        invalidated=True, valid=False, mitigated=True, touch_count=4,
        classification="unknown",
    )
    result = derive_structural_evidence(
        zone,
        origin_zone_type="demand", origin_zone_timestamp="200000",
        origin_zone_top=105.0, origin_zone_bottom=100.0,
    )
    assert result == "confirmed_current_event"
    assert derive_freshness_state(zone) == "invalidated"


def test_structural_evidence_supported_when_fresh_and_classified():
    """supported + fresh combination."""
    zone = make_zone(classification="reversal", touch_count=0, mitigated=False, invalidated=False)
    assert derive_structural_evidence(zone, None, None, None, None) == "supported"
    assert derive_freshness_state(zone) == "fresh"


def test_structural_evidence_supported_continuation_classification():
    zone = make_zone(classification="continuation")
    assert derive_structural_evidence(zone, None, None, None, None) == "supported"


def test_structural_evidence_unconfirmed_when_unknown_and_touched():
    """unconfirmed + touched combination."""
    zone = make_zone(classification="unknown", touch_count=1, mitigated=False)
    assert derive_structural_evidence(zone, None, None, None, None) == "unconfirmed"
    assert derive_freshness_state(zone) == "touched"


def test_structural_evidence_unconfirmed_when_unknown_and_mitigated():
    """unconfirmed + mitigated combination."""
    zone = make_zone(classification="unknown", touch_count=2, mitigated=True)
    assert derive_structural_evidence(zone, None, None, None, None) == "unconfirmed"
    assert derive_freshness_state(zone) == "mitigated"


def test_structural_evidence_unconfirmed_is_not_a_negative_label():
    """unknown classification must map to unconfirmed, never a distinct
    'bad'/negative label — same string as the plain no-evidence case."""
    unknown_zone = make_zone(classification="unknown")
    assert derive_structural_evidence(unknown_zone, None, None, None, None) == "unconfirmed"


def test_structural_evidence_non_current_zone_does_not_inherit_confirmation():
    """A zone of the matching type but a different timestamp/top/bottom
    than the current origin_zone_* must NOT read confirmed_current_event,
    even though some other zone is the current link."""
    other_zone = make_zone(zone_type="demand", top=50.0, bottom=48.0, timestamp="999999", classification="reversal")
    result = derive_structural_evidence(
        other_zone,
        origin_zone_type="demand", origin_zone_timestamp="200000",
        origin_zone_top=105.0, origin_zone_bottom=100.0,
    )
    assert result == "supported"  # falls through to classification-based reasoning, not confirmed


def test_structural_evidence_wrong_type_does_not_match_even_with_same_coordinates():
    """Type must match too — a supply zone can never inherit a demand
    origin link's confirmation, even with identical timestamp/top/bottom."""
    zone = make_zone(zone_type="supply", top=105.0, bottom=100.0, timestamp="200000", classification="unknown")
    result = derive_structural_evidence(
        zone,
        origin_zone_type="demand", origin_zone_timestamp="200000",
        origin_zone_top=105.0, origin_zone_bottom=100.0,
    )
    assert result == "unconfirmed"


def test_structural_evidence_no_current_origin_zone_never_confirms():
    """origin_zone_type=None (no confirmed link this event) -> no zone can
    ever read confirmed_current_event, regardless of its own fields."""
    zone = make_zone(zone_type="demand", top=105.0, bottom=100.0, timestamp=None, classification="unknown")
    result = derive_structural_evidence(zone, None, None, None, None)
    assert result == "unconfirmed"


def test_structural_evidence_partial_field_mismatch_rejected():
    """All four fields (type/timestamp/top/bottom) must match exactly —
    a near-miss on just one field must not confirm."""
    zone = make_zone(zone_type="demand", top=105.0, bottom=100.0, timestamp="200000", classification="unknown")
    result = derive_structural_evidence(
        zone,
        origin_zone_type="demand", origin_zone_timestamp="200000",
        origin_zone_top=105.01, origin_zone_bottom=100.0,  # top off by 0.01
    )
    assert result == "unconfirmed"
