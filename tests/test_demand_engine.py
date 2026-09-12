"""Fix #4B — targeted tests for DemandEngine's canonical context selector
(select_active_zone / get_context / get_label). No MT5 needed: pure zone
objects for the selector itself, and a stub candle engine for the
DemandEngine-level reuse tests.

Run in isolation (the rest of /tests is broken on unrelated pre-existing
imports — see CLAUDE.md):
    pytest tests/test_demand_engine.py -v
"""
from core.core_models import CandleSnapshot
from core.demand_engine import DemandEngine, SupplyDemandZone, select_active_zone


def make_zone(zone_type, top, bottom, valid=True):
    return SupplyDemandZone(type=zone_type, top=top, bottom=bottom, valid=valid)


def make_candle(o, h, l, c):
    return CandleSnapshot(open=o, high=h, low=l, close=c, volume=100, timestamp="0")


class FakeCandleEngine:
    """Returns a fixed candle list regardless of symbol/tf/count/cache —
    lets tests control current_price (candles[-1].close) without MT5."""

    def __init__(self, candles):
        self.candles = candles

    def get_snapshots(self, symbol, tf, count=50, cache=None):
        return self.candles


# ── select_active_zone (pure) ──────────────────────────────────────────

def test_no_zones_is_neutral():
    assert select_active_zone([], current_price=100.0) == ("neutral", None)


def test_no_valid_zones_is_neutral():
    zones = [make_zone("demand", top=105, bottom=100, valid=False)]
    assert select_active_zone(zones, current_price=102.0) == ("neutral", None)


def test_demand_level_is_top():
    zones = [make_zone("demand", top=105, bottom=100)]
    zone_type, level = select_active_zone(zones, current_price=110.0)
    assert zone_type == "demand"
    assert level == 105  # top, not bottom


def test_supply_level_is_bottom():
    zones = [make_zone("supply", top=120, bottom=115)]
    zone_type, level = select_active_zone(zones, current_price=110.0)
    assert zone_type == "supply"
    assert level == 115  # bottom, not top


def test_price_inside_zone_has_distance_zero_and_wins():
    inside = make_zone("demand", top=105, bottom=100)   # price 102 is inside
    outside = make_zone("supply", top=106, bottom=105.5)  # price 102 is 3.5 away
    zone_type, level = select_active_zone([outside, inside], current_price=102.0)
    assert zone_type == "demand"
    assert level == 105


def test_overlapping_zones_distance_zero_later_wins():
    """Two zones both contain current_price (both distance=0 — a genuine
    tie, not just 'close'). The LATER zone by list position must win, and
    the selector must reach that decision without reading candle_index or
    timestamp (it never even sets them here — make_zone leaves them at
    their dataclass defaults)."""
    earlier = make_zone("demand", top=105, bottom=95)  # also contains 100.0
    later = make_zone("supply", top=101, bottom=99)    # contains 100.0
    zone_type, level = select_active_zone([earlier, later], current_price=100.0)
    assert zone_type == "supply", "later zone (list position) must win on a distance tie"
    assert level == 99  # supply -> bottom


def test_multiple_zones_nearest_wins_regardless_of_type():
    far_demand = make_zone("demand", top=50, bottom=45)     # distance from 100 = 50
    near_supply = make_zone("supply", top=101, bottom=100.5)  # distance from 100 = 0.5
    zone_type, level = select_active_zone([far_demand, near_supply], current_price=100.0)
    assert zone_type == "supply"
    assert level == 100.5


def test_invalid_zone_ignored_even_if_nearer():
    near_but_mitigated = make_zone("demand", top=100.1, bottom=100.0, valid=False)
    far_but_valid = make_zone("supply", top=110, bottom=109, valid=True)
    zone_type, level = select_active_zone([near_but_mitigated, far_but_valid], current_price=100.0)
    assert zone_type == "supply"
    assert level == 109


def test_no_candles_is_neutral_via_get_context():
    engine = DemandEngine(candle_engine=FakeCandleEngine([]))
    assert engine.get_context("X", "M15") == ("neutral", None)
    assert engine.get_label("X", "M15") == "neutral"


# ── DemandEngine.get_label()/get_context() reuse the SAME rule ────────

def test_get_label_and_get_context_agree(monkeypatch):
    """The exact scenario where the OLD get_label() rule ('active[-1]', i.e.
    last item by LIST POSITION) and the canonical nearest-by-distance rule
    would disagree — proves get_label() now delegates to the same selector
    as get_context(), not a second independent rule. Uses only list
    position (no candle_index/timestamp — those are WIP-only fields this
    canonical selector and its tests deliberately don't depend on, so this
    test also runs unmodified against the isolated HEAD-only dataclass)."""
    import core.demand_engine as demand_engine_module

    earlier_but_nearer = SupplyDemandZone(type="demand", top=101, bottom=100.5, valid=True)
    later_but_farther = SupplyDemandZone(type="supply", top=50, bottom=45, valid=True)

    monkeypatch.setattr(
        demand_engine_module, "detect_zones",
        lambda candles: [earlier_but_nearer, later_but_farther],
    )

    engine = DemandEngine(candle_engine=FakeCandleEngine([make_candle(99, 101, 99, 100.0)]))

    context_type, context_level = engine.get_context("X", "M15")
    label = engine.get_label("X", "M15")

    # Old rule (active[-1], i.e. later_but_farther by list position) would
    # have returned "supply" here. Canonical rule picks the nearer zone
    # (earlier_but_nearer, distance 0.5 vs 50) -> "demand".
    assert context_type == "demand"
    assert context_level == 101  # demand -> top
    assert label == context_type, "get_label() must agree with get_context() — single selection rule"
