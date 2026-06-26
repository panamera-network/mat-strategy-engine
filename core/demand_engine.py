from dataclasses import dataclass
from typing import List

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


class DemandEngine:
    def __init__(self, candle_engine: CandleEngine):
        self.candle_engine = candle_engine

    def get_zones(self, symbol: str, tf: str, count: int = 50) -> List[SupplyDemandZone]:
        candles = self.candle_engine.get_snapshots(symbol, tf, count=count)
        return detect_zones(candles)

    def get_label(self, symbol: str, tf: str) -> str:
        zones = self.get_zones(symbol, tf)
        active = [z for z in zones if z.valid]
        if not active:
            return "neutral"
        return active[-1].type
