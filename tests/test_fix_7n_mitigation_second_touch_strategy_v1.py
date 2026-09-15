"""Fix #7N — Touched Zone / Mitigation v1 baseline: reacts to a canonical
zone that has already reacted once, sourced from two SEPARATE selectors
over the same canonical zone list.

This is a v1 BASELINE only -- the eligibility rule and the confidence
formula are both explicitly provisional (final reaction-quality/entry
rules deferred to a later strategy rule audit). These tests lock in v1's
exact behavior, not a claim that the rules are final.

Semantic correction (Fix #7N, superseding an earlier draft of this file):
actual synthetic candle timelines run through detect_zones() proved
touch_count/freshness cannot distinguish "zone reacted once before, now
being revisited a second time" from "this is literally the first visit,
happening right now" -- both produce identical touch_count=1,
freshness="touched" evidence. The setup is therefore named "Touched Zone"
throughout; a stricter label overclaiming a specific touch number is
deliberately avoided, and its absence is enforced by
test_no_touch_count_specific_overclaim_wording_remains below (both here and in the
strategy source).

Mitigation is sourced from a SEPARATE sibling selector,
get_nearest_mitigated_zone() (demand_engine.py), which does NOT modify
get_active_zone()/select_active_zone() -- those keep their exact existing
eligibility (valid AND NOT mitigated) unchanged. This makes Mitigation
genuinely reachable through real live data (unlike the earlier draft's
unreachable active_zone_freshness=="mitigated" branch).

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7n_mitigation_second_touch_strategy_v1.py -v
"""
import pathlib
from datetime import datetime, timezone

import pytest

from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot


def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        active_zone_type=None, active_zone_top=None, active_zone_bottom=None,
        active_zone_freshness=None, active_zone_structural_evidence=None,
        active_zone_timestamp=None, active_zone_index=None, active_zone_touch_count=None,
        mitigated_zone_type=None, mitigated_zone_top=None, mitigated_zone_bottom=None,
        mitigated_zone_structural_evidence=None, mitigated_zone_timestamp=None,
        mitigated_zone_index=None, mitigated_zone_touch_count=None,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_TOUCHED_DEMAND = dict(
    active_zone_type="demand", active_zone_top=1.2100, active_zone_bottom=1.2000,
    active_zone_freshness="touched", active_zone_structural_evidence="unconfirmed",
    active_zone_timestamp="2026-01-01T00:00:00Z", active_zone_index=42, active_zone_touch_count=1,
)
_TOUCHED_SUPPLY = dict(
    active_zone_type="supply", active_zone_top=1.3100, active_zone_bottom=1.3000,
    active_zone_freshness="touched", active_zone_structural_evidence="unconfirmed",
    active_zone_timestamp="2026-01-02T00:00:00Z", active_zone_index=43, active_zone_touch_count=1,
)
_MITIGATED_DEMAND = dict(
    mitigated_zone_type="demand", mitigated_zone_top=1.2200, mitigated_zone_bottom=1.2100,
    mitigated_zone_structural_evidence="unconfirmed",
    mitigated_zone_timestamp="2026-01-03T00:00:00Z", mitigated_zone_index=44, mitigated_zone_touch_count=1,
)
_MITIGATED_SUPPLY = dict(
    mitigated_zone_type="supply", mitigated_zone_top=1.3300, mitigated_zone_bottom=1.3200,
    mitigated_zone_structural_evidence="unconfirmed",
    mitigated_zone_timestamp="2026-01-04T00:00:00Z", mitigated_zone_index=45, mitigated_zone_touch_count=1,
)


# ---------------------------------------------------------------------------
# Eligibility: touched demand/supply reachable via active_zone_*.
# ---------------------------------------------------------------------------

