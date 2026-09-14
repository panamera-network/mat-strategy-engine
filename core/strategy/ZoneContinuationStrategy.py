from typing import Dict, Optional
from core.strategy.strategy_models import Strategy, StrategySnapshot, price_from_snapshot, strategy_momentum_confidence


class ZoneContinuationStrategy(Strategy):
    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        # Only act on lower timeframes
        if snapshot.timeframe not in ["M15", "M5"]:
            return None

        symbol = snapshot.symbol

        # Get higher timeframe zone context
        h1 = context.get(f"{symbol}_H1")
        h4 = context.get(f"{symbol}_H4")

        if not h1 or not h4:
            return None

        # Check if price is inside a valid zone
        zone_valid = h1.context_zone in ["demand", "supply"] or h4.context_zone in ["demand", "supply"]
        if not zone_valid:
            return None

        # Confirm structure shift on lower timeframe
        if snapshot.structure_type in ["breakout", "reversal"] and snapshot.structure_valid and not snapshot.suppression:
            direction = "long" if snapshot.structure_direction == "Bullish" else "short"
            zone_snap = h1 if h1.context_zone in ["demand", "supply"] else h4
            zone_source = zone_snap.context_zone
            # Fix #6AV — momentum ingredient migrated to the canonical,
            # signed, direction-agreement-gated helper (Fix #6AU);
            # `direction` here is the already-resolved "long"/"short" value
            # from structure_direction above, not a second/independent
            # direction.
            return {
                "symbol": symbol,
                "timeframe": snapshot.timeframe,
                "direction": direction,
                "reason": f"Zone continuation from {zone_source}",
                "confidence": strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction),
                "trigger": snapshot.structure_type,
                "timestamp": snapshot.timestamp,
                "price": price_from_snapshot(zone_snap)
            }

        return None
