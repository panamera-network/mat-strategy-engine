from typing import Dict, Optional
from core.strategy.strategy_models import Strategy, StrategySnapshot


class LastCandleBiasStrategy(Strategy):
    def react(self, event: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        # Only act on anchor timeframes
        anchor_tfs = ["D1", "H4", "W1", "M"]
        if event.timeframe not in anchor_tfs:
            return None

        # Get last candle snapshot
        anchor_key = f"{event.symbol}_{event.timeframe}"
        anchor_snapshot = context.get(anchor_key)
        if not anchor_snapshot or not anchor_snapshot.structure_valid:
            return None

        # Confirm it's the last bias candle
        if not getattr(anchor_snapshot, "is_last_bias_candle", False):
            return None

        # Get shift candle timeframe
        shift_tf_map = {
            "M": "D1",
            "W1": "H4",
            "D1": "H1",
            "H4": "M30"
        }
        shift_tf = shift_tf_map.get(event.timeframe)
        shift_key = f"{event.symbol}_{shift_tf}"
        shift_snapshot = context.get(shift_key)

        if not shift_snapshot or not shift_snapshot.structure_valid:
            return None

        # Confirm shift candle direction matches last candle
        last_direction = anchor_snapshot.structure_direction
        shift_direction = shift_snapshot.structure_direction

        if last_direction == shift_direction and not shift_snapshot.suppression:
            return {
                "symbol": event.symbol,
                "timeframe": event.timeframe,
                "direction": "long" if last_direction == "Bullish" else "short",
                "reason": f"Last candle bias confirmed by {shift_tf} shift candle",
                "confidence": shift_snapshot.momentum,
                "trigger": shift_snapshot.structure_type
            }

        return None