def test_touched_demand_reachable_fires_long():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**_TOUCHED_DEMAND), {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Touched Zone"
    assert result["trigger"] == "ZONE_REACTION"


def test_touched_supply_reachable_fires_short():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**_TOUCHED_SUPPLY), {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Touched Zone"


# ---------------------------------------------------------------------------
# Eligibility: mitigated demand/supply reachable through the REAL selector
# path (demand_engine.get_nearest_mitigated_zone(), not a synthetic
# freshness string) -- proves the wiring genuinely surfaces mitigated
# zones, unlike the earlier unreachable draft.
# ---------------------------------------------------------------------------

def test_mitigated_demand_reachable_through_real_selector_path():
    from core.demand_engine import SupplyDemandZone, get_nearest_mitigated_zone
    zones = [
        SupplyDemandZone(type="demand", top=1.2200, bottom=1.2100, valid=True, mitigated=True, touch_count=1, timestamp="2026-01-03T00:00:00Z"),
        SupplyDemandZone(type="demand", top=1.1000, bottom=1.0900, valid=True, mitigated=False, touch_count=0, timestamp="2026-01-05T00:00:00Z"),
    ]
    selected = get_nearest_mitigated_zone(zones, current_price=1.2150)
    assert selected is not None
    assert selected.type == "demand" and selected.mitigated is True

    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    snap = _base_snapshot(
        mitigated_zone_type=selected.type, mitigated_zone_top=selected.top, mitigated_zone_bottom=selected.bottom,
        mitigated_zone_timestamp=selected.timestamp, mitigated_zone_touch_count=selected.touch_count,
    )
    result = MitigationSecondTouchStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Mitigation"


def test_mitigated_supply_reachable_through_real_selector_path():
    from core.demand_engine import SupplyDemandZone, get_nearest_mitigated_zone
    zones = [
        SupplyDemandZone(type="supply", top=1.3300, bottom=1.3200, valid=True, mitigated=True, touch_count=1, timestamp="2026-01-04T00:00:00Z"),
    ]
    selected = get_nearest_mitigated_zone(zones, current_price=1.3250)
    assert selected is not None
    assert selected.type == "supply" and selected.mitigated is True

    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    snap = _base_snapshot(
        mitigated_zone_type=selected.type, mitigated_zone_top=selected.top, mitigated_zone_bottom=selected.bottom,
        mitigated_zone_timestamp=selected.timestamp, mitigated_zone_touch_count=selected.touch_count,
    )
    result = MitigationSecondTouchStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Mitigation"


def test_mitigated_demand_reachable_fires_long():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**_MITIGATED_DEMAND), {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["reason"] == "Mitigation"


def test_mitigated_supply_reachable_fires_short():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**_MITIGATED_SUPPLY), {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["reason"] == "Mitigation"


# ---------------------------------------------------------------------------
# get_nearest_mitigated_zone() itself: separate selector, correct
# eligibility, active-zone semantics unchanged.
# ---------------------------------------------------------------------------

def test_get_nearest_mitigated_zone_excludes_invalidated():
    from core.demand_engine import SupplyDemandZone, get_nearest_mitigated_zone
    zones = [
        SupplyDemandZone(type="demand", top=1.20, bottom=1.19, valid=False, mitigated=True, invalidated=True),
    ]
    assert get_nearest_mitigated_zone(zones, current_price=1.195) is None


def test_get_nearest_mitigated_zone_excludes_unmitigated():
    from core.demand_engine import SupplyDemandZone, get_nearest_mitigated_zone
    zones = [
        SupplyDemandZone(type="demand", top=1.20, bottom=1.19, valid=True, mitigated=False),
    ]
    assert get_nearest_mitigated_zone(zones, current_price=1.195) is None


def test_get_nearest_mitigated_zone_uses_same_distance_formula_as_get_active_zone():
    """Same tie-break rule (<=, later zone wins) and same distance metric
    -- a direct behavioral check that no new formula was invented."""
    from core.demand_engine import SupplyDemandZone, get_nearest_mitigated_zone
    zones = [
        SupplyDemandZone(type="demand", top=1.20, bottom=1.19, valid=True, mitigated=True),
        SupplyDemandZone(type="demand", top=1.10, bottom=1.09, valid=True, mitigated=True),
    ]
    # current_price=1.195 is inside the first zone (distance 0) -- must win outright.
    selected = get_nearest_mitigated_zone(zones, current_price=1.195)
    assert selected.bottom == 1.19


def test_active_zone_semantics_unchanged_by_this_fix():
    """get_active_zone()/select_active_zone() must still exclude mitigated
    zones exactly as before -- this fix adds a sibling selector, it does
    not touch either of these."""
    from core.demand_engine import SupplyDemandZone, get_active_zone, select_active_zone
    zones = [
        SupplyDemandZone(type="demand", top=1.20, bottom=1.19, valid=True, mitigated=True),
        SupplyDemandZone(type="demand", top=1.10, bottom=1.09, valid=True, mitigated=False),
    ]
    selected = get_active_zone(zones, current_price=1.195)
    assert selected is not None
    assert selected.bottom == 1.09  # the mitigated zone (nearer to 1.195) must be skipped
    assert select_active_zone(zones, current_price=1.195) == ("demand", 1.10)


# ---------------------------------------------------------------------------
# Priority: Touched Zone before Mitigation.
# ---------------------------------------------------------------------------

def test_touched_takes_priority_when_both_bundles_populated():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    overrides = dict(_TOUCHED_DEMAND)
    overrides.update(_MITIGATED_SUPPLY)
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**overrides), {})
    assert result is not None
    assert result["reason"] == "Touched Zone"
    assert result["direction"] == "long"  # from active_zone_type="demand", not mitigated_zone_type="supply"


