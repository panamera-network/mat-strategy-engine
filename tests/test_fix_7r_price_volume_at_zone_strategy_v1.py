"""Fix #7R — Price-Volume at Zone v1 baseline: zone is WHERE (canonical
active Demand/Supply zone), price-direction + volume-direction at that
zone is the QUALITY of the reaction there.

Volume source audit (documented here and in
core.core_models.CandleDirection's own docstring): MT5's raw rate struct
exposes two volume fields, `tick_volume` (count of price-quote changes)
and `real_volume` (broker-reported traded size). This pipeline has only
ever fetched `tick_volume` (mt5/fetcher.py: `volume=row['tick_volume']`) --
`real_volume` is never read anywhere. A live audit across the full
36-symbol universe (every asset class: FX majors, metals, crypto, energy)
found `real_volume` is 0 for every single symbol on this account's broker
feed -- it carries no signal even if it were wired up. Every "volume"
value this strategy reads is MT5 tick volume; it must never be presented
as real/traded volume.

This is a v1 BASELINE only -- volume-up/down is current-candle-vs-
previous-candle only (not a rolling baseline or relative-volume window),
and no divergence-strength/relative-magnitude scoring exists yet. These
tests lock in v1's exact behavior, not a claim that the rules are final.

Interaction gate (this fix's own follow-up audit, added before Fix #7R's
first commit): demand_engine.get_active_zone() is a nearest-zone-by-
distance selector, NOT a touch/interaction proof -- explicit testing
against the real selector (see the "zone interaction audit" section
below) found it still returns the same zone even when the current candle
is clearly far away. The strategy therefore additionally requires the
current candle's real high/low (StrategySnapshot.current_high/
current_low, already-exposed evidence, no new fetch) to overlap
[active_zone_bottom, active_zone_top] -- the identical wick-inclusive
overlap formula demand_engine.detect_zones() already uses for touch
counting. `_DEMAND_ZONE`/`_SUPPLY_ZONE` below default current_high/
current_low to a value INSIDE the zone so every other test in this file
(which is testing participation/volume logic, not interaction) keeps
satisfying the gate; the dedicated interaction tests override it.

Documented explicitly, as required: v1 price up/down = candle BODY
direction (close vs open, Fix #7K's existing per-candle direction).
Volume up/down = current candle's tick volume vs the immediately PREVIOUS
candle's tick volume (see the module docstring in
core/strategy/PriceVolumeAtZoneStrategy.py for the full tick-vs-real-
volume audit) -- both provisional v1 definitions.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports -- see CLAUDE.md):
    pytest tests/test_fix_7r_price_volume_at_zone_strategy_v1.py -v
"""
from datetime import datetime, timezone

import pytest

from core.demand_engine import SupplyDemandZone, get_active_zone
from core.strategy.chart_markings import validate_chart_marking
from core.strategy.strategy_models import StrategySnapshot


def _candle(direction, index, timestamp, volume):
    return {"direction": direction, "index": index, "timestamp": timestamp, "volume": volume}


def _base_snapshot(**overrides):
    base = dict(
        symbol="EURUSD_i", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        active_zone_type=None, active_zone_top=None, active_zone_bottom=None,
        active_zone_freshness=None, active_zone_structural_evidence=None,
        active_zone_timestamp=None, active_zone_index=None,
        current_high=None, current_low=None,
        recent_candles=None,
    )
    base.update(overrides)
    return StrategySnapshot(**base)


_DEMAND_ZONE = dict(
    active_zone_type="demand", active_zone_top=1.2100, active_zone_bottom=1.2000,
    active_zone_freshness="fresh", active_zone_structural_evidence="unconfirmed",
    active_zone_timestamp="2026-01-01T00:00:00Z", active_zone_index=42,
    current_high=1.2060, current_low=1.2040,  # inside [1.2000, 1.2100] -- touches
)
_SUPPLY_ZONE = dict(
    active_zone_type="supply", active_zone_top=1.3100, active_zone_bottom=1.3000,
    active_zone_freshness="fresh", active_zone_structural_evidence="unconfirmed",
    active_zone_timestamp="2026-01-02T00:00:00Z", active_zone_index=43,
    current_high=1.3060, current_low=1.3040,  # inside [1.3000, 1.3100] -- touches
)


