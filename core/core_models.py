from contextvars import Context
from dataclasses import  dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field



@dataclass
class CandleSnapshot:
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: str  # ISO 8601 or epoch
    range: float = field(init=False)
    body: float = field(init=False)
    bias: str = "neutral"
    suppressed: bool = False
    suppression_reason: str = ""

    def __post_init__(self):
        self.range = abs(self.high - self.low)
        self.body = abs(self.open - self.close)

    @property
    def conviction(self) -> float:
        return round(self.bias_score * 0.6 + self.strength_diagnostic.strength * 0.4, 2)

    @property
    def is_bullish(self) -> bool:
        return self.bias_label == "up"

    def summary(self) -> str:
        return f"{self.symbol} [{self.timeframe}] → Bias: {self.bias_label} ({self.bias_score}), Strength: {self.strength_diagnostic.strength}"

class StrengthDiagnostic:
    def __init__(self, strength: float, avg_body_ratio: float, momentum_slope: float):
        self.strength = strength
        self.avg_body_ratio = avg_body_ratio
        self.momentum_slope = momentum_slope

    def __lt__(self, other):
        if isinstance(other, (int, float)):
            return self.strength < other
        raise TypeError("Cannot compare StrengthDiagnostic with non-numeric type")

    def __repr__(self):
        return f"StrengthDiagnostic(strength={self.strength}, avg_body_ratio={self.avg_body_ratio}, momentum_slope={self.momentum_slope})"

    def to_dict(self):
        return {
            "strength": self.strength,
            "avg_body_ratio": self.avg_body_ratio,
            "momentum_slope": self.momentum_slope
        }


@dataclass
class BiasSnapshot:
    symbol: str
    timeframe: str
    bias_score: float           # scaled -10 to +10 or normalized -1.0 to +1.0
    bias_label: str             # "up", "down", "neutral"
    strength_diagnostic: StrengthDiagnostic
    bias_sequence: List[float] = field(default_factory=list)
    bullish_count: int = 0
    bearish_count: int = 0
    neutral_count: int = 0
    suppressed: bool = False
    suppression_reason: str = ""
    timestamp: Optional[str] = None

    @property
    def bias(self) -> float:
        return self.bias_score
    @property
    def strength(self) -> float:
        return self.strength_diagnostic.strength
    @property
    def parsed_timestamp(self) -> Optional[datetime]:
        if self.timestamp:
            return datetime.fromisoformat(self.timestamp)
        return None
    @property
    def label(self) -> str:
        return self.bias_label
    @property
    def score(self) -> float:
        return self
    
    def __post_init__(self):
        if not isinstance(self.strength_diagnostic, StrengthDiagnostic):
            raise TypeError(f"Expected StrengthDiagnostic, got {type(self.strength_diagnostic)}")



@dataclass
class MomentumSnapshot:
    symbol: str 
    timeframe: str 
    momentum: float           # scaled 0–10
    slope: float              # directional slope
    acceleration: float       # change in slope
    reversal: bool            # momentum reversal flag
    divergence: str = "None"  # "Bullish", "Bearish", "None"
    confidence_drop: bool = False
    direction: str = "Neutral"
    score: float = 0.0        # raw float before scaling


class StructureLabel(str, Enum):
    BOS = "BOS"
    CHOCH = "CHOCH"
    NONE = "None"

class StrategyMode(str, Enum):
    SWING = "swing"
    SCALP = "scalp"
    RANGE = "range"
    BREAKOUT = "breakout"