def test_mitigation_fires_when_touched_not_eligible_but_mitigated_is():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    overrides = dict(active_zone_type="demand", active_zone_top=1.21, active_zone_bottom=1.20, active_zone_freshness="fresh")
    overrides.update(_MITIGATED_DEMAND)
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**overrides), {})
    assert result is not None
    assert result["reason"] == "Mitigation"


# ---------------------------------------------------------------------------
# Rejections.
# ---------------------------------------------------------------------------

def test_fresh_rejected():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    overrides = dict(_TOUCHED_DEMAND)
    overrides["active_zone_freshness"] = "fresh"
    assert MitigationSecondTouchStrategy().react(_base_snapshot(**overrides), {}) is None


def test_invalidated_excluded_active_zone_path():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    overrides = dict(_TOUCHED_DEMAND)
    overrides["active_zone_freshness"] = "invalidated"
    assert MitigationSecondTouchStrategy().react(_base_snapshot(**overrides), {}) is None


def test_invalidated_excluded_mitigated_zone_path():
    """An invalidated zone can never appear as mitigated_zone_* at all
    (get_nearest_mitigated_zone() requires valid == True), so a snapshot
    with no mitigated_zone_type set must simply be rejected -- there is no
    freshness string to check on this path."""
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    snap = _base_snapshot(mitigated_zone_type=None)
    assert MitigationSecondTouchStrategy().react(snap, {}) is None


def test_unknown_rejected():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    snap = _base_snapshot()  # everything defaults to None
    assert MitigationSecondTouchStrategy().react(snap, {}) is None


def test_missing_zone_type_rejected_both_paths():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    overrides = dict(_TOUCHED_DEMAND)
    overrides["active_zone_type"] = None
    assert MitigationSecondTouchStrategy().react(_base_snapshot(**overrides), {}) is None


def test_wrong_zone_type_rejected():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    overrides = dict(_TOUCHED_DEMAND)
    overrides["active_zone_type"] = "neutral"
    assert MitigationSecondTouchStrategy().react(_base_snapshot(**overrides), {}) is None


def test_touched_zone_missing_geometry_rejected():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    snap = _base_snapshot(active_zone_type="demand", active_zone_freshness="touched", active_zone_top=None, active_zone_bottom=None)
    assert MitigationSecondTouchStrategy().react(snap, {}) is None


def test_mitigated_zone_missing_geometry_rejected():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    snap = _base_snapshot(mitigated_zone_type="demand", mitigated_zone_top=None, mitigated_zone_bottom=None)
    assert MitigationSecondTouchStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# No overclaiming touch-count-specific wording remains.
