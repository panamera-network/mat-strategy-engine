from typing import Literal, Optional
import MetaTrader5 as mt5
from pydantic import BaseModel, Field


TF_MAP = {
    "M1": mt5.TIMEFRAME_M1,
    "M5": mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "M30": mt5.TIMEFRAME_M30,
    "H1": mt5.TIMEFRAME_H1,
    "H4": mt5.TIMEFRAME_H4,
    "D1": mt5.TIMEFRAME_D1,
    "W1": mt5.TIMEFRAME_W1,
    "MN1": mt5.TIMEFRAME_MN1,
}

def resolve_timeframe(tf: str | int) -> int:
    """Resolve timeframe string, shorthand int, or MT5 constant to MT5 constant."""
    shorthand_map = {
        1: "M1", 5: "M5", 15: "M15", 30: "M30",
        60: "H1", 240: "H4", 1440: "D1", 10080: "W1", 43200: "MN1"
    }

    if tf in TF_MAP.values():
        return tf
    if isinstance(tf, int):
        tf = shorthand_map.get(tf)
        if not tf:
            raise ValueError(f"Invalid numeric timeframe: {tf}")
    if not isinstance(tf, str):
        raise TypeError(f"Expected str, int, or MT5 constant, got {type(tf)}")

    tf = tf.upper()
    if tf not in TF_MAP:
        raise ValueError(f"Invalid timeframe: {tf}")
    return TF_MAP[tf]

DEFAULT_CANDLE_COUNT = {
    "M1": 500,
    "M5": 400,
    "M15": 300,
    "M30": 200,
    "H1": 150,
    "H4": 100,
    "D1": 50,
    "W1": 30,
    "MN1": 12
}


class TimeframeData(BaseModel):
    bias: Literal["bullish", "bearish", "neutral"]
    momentum: float = Field(..., description="Momentum score, can be negative")
    duration: int = Field(..., ge=0, description="Duration in candle count")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score between 0 and 1")
    strength: float = Field(..., ge=0.0)
    range: float = Field(..., ge=0.0)
    volatility: Optional[float] = Field(default=0.0, ge=0.0)



class MultiTimeframeData(BaseModel):
    M1: Optional[TimeframeData]
    M5: Optional[TimeframeData]
    M15: Optional[TimeframeData]
    M30: Optional[TimeframeData]
    H1: Optional[TimeframeData]
    H4: Optional[TimeframeData]
    D1: Optional[TimeframeData]
    W1: Optional[TimeframeData]

def get_parent_tf(tf: str) -> str:
    parent_map = {
        "1m": "5m",
        "5m": "15m",
        "15m": "1h",
        "1h": "4h",
        "4h": "1d",
        "1d": "1w"
    }
    return parent_map.get(tf, tf)  # fallback to same tf if not found