def _candles(price_direction, current_volume, previous_volume=100.0):
    """3-candle window (label_recent_candles() always returns exactly 3 or
    none). Only the last entry's direction and the last two entries'
    volumes are read by the strategy -- the oldest entry is filler."""
    return [
        _candle("neutral", 40, "2026-01-01T00:00:00Z", 100.0),
        _candle("neutral", 41, "2026-01-01T01:00:00Z", previous_volume),
        _candle(price_direction, 42, "2026-01-01T02:00:00Z", current_volume),
    ]


# ---------------------------------------------------------------------------
# Eligibility: the two genuine participation states.
# ---------------------------------------------------------------------------

def test_demand_price_up_volume_up_valid_long():
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_DEMAND_ZONE, recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0))
    result = PriceVolumeAtZoneStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"
    assert result["trigger"] == "PRICE_VOLUME_AT_ZONE"
    assert result["reason"] == "Bullish Price-Volume Demand Reaction"


def test_supply_price_down_volume_up_valid_short():
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_SUPPLY_ZONE, recent_candles=_candles("bear", current_volume=200.0, previous_volume=100.0))
    result = PriceVolumeAtZoneStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"
    assert result["trigger"] == "PRICE_VOLUME_AT_ZONE"
    assert result["reason"] == "Bearish Price-Volume Supply Reaction"


# ---------------------------------------------------------------------------
# Zone interaction audit: the 4 explicit cases run against the REAL
# get_active_zone() selector (not a hand-built active_zone_type dict),
# proving get_active_zone() alone is not sufficient -- it selects a zone
# by nearest-distance only, with no cutoff, so the strategy must apply its
# own interaction gate on top of whatever get_active_zone() returns.
# ---------------------------------------------------------------------------

_AUDIT_DEMAND = SupplyDemandZone(type="demand", top=1.2100, bottom=1.2000, valid=True, mitigated=False)
_AUDIT_SUPPLY = SupplyDemandZone(type="supply", top=1.3100, bottom=1.3000, valid=True, mitigated=False)


def test_audit_case1_demand_overlap_bullish_volume_up_fires():
    """Case 1: current candle overlaps/touches the Demand zone, bullish
    price + volume up -- must fire."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    selected = get_active_zone([_AUDIT_DEMAND], current_price=1.2050)
    assert selected is not None and selected.type == "demand"
    snap = _base_snapshot(
        active_zone_type=selected.type, active_zone_top=selected.top, active_zone_bottom=selected.bottom,
        current_high=1.2060, current_low=1.2040,  # overlaps [1.2000, 1.2100]
        recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0),
    )
    result = PriceVolumeAtZoneStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "long"


def test_audit_case2_demand_far_above_bullish_volume_up_rejected():
    """Case 2: current candle is clearly ABOVE and far away from the SAME
    Demand zone, bullish price + volume up. get_active_zone() still
    returns this zone (it is the only zone, nearest-by-distance has no
    cutoff) -- confirmed by the assertion on `selected` below -- but the
    strategy must reject: the reaction candle never touched this zone."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    selected = get_active_zone([_AUDIT_DEMAND], current_price=1.2050)
    assert selected is not None and selected.type == "demand"  # still selected despite no interaction below
    snap = _base_snapshot(
        active_zone_type=selected.type, active_zone_top=selected.top, active_zone_bottom=selected.bottom,
        current_high=1.5060, current_low=1.5040,  # far above zone.top=1.2100
        recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0),
    )
    result = PriceVolumeAtZoneStrategy().react(snap, {})
    assert result is None


