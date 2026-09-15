from typing import Dict, Optional

from core.strategy.chart_markings import make_chart_marking
from core.strategy.strategy_models import (
    Strategy, StrategySnapshot, price_from_snapshot, strategy_momentum_confidence,
)

# Fix #7K — IPC v1 baseline confidence formula, reported explicitly per
# this fix's own requirement (no new core formula, only the canonical
# momentum ingredient already on StrategySnapshot -- same base+weight shape
# already used by StructureReversalStrategy, Fix #7H):
#
#   confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT *
#                strategy_momentum_confidence(atr_normalized_momentum, direction), 1.0), 2)
#
# BASE_CONFIDENCE (0.5) reflects the 3-candle IPC pattern's own
# unconditional confirmation (Ignite/Pullback/Confirmation color sequence
# already matched exactly -- eligibility is candle-sequence-only, per this
# fix's explicit "no zone/bias/structure/momentum gate" scope).
# MOMENTUM_WEIGHT (0.5) scales the canonical, direction-agreement-gated
# strategy_momentum_confidence() (Fix #6AU) on top of that base -- support
# evidence only, never gates eligibility, wrong-direction or unavailable
# (None/zero) ATR momentum contributes exactly 0. Range: exactly [0.5, 1.0]
# whenever eligible.
#
# This is a v1 baseline only -- parameter tuning (BASE_CONFIDENCE,
# MOMENTUM_WEIGHT, or a richer scoring formula) is explicitly deferred to a
# future IPC rule audit, per this fix's own instruction. Not a final rule.
BASE_CONFIDENCE = 0.5
MOMENTUM_WEIGHT = 0.5


class IPCStrategy(Strategy):
    """Fix #7K — IPC v1 baseline: Ignite -> Pullback -> Confirmation, a
    3-candle-sequence strategy using only standalone per-candle direction
    evidence (StrategySnapshot.recent_candles, Fix #7K's minimal additive
    wiring). No zone requirement, no bias requirement, no structure
    requirement, no momentum gate -- eligibility is the candle-color
    sequence only; momentum may only scale confidence once already
    eligible. This is a v1 baseline only, not a final rule set."""

    def react(self, snapshot: StrategySnapshot, context: Dict[str, StrategySnapshot]) -> Optional[Dict]:
        candles = snapshot.recent_candles
        if not candles or len(candles) < 3:
            return None

        ignite, pullback, confirmation = candles[-3], candles[-2], candles[-1]
        i_dir, p_dir, c_dir = ignite["direction"], pullback["direction"], confirmation["direction"]

        if i_dir == "bull" and p_dir == "bear" and c_dir == "bull":
            direction = "long"
            label = "Bullish IPC"
        elif i_dir == "bear" and p_dir == "bull" and c_dir == "bear":
            direction = "short"
            label = "Bearish IPC"
        else:
            return None

        momentum_term = strategy_momentum_confidence(snapshot.atr_normalized_momentum, direction)
        confidence = round(min(BASE_CONFIDENCE + MOMENTUM_WEIGHT * momentum_term, 1.0), 2)

        markings = [
            make_chart_marking(
                "candle", type(self).__name__, snapshot.timeframe, "IPC I",
                direction=direction, timestamp=ignite["timestamp"], candle_index=ignite["index"],
            ),
            make_chart_marking(
                "candle", type(self).__name__, snapshot.timeframe, "IPC P",
                direction=direction, timestamp=pullback["timestamp"], candle_index=pullback["index"],
            ),
            make_chart_marking(
                "candle", type(self).__name__, snapshot.timeframe, "IPC C",
                direction=direction, timestamp=confirmation["timestamp"], candle_index=confirmation["index"],
            ),
        ]

        return {
            "symbol": snapshot.symbol,
            "timeframe": snapshot.timeframe,
            "direction": direction,
            "reason": label,
            "confidence": confidence,
            "trigger": "IPC",
            "timestamp": snapshot.timestamp,
            "price": price_from_snapshot(snapshot),
            "chart_markings": markings,
        }
