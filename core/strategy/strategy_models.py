from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict



@dataclass
class StrategySnapshot:
    symbol: str
    timeframe: str
    bias: str
    momentum: float
    strength: float
    suppression: bool
    suppression_reason: str
    structure_type: str
    structure_direction: str
    structure_valid: bool
    context_zone: str
    context_level: Optional[float]
    timestamp: datetime
    current_high: Optional[float] = None
    current_low: Optional[float] = None
    is_last_bias_candle: bool = False
    engulfing_sequence: Optional[List[str]] = None
    engulfing_strength: Optional[str] = None
    # Fix #6AS — canonical, instrument-scale-independent momentum, copied
    # straight from StructureSnapshot.atr_normalized_momentum (Fix #6V).
    # Additive only; the legacy `momentum` field above (clamped [0,10],
    # per-instrument price-unit) is untouched and still populated exactly
    # as before. None whenever the engine didn't have enough candles for a
    # genuine ATR14 -- never backfilled/guessed. No Strategy plugin reads
    # this yet (Fix #6AR's audit) -- this fix only exposes the value.
    # POST /core/evaluate's raw-JSON-body construction
    # (StrategySnapshot(**snapshot_data)) omitting this key simply falls
    # through to this default (None) -- no fallback from legacy `momentum`
    # is invented for a caller that doesn't supply it.
    atr_normalized_momentum: Optional[float] = None

def price_from_snapshot(snapshot: StrategySnapshot) -> Optional[float]:
    """A representative chart price for a signal — for placing a marker/zone
    on the y-axis. Prefers the zone/level price; falls back to the midpoint
    of the latest candle's high/low."""
    if snapshot.context_level is not None:
        return snapshot.context_level
    if snapshot.current_high is not None and snapshot.current_low is not None:
        return round((snapshot.current_high + snapshot.current_low) / 2, 5)
    return None


class Strategy(ABC):
    @abstractmethod
    def react(
        self,
        snapshot: StrategySnapshot,
        context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        pass