@dataclass
class StructureSnapshot:
    symbol: str
    timeframe: str
    current_high: float
    current_low: float
    prev_high: float
    prev_low: float
    current_zone: str
    prev_zone: str
    structure: str = "neutral"
    structure_type: str = field(init=False)
    structure_direction: str = field(init=False)
    structure_valid: bool = field(init=False)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    context_zone: str = "neutral"
    context_level: float | None = None
    momentum: float = 0.0
    confidence_drop: bool = False
    strength: float = 0.0
    body_ratio: float = 0.0
    momentum_slope: float = 0.0
    suppression: bool = False
    suppression_reason: str = ""
    bias: str = "Neutral"




    def __post_init__(self):
        self.structure_type = self.detect_structure_label()
        self.structure_direction = self.infer_direction()
        self.structure_valid = self.structure_type in ["CHOCH", "BOS"]

    def detect_structure_label(self) -> str:
        if self.prev_zone in ["HH", "HL"] and self.current_low < self.prev_low:
            return "CHOCH"
        elif self.prev_zone in ["LL", "LH"] and self.current_high > self.prev_high:
            return "CHOCH"
        elif self.prev_zone == "HL" and self.current_high > self.prev_high:
            return "BOS"
        elif self.prev_zone == "LL" and self.current_low < self.prev_low:
            return "BOS"
        return "None"

    def infer_direction(self) -> str:
        if self.structure_type == "CHOCH":
            return "Bearish" if self.current_low < self.prev_low else "Bullish"
        elif self.structure_type == "BOS":
            return "Bullish" if self.current_high > self.prev_high else "Bearish"
        return "Neutral"


    @property
    def label_weight(self) -> float:
        return {
            "BOS": 1.0,
            "CHOCH": 0.7,
            "None": 0.0
        }.get(self.label, 0.0)


@dataclass
class DiagnosticSnapshot:
    candle: CandleSnapshot
    context: Context
    bias: BiasSnapshot
    momentum: MomentumSnapshot
    structure: StructureSnapshot
    strength: StrengthDiagnostic
    suppression: List[str] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "active"


@dataclass
class StyleSnapshot:
    symbol: str
    timeframe: str
    mode: str  # "swing" or "scalping"
    direction: str
    momentum: float
    bias: float
    structure_label: Optional[str] = None
    shift_confirmed: bool = False
    shift_direction: str = "bearish"
    shift_color: str = "#cccccc"
    demand: str = "neutral"
    duration: str = "0 min"
    conviction: float = 0.0
    conviction_breakdown: dict[str, float] = field(default_factory=dict)
    suppression: bool = False
    engulfing_sequence: Optional[List[str]] = None

    def __post_init__(self):
        self.compute_conviction()
    
    def compute_conviction(self):
        base = 0.0
        structure_weight = 0.0  # ✅ always defined
        demand_score = 0        # ✅ always defined

        if self.mode == "swing":
            structure_weight = {
                "BOS": 1.0,
                "CHOCH": 0.7,
                "None": 0.0
            }.get(self.structure_label or "None", 0.0)

            demand_map = {
                "strong buy": +2,
                "buy": +1,
                "neutral": 0,
                "sell": -1,
                "strong sell": -2
            }
            demand_score = demand_map.get(self.demand.lower(), 0)

            base = (
                structure_weight * 0.4 +
                (self.bias / 10) * 0.3 +
                demand_score * 0.3
            )

        elif self.mode == "scalping":
            shift_score = 1.0 if self.shift_confirmed else 0.0
            base = (
                (self.momentum / 10) * 0.5 +
                shift_score * 0.3 +
                (self.bias / 10) * 0.2
            )

        self.conviction = round(base, 2)
        self.conviction_breakdown = {
            "structure": round(structure_weight * 0.4, 2),
            "bias": round((self.bias / 10) * 0.3, 2),
            "zone_score": round(demand_score * 0.3, 2)  # ✅ also renamed to match your JSON
        }


        

class PriceSnapshot(BaseModel):
    symbol: str
    timeframe: str
    high: float
    low: float
    prev_high: float
    prev_low: float


class BiasShiftEvent(BaseModel):
    symbol: str
    timeframe: str
    previous_bias: str
    new_bias: str
    trigger: str
    confirmed: bool
    momentum: float
    confidence_drop: bool
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    suppression: List[str]
    zone: Optional[str]
    structure: Optional[str]
    direction: str


class StrategySnapshot(BaseModel):
    mode: str
    conviction: float
    reasons: list[str]
    suppressed: bool = False
    fallback: Optional[str] = None

class StrategyResponse(BaseModel):
    bias: dict
    scalping: dict
    swing: dict