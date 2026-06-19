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
    is_last_bias_candle: bool = False
    engulfing_sequence: Optional[List[str]] = None
    engulfing_strength: Optional[str] = None

class Strategy(ABC):
    @abstractmethod
    def react(
        self, 
        snapshot: StrategySnapshot, 
        context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        pass