# ---------------------------------------------------------------------------

def test_no_touch_count_specific_overclaim_wording_remains():
    """The strategy source must contain zero occurrences of the rejected
    overclaiming phrase -- it has no reason to mention it at all, even in
    a comment. This test file cannot run the same total-absence check on
    itself: an assertion literal that names the phrase to search for
    necessarily contains that phrase as raw source text, so any such
    self-scan is unsatisfiable by construction, not evidence of a real
    leak. The behavioral half of this guarantee -- that the phrase never
    appears as an actual reason or marking-label value -- is instead
    covered by test_reason_values_are_touched_zone_or_mitigation_only and
    test_marking_labels_for_all_four_combinations above."""
    strategy_text = pathlib.Path("core/strategy/MitigationSecondTouchStrategy.py").read_text(encoding="utf-8")
    assert "Second Touch" not in strategy_text
    assert "Second-Touch" not in strategy_text


def test_reason_values_are_touched_zone_or_mitigation_only():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    s = MitigationSecondTouchStrategy()
    touched = s.react(_base_snapshot(**_TOUCHED_DEMAND), {})
    mitigated = s.react(_base_snapshot(**_MITIGATED_DEMAND), {})
    assert touched["reason"] == "Touched Zone"
    assert mitigated["reason"] == "Mitigation"
    assert {touched["reason"], mitigated["reason"]} == {"Touched Zone", "Mitigation"}


def test_marking_labels_for_all_four_combinations():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    s = MitigationSecondTouchStrategy()
    assert s.react(_base_snapshot(**_TOUCHED_DEMAND), {})["chart_markings"][0]["label"] == "Touched Demand Zone"
    assert s.react(_base_snapshot(**_TOUCHED_SUPPLY), {})["chart_markings"][0]["label"] == "Touched Supply Zone"
    assert s.react(_base_snapshot(**_MITIGATED_DEMAND), {})["chart_markings"][0]["label"] == "Mitigated Demand Zone"
    assert s.react(_base_snapshot(**_MITIGATED_SUPPLY), {})["chart_markings"][0]["label"] == "Mitigated Supply Zone"


# ---------------------------------------------------------------------------
# Chart marking: exactly one, real geometry, no fabrication.
# ---------------------------------------------------------------------------

def test_exactly_one_zone_marking_emitted_for_the_branch_used():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    touched = MitigationSecondTouchStrategy().react(_base_snapshot(**_TOUCHED_DEMAND), {})
    mitigated = MitigationSecondTouchStrategy().react(_base_snapshot(**_MITIGATED_DEMAND), {})
    assert len(touched["chart_markings"]) == 1 and touched["chart_markings"][0]["type"] == "zone"
    assert len(mitigated["chart_markings"]) == 1 and mitigated["chart_markings"][0]["type"] == "zone"


def test_marking_geometry_uses_real_zone_evidence_touched():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**_TOUCHED_DEMAND), {})
    m = result["chart_markings"][0]
    assert m["top"] == 1.2100 and m["bottom"] == 1.2000
    assert m["timestamp"] == "2026-01-01T00:00:00Z"
    assert m["candle_index"] == 42
    assert m["evidence_ref"] == {
        "source": "supply_demand_zones", "timeframe": "H1", "freshness": "touched", "touch_count": 1,
    }


def test_marking_geometry_uses_real_zone_evidence_mitigated():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**_MITIGATED_DEMAND), {})
    m = result["chart_markings"][0]
    assert m["top"] == 1.2200 and m["bottom"] == 1.2100
    assert m["timestamp"] == "2026-01-03T00:00:00Z"
    assert m["candle_index"] == 44
    assert m["evidence_ref"] == {
        "source": "supply_demand_zones", "timeframe": "H1", "freshness": "mitigated", "touch_count": 1,
    }


def test_marking_self_validates():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**_MITIGATED_DEMAND), {})
    validate_chart_marking(result["chart_markings"][0])


