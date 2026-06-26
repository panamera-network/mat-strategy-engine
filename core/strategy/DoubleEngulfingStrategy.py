from typing import Dict, Optional
from core.strategy.strategy_models import Strategy, StrategySnapshot, price_from_snapshot

ACTIVE_TFS = ["M5", "M15", "H1", "H4", "D1"]

# sequence -> (direction, reason, confidence bonus if wick_extension else half that)
_SCENARIOS = {
    ("bull", "bull"): ("long", "Double bullish engulfing", 1.0),
    ("bear", "bear"): ("short", "Double bearish engulfing", 1.0),
    ("bull", "neutral", "bull"): ("long", "Delayed double bullish engulfing", 0.5),
    ("bull", "bear", "bull"): ("long", "Delayed double bullish engulfing", 0.5),
    ("bear", "neutral", "bear"): ("short", "Delayed double bearish engulfing", 0.5),
    ("bear", "bull", "bear"): ("short", "Delayed double bearish engulfing", 0.5),
    ("bull", "bear"): ("short", "Bearish engulfing reversal", 0.0),
    ("bear", "bull"): ("long", "Bullish engulfing reversal", 0.0),
}


class DoubleEngulfingStrategy(Strategy):
    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if snapshot.timeframe not in ACTIVE_TFS:
            return None

        sequence = snapshot.engulfing_sequence
        if not sequence:
            return None

        scenario = _SCENARIOS.get(tuple(sequence))
        if not scenario:
            return None

        direction, reason, full_bonus = scenario
        wick_extension = snapshot.engulfing_strength == "Strong"
        bonus = full_bonus if wick_extension else 0.0

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": reason,
            "confidence": min(snapshot.momentum + bonus, 1.0),
            "trigger": "engulfing",
            "timestamp": snapshot.timestamp,
            "price": price_from_snapshot(snapshot)
        }
