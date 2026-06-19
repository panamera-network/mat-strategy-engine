# Deprecated: bias computation now lives in bias/strategy.py
# Retained for multi-timeframe experiments and backtesting.


from typing import List, Dict

from bias.manifest import load_candles_for_symbol
from models import BiasDetails
from mt5.fetcher import Candle
from schemas.indicator_bias import BiasRow

def compute_bias(candles: List[Candle]) -> BiasDetails:
    if len(candles) < 2:
        return BiasDetails(
            bias="neutral",
            strength=0,
            confidence="low",
            avg_body_size=0
        )

    recent = candles[-100:]
    gain_volume = sum(c.volume for c in recent if c.close > c.open)
    loss_volume = sum(c.volume for c in recent if c.close < c.open)

    bias = "bullish" if gain_volume > loss_volume else "bearish" if loss_volume > gain_volume else "neutral"
    total_volume = gain_volume + loss_volume
    strength = 0 if total_volume == 0 else abs(gain_volume - loss_volume) / total_volume

    confidence = (
        "high" if strength > 0.6 else
        "medium" if strength > 0.3 else
        "low"
    )

    avg_body_size = sum(abs(c.close - c.open) for c in recent) / len(recent)

    return BiasDetails(
        bias=bias,
        strength=round(strength, 2),
        confidence=confidence,
        avg_body_size=round(avg_body_size, 2)
    )

def generate_bias_row(symbol: str, tf_data: Dict[str, List[Candle]]) -> BiasRow:
    biases = {tf: compute_bias(candles) for tf, candles in tf_data.items()}
    return BiasRow(symbol=symbol, biases=biases)

def generate_bias_rows(manifest: List[Dict]) -> List[BiasRow]:
    bias_rows = []
    for entry in manifest:
        symbol = entry["symbol"]
        tf_data = {
            "M5": load_candles_for_symbol(symbol, "M5"),
            "M15": load_candles_for_symbol(symbol, "M15"),
            "M30": load_candles_for_symbol(symbol, "M30"),
        }
        row = generate_bias_row(symbol, tf_data)
        bias_rows.append(row)
    return bias_rows
