"""Fix #5B, corrected — targeted tests for the additive
SupplyDemandZone.classification label (reversal / continuation / unknown).
Pure zone + SwingPoint objects, no MT5 needed.

Correction: continuation now additionally requires the zone's timestamp to
fall within the structure evidence's actual coverage window (earliest..
latest swing_points timestamp, padded by the reversal tolerance margin) —
a zone whose timestamp predates/postdates everything structure evidence
examined can never be "continuation" purely off its pattern, since there's
no real evidence it isn't sitting next to an unconfirmed swing outside that
window. Several tests below were updated from expecting "continuation" to
"unknown" for exactly this reason — see each test's comment.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_demand_zone_classification.py -v
"""
from core.core_models import SwingPoint
from core.demand_engine import (
    SupplyDemandZone,
    TIMEFRAME_SECONDS,
    _swing_tolerance_seconds,
    classify_zone,
    classify_zones,
)


def make_zone(zone_type, top=101.0, bottom=99.0, pattern="", timestamp=None):
    return SupplyDemandZone(type=zone_type, top=top, bottom=bottom, pattern=pattern, timestamp=timestamp)


def make_swing(label, timestamp, price=100.0, index=0):
    return SwingPoint(label=label, price=price, index=index, timestamp=timestamp)


# ── _swing_tolerance_seconds ─────────────────────────────────────────────

def test_tolerance_is_seconds_per_candle_times_swing_window():
    # H1 = 3600s/candle, SWING_WINDOW = 3 -> 10800s
    assert _swing_tolerance_seconds("H1") == TIMEFRAME_SECONDS["H1"] * 3


def test_tolerance_zero_for_unknown_timeframe():
    assert _swing_tolerance_seconds("BOGUS") == 0
    assert _swing_tolerance_seconds("") == 0


def test_tolerance_case_insensitive():
    assert _swing_tolerance_seconds("h1") == _swing_tolerance_seconds("H1")


# ── classify_zone: reversal ──────────────────────────────────────────────

def test_demand_zone_near_swing_low_is_reversal():
    zone = make_zone("demand", pattern="DBR", timestamp="100000")
    swing_points = [make_swing("LL", timestamp="100500")]  # 500s away, well inside H1 tolerance (10800s)
    assert classify_zone(zone, swing_points, timeframe="H1") == "reversal"


def test_supply_zone_near_swing_high_is_reversal():
    zone = make_zone("supply", pattern="RBD", timestamp="200000")
    swing_points = [make_swing("HH", timestamp="199000")]  # 1000s away
    assert classify_zone(zone, swing_points, timeframe="H1") == "reversal"


def test_demand_zone_near_HL_swing_is_also_reversal():
    """HL is still a confirmed swing low, not just LL."""
    zone = make_zone("demand", timestamp="100000")
    swing_points = [make_swing("HL", timestamp="100100")]
    assert classify_zone(zone, swing_points, timeframe="H1") == "reversal"


def test_supply_zone_near_LH_swing_is_also_reversal():
    """LH is still a confirmed swing high, not just HH."""
    zone = make_zone("supply", timestamp="100000")
    swing_points = [make_swing("LH", timestamp="99900")]
    assert classify_zone(zone, swing_points, timeframe="H1") == "reversal"


def test_reversal_requires_matching_direction_swing():
    """A demand zone near a swing HIGH (wrong direction) must not count as reversal."""
    zone = make_zone("demand", pattern="RBR", timestamp="100000")
    swing_points = [make_swing("HH", timestamp="100100")]
    assert classify_zone(zone, swing_points, timeframe="H1") == "continuation"


def test_reversal_boundary_inclusive():
    zone = make_zone("demand", timestamp="100000")
    tolerance = _swing_tolerance_seconds("H1")
    swing_points = [make_swing("LL", timestamp=str(100000 + tolerance))]  # exactly at boundary
    assert classify_zone(zone, swing_points, timeframe="H1") == "reversal"


