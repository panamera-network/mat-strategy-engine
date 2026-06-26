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