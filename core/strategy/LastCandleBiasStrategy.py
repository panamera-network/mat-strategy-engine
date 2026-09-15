from typing import Dict, Optional
from core.strategy.strategy_models import Strategy, StrategySnapshot, price_from_snapshot, strategy_momentum_confidence


class LastCandleBiasStrategy(Strategy):
    def react(self, event: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        # Only act on anchor timeframes
        anchor_tfs = ["D1", "H4", "W1", "MN1"]
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
            "MN1": "D1",
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

        # Fix #7B — canonical, direction-relative confidence, replacing the
        # raw (unsigned, per-instrument-scale) shift_snapshot.momentum
        # previously returned unmodified. `last_direction`
        # ("Bullish"/"Bearish") is the already-resolved anchor direction
        # used for the eligibility check above. Anchor/shift-TF eligibility
        # logic is untouched.
        if last_direction == shift_direction and not shift_snapshot.suppression:
            return {
                "symbol": event.symbol,
                "timeframe": event.timeframe,
                "direction": "long" if last_direction == "Bullish" else "short",
                "reason": f"Last candle bias confirmed by {shift_tf} shift candle",
                "confidence": strategy_momentum_confidence(shift_snapshot.atr_normalized_momentum, last_direction),
                "trigger": shift_snapshot.structure_type,
                "timestamp": event.timestamp,
                "price": price_from_snapshot(shift_snapshot)
            }

        return None