def test_outside_tolerance_is_not_reversal():
    """The single swing point sits 1s past the reversal-matching boundary
    from the zone, so reversal must not fire — but it's also the ONLY
    evidence available, and its own coverage window (padded by tolerance)
    doesn't quite reach back to the zone either, so this now correctly
    falls to "unknown", not a bare pattern-only "continuation" (correction)."""
    zone = make_zone("demand", pattern="RBR", timestamp="100000")
    tolerance = _swing_tolerance_seconds("H1")
    swing_points = [make_swing("LL", timestamp=str(100000 + tolerance + 1))]  # 1s past boundary
    assert classify_zone(zone, swing_points, timeframe="H1") == "unknown"


# ── classify_zone: continuation ──────────────────────────────────────────

def test_demand_zone_RBR_within_coverage_is_continuation():
    """Zone sits inside the structure evidence's coverage window (between
    two confirmed swings) and isn't near either — genuine continuation."""
    zone = make_zone("demand", pattern="RBR", timestamp="150000")
    swing_points = [make_swing("LL", timestamp="100000"), make_swing("HH", timestamp="200000")]
    assert classify_zone(zone, swing_points, timeframe="H1") == "continuation"


def test_supply_zone_DBD_within_coverage_is_continuation():
    zone = make_zone("supply", pattern="DBD", timestamp="150000")
    swing_points = [make_swing("LL", timestamp="100000"), make_swing("HH", timestamp="200000")]
    assert classify_zone(zone, swing_points, timeframe="H1") == "continuation"


def test_demand_zone_RBR_far_from_swings_is_unknown():
    """Correction target: a zone from an old candle, far outside the
    structure evidence's coverage window, must be "unknown" even with a
    continuation-shaped pattern — there's no evidence backing "not near a
    swing" that far outside what structure evidence actually examined.
    (Previously this asserted "continuation" — that was the bug.)"""
    zone = make_zone("demand", pattern="RBR", timestamp="500000")
    swing_points = [make_swing("LL", timestamp="0")]  # coverage far in the past, nowhere near the zone
    assert classify_zone(zone, swing_points, timeframe="H1") == "unknown"


def test_supply_zone_DBD_far_from_swings_is_unknown():
    """Same correction, supply side."""
    zone = make_zone("supply", pattern="DBD", timestamp="500000")
    swing_points = [make_swing("HH", timestamp="0")]
    assert classify_zone(zone, swing_points, timeframe="H1") == "unknown"


def test_old_zone_outside_structure_window_with_RBR_pattern_is_unknown():
    """The explicit correction regression: a realistic structure coverage
    window (confirmed swings spanning timestamps 100000..500000), and a
    zone from a much older candle sitting well before that entire window —
    even with a perfect RBR pattern, this must be "unknown", never
    "continuation", since structure evidence never examined that far back."""
    swing_points = [make_swing("LL", timestamp="100000"), make_swing("HL", timestamp="500000")]
    old_zone = make_zone("demand", pattern="RBR", timestamp="0")  # well before coverage starts (100000)
    assert classify_zone(old_zone, swing_points, timeframe="H1") == "unknown"

    # Sanity check: a zone genuinely inside this window (and not near either
    # swing closely enough to be a reversal) with the same pattern still
    # classifies as continuation — proving the rejection above is
    # specifically about being outside the window, not a broken pattern check.
    recent_zone = make_zone("demand", pattern="RBR", timestamp="300000")
    assert classify_zone(recent_zone, swing_points, timeframe="H1") == "continuation"


def test_demand_zone_wrong_pattern_for_continuation_is_unknown():
    """DBD is a supply-side continuation pattern, not demand's."""
    zone = make_zone("demand", pattern="DBD", timestamp="500000")
    assert classify_zone(zone, [], timeframe="H1") == "unknown"


# ── classify_zone: unknown fallback ──────────────────────────────────────

