from typing import Dict, Optional
from core.strategy.strategy_models import Strategy, StrategySnapshot


class DoubleEngulfingStrategy(Strategy):
    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        # Only act on timeframes where engulfing matters
        if snapshot.timeframe not in ["M5","M15", "H1", "H4", "D1"]:
            return None

        # Check if engulfing sequence is present
        sequence = snapshot.engulfing_sequence
        if not sequence:
            return None

        wick_extension = snapshot.engulfing_strength == "Strong"

        # Scenario 1: two consecutive bullish engulfings
        if sequence == ["bull", "bull"]:
            return {
                "symbol": snapshot.symbol,
                "timeframe": snapshot.timeframe,
                "direction": "long",
                "reason": "Double bullish engulfing",
                "confidence": snapshot.momentum + (1.0 if wick_extension else 0.0),
                "trigger": "engulfing",
                "timestamp": snapshot.timestamp
            }

        # Scenario 2: delayed confirmation (bull, neutral/red, bull)
        if sequence == ["bull", "neutral", "bull"] or sequence == ["bull", "bear", "bull"]:
            return {
                "symbol": snapshot.symbol,
                "timeframe": snapshot.timeframe,
                "direction": "long",
                "reason": "Delayed double bullish engulfing",
                "confidence": snapshot.momentum + (0.5 if wick_extension else 0.0),
                "trigger": "engulfing",
                "timestamp": snapshot.timestamp
            }

        # Scenario 3: reversal engulfing (bull → bear)
        if sequence == ["bull", "bear"]:
            return {
                "symbol": snapshot.symbol,
                "timeframe": snapshot.timeframe,
                "direction": "short",
                "reason": "Bearish engulfing reversal",
                "confidence": snapshot.momentum,
                "trigger": "engulfing",
                "timestamp": snapshot.timestamp
            }

        return None
