from typing import Dict, List, Optional, Tuple
from core.strategy.strategy_models import Strategy, StrategySnapshot, price_from_snapshot


class GroupedLastCandleBiasStrategy(Strategy):
    ANCHOR_TFS = ["MN1", "W1", "D1", "H4"]
    GROUP_A = ["MN1", "W1", "D1"]
    GROUP_B = ["W1", "D1", "H4"]
    SHIFT_TF_MAP = {"MN1": "D1", "W1": "H4", "D1": "H1", "H4": "M30"}
    FILTER_TF_MAP = {
        "MN1": ["H1", "M15"],
        "W1": ["M30", "M5"],
        "D1": ["M15", "M1"],
        "H4": ["M15", "M5"],
    }

    def react(self, event: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if event.timeframe not in self.ANCHOR_TFS:
            return None

        symbol = event.symbol

        def count_in_group(group: List[str], direction: str) -> int:
            total = 0
            for tf in group:
                snap = context.get(f"{symbol}_{tf}")
                if snap and getattr(snap, "is_last_bias_candle", False) and snap.structure_direction == direction:
                    total += 1
            return total

        direction, group_label = self._resolve_group(count_in_group)
        if not direction:
            return None  # No valid group alignment

        shift_tf = self.SHIFT_TF_MAP.get(event.timeframe)
        shift_snap = context.get(f"{symbol}_{shift_tf}")
        if not shift_snap or shift_snap.structure_direction != direction or shift_snap.suppression:
            return None

        # Optional filter check if range > 50 pips (skipped if range data unavailable)
        if shift_snap.current_high is not None and shift_snap.current_low is not None:
            range_size = abs(shift_snap.current_high - shift_snap.current_low)
            if range_size > 50:
                filters = self.FILTER_TF_MAP.get(event.timeframe, [])
                valid_filter = any(
                    context.get(f"{symbol}_{ft}") and
                    context[f"{symbol}_{ft}"].structure_direction == direction and
                    not context[f"{symbol}_{ft}"].suppression
                    for ft in filters
                )
                if not valid_filter:
                    return None

        return {
            "symbol": symbol,
            "timeframe": event.timeframe,
            "direction": "long" if direction == "Bullish" else "short",
            "reason": f"Grouped last candle bias ({group_label}) confirmed by {shift_tf} shift candle",
            "confidence": shift_snap.momentum,
            "trigger": shift_snap.structure_type,
            "timestamp": event.timestamp,
            "price": price_from_snapshot(shift_snap),
        }

    def _resolve_group(self, count_in_group) -> Tuple[Optional[str], Optional[str]]:
        bull_a = count_in_group(self.GROUP_A, "Bullish")
        bear_a = count_in_group(self.GROUP_A, "Bearish")
        if bull_a >= 3:
            return "Bullish", "A"
        if bear_a >= 3:
            return "Bearish", "A"

        bull_b = count_in_group(self.GROUP_B, "Bullish")
        bear_b = count_in_group(self.GROUP_B, "Bearish")
        if bull_b == 2 and bear_b == 1:
            return "Bullish", "B"
        if bear_b == 2 and bull_b == 1:
            return "Bearish", "B"

        return None, None
