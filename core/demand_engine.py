from dataclasses import dataclass
from typing import List, Optional, Tuple

from core.CandleEngine import CandleEngine
from core.core_models import CandleSnapshot

ATR_PERIOD = 14
BODY_ATR_RATIO = 0.6  # candle body must exceed 60% of ATR to mark a zone


@dataclass
class SupplyDemandZone:
    type: str            # "demand" or "supply"
    top: float
    bottom: float
    valid: bool = True
    strength: float = 0.0
    mitigated: bool = False


def compute_atr(candles: List[CandleSnapshot], period: int = ATR_PERIOD) -> float:
    """Average True Range over the most recent `period` candles."""
    if len(candles) < 2:
        return 0.0

    true_ranges = []
    for i in range(1, len(candles)):
        high, low = candles[i].high, candles[i].low
        prev_close = candles[i - 1].close
        true_ranges.append(max(high - low, abs(high - prev_close), abs(low - prev_close)))

    recent = true_ranges[-period:]
    return sum(recent) / len(recent) if recent else 0.0


def detect_zones(candles: List[CandleSnapshot]) -> List[SupplyDemandZone]:
    """Demand/supply zones from strong-bodied candles (body > 60% of ATR),
    marked mitigated once price closes back inside the zone."""
    atr = compute_atr(candles)
    if atr <= 0:
        return []

    zones: List[SupplyDemandZone] = []

    for i, c in enumerate(candles):
        body = abs(c.close - c.open)
        if body <= atr * BODY_ATR_RATIO:
            continue

        if c.close > c.open:
            zone = SupplyDemandZone(type="demand", top=c.open, bottom=c.low, strength=round(body / atr, 2))
        else:
            zone = SupplyDemandZone(type="supply", top=c.high, bottom=c.open, strength=round(body / atr, 2))

        for later in candles[i + 1:]:
            if zone.bottom <= later.close <= zone.top:
                zone.mitigated = True
                zone.valid = False
                break

        zones.append(zone)

    return zones


def select_active_zone(zones: List[SupplyDemandZone], current_price: float) -> Tuple[str, Optional[float]]:
    """Canonical DemandEngine context selector (Fix #4B) — the single zone-
    selection rule for this engine. Picks the active (valid) zone nearest to
    current_price; distance is 0 if current_price sits inside [bottom, top].
    On a distance tie, the LATER zone in `zones` wins — list position only,
    not candle_index/timestamp (WIP-only fields this canonical selector
    deliberately does not depend on).
    demand level = top (proximal edge, price approaches from above);
    supply level = bottom (proximal edge, price approaches from below).
    No active zone -> ("neutral", None). Wired into StructureEngine via
    get_context() (Fix #4C/#4D3) — the legacy detect_snd() heuristic in
    structure_utils.py has since been removed (Fix #4E1)."""
    active = [z for z in zones if z.valid]
    if not active:
        return "neutral", None

    def distance(zone: SupplyDemandZone) -> float:
        if zone.bottom <= current_price <= zone.top:
            return 0.0
        if current_price < zone.bottom:
            return zone.bottom - current_price
        return current_price - zone.top

    nearest = active[0]
    nearest_distance = distance(nearest)
    for zone in active[1:]:
        d = distance(zone)
        if d <= nearest_distance:  # <=, not < — later zone wins on a tie
            nearest = zone
            nearest_distance = d

    level = nearest.top if nearest.type == "demand" else nearest.bottom
    return nearest.type, level


class DemandEngine:
    def __init__(self, candle_engine: CandleEngine):
        self.candle_engine = candle_engine

    def get_zones(self, symbol: str, tf: str, count: int = 50, cache=None) -> List[SupplyDemandZone]:
        candles = self.candle_engine.get_snapshots(symbol, tf, count=count, cache=cache)
        return detect_zones(candles)

    def get_context(self, symbol: str, tf: str, count: int = 50, cache=None, zones: Optional[List[SupplyDemandZone]] = None) -> Tuple[str, Optional[float]]:
        """Canonical context_zone/context_level for a symbol/timeframe —
        see select_active_zone(). get_label() below reuses this so
        DemandEngine has exactly one zone-selection rule, not two.

        Fix #4D3 — optional `zones`: pass an already-computed zone list
        (e.g. from get_zones()) to skip detect_zones() here and reuse it
        instead. Omitted/None (every existing caller) behaves exactly as
        before — detect_zones() runs here same as always."""
        candles = self.candle_engine.get_snapshots(symbol, tf, count=count, cache=cache)
        if not candles:
            return "neutral", None
        if zones is None:
            zones = detect_zones(candles)
        return select_active_zone(zones, candles[-1].close)

    def get_label(self, symbol: str, tf: str, cache=None) -> str:
        zone_type, _ = self.get_context(symbol, tf, cache=cache)
        return zone_type