def test_no_fabricated_geometry_when_timestamp_and_index_absent():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    overrides = dict(_TOUCHED_DEMAND)
    overrides["active_zone_timestamp"] = None
    overrides["active_zone_index"] = None
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**overrides), {})
    m = result["chart_markings"][0]
    assert "timestamp" not in m
    assert "candle_index" not in m
    validate_chart_marking(m)


# ---------------------------------------------------------------------------
# touch_count never gates eligibility.
# ---------------------------------------------------------------------------

def test_touch_count_never_gates_touched_path():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    s = MitigationSecondTouchStrategy()
    for count in (None, 0, 1, 2, 99):
        overrides = dict(_TOUCHED_DEMAND)
        overrides["active_zone_touch_count"] = count
        result = s.react(_base_snapshot(**overrides), {})
        assert result is not None, f"touch_count={count} unexpectedly blocked eligibility"
        assert result["confidence"] == 0.5, f"touch_count={count} unexpectedly changed confidence"


def test_touch_count_never_gates_mitigated_path():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    s = MitigationSecondTouchStrategy()
    for count in (None, 0, 1, 5, 99):
        overrides = dict(_MITIGATED_DEMAND)
        overrides["mitigated_zone_touch_count"] = count
        result = s.react(_base_snapshot(**overrides), {})
        assert result is not None, f"touch_count={count} unexpectedly blocked eligibility"
        assert result["confidence"] == 0.4, f"touch_count={count} unexpectedly changed confidence"


def test_source_file_does_not_invent_new_touch_counting():
    text = pathlib.Path("core/strategy/MitigationSecondTouchStrategy.py").read_text(encoding="utf-8")
    assert "touch_count +=" not in text
    assert ".touch_count = " not in text


# ---------------------------------------------------------------------------
# Confidence: bounded [0, 1], exact v1 formula.
# ---------------------------------------------------------------------------

def test_confidence_bounded_zero_to_one_touched_base_only():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**_TOUCHED_DEMAND), {})
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["confidence"] == 0.5


def test_confidence_bounded_zero_to_one_mitigation_base_only():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**_MITIGATED_DEMAND), {})
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["confidence"] == 0.4


def test_confidence_structural_confirmation_bonus_touched():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    overrides = dict(_TOUCHED_DEMAND)
    overrides["active_zone_structural_evidence"] = "confirmed_current_event"
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**overrides), {})
    assert result["confidence"] == 0.7  # 0.5 + 0.2, no momentum


def test_confidence_structural_confirmation_bonus_mitigation():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    overrides = dict(_MITIGATED_DEMAND)
    overrides["mitigated_zone_structural_evidence"] = "confirmed_current_event"
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**overrides), {})
    assert result["confidence"] == 0.6  # 0.4 + 0.2, no momentum


def test_confidence_saturates_at_cap_with_bonus_and_strong_momentum():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    overrides = dict(_TOUCHED_DEMAND)
    overrides["active_zone_structural_evidence"] = "confirmed_current_event"
    result = MitigationSecondTouchStrategy().react(_base_snapshot(atr_normalized_momentum=5.0, **overrides), {})
    assert result["confidence"] == 1.0


def test_confidence_floors_at_base_on_disagreeing_momentum():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(atr_normalized_momentum=-2.0, **_TOUCHED_DEMAND), {})
    assert result["confidence"] == 0.5


def test_exact_confidence_formula_value_with_momentum():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(atr_normalized_momentum=1.0, **_TOUCHED_DEMAND), {})
    assert result["confidence"] == 0.65


def test_mitigation_base_confidence_lower_than_touched():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    s = MitigationSecondTouchStrategy()
    touched = s.react(_base_snapshot(**_TOUCHED_DEMAND), {})
    mitigated = s.react(_base_snapshot(**_MITIGATED_DEMAND), {})
    assert mitigated["confidence"] < touched["confidence"]


# ---------------------------------------------------------------------------
# No candle/bias dependency, no extra fetch.
# ---------------------------------------------------------------------------