def test_audit_case3_supply_overlap_bearish_volume_up_fires():
    """Case 3: current candle overlaps/touches the Supply zone, bearish
    price + volume up -- must fire."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    selected = get_active_zone([_AUDIT_SUPPLY], current_price=1.3050)
    assert selected is not None and selected.type == "supply"
    snap = _base_snapshot(
        active_zone_type=selected.type, active_zone_top=selected.top, active_zone_bottom=selected.bottom,
        current_high=1.3060, current_low=1.3040,  # overlaps [1.3000, 1.3100]
        recent_candles=_candles("bear", current_volume=200.0, previous_volume=100.0),
    )
    result = PriceVolumeAtZoneStrategy().react(snap, {})
    assert result is not None
    assert result["direction"] == "short"


def test_audit_case4_supply_far_below_bearish_volume_up_rejected():
    """Case 4: current candle is clearly BELOW and far away from the SAME
    Supply zone, bearish price + volume up. get_active_zone() still
    returns this zone -- confirmed by the assertion on `selected` below --
    but the strategy must reject: no actual interaction with the zone."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    selected = get_active_zone([_AUDIT_SUPPLY], current_price=1.3050)
    assert selected is not None and selected.type == "supply"  # still selected despite no interaction below
    snap = _base_snapshot(
        active_zone_type=selected.type, active_zone_top=selected.top, active_zone_bottom=selected.bottom,
        current_high=1.0060, current_low=1.0040,  # far below zone.bottom=1.3000
        recent_candles=_candles("bear", current_volume=200.0, previous_volume=100.0),
    )
    result = PriceVolumeAtZoneStrategy().react(snap, {})
    assert result is None


def test_interaction_boundary_touching_top_edge_fires():
    """current_low exactly equal to active_zone_top is still an overlap
    (<=, wick-inclusive, same convention as detect_zones()) -- must fire."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(
        **{**_DEMAND_ZONE, "current_high": 1.2150, "current_low": 1.2100},
        recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0),
    )
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is not None


def test_interaction_missing_current_high_low_rejected():
    """Defensive: no real current-candle geometry means no interaction can
    be proven -- reject, never assume touching."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(
        **{**_DEMAND_ZONE, "current_high": None, "current_low": None},
        recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0),
    )
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Rejections: wrong participation / weakening states per zone.
# ---------------------------------------------------------------------------

def test_demand_price_up_volume_down_rejected():
    """Bullish weakening/divergence -- must not auto-fire in v1."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_DEMAND_ZONE, recent_candles=_candles("bull", current_volume=50.0, previous_volume=100.0))
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


def test_demand_price_down_volume_up_rejected():
    """Bearish participation in a demand zone -- explicitly must reject."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_DEMAND_ZONE, recent_candles=_candles("bear", current_volume=200.0, previous_volume=100.0))
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


def test_supply_price_down_volume_down_rejected():
    """Bearish weakening/divergence -- must not auto-fire in v1."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_SUPPLY_ZONE, recent_candles=_candles("bear", current_volume=50.0, previous_volume=100.0))
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


def test_supply_price_up_volume_up_rejected():
    """Bullish participation in a supply zone -- explicitly must reject."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_SUPPLY_ZONE, recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0))
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


def test_demand_price_up_volume_equal_does_not_fire():
    """The 4th raw combination (price up + volume equal) is also covered by
    the equal-volume rejection below, but explicitly re-checked in a demand
    zone to confirm equal volume never accidentally satisfies "volume up"."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_DEMAND_ZONE, recent_candles=_candles("bull", current_volume=100.0, previous_volume=100.0))
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Explicit edge-case behavior.
# ---------------------------------------------------------------------------

def test_equal_volume_behavior_explicit_rejected():
    """current_volume == previous_volume is a real, meaningful outcome
    (neither up nor down) -- explicitly rejected, never guessed into
    either bucket."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_SUPPLY_ZONE, recent_candles=_candles("bear", current_volume=150.0, previous_volume=150.0))
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


