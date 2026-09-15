from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import (
    Strategy, StrategySnapshot, price_from_snapshot, strategy_momentum_confidence,
)

# Fix #7H — confidence formula, reported explicitly per this fix's own
# requirement (no new core formula, only canonical ingredients already on
# StrategySnapshot):
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
#
# BASE_CONFIDENCE (0.5) reflects the CHoCH trigger's own unconditional
# structural confirmation -- structure_utils.detect_structure_event() only
# ever labels an event "CHOCH" once it is already fully confirmed (unlike
# BOS, which BiasEngine additionally gates on a matching pre_break_trend
# for its own full score -- this strategy's eligibility never touches
# pre_break_trend at all, per this fix's structure-first-only scope).
# MOMENTUM_WEIGHT (0.5) scales the canonical, direction-agreement-gated
# strategy_momentum_confidence() (Fix #6AU) on top of that base -- reused
# unmodified, so wrong-direction or unavailable (None/zero) ATR momentum
# contributes exactly 0 to this term, same as every other plugin using it.
# Range: exactly [0.5, 1.0] whenever eligible; momentum is support only,
# never gates eligibility.
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5


class StructureReversalStrategy(Strategy):
    """Fix #7H — first genuinely new V12 strategy: CHoCH-only structural
    reversal, using only canonical structure evidence already on
    StrategySnapshot. No zone requirement, no bias requirement, no
    momentum gate -- eligibility is structure-first and structure-only;
    momentum may only scale confidence once already eligible."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if not snapshot.structure_valid:
            return None
        if snapshot.structure_type != "CHOCH":
            return None

        if snapshot.structure_direction == "Bullish":
            direction = "long"
            label = "Bullish CHoCH"
        elif snapshot.structure_direction == "Bearish":
            direction = "short"
            label = "Bearish CHoCH"
        else:
            # Neutral or any unrecognized structure_direction -- no candidate.
            return None

        momentum_term = strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction)
        confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * momentum_term, 1.0), 2)

        price = snapshot.event_broken_level
        if price is None:
            price = price_from_snapshot(snapshot)

        marking = make_chart_marking(
            "structure",
            type(self).__name__,
            snapshot.timeframe,
            label,
            direction=direction,
            price=snapshot.event_broken_level,
            timestamp=snapshot.event_timestamp,
            candle_index=snapshot.event_index,
            evidence_ref={
                "source": "structure_events",
                "timeframe": snapshot.timeframe,
                "index": snapshot.event_index,
            },
        )

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "CHOCH",
            "timestamp": snapshot.timestamp,
            "price": price,
            "chart_markings": [marking],
        }