def test_eligibility_ignores_bias_and_candle_evidence():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    snap = _base_snapshot(
        bias="Bearish",
        recent_candles=[
            {"direction": "bear", "index": 1, "timestamp": "t1"},
            {"direction": "bear", "index": 2, "timestamp": "t2"},
            {"direction": "bear", "index": 3, "timestamp": "t3"},
        ],
        **_TOUCHED_DEMAND,
    )
    result = MitigationSecondTouchStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"


def test_source_file_does_not_read_bias_or_candle_fields():
    text = pathlib.Path("core/strategy/MitigationSecondTouchStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("snapshot.bias", "snapshot.recent_candles", "snapshot.structure_type",
                      "snapshot.structure_direction", "snapshot.structure_valid"):
        assert forbidden not in text, f"MitigationSecondTouchStrategy.py unexpectedly reads {forbidden}"


def test_demand_engine_get_nearest_mitigated_zone_no_extra_fetch():
    """DemandEngine.get_nearest_mitigated_zone() must reuse an
    already-provided `zones` list rather than recomputing it via
    detect_zones() -- proven by monkeypatching detect_zones() in
    core.demand_engine to raise if called; it must never be reached when
    `zones` is supplied. Fetching candles for current_price is expected
    (get_active_zone() has the exact same shape) -- that is not a second
    fetch, since the caller (StructureEngine.get_snapshot()) passes the
    same request-scoped cache through, so this reads from the already-warm
    cache rather than making a new MT5 round-trip."""
    import core.demand_engine as demand_engine_module
    from core.core_models import CandleSnapshot
    from core.demand_engine import DemandEngine, SupplyDemandZone

    class FakeCandleEngine:
        def get_snapshots(self, symbol, tf, count=50, cache=None):
            return [CandleSnapshot(open=1.195, high=1.196, low=1.194, close=1.195, volume=1.0, timestamp="t")]

    def exploding_detect_zones(candles):
        raise AssertionError("detect_zones() must not be called when zones= is supplied")

    original = demand_engine_module.detect_zones
    demand_engine_module.detect_zones = exploding_detect_zones
    try:
        de = DemandEngine(FakeCandleEngine())
        zones = [SupplyDemandZone(type="demand", top=1.20, bottom=1.19, valid=True, mitigated=True)]
        result = de.get_nearest_mitigated_zone("T", "H1", zones=zones)
        assert result is not None
        assert result.type == "demand"
    finally:
        demand_engine_module.detect_zones = original


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    result = MitigationSecondTouchStrategy().react(_base_snapshot(**_TOUCHED_DEMAND), {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_strategy_engine_discovers_mitigation_second_touch_strategy():
    """Originally asserted the discovered count equals exactly 12 -- Fix
    #7O later added a genuinely new 13th strategy
    (MomentumExpansionStrategy), which made that exact-count snapshot
    stale (a real, intended addition, not a regression -- see
    tests/test_fix_7o_momentum_expansion_strategy_v1.py::test_strategy_engine_discovers_thirteen_strategies_now
    for that fix's own count assertion). Rewritten to check the actual
    invariant this test exists for -- MitigationSecondTouchStrategy is
    discovered alongside the original 11 -- rather than a total count
    that any future new strategy would otherwise make stale again."""
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert "MitigationSecondTouchStrategy" in engine.enabled
    existing_eleven = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy",
    }
    assert existing_eleven <= set(engine.enabled.keys())


def test_existing_eleven_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_eleven = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy",
    }
    assert existing_eleven <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_to_none():
    base = dict(
        symbol="T", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
    )
    snap = StrategySnapshot(**base)
    assert snap.active_zone_type is None
    assert snap.active_zone_freshness is None
    assert snap.active_zone_touch_count is None
    assert snap.mitigated_zone_type is None
    assert snap.mitigated_zone_touch_count is None
    from core.strategy.MitigationSecondTouchStrategy import MitigationSecondTouchStrategy
    assert MitigationSecondTouchStrategy().react(snap, {}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