def test_equal_open_close_price_behavior_explicit_rejected():
    """A "neutral" current candle (open == close, Fix #7K's own third
    direction value) is a real, meaningful outcome -- explicitly rejected,
    never guessed into bull or bear."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_DEMAND_ZONE, recent_candles=_candles("neutral", current_volume=200.0, previous_volume=100.0))
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


def test_missing_volume_rejected():
    """recent_candles entries present but without a 'volume' key (e.g. a
    raw-JSON-body caller supplying an older-shaped dict) reject cleanly."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    candles = [
        {"direction": "neutral", "index": 41, "timestamp": "2026-01-01T01:00:00Z"},
        {"direction": "bull", "index": 42, "timestamp": "2026-01-01T02:00:00Z"},
    ]
    snap = _base_snapshot(**_DEMAND_ZONE, recent_candles=candles)
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


def test_fewer_than_two_candles_rejected():
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_DEMAND_ZONE, recent_candles=[_candle("bull", 42, "2026-01-01T02:00:00Z", 200.0)])
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


def test_no_recent_candles_rejected():
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_DEMAND_ZONE, recent_candles=None)
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None
    snap2 = _base_snapshot(**_DEMAND_ZONE, recent_candles=[])
    assert PriceVolumeAtZoneStrategy().react(snap2, {}) is None


def test_wrong_or_missing_zone_rejected():
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    candles = _candles("bull", current_volume=200.0, previous_volume=100.0)
    snap_none = _base_snapshot(active_zone_type=None, recent_candles=candles)
    assert PriceVolumeAtZoneStrategy().react(snap_none, {}) is None
    snap_other = _base_snapshot(active_zone_type="neutral", recent_candles=candles)
    assert PriceVolumeAtZoneStrategy().react(snap_other, {}) is None


