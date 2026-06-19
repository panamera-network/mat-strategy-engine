from engine.core_models import BiasSnapshot, CandleSnapshot
from mt5.fetcher import Candle


def detect_bias(c1: Candle, c2: Candle, c3: Candle) -> float:
    # Example: Higher High + Higher Low → bullish
    if c2.high > c1.high and c2.low > c1.low and c3.high > c2.high:
        return +1.0
    elif c2.low < c1.low and c2.high < c1.high and c3.low < c2.low:
        return -1.0
    else:
        return 0.0
    
def compute_bias_strength(bias_seq: list[float]) -> float:
    if not bias_seq:
        return 0.0

    total = len(bias_seq)
    bullish = bias_seq.count(1.0)
    bearish = bias_seq.count(-1.0)

    dominant = max(bullish, bearish)
    strength = (dominant / total) * 10

    return round(strength, 1)

def compute_bias_sequence(candles: list[CandleSnapshot]) -> list[float]:
    bias_seq = []

    for i in range(2, len(candles)):
        c1, c2, c3 = candles[i-2], candles[i-1], candles[i]

        bias = detect_bias(c1, c2, c3)  # returns float in [-1.0, 0.0, +1.0]
        bias_seq.append(bias)

    return bias_seq

def generate_bias_snapshots(symbol: str, candles_by_tf: dict[str, list[Candle]]) -> list[BiasSnapshot]:
    snapshots = []

    for tf, candles in candles_by_tf.items():
        bias_seq = compute_bias_sequence(candles)  # returns list of -1.0, 0.0, 1.0
        scaled_bias = round(bias_seq[-1] * 10, 1) if bias_seq else 0.0
        strength = compute_bias_strength(bias_seq)  # returns 0–10

        snapshots.append(BiasSnapshot(
            symbol=symbol,
            timeframe=tf,
            bias=scaled_bias,
            strength=strength
        ))

def derive_direction(bias_map: dict[str, dict]) -> str:
    biases = [v["bias"] for v in bias_map.values()]
    if all(b == "bullish" for b in biases):
        return "uptrend"
    elif all(b == "bearish" for b in biases):
        return "downtrend"
    else:
        return "choppy"

def detect_trend(bias: float, strength: float) -> str:
    if strength < 4:
        return "Unclear"
    if bias >= 7:
        return "Uptrend"
    if bias <= -7:
        return "Downtrend"
    return "Sideways"