def test_no_timestamp_is_unknown_even_with_continuation_pattern():
    """Correction: continuation now also requires checking the zone's
    timestamp against structure coverage — without a timestamp at all,
    neither reversal NOR continuation can be evaluated, so this is
    "unknown" (previously this asserted "continuation" via a pattern-only
    fallback — that fallback no longer exists)."""
    zone = make_zone("demand", pattern="RBR", timestamp=None)
    swing_points = [make_swing("LL", timestamp="100000")]
    assert classify_zone(zone, swing_points, timeframe="H1") == "unknown"


def test_no_timestamp_and_no_continuation_pattern_is_unknown():
    zone = make_zone("demand", pattern="DBR", timestamp=None)
    swing_points = [make_swing("LL", timestamp="100000")]
    assert classify_zone(zone, swing_points, timeframe="H1") == "unknown"


def test_no_swing_points_and_no_continuation_pattern_is_unknown():
    zone = make_zone("demand", pattern="DBR", timestamp="100000")
    assert classify_zone(zone, [], timeframe="H1") == "unknown"


def test_empty_swing_points_is_unknown_even_with_continuation_pattern():
    """Correction: empty swing_points means zero structure coverage —
    there's nothing to confirm the zone isn't near an unconfirmed swing,
    so this can never be "continuation" purely off pattern anymore
    (previously it fell back to pattern-only continuation — that was the bug)."""
    zone = make_zone("demand", pattern="RBR", timestamp="100000")
    assert classify_zone(zone, [], timeframe="H1") == "unknown"


def test_unresolvable_timeframe_skips_reversal_check():
    """Blank/unknown timeframe -> tolerance 0 -> never "reversal", even
    with a swing point at the exact same timestamp — avoids an accidental
    exact-match false positive when tolerance can't be determined. The
    single swing point's coverage window collapses to exactly its own
    timestamp (tolerance 0 padding), which happens to equal the zone's
    timestamp here, so continuation still fires via the coverage+pattern
    check — an intentional coincidence of this test's exact values."""
    zone = make_zone("demand", pattern="RBR", timestamp="100000")
    swing_points = [make_swing("LL", timestamp="100000")]
    assert classify_zone(zone, swing_points, timeframe="") == "continuation"


def test_bad_timestamp_type_is_unknown():
    """zone_ts unresolvable -> skip reversal check -> also fails the
    coverage check (which requires a resolvable zone_ts) -> unknown,
    regardless of pattern (correction: no more pattern-only fallback)."""
    zone = make_zone("demand", pattern="RBR", timestamp="not-a-number")
    swing_points = [make_swing("LL", timestamp="100000")]
    assert classify_zone(zone, swing_points, timeframe="H1") == "unknown"


def test_invalid_zone_type_is_unknown():
    zone = SupplyDemandZone(type="bogus", top=1.0, bottom=0.0, timestamp="100000")
    assert classify_zone(zone, [], timeframe="H1") == "unknown"


# ── classify_zones (batch) ────────────────────────────────────────────────

def test_classify_zones_sets_classification_in_place_and_returns_list():
    zones = [
        make_zone("demand", pattern="RBR", timestamp="500000"),
        make_zone("supply", pattern="RBD", timestamp="100000"),
    ]
    # Two swing points widen the coverage window to include both zones'
    # timestamps (500000 needs a swing near it too — correction requires
    # coverage, not just any single swing anywhere).
    swing_points = [make_swing("HH", timestamp="100100"), make_swing("HH", timestamp="505000")]
    result = classify_zones(zones, swing_points, timeframe="H1")
    assert result is zones  # same list, mutated in place
    assert zones[0].classification == "continuation"
    assert zones[1].classification == "reversal"


def test_classify_zones_defaults_new_zone_to_unknown_before_classification():
    """detect_zones() itself is unchanged — zones start life as "unknown"
    until classify_zone()/classify_zones() is explicitly called."""
    zone = SupplyDemandZone(type="demand", top=1.0, bottom=0.0)
    assert zone.classification == "unknown"


if __name__ == "__main__":
    import sys
    import pytest as _pytest
    sys.exit(_pytest.main([__file__, "-v"]))
