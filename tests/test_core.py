from candle import Candle
from strategy import compute_bias


def test_compute_bias():
    candles = [
        Candle(timestamp="t1", open=1.0, close=1.2, high=1.3, low=0.9, volume=100),
        Candle(timestamp="t2", open=1.2, close=1.1, high=1.25, low=1.0, volume=80),
        # Add more mock candles...
    ]
    result = compute_bias(candles)
    assert result["bias"] in ["bullish", "bearish", "neutral"]
    assert 0 <= result["strength"] <= 1
