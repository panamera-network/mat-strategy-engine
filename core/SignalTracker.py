from core.CandleEngine import CandleEngine
from core.log import log_error


class SignalTracker:
    def __init__(self, candle_engine: CandleEngine):
        self.candle_engine = candle_engine

    def get_duration(self, symbol: str, tf: str) -> dict:
        candles = self.candle_engine.get_snapshot(symbol, tf)
        count = 0
        direction = None

        for c in reversed(candles):
            if c.close > c.open:
                direction = "bullish"
                count += 1
            elif c.close < c.open:
                direction = "bearish"
                break
            else:
                break  # Doji or neutral

        last_candle = candles[-1] if candles else None

        return {
            "duration": count,
            "direction": direction or "neutral",
            "last_close": last_candle.close if last_candle else None,
            "last_open": last_candle.open if last_candle else None,
            "suppressed": count == 0
        }

# Instantiate with an actual engine instance
candle_engine = CandleEngine()
signal_tracker = SignalTracker(candle_engine)

def get_duration(symbol: str, mode: str) -> str:
    tf = "M5" if mode == "scalping" else "H1"
    info = compute_signal_duration(symbol, tf)
    return f"{info['duration']} min ({info['direction']})"


def compute_signal_duration(symbol: str, tf: str) -> dict:
    try:
        return signal_tracker.get_duration(symbol, tf)
    except Exception as e:
        log_error(symbol, tf, "duration_fetch", str(e))
        return {
            "duration": 0,
            "direction": "error",
            "last_close": None,
            "last_open": None,
            "suppressed": True
        }
