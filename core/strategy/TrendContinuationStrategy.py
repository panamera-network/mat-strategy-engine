from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import (
    Strategy, StrategySnapshot, price_from_snapshot, strategy_momentum_confidence,
)

# Fix #7L — Trend Continuation v1 baseline confidence formula, reported
# explicitly per this fix's own requirement (no new core formula, only the
# canonical momentum ingredient already on StrategySnapshot -- same
# base+weight shape already used by StructureReversalStrategy (Fix #7H)
# and IPCStrategy (Fix #7K)):
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
#
# BASE_CONFIDENCE (0.5) reflects the confirmed canonical continuation
# itself -- a BOS whose structure_direction agrees with pre_break_trend
# (Fix #6C) is already a substantiated continuation claim, not a
# default/fallback label (see structure_utils.detect_structure_event()'s
# own Fix #6C commentary on the BOS-from-Neutral edge case this
# eligibility gate deliberately excludes). MOMENTUM_WEIGHT (0.5) scales
# the canonical, direction-agreement-gated strategy_momentum_confidence()
# (Fix #6AU) on top of that base -- support evidence only, never gates
# eligibility. Range: exactly [0.5, 1.0] whenever eligible.
#
# This is a v1 baseline only -- no bias/zone/body-dominance/strength
# scoring is introduced here; parameter tuning and any richer formula are
# explicitly deferred to a future Trend Continuation rule audit.
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5


class TrendContinuationStrategy(Strategy):
    """Fix #7L — Trend Continuation v1: a valid BOS whose direction agrees
    with the canonical pre-break trend (Fix #6C), i.e. a genuine
    continuation of an already-established trend -- not a CHoCH (trend
    flip) and not a BOS-from-Neutral default/fallback label. No zone
    requirement, no candle-pattern requirement, no new trend/BOS formula
    -- consumes only existing canonical Structure evidence already on
    StrategySnapshot. Momentum may only scale confidence once already
    eligible."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        if not snapshot.structure_valid:
            return None
        if snapshot.structure_type != "BOS":
            return None

        if snapshot.structure_direction == "Bullish" and snapshot.pre_break_trend == "Bullish":
            direction = "long"
            label = "Bullish BOS Continuation"
        elif snapshot.structure_direction == "Bearish" and snapshot.pre_break_trend == "Bearish":
            direction = "short"
            label = "Bearish BOS Continuation"
        else:
            # CHoCH, a BOS-from-Neutral default label (pre_break_trend ==
            # "Neutral"), or a BOS whose direction disagrees with
            # pre_break_trend -- none of these are a genuine continuation.
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
            "trigger": "BOS",
            "timestamp": snapshot.timestamp,
            "price": price,
            "chart_markings": [marking],
        }
