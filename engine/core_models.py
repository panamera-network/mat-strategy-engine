from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, Optional
from pydantic import BaseModel


@dataclass
class CandleSnapshot:
    open: float
    high: float
    low: float
    close: float
    time: str  # ISO format or epoch
    volume: float
    range: float = field(init=False)
    body: float = field(init=False)
    bias: str = "neutral"  # "bullish", "bearish", "neutral"

    def __post_init__(self):
        self.range = abs(self.high - self.low)
        self.body = abs(self.open - self.close)

@dataclass
class BiasSnapshot:
    symbol: str
    timeframe: str
    bias: float     # scaled -10 to +10
    strength: float # scaled 0 to 10

bias_seq: list[float]  # e.g. [-1.0, -1.0, 0.0, +1.0]
# bullish = 5, bearish = 1, total = 7
# strength = 5 / 7 * 10 ≈ 7.1

@dataclass
def compute_conviction(self, atr: float = None):
    # Normalize momentum
    if atr and atr > 0:
        mom_score = max(min(self.momentum / atr, 1.0), -1.0)
    else:
        mom_score = 0.0

    # Fix zone mapping
    zone_map = {
        "demand": +1,
        "supply": -1,
        "neutral": 0
    }
    zone_score = zone_map.get(self.demand.lower(), 0)

    # Shift
    shift_score = 1.0 if self.shift.get("confirmed") else 0.0

    self.conviction = round(
        mom_score * 0.5 +
        zone_score * 0.3 +
        shift_score * 0.2,
        2
    )

@dataclass
class PriceSnapshot:
    symbol: str
    timeframe: str
    high: float
    low: float
    prev_high: float
    prev_low: float

@dataclass
class StructureSnapshot:
    symbol: str
    timeframe: str
    current_high: float
    current_low: float
    prev_high: float
    prev_low: float
    prev_zone: str  # "HH", "HL", "LH", "LL"

    label: str = field(init=False)       # "CHOCH", "BOS", or "None"
    direction: str = field(init=False)   # "Bullish", "Bearish", or "Neutral"

    def __post_init__(self):
        self.label = self.detect_structure_label()
        self.direction = self.infer_direction()

    def detect_structure_label(self) -> str:
        if self.prev_zone in ["HH", "HL"] and self.current_low < self.prev_low:
            return "CHOCH"
        elif self.prev_zone in ["LH", "LL"] and self.current_high > self.prev_high:
            return "CHOCH"
        elif self.prev_zone == "HL" and self.current_high > self.prev_high:
            return "BOS"
        elif self.prev_zone == "LL" and self.current_low < self.prev_low:
            return "BOS"
        return "None"

    def infer_direction(self) -> str:
        if self.label == "CHOCH":
            return "Bearish" if self.current_low < self.prev_low else "Bullish"
        elif self.label == "BOS":
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
    symbol: str
    timeframe: str
    zone: str
    structure_signal: str
    momentum: float
    direction: str
    divergence: str
    confidence_drop: bool
    confidence_score: float = 0.0
    confidence_breakdown: dict[str, str] = field(default_factory=dict)
    structure: StructureSnapshot = None
    status: str = "Strong"  # or "Weak", "Suppressed"

    @property
    def current_high(self): return self.structure.current_high
    @property
    def current_low(self): return self.structure.current_low
    @property
    def prev_high(self): return self.structure.prev_high
    @property
    def prev_low(self): return self.structure.prev_low
    @property
    def prev_zone(self): return self.structure.prev_zone

@dataclass
class MomentumPoint:
    symbol: str
    timeframe: str
    price: float
    momentum: float

@dataclass
class MomentumSnapshot:
    symbol: str
    timeframe: str
    momentum: float  # scaled 0–10
    divergence: str  # "Bullish", "Bearish", "None"
    confidence_drop: bool
    direction: str
    score: float  # raw float before scaling

@dataclass
class DiagnosticTile:
    symbol: str
    timeframe: str
    bias: float           # scaled -10 to +10
    strength: float       # scaled 0 to 10
    zone: str             # HH, HL, LH, LL
    structure_event: str  # BOS, CHOCH, Neutral
    momentum: float       # scaled 0 to 10
    divergence: str       # Bullish, Bearish, None
    confidence_drop: bool
    status: str           # Strong, Weak, Suppressed

@dataclass
class DiagnosticValidation:
    is_valid: bool
    tile_color: str
    tooltip: str

@dataclass
class SuppressionInfo:
    reason: str
    suppressed: bool = True

@dataclass
class BiasShiftEvent:
    symbol: str
    timeframe: str
    previous_bias: str  # "Bullish", "Bearish", "Neutral"
    new_bias: str       # "Bullish", "Bearish"
    trigger: str        # e.g. "CHOCH + Bearish Divergence"
    confirmed: bool
    momentum: float
    confidence_drop: bool
    timestamp: datetime

class SuppressionSchema(BaseModel):
    reason: str
    suppressed: bool

class BiasShiftSchema(BaseModel):
    symbol: str
    timeframe: str
    previous_bias: str
    new_bias: str
    trigger: str
    confirmed: bool
    momentum: float
    confidence_drop: bool
    timestamp: datetime
    suppression: Optional[SuppressionSchema] = None

class BiasFrame(BaseModel):
    bias: str
    strength: float
    suppressed: Optional[bool] = False
    reason: Optional[str] = ""

class ShiftInfo(BaseModel):
    previous_bias: str
    new_bias: str
    trigger: str
    confirmed: bool
    reason: str

class ModeDiagnostics(BaseModel):
    shift: ShiftInfo
    momentum: float
    demand: str
    duration: str

class SymbolDiagnostics(BaseModel):
    bias: Dict[str, BiasFrame]
    scalping: ModeDiagnostics
    swing: ModeDiagnostics

class DiagnosticSnapshotModel(BaseModel):
    symbol: str
    timeframe: str
    zone: str
    structure_signal: str
    momentum: float
    direction: str
    divergence: str
    confidence_drop: bool
    confidence_score: float
    confidence_breakdown: dict[str, str]
    demand_label: str
    signal_duration: int
    structure_weight: float