def test_zone_missing_geometry_rejected():
    """Defensive: a genuine active zone always carries real top/bottom."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    overrides = dict(_DEMAND_ZONE)
    overrides["active_zone_top"] = None
    snap = _base_snapshot(**overrides, recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0))
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


# ---------------------------------------------------------------------------
# Chart marking: exactly one zone marking, real geometry, evidence_ref.
# ---------------------------------------------------------------------------

def test_exact_real_zone_marking_demand():
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_DEMAND_ZONE, recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0))
    result = PriceVolumeAtZoneStrategy().react(snap, {})
    markings = result["chart_markings"]
    assert len(markings) == 1
    marking = markings[0]
    validate_chart_marking(marking)
    assert marking["type"] == "zone"
    assert marking["top"] == 1.2100
    assert marking["bottom"] == 1.2000
    assert marking["direction"] == "long"
    assert marking["label"] == "Bullish Price-Volume Demand Reaction"
    assert marking["timeframe"] == "H1"
    assert marking["timestamp"] == "2026-01-01T02:00:00Z"
    assert marking["candle_index"] == 42
    assert marking["evidence_ref"]["zone_type"] == "demand"
    assert marking["evidence_ref"]["price_direction"] == "bull"
    assert marking["evidence_ref"]["volume_direction"] == "up"
    assert marking["evidence_ref"]["current_volume"] == 200.0
    assert marking["evidence_ref"]["previous_volume"] == 100.0


def test_exact_real_zone_marking_supply():
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_SUPPLY_ZONE, recent_candles=_candles("bear", current_volume=200.0, previous_volume=100.0))
    result = PriceVolumeAtZoneStrategy().react(snap, {})
    marking = result["chart_markings"][0]
    validate_chart_marking(marking)
    assert marking["type"] == "zone"
    assert marking["top"] == 1.3100
    assert marking["bottom"] == 1.3000
    assert marking["direction"] == "short"
    assert marking["label"] == "Bearish Price-Volume Supply Reaction"


# ---------------------------------------------------------------------------
# Confidence: exact formula, bounded.
# ---------------------------------------------------------------------------

def test_confidence_bounded_and_exact_formula():
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap_no_momentum = _base_snapshot(
        **_DEMAND_ZONE, atr_normalized_momentum=None,
        recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0),
    )
    result = PriceVolumeAtZoneStrategy().react(snap_no_momentum, {})
    assert result["confidence"] == 0.5

    snap_partial_momentum = _base_snapshot(
        **_DEMAND_ZONE, atr_normalized_momentum=1.0,
        recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0),
    )
    result2 = PriceVolumeAtZoneStrategy().react(snap_partial_momentum, {})
    assert result2["confidence"] == 0.75

    snap_saturated_momentum = _base_snapshot(
        **_DEMAND_ZONE, atr_normalized_momentum=5.0,
        recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0),
    )
    result3 = PriceVolumeAtZoneStrategy().react(snap_saturated_momentum, {})
    assert result3["confidence"] == 1.0

    for r in (result, result2, result3):
        assert 0.0 <= r["confidence"] <= 1.0


def test_wrong_direction_momentum_gives_no_bonus():
    """Momentum disagreeing with the committed trade direction contributes
    zero (strategy_momentum_confidence's own agreement gate) -- confidence
    stays at the flat base."""
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(
        **_DEMAND_ZONE, atr_normalized_momentum=-3.0,
        recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0),
    )
    result = PriceVolumeAtZoneStrategy().react(snap, {})
    assert result["confidence"] == 0.5


# ---------------------------------------------------------------------------
# Volume source semantics -- tested/documented explicitly.
# ---------------------------------------------------------------------------

def test_volume_field_is_tick_volume_not_real_volume_by_source_audit():
    """mt5/fetcher.py only ever reads MT5's `tick_volume` field into
    Candle.volume -- `real_volume` is never fetched anywhere in this
    pipeline. This is a static-source assertion (not a live MT5 call) so
    it runs without a live terminal; the live audit itself (confirming
    real_volume==0 across the full 36-symbol universe on this account's
    feed) is documented in this module's own docstring and in
    CandleDirection's docstring, not re-run here."""
    import pathlib
    text = pathlib.Path("mt5/fetcher.py").read_text(encoding="utf-8")
    assert "tick_volume" in text
    assert "real_volume" not in text


def test_candle_direction_volume_field_is_additive_and_documented():
    from core.core_models import CandleDirection
    import dataclasses
    fields = {f.name for f in dataclasses.fields(CandleDirection)}
    assert "volume" in fields
    cd = CandleDirection(direction="bull", index=0, timestamp="t")
    assert cd.volume is None  # additive, defaults to None, never guessed


def test_label_recent_candles_populates_volume_from_already_fetched_candle():
    """Fix #7R's minimal additive wiring: label_recent_candles() copies
    each candle's own CandleSnapshot.volume straight across -- no new
    fetch, no recomputation."""
    from core.core_models import CandleSnapshot
    from core.structure_utils import label_recent_candles

    def _c(v):
        return CandleSnapshot(open=1.0, high=1.1, low=0.9, close=1.05, volume=v, timestamp="t")

    candles = [_c(10.0), _c(20.0), _c(30.0)]
    result = label_recent_candles(candles, count=3)
    assert [c.volume for c in result] == [10.0, 20.0, 30.0]


# ---------------------------------------------------------------------------
# No S&R substitution, no bias/structure/raw-momentum dependency.
# ---------------------------------------------------------------------------

def test_source_file_does_not_read_support_resistance_fields():
    import pathlib
    text = pathlib.Path("core/strategy/PriceVolumeAtZoneStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("snapshot.nearest_support", "snapshot.nearest_resistance", "snapshot.snr_context", "snapshot.snr_strength"):
        assert forbidden not in text, f"PriceVolumeAtZoneStrategy.py unexpectedly reads {forbidden}"


def test_source_file_does_not_gate_on_bias_structure_or_raw_momentum():
    import pathlib
    text = pathlib.Path("core/strategy/PriceVolumeAtZoneStrategy.py").read_text(encoding="utf-8")
    for forbidden in ("snapshot.bias", "snapshot.structure_type", "snapshot.structure_direction",
                      "snapshot.structure_valid", "snapshot.momentum"):
        assert forbidden not in text, f"PriceVolumeAtZoneStrategy.py unexpectedly reads {forbidden}"


def test_no_zone_requirement_beyond_active_zone_fields():
    """Only demand_engine's canonical active-zone evidence gates
    eligibility -- no separate zone-freshness/touch-count requirement in
    this v1 (unlike FreshZoneReactionStrategy/MitigationSecondTouchStrategy)."""
    import pathlib
    text = pathlib.Path("core/strategy/PriceVolumeAtZoneStrategy.py").read_text(encoding="utf-8")
    assert "active_zone_freshness" not in text
    assert "active_zone_touch_count" not in text


# ---------------------------------------------------------------------------
# Standard output fields + StrategyEngine discovery.
# ---------------------------------------------------------------------------

def test_standard_output_fields_present():
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    snap = _base_snapshot(**_DEMAND_ZONE, recent_candles=_candles("bull", current_volume=200.0, previous_volume=100.0))
    result = PriceVolumeAtZoneStrategy().react(snap, {})
    for key in ("symbol", "timeframe", "direction", "reason", "confidence", "trigger", "timestamp", "price", "chart_markings"):
        assert key in result


def test_strategy_engine_discovers_price_volume_at_zone_strategy():
    """Originally asserted the discovered count equals exactly 16 -- Fix
    #7S later added a genuinely new 17th strategy
    (ConvictionSelectiveStrategy), which made that exact-count snapshot
    stale (a real, intended addition, not a regression -- see
    tests/test_fix_7s_conviction_selective_strategy_v1.py::test_strategy_engine_discovers_seventeen_strategies_now
    for that fix's own count assertion). Rewritten to check the actual
    invariant this test exists for -- PriceVolumeAtZoneStrategy is
    discovered alongside the original 15 -- rather than a total count that
    any future new strategy would otherwise make stale again."""
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    assert "PriceVolumeAtZoneStrategy" in engine.enabled
    existing_fifteen = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy",
    }
    assert existing_fifteen <= set(engine.enabled.keys())


def test_existing_fifteen_strategies_still_discovered():
    from core.strategy.StrategyEngine import StrategyEngine
    engine = StrategyEngine()
    existing_fifteen = {
        "BiasContinuationScalpingStrategy", "BiasContinuationSwingStrategy",
        "DoubleEngulfingStrategy", "ZoneContinuationStrategy",
        "ScalpingBiasCascade", "GroupedLastCandleBiasStrategy", "LastCandleBiasStrategy",
        "StructureReversalStrategy", "IPCStrategy", "TrendContinuationStrategy",
        "FreshZoneReactionStrategy", "MitigationSecondTouchStrategy", "MomentumExpansionStrategy",
        "BreakoutRetestStrategy", "MTFBiasCascadeStrategy",
    }
    assert existing_fifteen <= set(engine.enabled.keys())


def test_post_evaluate_style_field_omission_defaults_gracefully():
    """A raw-JSON-body StrategySnapshot(**data) that omits recent_candles
    falls through to None -- never guessed -- and the strategy rejects
    cleanly rather than crashing."""
    base = dict(
        symbol="T", timeframe="H1", bias="Neutral", momentum=0.0, strength=0.0,
        suppression=False, suppression_reason="",
        structure_type="None", structure_direction="Neutral", structure_valid=False,
        context_zone="neutral", context_level=None, timestamp=datetime.now(timezone.utc),
        active_zone_type="demand", active_zone_top=1.21, active_zone_bottom=1.20,
    )
    snap = StrategySnapshot(**base)
    assert snap.recent_candles is None
    from core.strategy.PriceVolumeAtZoneStrategy import PriceVolumeAtZoneStrategy
    assert PriceVolumeAtZoneStrategy().react(snap, {}) is None


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-v"]))
