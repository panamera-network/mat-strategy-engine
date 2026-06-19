from typing import Dict, Optional
from core.strategy.strategy_models import Strategy, StrategySnapshot


class GroupedLastCandleBiasStrategy(Strategy):
    def react(self, event: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        # Only act on anchor timeframes
        anchor_tfs = ["M", "W1", "D1", "H4"]
        if event.timeframe not in anchor_tfs:
            return None

        symbol = event.symbol

        # Define groupings
        group_a = ["M", "W1", "D1"]
        group_b = ["W1", "D1", "H4"]

        # Check last candle bias alignment
        def is_bullish(tf):
            snap = context.get(f"{symbol}_{tf}")
            return snap and getattr(snap, "is_last_bias_candle", False) and snap.structure_direction == "Bullish"

        def is_bearish(tf):
            snap = context.get(f"{symbol}_{tf}")
            return snap and getattr(snap, "is_last_bias_candle", False) and snap.structure_direction == "Bearish"

        bullish_count = sum(is_bullish(tf) for tf in group_a)
        bearish_count = sum(is_bearish(tf) for tf in group_a)

        if bullish_count >= 3:
            group = "A"
            direction = "long"
        elif bullish_count == 2 and bearish_count == 1:
            group = "B"
            direction = "long"
        else:
            return None  # No valid group alignment

        # Confirm shift candle
        shift_tf_map = {
            "M": "D1",
            "W1": "H4",
            "D1": "H1"
        }
        filter_tf_map = {
            "M": ["H1", "M15"],
            "W1": ["M30", "M5"],
            "D1": ["M15", "M1"]
        }

        shift_tf = shift_tf_map.get(event.timeframe)
        shift_snap = context.get(f"{symbol}_{shift_tf}")
        if not shift_snap or shift_snap.structure_direction != "Bullish" or shift_snap.suppression:
            return None

        # Optional filter check if range > 50 pips
        range_size = abs(shift_snap.current_high - shift_snap.current_low)
        if range_size > 50:
            filters = filter_tf_map.get(event.timeframe, [])
            valid_filter = any(
                context.get(f"{symbol}_{ft}") and
                context[f"{symbol}_{ft}"].structure_direction == "Bullish" and
                not context[f"{symbol}_{ft}"].suppression
                for ft in filters
            )
            if not valid_filter:
                return None

        return {
            "symbol": symbol,
            "timeframe": event.timeframe,
            "direction": direction,
            "reason": f"Grouped last candle bias ({group}) confirmed by {shift_tf} shift candle",
            "confidence": shift_snap.momentum,
            "trigger": shift_snap.structure_type
        }
